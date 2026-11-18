"""Gemini Live WebSocket proxy.

Client (browser) → this backend WebSocket → Gemini Live.

Client messages (JSON over text):
  {"type":"start","country":"US","currency":"USD"}
  {"type":"audio","data":"<base64 PCM16 16kHz>"}
  {"type":"video","data":"<base64 JPEG>"}
  {"type":"text","text":"...","id":"..."}
  {"type":"close"}

Server messages back to client:
  {"type":"session","model":"gemini-3.8-live"}
  {"type":"transcript","speaker":"User|Agent","text":"...","final":bool,"id":"..."}
  {"type":"audio","data":"<base64 PCM16 24kHz>"}
  {"type":"tool","name":"log_book_spine","phase":"done","args":{...},"result":{...}}
  {"type":"inventory_update","new_books":[...],"new_items":[...]}
  {"type":"packet_ready","json_url":"...","html_url":"..."}
  {"type":"interrupted"}
  {"type":"error","message":"..."}
"""
from __future__ import annotations
import asyncio
import base64
import contextlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from .. import storage
from ..config import get_settings
from ..services.books import BookResolver
from ..services.dedup import book_dedup_key, item_dedup_key
from ..services.live_tools import LIVE_MODEL_ID, build_live_config, scheduling_for
from ..services.measurement import TYPICAL_HEIGHTS
from ..services.packet import save_packet
from ..services.pricing import PricingService, is_rare

log = logging.getLogger(__name__)
router = APIRouter()


SendFn = Callable[[dict[str, Any]], Awaitable[None]]


async def _run_tool(
    name: str, args: dict[str, Any],
    sweep_id: str, country: str,
    books: BookResolver, pricing: PricingService,
    send: SendFn,
    bg_tasks: set[asyncio.Task],
) -> tuple[dict[str, Any], bool]:
    """Execute a tool from Gemini Live. Returns (result_for_model, urgent)."""
    if name == "log_book_spine":
        return await _tool_log_book(args, sweep_id, country, books, pricing, send, bg_tasks)
    if name == "log_non_book_item":
        return await _tool_log_item(args, sweep_id, country, pricing, send, bg_tasks)
    if name == "ask_calibration":
        return {"ok": True, "say": "I'll ask the user to pace one wall."}, False
    if name == "record_wall_measurement":
        return _tool_wall(args, sweep_id)
    if name == "sync_inventory":
        return _tool_sync(args, sweep_id)
    return {"error": f"Unknown tool {name}"}, False


def _spawn_bg(bg_tasks: set[asyncio.Task], coro) -> None:
    task = asyncio.create_task(coro)
    bg_tasks.add(task)
    task.add_done_callback(bg_tasks.discard)


async def _tool_log_book(
    args: dict[str, Any], sweep_id: str, country: str,
    books: BookResolver, pricing: PricingService, send: SendFn,
    bg_tasks: set[asyncio.Task],
) -> tuple[dict[str, Any], bool]:
    """Fast path: persist OCR + push a card immediately. Resolve/price in background."""
    title = (args.get("title") or "").strip()
    author = (args.get("author") or "").strip()
    publisher = (args.get("publisher") or "").strip()
    legibility = args.get("legibility", "unreadable")
    format_hint = args.get("format_hint", "unknown")
    rare_signal = (args.get("rare_signal") or "").strip()
    shelf_hint = (args.get("shelf_hint") or "").strip()
    visible_text = (args.get("visible_text") or "").strip()

    # Dedup on OCR-ish key first so we don't block on OpenLibrary.
    dk = book_dedup_key(title, author, shelf_hint, 0)
    if storage.book_exists_by_dedup(sweep_id, dk):
        return {"ok": True, "deduplicated": True}, False

    rare, rare_reason = is_rare([rare_signal] if rare_signal else [], title)
    status = "needs_appraisal" if rare else ("unidentified" if legibility == "unreadable" else "logging")
    rflag = rare_reason if rare else ""
    spine_h = TYPICAL_HEIGHTS.get(format_hint, 0.0)
    spine_t = 0.0
    scale_method = "standard_book_format" if spine_h > 0 else ""

    book_id = f"bk_{uuid.uuid4().hex[:10]}"
    storage.upsert_book_candidate(
        id=book_id, sweep_id=sweep_id, frame_id="live",
        shelf=shelf_hint, position=0,
        bbox_json=json.dumps({}),
        ocr_text=visible_text, ocr_title=title, ocr_author=author, ocr_publisher=publisher,
        spine_height_cm=spine_h, spine_thickness_cm=spine_t,
        resolved_title="", resolved_author="", resolved_edition="", resolved_isbn="",
        id_confidence=0.0,
        status=status, rare_flag_reason=rflag,
        replacement_cost_json=None, used_value_json=None,
        dedup_key=dk,
    )

    revisit = legibility in ("unreadable", "partial") or status == "needs_appraisal"
    notes = []
    if revisit:
        notes.append("revisit")
        await send({
            "type": "revisit",
            "kind": "book",
            "id": book_id,
            "hint": "Need a clearer look at that spine — pan back slowly.",
            "shelf_hint": shelf_hint,
            "title": title,
        })

    await send({
        "type": "inventory_update",
        "new_books": [{
            "id": book_id,
            "title": title,
            "author": author,
            "status": status,
            "id_confidence": 0.0,
            "spine_height_cm": spine_h,
            "spine_thickness_cm": spine_t,
            "scale_method": scale_method,
            "image_url": "",
            "price_label": "",
            "processing": True,
        }],
        "new_items": [],
        "notes": notes,
    })

    # Heavy work off the Live turn — Gemini keeps talking / seeing.
    _spawn_bg(
        bg_tasks,
        _enrich_book(
            book_id=book_id, sweep_id=sweep_id, country=country,
            title=title, author=author, publisher=publisher,
            legibility=legibility, rare=rare, rflag=rflag,
            spine_h=spine_h, spine_t=spine_t, scale_method=scale_method,
            books=books, pricing=pricing, send=send,
        ),
    )

    return {
        "ok": True,
        "status": status,
        "logged_title": title,
        "revisit": revisit,
        "hint": "Ask the user to look back at that shelf for a clearer spine." if revisit else "",
        "spine_height_cm": spine_h,
        "enriching": True,
    }, revisit


async def _enrich_book(
    *, book_id: str, sweep_id: str, country: str,
    title: str, author: str, publisher: str, legibility: str,
    rare: bool, rflag: str, spine_h: float, spine_t: float, scale_method: str,
    books: BookResolver, pricing: PricingService, send: SendFn,
) -> None:
    resolved = None
    if legibility != "unreadable" and (title or author):
        try:
            resolved = await books.resolve(title, author, publisher)
        except Exception as e:
            log.warning("resolve failed: %s", e)

    status = "unidentified"
    if rare:
        status = "needs_appraisal"
    elif resolved and resolved.source != "none":
        status = "identified"

    rc_json = uv_json = None
    price_label = ""
    image_url = (resolved.cover_url if resolved else "") or ""
    currency = ""

    if status == "identified" and resolved:
        try:
            rc = await pricing.price_book_new(resolved.title, resolved.author, resolved.isbn, country)
            if rc.amount and rc.source:
                rc_json = json.dumps({
                    "amount": rc.amount, "source": rc.source, "url": rc.url,
                    "retrieved_at": rc.retrieved_at, "converted": rc.converted,
                    "condition_assumed": rc.condition_assumed, "thumbnail": rc.thumbnail,
                })
                price_label = f"{rc.currency} {rc.amount:,.2f}"
                currency = rc.currency
                if rc.thumbnail and not image_url:
                    image_url = rc.thumbnail
            uv = await pricing.price_book_used(resolved.title, resolved.author, resolved.isbn, country)
            if uv.amount and uv.source:
                uv_json = json.dumps({
                    "amount": uv.amount, "source": uv.source, "url": uv.url,
                    "retrieved_at": uv.retrieved_at, "converted": uv.converted,
                    "condition_assumed": uv.condition_assumed, "thumbnail": uv.thumbnail,
                })
                if not price_label:
                    price_label = f"~{uv.currency} {uv.amount:,.2f} used"
                    currency = uv.currency
                if uv.thumbnail and not image_url:
                    image_url = uv.thumbnail
        except Exception as e:
            log.warning("pricing failed: %s", e)

    storage.patch_book_candidate(
        book_id,
        resolved_title=resolved.title if resolved else "",
        resolved_author=resolved.author if resolved else "",
        resolved_edition=resolved.edition if resolved else "",
        resolved_isbn=resolved.isbn if resolved else "",
        id_confidence=resolved.confidence if resolved else 0.0,
        status=status,
        rare_flag_reason=rflag,
        replacement_cost_json=rc_json,
        used_value_json=uv_json,
    )

    with contextlib.suppress(Exception):
        await send({
            "type": "inventory_update",
            "new_books": [{
                "id": book_id,
                "title": (resolved.title if resolved and resolved.title else title),
                "author": (resolved.author if resolved and resolved.author else author),
                "status": status,
                "id_confidence": resolved.confidence if resolved else 0.0,
                "spine_height_cm": spine_h,
                "spine_thickness_cm": spine_t,
                "scale_method": scale_method,
                "image_url": image_url,
                "price_label": price_label,
                "currency": currency,
                "processing": False,
            }],
            "new_items": [],
            "notes": [],
        })


async def _tool_log_item(
    args: dict[str, Any], sweep_id: str, country: str,
    pricing: PricingService, send: SendFn,
    bg_tasks: set[asyncio.Task],
) -> tuple[dict[str, Any], bool]:
    category = args.get("category", "other")
    description = (args.get("description") or "").strip()
    brand_model = (args.get("brand_model") or "").strip()
    needs_appraisal = bool(args.get("needs_appraisal", False))
    reason = (args.get("appraisal_reason") or "").strip()

    dk = item_dedup_key(category, description, brand_model)
    status = "needs_appraisal" if needs_appraisal else "logging"

    item_id = f"it_{uuid.uuid4().hex[:10]}"
    storage.upsert_item_candidate(
        id=item_id, sweep_id=sweep_id, frame_id="live",
        category=category, description=description, brand_model=brand_model,
        dims_json=json.dumps({}),
        status=status, replacement_cost_json=None,
        confidence=0.6, dedup_key=dk,
    )

    revisit = needs_appraisal
    if revisit:
        await send({
            "type": "revisit",
            "kind": "item",
            "id": item_id,
            "hint": "Need a closer look — is that an original or a print?",
            "description": description,
        })

    await send({
        "type": "inventory_update",
        "new_books": [],
        "new_items": [{
            "id": item_id, "category": category,
            "description": description, "brand_model": brand_model,
            "status": status, "appraisal_reason": reason,
            "image_url": "", "price_label": "", "processing": True,
        }],
        "notes": ["revisit"] if revisit else [],
    })

    if not needs_appraisal:
        _spawn_bg(
            bg_tasks,
            _enrich_item(
                item_id=item_id, country=country,
                category=category, description=description, brand_model=brand_model,
                reason=reason, pricing=pricing, send=send,
            ),
        )
    else:
        # Mark processing done — awaiting user answer, not a web search.
        with contextlib.suppress(Exception):
            await send({
                "type": "inventory_update",
                "new_books": [],
                "new_items": [{
                    "id": item_id, "category": category,
                    "description": description, "brand_model": brand_model,
                    "status": status, "appraisal_reason": reason,
                    "image_url": "", "price_label": "", "processing": False,
                }],
                "notes": [],
            })

    return {
        "ok": True,
        "status": status,
        "revisit": revisit,
        "hint": "Ask if it is an original or a print, then look again if needed." if revisit else "",
        "enriching": not needs_appraisal,
    }, revisit


async def _enrich_item(
    *, item_id: str, country: str,
    category: str, description: str, brand_model: str, reason: str,
    pricing: PricingService, send: SendFn,
) -> None:
    status = "range"
    rc_json = None
    price_label = ""
    image_url = ""
    try:
        rng = await pricing.price_item_range(category, description, brand_model, country)
        if rng.get("source"):
            rc_json = json.dumps(rng)
            status = "priced" if rng.get("low") == rng.get("high") else "range"
            lo, hi = rng.get("low") or 0, rng.get("high") or 0
            if lo and hi and lo != hi:
                price_label = f"{lo:,.0f}–{hi:,.0f}"
            elif lo:
                price_label = f"{lo:,.2f}"
            image_url = rng.get("thumbnail") or ""
    except Exception as e:
        log.warning("item pricing failed: %s", e)

    storage.patch_item_candidate(
        item_id, status=status, replacement_cost_json=rc_json,
    )
    with contextlib.suppress(Exception):
        await send({
            "type": "inventory_update",
            "new_books": [],
            "new_items": [{
                "id": item_id, "category": category,
                "description": description, "brand_model": brand_model,
                "status": status, "appraisal_reason": reason,
                "image_url": image_url, "price_label": price_label, "processing": False,
            }],
            "notes": [],
        })


def _tool_wall(args: dict[str, Any], sweep_id: str) -> tuple[dict[str, Any], bool]:
    label = args.get("wall_label")
    length_m = float(args.get("length_m", 0) or 0)
    if length_m <= 0:
        return {"ok": False, "error": "length must be positive"}, False
    patch: dict[str, Any] = {}
    if label == "length":
        patch["length_m"] = length_m
    elif label == "width":
        patch["width_m"] = length_m
    elif label == "ceiling_height":
        patch["height_m"] = length_m
    if not patch:
        return {"ok": False, "error": "unknown wall_label"}, False
    storage.update_room(sweep_id, **patch, scale_method="user_pacing", confidence=0.7)
    # If we have both length and width, compute floor area
    room = storage.get_room(sweep_id) or {}
    if room.get("length_m") and room.get("width_m"):
        floor = round(room["length_m"] * room["width_m"], 2)
        height = room.get("height_m") or 2.5
        wall_area = round(2 * (room["length_m"] + room["width_m"]) * height, 2)
        storage.update_room(sweep_id, floor_area_m2=floor, wall_area_m2=wall_area)
    return {"ok": True, **patch}, False


def _tool_sync(args: dict[str, Any], sweep_id: str) -> tuple[dict[str, Any], bool]:
    try:
        json_path, html_path = save_packet(sweep_id)
        return {"ok": True, "json": str(json_path.name), "html": str(html_path.name)}, False
    except Exception as e:
        log.exception("sync_inventory failed: %s", e)
        return {"ok": False, "error": str(e)}, False


@router.websocket("/ws/live")
async def live_ws(ws: WebSocket) -> None:
    await ws.accept()
    settings = get_settings()
    if not settings.gemini_api_key:
        await ws.send_json({"type": "error", "message": "GEMINI_API_KEY not set on backend"})
        await ws.close()
        return

    # Wait for the start handshake
    try:
        first = await ws.receive_text()
        start = json.loads(first)
    except Exception:
        await ws.close()
        return
    if start.get("type") != "start":
        await ws.send_json({"type": "error", "message": "first message must be type=start"})
        await ws.close()
        return

    country = (start.get("country") or settings.default_country).upper()
    currency = start.get("currency") or settings.default_currency
    sweep_id = f"sw_{uuid.uuid4().hex[:10]}"
    started_at = datetime.now(timezone.utc)
    storage.insert_sweep(sweep_id, started_at.isoformat(), start.get("device", ""), country, currency)

    # Serialize all outbound WS frames so tool/inventory traffic cannot interleave
    # with PCM chunks and stall the browser playback timeline.
    send_lock = asyncio.Lock()

    async def send(payload: dict[str, Any]) -> None:
        async with send_lock:
            await ws.send_json(payload)

    await send({"type": "session", "sweep_id": sweep_id, "model": LIVE_MODEL_ID})

    # The google-genai SDK defaults to an API version Gemini Live rejects.
    # v1beta is where BidiGenerateContent lives for the AI Studio endpoint.
    client = genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
    books_res = BookResolver()
    pricing = PricingService()
    config = build_live_config(country=country, currency=currency)

    tool_tasks: dict[str, asyncio.Task] = {}
    tasks: set[asyncio.Task] = set()
    bg_tasks: set[asyncio.Task] = set()

    async def run_and_respond(fc, live_session) -> None:
        name = str(fc.name or "")
        args = dict(fc.args or {})
        call_id = str(fc.id or uuid.uuid4().hex)
        urgent = False
        try:
            await send({"type": "tool", "name": name, "args": args, "phase": "running", "id": call_id})
            result, urgent = await _run_tool(
                name, args, sweep_id, country, books_res, pricing, send, bg_tasks,
            )
            await send({"type": "tool", "name": name, "phase": "done", "result": result, "id": call_id})
        except Exception as e:
            log.exception("tool failed")
            result = {"error": str(e)}
            with contextlib.suppress(Exception):
                await send({"type": "tool", "name": name, "phase": "error", "result": result, "id": call_id})
        sched = scheduling_for(urgent=urgent)
        await live_session.send_tool_response(function_responses=[
            types.FunctionResponse(id=call_id, name=name, response=result, scheduling=sched),
        ])

    try:
        async with client.aio.live.connect(model=LIVE_MODEL_ID, config=config) as live_session:
            await send({"type": "ready"})

            async def client_to_gemini() -> None:
                while True:
                    raw = await ws.receive_text()
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    kind = msg.get("type")
                    if kind == "audio":
                        data = base64.b64decode(msg.get("data", ""))
                        # Drop odd-length PCM frames — they corrupt Int16 decode on Gemini.
                        if len(data) >= 2 and len(data) % 2 == 0:
                            await live_session.send_realtime_input(
                                audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"),
                            )
                    elif kind == "video":
                        data = base64.b64decode(msg.get("data", ""))
                        if data and data[:3] == b"\xff\xd8\xff":
                            await live_session.send_realtime_input(
                                video=types.Blob(data=data, mime_type="image/jpeg"),
                            )
                    elif kind == "text":
                        text = (msg.get("text") or "").strip()
                        if text:
                            await live_session.send_client_content(
                                turns=types.Content(role="user", parts=[types.Part(text=text)]),
                                turn_complete=True,
                            )
                    elif kind == "close":
                        return

            async def gemini_to_client() -> None:
                # receive() can end between turns; keep reopening until the client hangs up.
                while True:
                    async for response in live_session.receive():
                        if response.tool_call and response.tool_call.function_calls:
                            for fc in response.tool_call.function_calls:
                                if str(fc.id) in tool_tasks:
                                    continue
                                t = asyncio.create_task(run_and_respond(fc, live_session))
                                tool_tasks[str(fc.id)] = t
                                def _cleanup(done, key=str(fc.id)):
                                    tool_tasks.pop(key, None)
                                t.add_done_callback(_cleanup)
                        content = response.server_content
                        if not content:
                            continue
                        if content.interrupted:
                            await send({"type": "interrupted"})
                        for speaker, chunk in (("User", content.input_transcription),
                                               ("Agent", content.output_transcription)):
                            if chunk and chunk.text:
                                await send({
                                    "type": "transcript",
                                    "speaker": speaker,
                                    "text": chunk.text,
                                    "final": bool(getattr(chunk, "finished", False)),
                                })
                        if content.model_turn and not content.interrupted:
                            for part in content.model_turn.parts or []:
                                if part.inline_data and part.inline_data.data:
                                    mime = part.inline_data.mime_type or ""
                                    if mime.startswith("audio/pcm"):
                                        await send({
                                            "type": "audio",
                                            "data": base64.b64encode(part.inline_data.data).decode(),
                                            "mime_type": mime,
                                        })

            tasks.add(asyncio.create_task(client_to_gemini()))
            tasks.add(asyncio.create_task(gemini_to_client()))
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=20 * 60)
            for t in done:
                # client_to_gemini returns on close; gemini_to_client should not finish early.
                with contextlib.suppress(asyncio.CancelledError):
                    t.result()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("live session failed: %s", e)
        with contextlib.suppress(Exception):
            await send({"type": "error", "message": f"live session failed: {e}"})
    finally:
        # Let in-flight resolve/price finish so the packet isn't half-empty.
        if bg_tasks:
            with contextlib.suppress(Exception):
                await asyncio.wait(bg_tasks, timeout=45)
            for t in list(bg_tasks):
                if not t.done():
                    t.cancel()
            with contextlib.suppress(Exception):
                await asyncio.gather(*bg_tasks, return_exceptions=True)
        # Build final packet
        try:
            duration = (datetime.now(timezone.utc) - started_at).total_seconds()
            storage.finalize_sweep(sweep_id, duration)
            json_path, html_path = save_packet(sweep_id)
            with contextlib.suppress(Exception):
                await send({
                    "type": "packet_ready",
                    "sweep_id": sweep_id,
                    "json_url": f"/sweeps/{sweep_id}/claim_packet.json",
                    "html_url": f"/sweeps/{sweep_id}/report.html",
                })
        except Exception:
            log.exception("packet build failed")
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*tasks, return_exceptions=True)
        await books_res.close()
        await pricing.close()
        with contextlib.suppress(Exception):
            await ws.close()
