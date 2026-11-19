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
from ..services.dedup import (
    book_dedup_key,
    find_matching_book,
    find_matching_item,
    item_dedup_key,
)
from ..services.cost_tracker import CostTracker
from ..services.live_tools import LIVE_MODEL_ID, build_live_config, scheduling_for
from ..services.measurement import (
    PlaneAnchor, aggregate_room, format_spine_cm, shelved_wall_area_m2,
)
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
    *,
    latest_frame_id: str = "live",
    cost: CostTracker | None = None,
    end_requested: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Execute a tool from Gemini Live. Returns (result_for_model, urgent)."""
    if name == "log_book_spine":
        return await _tool_log_book(
            args, sweep_id, country, books, pricing, send, bg_tasks,
            frame_id=latest_frame_id, cost=cost,
        )
    if name == "log_non_book_item":
        return await _tool_log_item(
            args, sweep_id, country, pricing, send, bg_tasks,
            frame_id=latest_frame_id, cost=cost,
        )
    if name == "apply_correction":
        return await _tool_correct(args, sweep_id, country, pricing, send, bg_tasks)
    if name == "record_room_dimensions":
        return _tool_room(args, sweep_id)
    if name == "ask_calibration":
        return {
            "ok": True,
            "skip": True,
            "say": "Ask one short room-size question if needed, or use record_room_dimensions from a visible reference.",
        }, False
    if name == "record_wall_measurement":
        return _tool_wall(args, sweep_id)
    if name == "sync_inventory":
        # Never finalize mid-sweep — only after the client sends end_sweep.
        if not end_requested:
            return {
                "ok": False,
                "skipped": True,
                "hint": (
                    "Sweep is still in progress. Do NOT end. "
                    "Keep logging visible spines/items. Wait for the user to end the sweep."
                ),
            }, False
        return await _tool_sync(args, sweep_id, send, cost=cost)
    return {"error": f"Unknown tool {name}"}, False


def _spawn_bg(bg_tasks: set[asyncio.Task], coro) -> None:
    task = asyncio.create_task(coro)
    bg_tasks.add(task)
    task.add_done_callback(bg_tasks.discard)


async def _tool_log_book(
    args: dict[str, Any], sweep_id: str, country: str,
    books: BookResolver, pricing: PricingService, send: SendFn,
    bg_tasks: set[asyncio.Task],
    *,
    frame_id: str = "live",
    cost: CostTracker | None = None,
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

    # Never invent: empty title + unreadable stays unidentified.
    if not title and legibility != "unreadable":
        legibility = "unreadable"

    # Dedup: exact key + fuzzy match against books already in this sweep.
    dk = book_dedup_key(title, author, shelf_hint, 0)
    if storage.book_exists_by_dedup(sweep_id, dk):
        return {
            "ok": True,
            "deduplicated": True,
            "hint": "Duplicate — silent, keep capturing other spines.",
        }, False
    match = find_matching_book(
        storage.get_books(sweep_id), title=title, author=author, shelf=shelf_hint,
    )
    if match:
        return {
            "ok": True,
            "deduplicated": True,
            "hint": "Duplicate — silent, keep capturing other spines.",
            "existing_id": match.get("id"),
        }, False

    rare, rare_reason = is_rare([rare_signal] if rare_signal else [], title)
    status = "needs_appraisal" if rare else ("unidentified" if legibility == "unreadable" else "logging")
    rflag = rare_reason if rare else ""
    # Standard book formats are an allowed metric-scale source per the brief.
    spine_h, spine_t, scale_method = format_spine_cm(format_hint)

    book_id = f"bk_{uuid.uuid4().hex[:10]}"
    storage.upsert_book_candidate(
        id=book_id, sweep_id=sweep_id, frame_id=frame_id or "live",
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
    if cost:
        cost.bump("books_logged")

    # Unreadable/partial → log silently and keep walking. Do NOT AR-nag every blurry spine.
    # Rare books: flag for appraisal; agent may ask one short clarifying question later.
    notes: list[str] = []
    if status == "unidentified":
        notes.append("unidentified")
    if status == "needs_appraisal":
        notes.append("needs_appraisal")

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
            "shelf": shelf_hint,
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

    total = len(storage.get_books(sweep_id)) + len(storage.get_items(sweep_id))
    milestone = total > 0 and total % 5 == 0
    return {
        "ok": True,
        "status": status,
        "logged_title": title,
        "revisit": False,
        "total_logged": total,
        "hint": (
            f"Stay silent except say once: 'Logged {total} items.' Then keep logging."
            if milestone
            else "Stay silent — chime handles confirm. Immediately log the next spine."
        ),
        "spine_height_cm": spine_h,
        "enriching": True,
    }, False


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

    rc_obj: dict[str, Any] | None = None
    uv_obj: dict[str, Any] | None = None
    price_label = ""
    image_url = (resolved.cover_url if resolved else "") or ""
    currency = ""

    if status == "identified" and resolved:
        try:
            rc = await pricing.price_book_new(resolved.title, resolved.author, resolved.isbn, country)
            if rc.amount and rc.source:
                rc_obj = {
                    "amount": rc.amount, "source": rc.source, "url": rc.url,
                    "retrieved_at": rc.retrieved_at, "converted": rc.converted,
                    "condition_assumed": rc.condition_assumed, "currency": rc.currency,
                    "thumbnail": rc.thumbnail,
                }
                price_label = f"{rc.currency} {rc.amount:,.2f} new"
                currency = rc.currency
                if rc.thumbnail and not image_url:
                    image_url = rc.thumbnail
            uv = await pricing.price_book_used(resolved.title, resolved.author, resolved.isbn, country)
            if uv.amount and uv.source:
                uv_obj = {
                    "amount": uv.amount, "source": uv.source, "url": uv.url,
                    "retrieved_at": uv.retrieved_at, "converted": uv.converted,
                    "condition_assumed": uv.condition_assumed, "currency": uv.currency,
                    "thumbnail": uv.thumbnail,
                }
                used_bit = f"~{uv.currency} {uv.amount:,.2f} used"
                price_label = f"{price_label} · {used_bit}" if price_label else used_bit
                currency = currency or uv.currency
                if uv.thumbnail and not image_url:
                    image_url = uv.thumbnail
        except Exception as e:
            log.warning("pricing failed: %s", e)
    elif status == "needs_appraisal":
        price_label = "needs appraisal"
    elif status == "unidentified":
        price_label = "unpriced — unread spine"

    storage.patch_book_candidate(
        book_id,
        resolved_title=resolved.title if resolved else "",
        resolved_author=resolved.author if resolved else "",
        resolved_edition=resolved.edition if resolved else "",
        resolved_isbn=resolved.isbn if resolved else "",
        id_confidence=resolved.confidence if resolved else 0.0,
        status=status,
        rare_flag_reason=rflag,
        replacement_cost_json=json.dumps(rc_obj) if rc_obj else None,
        used_value_json=json.dumps(uv_obj) if uv_obj else None,
    )

    with contextlib.suppress(Exception):
        await send({
            "type": "inventory_update",
            "new_books": [{
                "id": book_id,
                "title": (resolved.title if resolved and resolved.title else title),
                "author": (resolved.author if resolved and resolved.author else author),
                "edition": (resolved.edition if resolved else "") or "",
                "isbn": (resolved.isbn if resolved else "") or "",
                "status": status,
                "id_confidence": resolved.confidence if resolved else 0.0,
                "spine_height_cm": spine_h,
                "spine_thickness_cm": spine_t,
                "scale_method": scale_method,
                "image_url": image_url,
                "price_label": price_label,
                "currency": currency,
                "replacement_cost": rc_obj or {},
                "used_value": uv_obj or {},
                "processing": False,
            }],
            "new_items": [],
            "notes": [],
        })


async def _tool_log_item(
    args: dict[str, Any], sweep_id: str, country: str,
    pricing: PricingService, send: SendFn,
    bg_tasks: set[asyncio.Task],
    *,
    frame_id: str = "live",
    cost: CostTracker | None = None,
) -> tuple[dict[str, Any], bool]:
    category = args.get("category", "other")
    description = (args.get("description") or "").strip()
    brand_model = (args.get("brand_model") or "").strip()
    needs_appraisal = bool(args.get("needs_appraisal", False))
    reason = (args.get("appraisal_reason") or "").strip()
    dims = {
        "w": float(args.get("approx_width_cm") or 0),
        "h": float(args.get("approx_height_cm") or 0),
        "d": float(args.get("approx_depth_cm") or 0),
    }

    # Art / portraits default to needs_appraisal unless user later marks print.
    if category == "artwork":
        needs_appraisal = True
        reason = reason or "artwork defaults to needs_appraisal"

    dk = item_dedup_key(category, description, brand_model)
    existing_items = storage.get_items(sweep_id)
    if any(i.get("dedup_key") == dk for i in existing_items) or find_matching_item(
        existing_items, category=category, description=description, brand_model=brand_model,
    ):
        return {
            "ok": True,
            "deduplicated": True,
            "hint": "Duplicate — silent, keep capturing.",
        }, False

    status = "needs_appraisal" if needs_appraisal else "logging"

    item_id = f"it_{uuid.uuid4().hex[:10]}"
    storage.upsert_item_candidate(
        id=item_id, sweep_id=sweep_id, frame_id=frame_id or "live",
        category=category, description=description, brand_model=brand_model,
        dims_json=json.dumps(dims),
        status=status, replacement_cost_json=None,
        confidence=0.6, dedup_key=dk,
    )
    if cost:
        cost.bump("items_logged")
    # Keep shelved wall area current as shelving units appear.
    if category == "shelving":
        storage.update_room(
            sweep_id, shelved_wall_area_m2=shelved_wall_area_m2(storage.get_items(sweep_id)),
        )

    # Art/portrait: ask ONCE via voice later — no AR "go back" spam.
    if needs_appraisal:
        await send({
            "type": "revisit",
            "kind": "item",
            "id": item_id,
            "hint": "Original or a print?",
            "ask_once": True,
            "description": description,
        })

    await send({
        "type": "inventory_update",
        "new_books": [],
        "new_items": [{
            "id": item_id, "category": category,
            "description": description, "brand_model": brand_model,
            "status": status, "appraisal_reason": reason,
            "image_url": "",
            "price_label": "needs appraisal" if needs_appraisal else "",
            "processing": not needs_appraisal,
        }],
        "notes": ["needs_appraisal"] if needs_appraisal else [],
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

    total = len(storage.get_books(sweep_id)) + len(storage.get_items(sweep_id))
    milestone = total > 0 and total % 5 == 0
    if needs_appraisal:
        hint = "Stay silent. Ask once later 'original or print?' then keep logging."
    elif milestone:
        hint = f"Stay silent except say once: 'Logged {total} items.' Then keep logging."
    else:
        hint = "Stay silent — chime handles confirm. Immediately log the next item."
    return {
        "ok": True,
        "status": status,
        "revisit": False,
        "total_logged": total,
        "hint": hint,
        "enriching": not needs_appraisal,
    }, False


async def _enrich_item(
    *, item_id: str, country: str,
    category: str, description: str, brand_model: str, reason: str,
    pricing: PricingService, send: SendFn,
) -> None:
    status = "range"
    rc_obj: dict[str, Any] = {}
    price_label = ""
    image_url = ""
    try:
        rng = await pricing.price_item_range(category, description, brand_model, country)
        if rng.get("source"):
            rc_obj = rng
            status = "priced" if rng.get("low") == rng.get("high") else "range"
            lo, hi = rng.get("low") or 0, rng.get("high") or 0
            src = rng.get("source") or ""
            if lo and hi and lo != hi:
                price_label = f"{lo:,.0f}–{hi:,.0f} ({src})"
            elif lo:
                price_label = f"{lo:,.2f} ({src})"
            image_url = rng.get("thumbnail") or ""
        else:
            price_label = "no sourced price"
            status = "range"
    except Exception as e:
        log.warning("item pricing failed: %s", e)
        price_label = "pricing failed"

    storage.patch_item_candidate(
        item_id, status=status,
        replacement_cost_json=json.dumps(rc_obj) if rc_obj else None,
    )
    with contextlib.suppress(Exception):
        await send({
            "type": "inventory_update",
            "new_books": [],
            "new_items": [{
                "id": item_id, "category": category,
                "description": description, "brand_model": brand_model,
                "status": status, "appraisal_reason": reason,
                "image_url": image_url, "price_label": price_label,
                "replacement_cost": rc_obj,
                "processing": False,
            }],
            "notes": [],
        })


async def _tool_correct(
    args: dict[str, Any], sweep_id: str, country: str,
    pricing: PricingService, send: SendFn,
    bg_tasks: set[asyncio.Task],
) -> tuple[dict[str, Any], bool]:
    """Mutate inventory from a spoken user correction."""
    action = (args.get("action") or "").strip()
    target_id = (args.get("target_id") or "").strip()
    shelf_hint = (args.get("shelf_hint") or "").strip().lower()
    edition = (args.get("edition") or "").strip()
    note = (args.get("note") or "").strip()

    books = storage.get_books(sweep_id)
    items = storage.get_items(sweep_id)

    def _latest_book() -> dict | None:
        return books[-1] if books else None

    def _latest_item() -> dict | None:
        return items[-1] if items else None

    if action == "mark_rare":
        b = next((x for x in books if x["id"] == target_id), None) or _latest_book()
        if not b:
            return {"ok": False, "error": "no book to mark"}, True
        storage.patch_book_candidate(
            b["id"], status="needs_appraisal",
            rare_flag_reason=note or "user: first edition / rare / signed",
            replacement_cost_json=None, used_value_json=None,
        )
        storage.add_review(sweep_id, b["id"], note or "user flagged rare — needs appraisal")
        await send({
            "type": "inventory_update",
            "new_books": [{"id": b["id"], "status": "needs_appraisal",
                           "price_label": "needs appraisal", "processing": False}],
            "new_items": [], "notes": ["needs_appraisal"],
        })
        return {"ok": True, "action": action, "id": b["id"],
                "hint": "Acknowledge once: flagged for appraisal."}, True

    if action == "set_edition":
        b = next((x for x in books if x["id"] == target_id), None) or _latest_book()
        if not b:
            return {"ok": False, "error": "no book"}, True
        storage.patch_book_candidate(b["id"], resolved_edition=edition or note or "user-stated edition")
        if any(k in (edition or note).lower() for k in ("first", "1st", "signed", "limited")):
            storage.patch_book_candidate(
                b["id"], status="needs_appraisal",
                rare_flag_reason=f"user edition: {edition or note}",
                replacement_cost_json=None, used_value_json=None,
            )
        return {"ok": True, "action": action, "id": b["id"],
                "hint": "Acknowledge once: edition noted."}, True

    if action == "mark_print":
        it = next((x for x in items if x["id"] == target_id), None) or _latest_item()
        if not it:
            return {"ok": False, "error": "no item"}, True
        storage.patch_item_candidate(it["id"], status="logging")
        _spawn_bg(
            bg_tasks,
            _enrich_item(
                item_id=it["id"], country=country,
                category=it.get("category") or "artwork",
                description=it.get("description") or "",
                brand_model=it.get("brand_model") or "",
                reason="user: print", pricing=pricing, send=send,
            ),
        )
        return {"ok": True, "action": action, "id": it["id"],
                "hint": "Acknowledge once: noted as a print, pricing it."}, True

    if action == "mark_original":
        it = next((x for x in items if x["id"] == target_id), None) or _latest_item()
        if not it:
            return {"ok": False, "error": "no item"}, True
        storage.patch_item_candidate(
            it["id"], status="needs_appraisal", replacement_cost_json=None,
        )
        storage.add_review(sweep_id, it["id"], "user: original art — needs appraisal")
        return {"ok": True, "action": action, "id": it["id"],
                "hint": "Acknowledge once: left for appraisal."}, True

    if action == "skip_shelf":
        removed = 0
        for b in books:
            shelf = (b.get("shelf") or "").lower()
            if shelf_hint and shelf_hint in shelf:
                storage.delete_book(b["id"])
                removed += 1
        storage.add_review(sweep_id, "shelf", f"skipped shelf '{shelf_hint}' — not theirs ({removed} removed)")
        await send({
            "type": "inventory_update",
            "new_books": [], "new_items": [],
            "notes": [f"skipped_shelf:{removed}"],
            "removed_ids": [b["id"] for b in books if shelf_hint in (b.get("shelf") or "").lower()],
        })
        return {"ok": True, "action": action, "removed": removed,
                "hint": f"Acknowledge once: skipping that shelf ({removed} cleared)."}, True

    if action == "remove_last":
        b = _latest_book()
        if b:
            storage.delete_book(b["id"])
            storage.add_review(sweep_id, b["id"], "removed by user correction")
            await send({
                "type": "inventory_update",
                "new_books": [], "new_items": [],
                "notes": ["removed"],
                "removed_ids": [b["id"]],
            })
            return {"ok": True, "action": action, "id": b["id"],
                    "hint": "Acknowledge once: removed."}, True
        return {"ok": False, "error": "nothing to remove"}, True

    return {"ok": False, "error": f"unknown action {action}"}, False


def _tool_room(args: dict[str, Any], sweep_id: str) -> tuple[dict[str, Any], bool]:
    """Room geometry from the same sweep (visual reference or user-stated)."""
    length_m = float(args.get("length_m") or 0)
    width_m = float(args.get("width_m") or 0)
    height_m = float(args.get("height_m") or 0) or 2.4
    if length_m <= 0 or width_m <= 0:
        return {"ok": False, "error": "length_m and width_m must be positive"}, False
    # Normalise so length is the longer side.
    if width_m > length_m:
        length_m, width_m = width_m, length_m
    scale_method = (args.get("scale_method") or "visual_reference").strip()
    confidence = float(args.get("confidence") or 0.55)
    confidence = max(0.0, min(1.0, confidence))
    shelved = float(args.get("shelved_wall_area_m2") or 0)
    floor = round(length_m * width_m, 2)
    wall = round(2 * (length_m + width_m) * height_m, 2)
    if shelved <= 0:
        shelved = shelved_wall_area_m2(storage.get_items(sweep_id))
    storage.update_room(
        sweep_id,
        length_m=round(length_m, 2),
        width_m=round(width_m, 2),
        height_m=round(height_m, 2),
        floor_area_m2=floor,
        wall_area_m2=wall,
        shelved_wall_area_m2=round(shelved, 2),
        scale_method=scale_method,
        confidence=confidence,
    )
    return {
        "ok": True,
        "length_m": round(length_m, 2),
        "width_m": round(width_m, 2),
        "height_m": round(height_m, 2),
        "floor_area_m2": floor,
        "floor_area_ft2": round(floor * 10.7639, 1),
        "wall_area_m2": wall,
        "shelved_wall_area_m2": round(shelved, 2),
        "scale_method": scale_method,
        "hint": "Stay silent or one short confirm. Keep logging books and non-book items.",
    }, False


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
    storage.update_room(sweep_id, **patch, scale_method="user_stated", confidence=0.7)
    room = storage.get_room(sweep_id) or {}
    if room.get("length_m") and room.get("width_m"):
        floor = round(room["length_m"] * room["width_m"], 2)
        height = room.get("height_m") or 2.4
        wall_area = round(2 * (room["length_m"] + room["width_m"]) * height, 2)
        storage.update_room(sweep_id, floor_area_m2=floor, wall_area_m2=wall_area)
    return {"ok": True, **patch}, False


def _build_summary(sweep_id: str) -> dict[str, Any]:
    """Rubric-facing summary for voice readback + client sheet."""
    from ..services.packet import build_packet

    packet = build_packet(sweep_id)
    t = packet.totals
    room = packet.room
    ocr_by_id = {
        r["id"]: (r.get("resolved_title") or r.get("ocr_title") or "(unreadable)")
        for r in storage.get_books(sweep_id)
    }
    books_preview = [
        {
            "title": (b.title or ocr_by_id.get(b.id) or "(unreadable)"),
            "status": b.status,
            "spine_cm": b.spine_height_cm,
            "replacement": (b.replacement_cost.amount if b.replacement_cost else None),
            "used": (b.used_value.amount if b.used_value else None),
        }
        for b in packet.books[:12]
    ]
    items_preview = [
        {
            "description": i.description or i.category,
            "category": i.category,
            "status": i.status,
            "price_low": (i.replacement_cost.low if i.replacement_cost else None),
            "price_high": (i.replacement_cost.high if i.replacement_cost else None),
        }
        for i in packet.items[:12]
    ]
    return {
        "book_count": t.book_count,
        "books_identified": t.books_identified,
        "books_unidentified": t.books_unidentified,
        "shelf_run_m": t.shelf_run_m,
        "books_replacement_cost": t.books_replacement_cost,
        "books_used_value": t.books_used_value,
        "item_count": len(packet.items),
        "items_replacement_cost_low": t.items_replacement_cost_low,
        "items_replacement_cost_high": t.items_replacement_cost_high,
        "excluded_from_totals": t.excluded_from_totals,
        "review_queue_count": len(packet.review_queue),
        "room": {
            "length_m": room.length_m,
            "width_m": room.width_m,
            "height_m": room.height_m,
            "floor_area_m2": room.floor_area_m2,
            "floor_area_ft2": round(room.floor_area_m2 * 10.7639, 1) if room.floor_area_m2 else 0,
            "wall_area_m2": room.wall_area_m2,
            "shelved_wall_area_m2": room.shelved_wall_area_m2,
            "scale_method": room.scale_method,
            "confidence": room.confidence,
        },
        "books_preview": books_preview,
        "items_preview": items_preview,
        "speak": (
            f"{t.book_count} books, {t.books_identified} identified, "
            f"{len(packet.items)} other items. "
            f"Floor about {room.floor_area_m2:.1f} square metres. "
            f"{len(packet.review_queue)} lines need review. Packet ready."
        ),
    }


async def _tool_sync(
    args: dict[str, Any], sweep_id: str, send: SendFn | None = None,
    *,
    cost: CostTracker | None = None,
) -> tuple[dict[str, Any], bool]:
    try:
        # Recompute shelved wall area from shelving items before packet build.
        shelved = shelved_wall_area_m2(storage.get_items(sweep_id))
        storage.update_room(sweep_id, shelved_wall_area_m2=shelved)
        json_path, html_path = save_packet(sweep_id)
        if cost:
            cost.write(storage.SWEEPS_DIR / sweep_id)
        summary = _build_summary(sweep_id)
        if send is not None:
            with contextlib.suppress(Exception):
                await send({
                    "type": "packet_ready",
                    "sweep_id": sweep_id,
                    "json_url": f"/sweeps/{sweep_id}/claim_packet.json",
                    "html_url": f"/sweeps/{sweep_id}/report.html",
                    "summary": summary,
                })
        return {
            "ok": True,
            "json": str(json_path.name),
            "html": str(html_path.name),
            "summary": summary,
            # No "say this" hint — the end_sweep handler speaks the summary once.
            "hint": "Packet already built. Stay silent — do not speak or call tools.",
        }, False
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
    cost = CostTracker(sweep_id=sweep_id)

    # Serialize outbound WS frames. Audio uses a coalescer so the phone gets
    # fewer, larger PCM blobs (less JSON churn → fewer "welcome….in….usd" gaps).
    send_lock = asyncio.Lock()
    audio_coalesce: dict[str, Any] = {"buf": bytearray(), "flush_task": None}

    async def send(payload: dict[str, Any]) -> None:
        async with send_lock:
            await ws.send_json(payload)

    async def _flush_audio_coalesce() -> None:
        audio_coalesce["flush_task"] = None
        raw = bytes(audio_coalesce["buf"])
        audio_coalesce["buf"].clear()
        if not raw:
            return
        await send({
            "type": "audio",
            "data": base64.b64encode(raw).decode(),
            "mime_type": "audio/pcm;rate=24000",
        })

    async def send_audio_pcm(data: bytes, _mime: str = "") -> None:
        """Batch ~120ms of PCM before sending to reduce WS chatter on the phone."""
        audio_coalesce["buf"].extend(data)
        # 24kHz mono PCM16 → 48000 bytes/sec; ~120ms ≈ 5760 bytes
        if len(audio_coalesce["buf"]) >= 5760:
            t = audio_coalesce.get("flush_task")
            if t is not None:
                t.cancel()
                audio_coalesce["flush_task"] = None
            await _flush_audio_coalesce()
        else:
            t = audio_coalesce.get("flush_task")
            if t is None or t.done():
                async def _delayed() -> None:
                    await asyncio.sleep(0.08)
                    await _flush_audio_coalesce()
                audio_coalesce["flush_task"] = asyncio.create_task(_delayed())

    await send({"type": "session", "sweep_id": sweep_id, "model": LIVE_MODEL_ID})

    # The google-genai SDK defaults to an API version Gemini Live rejects.
    # v1beta is where BidiGenerateContent lives for the AI Studio endpoint.
    client = genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
    books_res = BookResolver()
    pricing = PricingService()

    tool_tasks: dict[str, asyncio.Task] = {}
    bg_tasks: set[asyncio.Task] = set()
    plane_anchors: list[PlaneAnchor] = []
    # Evidence frames: every Nth video JPEG is persisted; books/items point at the latest.
    latest_frame: dict[str, str] = {"id": "live"}
    frame_counter = {"n": 0}
    last_saved_frame_at = {"t": 0.0}
    # Gate tool logs until real camera frames arrive — prevents hallucinated burst at start.
    video_ready = {"ok": False, "count": 0}
    # Intro must finish speaking (start_tracking + client audio drain) before logging.
    tracking = {"ok": False, "pending": False}
    recent_logs = {"t": 0.0, "n": 0}
    end_gate = {"ok": False}

    # Shared across Gemini reconnects — client WS stays up; only Live is reset.
    session_box: dict[str, Any] = {"s": None}
    mute_audio = False
    client_done = asyncio.Event()
    refuse_reset = asyncio.Event()
    # Large enough that continuous mic PCM isn't dropped under video load.
    inbound: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=256)

    def _persist_video_frame(data: bytes) -> str | None:
        """Save evidence JPEG at most ~1/sec. Returns frame filename or None."""
        import time as _time
        now = _time.monotonic()
        if now - last_saved_frame_at["t"] < 1.0:
            return None
        if len(data) < 500:
            return None
        frame_counter["n"] += 1
        # Globally unique — bare f_0001 collides across sweeps in SQLite.
        fid = f"{sweep_id}_f{frame_counter['n']:04d}"
        frame_dir = storage.FRAMES_DIR / sweep_id
        frame_dir.mkdir(parents=True, exist_ok=True)
        path = frame_dir / f"f_{frame_counter['n']:04d}.jpg"
        try:
            path.write_bytes(data)
            storage.insert_frame(
                fid, sweep_id, datetime.now(timezone.utc).isoformat(),
                str(path), 0, 0, 0.0, 0.0, None,
            )
            latest_frame["id"] = fid
            last_saved_frame_at["t"] = now
            cost.bump("frames_saved")
            return fid
        except Exception as e:
            log.warning("frame save failed: %s", e)
            return None

    REFUSAL_PHRASES = (
        "language model",
        "i can't help",
        "i cannot help",
        "can't assist",
        "cannot assist",
        "as an ai",
        "i'm just a",
        "i am just a",
        "i can't do that",
        "i cannot do that",
        "unable to help",
    )

    def _resume_note() -> str:
        n_books = len(storage.get_books(sweep_id))
        n_items = len(storage.get_items(sweep_id))
        return (
            f"RESUME mid-sweep: already logged {n_books} books and {n_items} items. "
            "Do not re-log those. Continue capturing NEW spines/items only. "
            "Say 'still logging' once, then keep tool-calling."
        )

    async def run_and_respond(fc) -> None:
        live_session = session_box.get("s")
        if live_session is None:
            return
        name = str(fc.name or "")
        args = dict(fc.args or {})
        call_id = str(fc.id or uuid.uuid4().hex)
        urgent = False
        result: dict[str, Any] = {}
        try:
            await send({"type": "tool", "name": name, "args": args, "phase": "running", "id": call_id})
            inventory_tools = ("log_book_spine", "log_non_book_item", "record_room_dimensions")
            if name == "start_tracking":
                # Model finished the intro *text* — wait for the phone to finish
                # playing the intro *voice* before unlocking inventory.
                # Do NOT include a "say" hint — that made the model talk again and
                # cut the intro short.
                if tracking["ok"]:
                    result = {"ok": True, "already": True}
                else:
                    tracking["pending"] = True
                    await send({"type": "phase", "phase": "intro_done"})
                    result = {
                        "ok": True,
                        "hint": "Stay silent. Wait for the app to confirm tracking.",
                    }
            elif name in inventory_tools and not tracking["ok"]:
                result = {
                    "ok": False,
                    "skipped": True,
                    "hint": (
                        "Intro not finished. Speak the greeting completely, then call "
                        "start_tracking. Do NOT log anything yet."
                    ),
                }
            elif name in ("log_book_spine", "log_non_book_item") and (
                not video_ready["ok"] or video_ready["count"] < 2
            ):
                # Block inventory tools until we have real video — stops invented burst logs.
                result = {
                    "ok": False,
                    "skipped": True,
                    "hint": (
                        "No clear camera frame yet. Do NOT invent items. "
                        "Wait for real video before logging."
                    ),
                }
            else:
                # Soft rate limit: max 3 inventory logs / 2s to stop hallucination floods.
                import time as _time
                now = _time.monotonic()
                if name in ("log_book_spine", "log_non_book_item"):
                    if now - recent_logs["t"] > 2.0:
                        recent_logs["t"] = now
                        recent_logs["n"] = 0
                    recent_logs["n"] += 1
                    if recent_logs["n"] > 5:
                        result = {
                            "ok": False,
                            "skipped": True,
                            "hint": "Too many logs too fast — pause. Only log clearly NEW visible items.",
                        }
                if not result:
                    timer = cost.stage(f"tool_{name}")
                    timer.start()
                    result, urgent = await _run_tool(
                        name, args, sweep_id, country, books_res, pricing, send, bg_tasks,
                        latest_frame_id=latest_frame["id"], cost=cost,
                        end_requested=end_gate["ok"],
                    )
                    timer.stop()
            await send({"type": "tool", "name": name, "phase": "done", "result": result, "id": call_id})
        except Exception as e:
            log.exception("tool failed")
            result = {"error": str(e)}
            with contextlib.suppress(Exception):
                await send({"type": "tool", "name": name, "phase": "error", "result": result, "id": call_id})
        sess = session_box.get("s")
        if sess is None:
            return
        sched = scheduling_for(urgent=urgent)
        with contextlib.suppress(Exception):
            await sess.send_tool_response(function_responses=[
                types.FunctionResponse(id=call_id, name=name, response=result, scheduling=sched),
            ])

    async def client_reader() -> None:
        """Read phone WS once; fan into queue so Gemini can reconnect underneath."""
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                kind = msg.get("type")
                if kind == "close":
                    await inbound.put(None)
                    client_done.set()
                    return
                if kind == "plane":
                    try:
                        plane_anchors.append(PlaneAnchor(
                            kind=str(msg.get("kind") or "other"),
                            area_m2=float(msg.get("area_m2") or 0),
                            width_m=float(msg.get("width_m") or 0),
                            height_m=float(msg.get("height_m") or 0),
                        ))
                        agg = aggregate_room(plane_anchors)
                        storage.update_room(
                            sweep_id,
                            **agg,
                            scale_method="arkit_plane_detection",
                            confidence=0.8 if plane_anchors else 0.0,
                        )
                    except Exception as e:
                        log.warning("plane update failed: %s", e)
                    continue
                if kind == "tracking_ready":
                    # Client finished playing the intro voice — unlock logging now.
                    tracking["ok"] = True
                    tracking["pending"] = False
                    with contextlib.suppress(Exception):
                        await send({"type": "phase", "phase": "tracking"})
                    continue
                if kind == "end_sweep":
                    end_gate["ok"] = True
                    # Finalize once server-side — do NOT ask the model to call sync again
                    # (that was causing the "saved for your claim" loop).
                    sync_result, _ = await _tool_sync(
                        {"reason": "client_end_sweep"}, sweep_id, send, cost=cost,
                    )
                    speak = ""
                    if isinstance(sync_result, dict):
                        speak = (sync_result.get("summary") or {}).get("speak") or ""
                    msg = {
                        "type": "text",
                        "text": (
                            "The sweep is over. Say the following summary ONCE in one short "
                            "paragraph, then stay completely silent. Do not repeat. Do not "
                            "call any tools. Do not say anything about saving documents again.\n\n"
                            f"{speak or 'Sweep complete. Packet ready.'}"
                        ),
                    }
                # Never drop mic audio — under pressure, drop video frames only.
                kind_q = msg.get("type")
                if kind_q == "video":
                    with contextlib.suppress(asyncio.QueueFull):
                        inbound.put_nowait(msg)
                else:
                    while True:
                        try:
                            inbound.put_nowait(msg)
                            break
                        except asyncio.QueueFull:
                            dropped = None
                            with contextlib.suppress(asyncio.QueueEmpty):
                                dropped = inbound.get_nowait()
                            # If we popped audio, put it back ahead of us (prefer older audio).
                            if dropped and dropped.get("type") == "audio":
                                with contextlib.suppress(asyncio.QueueFull):
                                    inbound.put_nowait(dropped)
                                break
        except WebSocketDisconnect:
            await inbound.put(None)
            client_done.set()
        except Exception:
            log.exception("client_reader failed")
            await inbound.put(None)
            client_done.set()

    audio_stats = {"n": 0, "bytes": 0, "last_log": 0.0}

    async def pump_to_gemini() -> None:
        """Forward phone A/V + scan ticks. Auto-VAD needs a continuous audio stream."""
        while not client_done.is_set():
            msg = await inbound.get()
            if msg is None:
                return
            sess = session_box.get("s")
            if sess is None:
                # Gemini not connected yet — don't discard mic/video; retry shortly.
                await asyncio.sleep(0.05)
                with contextlib.suppress(asyncio.QueueFull):
                    if msg.get("type") != "video":
                        inbound.put_nowait(msg)
                continue
            kind = msg.get("type")
            try:
                if kind == "audio":
                    data = base64.b64decode(msg.get("data", ""))
                    if len(data) >= 2 and len(data) % 2 == 0:
                        audio_stats["n"] += 1
                        audio_stats["bytes"] += len(data)
                        import time as _time
                        now = _time.monotonic()
                        if now - audio_stats["last_log"] > 5.0:
                            audio_stats["last_log"] = now
                            log.info(
                                "mic uplink: %s chunks / %s KB (sweep=%s)",
                                audio_stats["n"], audio_stats["bytes"] // 1024, sweep_id,
                            )
                        await sess.send_realtime_input(
                            audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"),
                        )
                elif kind == "video":
                    if end_gate["ok"]:
                        continue  # stop feeding camera after End
                    data = base64.b64decode(msg.get("data", ""))
                    mime = ""
                    if data[:3] == b"\xff\xd8\xff":
                        mime = "image/jpeg"
                    elif len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
                        mime = "image/png"
                    if data and mime:
                        video_ready["count"] += 1
                        if video_ready["count"] >= 2:
                            video_ready["ok"] = True
                        if mime == "image/jpeg":
                            _persist_video_frame(data)
                        await sess.send_realtime_input(
                            video=types.Blob(data=data, mime_type=mime),
                        )
                elif kind == "text":
                    text = (msg.get("text") or "").strip()
                    if text:
                        await sess.send_client_content(
                            turns=types.Content(
                                role="user", parts=[types.Part(text=text)],
                            ),
                            turn_complete=True,
                        )
                elif kind == "look_tick":
                    if not tracking["ok"] or not video_ready["ok"] or end_gate["ok"]:
                        continue
                    n_books = len(storage.get_books(sweep_id))
                    n_items = len(storage.get_items(sweep_id))
                    room = storage.get_room(sweep_id) or {}
                    has_room = bool(room.get("floor_area_m2"))
                    # Tool-only nudge — do not speak unless directing capture.
                    await sess.send_realtime_input(
                        text=(
                            f"[scan silent] books={n_books} items={n_items} room={has_room}. "
                            "Tool-call only if you clearly see something NEW. "
                            "Speak only if you need a better view or a short clarification. "
                            "Never invent. Never sync. Never repeat yourself."
                        ),
                    )
            except Exception as e:
                log.warning("pump_to_gemini send failed: %s", e)
                refuse_reset.set()
                return

    async def look_heartbeat() -> None:
        """Occasional silent scan nudge — only after intro→tracking, never after End."""
        for _ in range(80):
            if client_done.is_set() or refuse_reset.is_set() or end_gate["ok"]:
                return
            if tracking["ok"] and video_ready["ok"]:
                break
            await asyncio.sleep(0.25)
        if not tracking["ok"] or end_gate["ok"]:
            return
        await asyncio.sleep(2.0)
        while not client_done.is_set() and not refuse_reset.is_set() and not end_gate["ok"]:
            try:
                inbound.put_nowait({"type": "look_tick"})
            except asyncio.QueueFull:
                pass
            await asyncio.sleep(8.0)

    async def gemini_to_client(live_session, *, resumed: bool) -> None:
        nonlocal mute_audio
        agent_text_buf = ""
        if resumed:
            tracking["ok"] = True
            tracking["pending"] = False
            with contextlib.suppress(Exception):
                await send({"type": "phase", "phase": "tracking"})
            kick = (
                "Camera still live. Resume in full sentences. Log NEW books AND non-book items. "
                "Set room dimensions if missing. Never invent. Never sync until user ends. "
                "Finish every spoken sentence completely — never cut yourself off."
            )
        else:
            with contextlib.suppress(Exception):
                await send({"type": "phase", "phase": "intro"})
            kick = (
                "INTRO PHASE. Speak your FULL greeting out loud in two complete sentences: "
                "confirm country/currency, then explain one continuous pass covering every "
                "shelf, wall and floor. Do NOT cut yourself off. Only AFTER the last spoken "
                "word, call start_tracking with intro_done=true. Do NOT log books, items, or "
                "room before that. Do NOT call sync_inventory. Never restart mid-sentence."
            )

        with contextlib.suppress(Exception):
            await live_session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=kick)],
                ),
                turn_complete=True,
            )
        while True:
            async for response in live_session.receive():
                if refuse_reset.is_set() or client_done.is_set():
                    return
                if response.tool_call and response.tool_call.function_calls:
                    for fc in response.tool_call.function_calls:
                        if str(fc.id) in tool_tasks:
                            continue
                        t = asyncio.create_task(run_and_respond(fc))
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
                        if speaker == "User":
                            log.info("user transcript: %s", (chunk.text or "")[:120])
                        if speaker == "Agent":
                            agent_text_buf = (agent_text_buf + chunk.text)[-800:]
                            low = agent_text_buf.lower()
                            if any(p in low for p in REFUSAL_PHRASES):
                                log.warning("refusal detected — resetting Live session")
                                mute_audio = True
                                await send({"type": "interrupted"})
                                await send({
                                    "type": "banner",
                                    "text": "Reconnecting voice — keep sweeping",
                                })
                                refuse_reset.set()
                                return
                            # Kill the "saved for your insurance claim" death loop.
                            if end_gate["ok"] and low.count("insurance") + low.count("claim") >= 3:
                                mute_audio = True
                                await send({"type": "interrupted"})
                                return
                if content.model_turn and not content.interrupted and not mute_audio:
                    for part in content.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            mime = part.inline_data.mime_type or ""
                            if mime.startswith("audio/pcm"):
                                await send_audio_pcm(part.inline_data.data, mime)
                # Signal the phone when generation/turn ends so intro can wait for *voice*.
                if getattr(content, "generation_complete", False):
                    # Flush any held PCM so the last words aren't stuck in the coalescer.
                    t = audio_coalesce.get("flush_task")
                    if t is not None:
                        t.cancel()
                        audio_coalesce["flush_task"] = None
                    await _flush_audio_coalesce()
                    await send({"type": "agent_generation_complete"})
                if getattr(content, "turn_complete", False):
                    t = audio_coalesce.get("flush_task")
                    if t is not None:
                        t.cancel()
                        audio_coalesce["flush_task"] = None
                    await _flush_audio_coalesce()
                    await send({"type": "agent_turn_complete"})

    try:
        reader_task = asyncio.create_task(client_reader())
        await send({"type": "ready"})
        resume = False
        reconnects = 0
        while not client_done.is_set() and reconnects < 8:
            refuse_reset.clear()
            mute_audio = False
            config = build_live_config(
                country=country,
                currency=currency,
                resume_note=_resume_note() if resume else "",
            )
            session_tasks: set[asyncio.Task] = set()
            try:
                async with client.aio.live.connect(model=LIVE_MODEL_ID, config=config) as live_session:
                    session_box["s"] = live_session
                    if resume:
                        await send({
                            "type": "banner",
                            "text": "Voice back — keep walking, still logging",
                        })
                        log.info("Live session reconnected (attempt %s)", reconnects)
                    pump_t = asyncio.create_task(pump_to_gemini())
                    recv_t = asyncio.create_task(
                        gemini_to_client(live_session, resumed=resume),
                    )
                    beat_t = asyncio.create_task(look_heartbeat())
                    session_tasks.update((pump_t, recv_t, beat_t))
                    refuse_t = asyncio.create_task(refuse_reset.wait())
                    done_t = asyncio.create_task(client_done.wait())
                    await asyncio.wait(
                        {pump_t, recv_t, beat_t, refuse_t, done_t},
                        return_when=asyncio.FIRST_COMPLETED,
                        timeout=20 * 60,
                    )
                    for t in (pump_t, recv_t, beat_t, refuse_t, done_t):
                        t.cancel()
                    with contextlib.suppress(Exception):
                        await asyncio.gather(
                            pump_t, recv_t, beat_t, refuse_t, done_t,
                            return_exceptions=True,
                        )
            except Exception as e:
                log.exception("live connect failed: %s", e)
                await asyncio.sleep(0.6)
            finally:
                session_box["s"] = None

            if client_done.is_set():
                break
            # After End, do not reconnect — that re-greeted / re-summarized in a loop.
            if end_gate["ok"]:
                break
            if refuse_reset.is_set():
                resume = True
                reconnects += 1
                while not inbound.empty():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        inbound.get_nowait()
                await asyncio.sleep(0.35)
                continue
            resume = True
            reconnects += 1
            await asyncio.sleep(0.5)

        reader_task.cancel()
        with contextlib.suppress(Exception):
            await reader_task
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
        # Build final packet only if the user ended — never auto-complete on drop/reconnect.
        try:
            duration = (datetime.now(timezone.utc) - started_at).total_seconds()
            storage.finalize_sweep(sweep_id, duration)
            storage.update_room(
                sweep_id, shelved_wall_area_m2=shelved_wall_area_m2(storage.get_items(sweep_id)),
            )
            if end_gate["ok"]:
                json_path, html_path = save_packet(sweep_id)
                cost.bump(
                    "serpapi_search",
                    cost.counts.get("items_logged", 0) + cost.counts.get("books_logged", 0),
                )
                cost.write(storage.SWEEPS_DIR / sweep_id)
                with contextlib.suppress(Exception):
                    await send({
                        "type": "packet_ready",
                        "sweep_id": sweep_id,
                        "json_url": f"/sweeps/{sweep_id}/claim_packet.json",
                        "html_url": f"/sweeps/{sweep_id}/report.html",
                    })
            else:
                cost.write(storage.SWEEPS_DIR / sweep_id)
        except Exception:
            log.exception("packet build failed")
        client_done.set()
        refuse_reset.set()
        for t in list(tool_tasks.values()):
            t.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*tool_tasks.values(), return_exceptions=True)
        await books_res.close()
        await pricing.close()
        with contextlib.suppress(Exception):
            await ws.close()
