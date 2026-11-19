"""Claim packet assembly. Totals are computed here in Python — never written by the LLM.

An empty field is the correct answer when we don't know. A filled field with no evidence is a defect.
Any row without a sourced price is excluded from totals and appended to the review queue."""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models.schema import (
    Book, ClaimPacket, Item, ItemDimensions, Price, PriceRange,
    ReviewItem, Room, Sweep, Totals,
)
from .. import storage

log = logging.getLogger(__name__)


def _parse_price(s: str | None) -> Price | None:
    if not s:
        return None
    try:
        d = json.loads(s)
    except Exception:
        return None
    if not d.get("amount") or not d.get("source"):
        return None
    return Price(
        amount=float(d["amount"]),
        source=d.get("source", ""),
        url=d.get("url", ""),
        retrieved_at=d.get("retrieved_at", ""),
        converted=bool(d.get("converted", False)),
        condition_assumed=d.get("condition_assumed", ""),
    )


def _parse_range(s: str | None) -> PriceRange | None:
    if not s:
        return None
    try:
        d = json.loads(s)
    except Exception:
        return None
    if not d.get("source") or (not d.get("low") and not d.get("high")):
        return None
    return PriceRange(
        low=d.get("low", 0), high=d.get("high", 0),
        source=d.get("source", ""), url=d.get("url", ""),
        retrieved_at=d.get("retrieved_at", ""),
    )


def build_packet(sweep_id: str) -> ClaimPacket:
    sweep_row = storage.get_sweep(sweep_id)
    if not sweep_row:
        raise ValueError(f"unknown sweep {sweep_id}")

    room_row = storage.get_room(sweep_id) or {}
    book_rows = storage.get_books(sweep_id)
    item_rows = storage.get_items(sweep_id)
    review_rows = storage.get_review(sweep_id)

    sweep = Sweep(
        id=sweep_row["id"],
        captured_at=sweep_row["captured_at"],
        device=sweep_row.get("device") or "",
        duration_s=sweep_row.get("duration_s") or 0,
        country=sweep_row.get("country") or "",
        currency=sweep_row.get("currency") or "",
    )

    floor_m2 = room_row.get("floor_area_m2") or 0
    wall_m2 = room_row.get("wall_area_m2") or 0
    room = Room(
        length_m=room_row.get("length_m") or 0,
        width_m=room_row.get("width_m") or 0,
        height_m=room_row.get("height_m") or 0,
        floor_area_m2=floor_m2,
        wall_area_m2=wall_m2,
        shelved_wall_area_m2=room_row.get("shelved_wall_area_m2") or 0,
        scale_method=room_row.get("scale_method") or "",
        confidence=room_row.get("confidence") or 0,
        floor_area_ft2=round(floor_m2 * 10.7639, 2) if floor_m2 else 0,
        wall_area_ft2=round(wall_m2 * 10.7639, 2) if wall_m2 else 0,
        shape_notes=(
            "rectangular from largest floor plane + vertical wall planes"
            if floor_m2 else "no ARKit planes — room geometry unknown"
        ),
    )

    books: list[Book] = []
    review_from_rows: list[ReviewItem] = list()
    totals = Totals()
    shelf_run_mm = 0.0

    for r in book_rows:
        rc = _parse_price(r.get("replacement_cost_json"))
        uv = _parse_price(r.get("used_value_json"))
        status = r.get("status") or "unidentified"

        book = Book(
            id=r["id"],
            shelf=r.get("shelf") or "",
            position=r.get("position") or 0,
            frame_ref=r.get("frame_id") or "",
            status=status,
            title=r.get("resolved_title") or "",
            author=r.get("resolved_author") or "",
            edition=r.get("resolved_edition") or "",
            isbn=r.get("resolved_isbn") or "",
            spine_height_cm=r.get("spine_height_cm") or 0,
            spine_thickness_cm=r.get("spine_thickness_cm") or 0,
            id_confidence=r.get("id_confidence") or 0,
            replacement_cost=rc,
            used_value=uv,
            rare_flag_reason=r.get("rare_flag_reason") or "",
        )
        books.append(book)

        totals.book_count += 1
        if status == "identified":
            totals.books_identified += 1
        elif status == "unidentified":
            totals.books_unidentified += 1

        if book.spine_thickness_cm > 0:
            shelf_run_mm += book.spine_thickness_cm * 10

        if status == "needs_appraisal":
            review_from_rows.append(ReviewItem(ref_id=book.id, reason=book.rare_flag_reason or "needs_appraisal"))
            totals.excluded_from_totals += 1
            continue

        if rc:
            totals.books_replacement_cost += rc.amount
        else:
            review_from_rows.append(ReviewItem(ref_id=book.id, reason="no sourced replacement price"))
            totals.excluded_from_totals += 1
        if uv:
            totals.books_used_value += uv.amount

    totals.shelf_run_m = round(shelf_run_mm / 1000, 3)

    items: list[Item] = []
    for r in item_rows:
        rng = _parse_range(r.get("replacement_cost_json"))
        status = r.get("status") or "range"
        dims = {}
        try:
            dims = json.loads(r.get("dims_json") or "{}")
        except Exception:
            dims = {}
        item = Item(
            id=r["id"],
            category=r.get("category") or "",
            description=r.get("description") or "",
            brand_model=r.get("brand_model") or "",
            frame_ref=r.get("frame_id") or "",
            dimensions_cm=ItemDimensions(
                w=dims.get("w", 0), h=dims.get("h", 0), d=dims.get("d", 0)
            ),
            status=status,
            replacement_cost=rng,
            confidence=r.get("confidence") or 0,
        )
        items.append(item)

        if status == "needs_appraisal":
            review_from_rows.append(ReviewItem(ref_id=item.id, reason="art/antique — needs appraisal"))
            totals.excluded_from_totals += 1
            continue
        if rng:
            totals.items_replacement_cost_low += rng.low
            totals.items_replacement_cost_high += rng.high
        else:
            review_from_rows.append(ReviewItem(ref_id=item.id, reason="no sourced price range"))
            totals.excluded_from_totals += 1

    review_queue = [ReviewItem(ref_id=r["ref_id"], reason=r["reason"]) for r in review_rows] + review_from_rows

    # Round money totals to 2dp for presentation (actual math stays float)
    totals.books_replacement_cost = round(totals.books_replacement_cost, 2)
    totals.books_used_value = round(totals.books_used_value, 2)
    totals.items_replacement_cost_low = round(totals.items_replacement_cost_low, 2)
    totals.items_replacement_cost_high = round(totals.items_replacement_cost_high, 2)

    return ClaimPacket(
        sweep=sweep, room=room, books=books, items=items,
        totals=totals, review_queue=review_queue,
    )


def save_packet(sweep_id: str) -> tuple[Path, Path]:
    packet = build_packet(sweep_id)
    out_dir = storage.SWEEPS_DIR / sweep_id
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "claim_packet.json"
    json_path.write_text(json.dumps(packet.model_dump(), indent=2, ensure_ascii=False))

    # HTML report
    from .report import render_report
    html_path = out_dir / "report.html"
    html_path.write_text(render_report(packet))
    return json_path, html_path
