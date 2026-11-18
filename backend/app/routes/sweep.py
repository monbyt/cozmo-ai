"""Sweep WebSocket + REST endpoints.

WebSocket protocol (JSON text + binary frames):
  C->S  {"type":"start", "country":"US", "currency":"USD", "device":"iPhone 15 Pro"}
  S->C  {"type":"started", "sweep_id":"sw_..."}

  C->S  {"type":"frame_meta", "frame_id":"f_...", "ts":"...", "shelf_hint":"left wall / shelf 2",
         "intrinsics":{"fx":...,"fy":...,"cx":...,"cy":...,"width":...,"height":...},
         "orientation":{"roll":...,"pitch":...,"yaw":...},
         "depth":[{"u":..,"v":..,"value_m":..},...]}
  C->S  <binary JPEG bytes for that frame>

  C->S  {"type":"plane", "kind":"floor|wall|ceiling|other", "area_m2":..., "width_m":..., "height_m":...}
  C->S  {"type":"voice_text", "text":"...", "role":"user"}   (optional transcript)
  C->S  {"type":"end"}

  S->C  {"type":"inventory_update", "new_books":[...], "new_items":[...], "notes":[...]}
  S->C  {"type":"packet_ready", "sweep_id":"...", "json_url":"...", "html_url":"..."}
"""
from __future__ import annotations
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from .. import storage
from ..services.packet import save_packet
from ..services.perception_orchestrator import PerceptionOrchestrator

log = logging.getLogger(__name__)
router = APIRouter()


def _blur_score(image_bytes: bytes) -> float:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


def _glare_score(image_bytes: bytes) -> float:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    # Fraction of saturated pixels
    return float((img > 240).mean())


@router.websocket("/ws/sweep")
async def sweep_ws(ws: WebSocket) -> None:
    await ws.accept()
    orchestrator = PerceptionOrchestrator()
    sweep_id: str | None = None
    country = "US"
    started_at: datetime | None = None
    last_frame_meta: dict[str, Any] | None = None
    pending_tasks: set[asyncio.Task] = set()

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            if "text" in msg and msg["text"] is not None:
                data = json.loads(msg["text"])
                mtype = data.get("type")

                if mtype == "start":
                    sweep_id = f"sw_{uuid.uuid4().hex[:10]}"
                    country = (data.get("country") or "US").upper()
                    currency = data.get("currency") or "USD"
                    device = data.get("device") or ""
                    started_at = datetime.now(timezone.utc)
                    storage.insert_sweep(
                        sweep_id, started_at.isoformat(), device, country, currency
                    )
                    await ws.send_json({"type": "started", "sweep_id": sweep_id})

                elif mtype == "frame_meta":
                    last_frame_meta = data

                elif mtype == "plane" and sweep_id:
                    orchestrator.record_plane(sweep_id, data)

                elif mtype == "end" and sweep_id:
                    # Wait for inflight frame tasks
                    if pending_tasks:
                        await asyncio.gather(*pending_tasks, return_exceptions=True)
                    duration = (datetime.now(timezone.utc) - started_at).total_seconds() if started_at else 0
                    storage.finalize_sweep(sweep_id, duration)
                    orchestrator.finalize_room(sweep_id)
                    json_path, html_path = save_packet(sweep_id)
                    await ws.send_json({
                        "type": "packet_ready",
                        "sweep_id": sweep_id,
                        "json_url": f"/sweeps/{sweep_id}/claim_packet.json",
                        "html_url": f"/sweeps/{sweep_id}/report.html",
                    })

            elif "bytes" in msg and msg["bytes"] is not None and sweep_id and last_frame_meta:
                image_bytes: bytes = msg["bytes"]
                frame_id = last_frame_meta.get("frame_id") or f"f_{uuid.uuid4().hex[:8]}"
                ts = last_frame_meta.get("ts") or datetime.now(timezone.utc).isoformat()
                frame_path = storage.FRAMES_DIR / sweep_id / f"{frame_id}.jpg"
                frame_path.parent.mkdir(parents=True, exist_ok=True)
                frame_path.write_bytes(image_bytes)

                intr = last_frame_meta.get("intrinsics")
                blur = _blur_score(image_bytes)
                glare = _glare_score(image_bytes)
                width = intr.get("width") if intr else 0
                height = intr.get("height") if intr else 0
                storage.insert_frame(
                    frame_id, sweep_id, ts, str(frame_path),
                    width, height, blur, glare, last_frame_meta.get("orientation"),
                )

                # Quality gate — tell the agent to slow down / move closer
                if blur < 60:
                    await ws.send_json({"type": "capture_note", "note": "blur_high", "frame_id": frame_id})
                if glare > 0.05:
                    await ws.send_json({"type": "capture_note", "note": "glare_high", "frame_id": frame_id})

                async def _process(frame_meta=last_frame_meta, fp=frame_path):
                    updates = await orchestrator.ingest_frame(
                        sweep_id=sweep_id, frame_path=fp,
                        intrinsics=frame_meta.get("intrinsics"),
                        depth_samples=frame_meta.get("depth"),
                        orientation=frame_meta.get("orientation"),
                        country=country,
                        shelf_hint=frame_meta.get("shelf_hint", ""),
                    )
                    # Split agent utterances into their own messages so the client can throttle TTS.
                    agent_lines = updates.pop("agent_say", [])
                    try:
                        await ws.send_json({"type": "inventory_update", **updates})
                        for line in agent_lines:
                            await ws.send_json({"type": "agent_say", "text": line})
                    except Exception:
                        pass

                task = asyncio.create_task(_process())
                pending_tasks.add(task)
                task.add_done_callback(pending_tasks.discard)

    except WebSocketDisconnect:
        log.info("ws disconnected (sweep=%s)", sweep_id)
    finally:
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        await orchestrator.close()


@router.get("/sweeps/{sweep_id}/claim_packet.json")
async def get_packet_json(sweep_id: str):
    p = storage.SWEEPS_DIR / sweep_id / "claim_packet.json"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/json")


@router.get("/sweeps/{sweep_id}/report.html")
async def get_packet_html(sweep_id: str):
    p = storage.SWEEPS_DIR / sweep_id / "report.html"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="text/html")


@router.get("/sweeps/{sweep_id}/frames/{frame_name}")
async def get_frame(sweep_id: str, frame_name: str):
    p = storage.FRAMES_DIR / sweep_id / frame_name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")


@router.post("/sweeps/{sweep_id}/reprice")
async def reprice(sweep_id: str, country: str):
    """Deliverable: price the same 10 books under a second locale.
    Writes a sibling JSON file 'claim_packet_<country>.json' without touching the primary packet."""
    from ..services.pricing import PricingService
    from ..services.packet import build_packet
    ps = PricingService()
    try:
        packet = build_packet(sweep_id)
        out: list[dict[str, Any]] = []
        picked = 0
        for b in packet.books:
            if picked >= 10:
                break
            if b.status != "identified":
                continue
            rc = await ps.price_book_new(b.title, b.author, b.isbn, country)
            uv = await ps.price_book_used(b.title, b.author, b.isbn, country)
            out.append({
                "id": b.id, "title": b.title, "author": b.author, "isbn": b.isbn,
                "country": country,
                "replacement_cost": rc.__dict__,
                "used_value": uv.__dict__,
            })
            picked += 1
        reprice_path = storage.SWEEPS_DIR / sweep_id / f"reprice_{country}.json"
        reprice_path.parent.mkdir(parents=True, exist_ok=True)
        reprice_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
        return JSONResponse({"rows": out, "written": str(reprice_path)})
    finally:
        await ps.close()
