"""Glues vision + book resolution + pricing + dedup + storage.

Called per incoming frame. Keeps the websocket handler slim."""
from __future__ import annotations
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import storage
from ..config import get_settings
from .books import BookResolver
from .dedup import book_dedup_key, item_dedup_key
from .measurement import (
    DepthSample, Intrinsics, PlaneAnchor,
    aggregate_room, bbox_to_metric_from_depth, bbox_to_metric_from_reference,
    TYPICAL_HEIGHTS,
)
from .pricing import PricingService, is_rare
from .vision import VisionService

log = logging.getLogger(__name__)


class PerceptionOrchestrator:
    def __init__(self, vision: VisionService | None = None, books: BookResolver | None = None,
                 pricing: PricingService | None = None):
        self.vision = vision or VisionService()
        self.books = books or BookResolver()
        self.pricing = pricing or PricingService()
        # Track plane anchors per sweep to aggregate the room at the end.
        self._planes: dict[str, list[PlaneAnchor]] = {}
        # Track the first resolved book's spine as reference-object fallback for scale.
        self._ref_book_px_height: dict[str, float] = {}

    async def close(self):
        await self.books.close()
        await self.pricing.close()

    async def ingest_frame(
        self,
        sweep_id: str,
        frame_path: Path,
        intrinsics: dict[str, float] | None,
        depth_samples: list[dict[str, Any]] | None,
        orientation: dict[str, Any] | None,
        country: str,
        shelf_hint: str = "",
    ) -> dict[str, Any]:
        """Process a frame end-to-end. Returns incremental updates for the websocket.
        `agent_say` is a list of short lines the client should speak proactively."""
        updates: dict[str, Any] = {"new_books": [], "new_items": [], "notes": [], "agent_say": []}

        intr = None
        if intrinsics:
            intr = Intrinsics(**{k: intrinsics.get(k, 0) for k in ("fx", "fy", "cx", "cy", "width", "height")})
        depth_s = [DepthSample(**d) for d in (depth_samples or [])]

        # Run vision for spines + items in parallel
        spines_task = asyncio.to_thread(self.vision.detect_spines, frame_path)
        items_task = asyncio.to_thread(self.vision.detect_items, frame_path)
        spines_result, items_result = await asyncio.gather(spines_task, items_task, return_exceptions=True)

        if isinstance(spines_result, Exception):
            log.exception("spine detection failed: %s", spines_result)
            spines_result = {"spines": []}
        if isinstance(items_result, Exception):
            log.exception("item detection failed: %s", items_result)
            items_result = {"items": []}

        # Frame-quality note
        fq = (spines_result.get("frame_quality") or {})
        if fq.get("blur") == "severe" or fq.get("glare") == "severe":
            updates["notes"].append(f"low_quality:{fq.get('blur')}_blur,{fq.get('glare')}_glare")

        # Process spines
        for idx, spine in enumerate(spines_result.get("spines", [])):
            await self._process_spine(sweep_id, frame_path, spine, intr, depth_s, country, shelf_hint, idx, updates)

        # Process non-book items
        for idx, item in enumerate(items_result.get("items", [])):
            await self._process_item(sweep_id, frame_path, item, country, updates)

        # Proactive agent lines based on what we just learned
        new_books = updates["new_books"]
        new_items = updates["new_items"]
        if new_books:
            identified = [b for b in new_books if b["status"] == "identified"]
            if identified:
                first = identified[0]
                updates["agent_say"].append(
                    f"Got {first['title']} by {first['author']}." if first.get("author")
                    else f"Got {first['title']}."
                )
            if len(new_books) >= 3:
                updates["agent_say"].append(f"That's {len(new_books)} more spines in this frame — keep panning.")
            appraise_books = [b for b in new_books if b["status"] == "needs_appraisal"]
            if appraise_books:
                updates["agent_say"].append("Flagged a signed or rare one — I'll leave that to the appraiser.")
        for it in new_items:
            if it["status"] == "needs_appraisal":
                cat = it.get("category", "artwork")
                updates["agent_say"].append(f"I see {cat}. Is it an original or a print?")
                break  # one question at a time
        return updates

    async def _process_spine(
        self, sweep_id: str, frame_path: Path, spine: dict[str, Any],
        intr: Intrinsics | None, depth_s: list[DepthSample],
        country: str, shelf_hint: str, position: int, updates: dict[str, Any],
    ) -> None:
        bbox = spine.get("bbox") or {}
        legibility = spine.get("legibility", "unreadable")
        ocr_title = spine.get("ocr_title", "").strip()
        ocr_author = spine.get("ocr_author", "").strip()
        ocr_publisher = spine.get("ocr_publisher", "").strip()
        rare_signals = spine.get("rare_signals") or []

        # Resolve book (even if unreadable, we record the slot)
        resolved = None
        if legibility != "unreadable" and (ocr_title or ocr_author):
            resolved = await self.books.resolve(ocr_title, ocr_author, ocr_publisher)

        # Dedup
        dk = book_dedup_key(
            resolved.title if resolved else "",
            resolved.author if resolved else "",
            shelf_hint,
            position,
        )
        if storage.book_exists_by_dedup(sweep_id, dk):
            return

        # Measurement
        spine_h = spine_t = 0.0
        scale_method = ""
        if intr:
            metric = bbox_to_metric_from_depth(bbox, intr, depth_s)
            if metric:
                spine_h, spine_t, scale_method = metric
            elif resolved and resolved.source != "none":
                # First resolved book becomes the scale anchor for later unidentified ones in the same frame.
                self._ref_book_px_height[sweep_id] = bbox.get("h", 0) * intr.height
                spine_h = TYPICAL_HEIGHTS["hardcover_trade"]
                px = self._ref_book_px_height[sweep_id] or 1.0
                m = bbox_to_metric_from_reference(bbox, intr, spine_h, px)
                spine_h, spine_t, scale_method = m
            elif sweep_id in self._ref_book_px_height:
                px = self._ref_book_px_height[sweep_id]
                m = bbox_to_metric_from_reference(bbox, intr, TYPICAL_HEIGHTS["hardcover_trade"], px)
                spine_h, spine_t, scale_method = m

        # Rare flag
        rare, rare_reason = is_rare(rare_signals, ocr_title)
        status = "unidentified"
        rare_flag_reason = ""
        if rare:
            status = "needs_appraisal"
            rare_flag_reason = rare_reason
        elif resolved and resolved.source != "none":
            status = "identified"

        # Pricing — only for identified, non-rare, with a title
        rc_json = uv_json = None
        if status == "identified":
            try:
                rc = await self.pricing.price_book_new(
                    resolved.title, resolved.author, resolved.isbn, country
                )
                if rc.amount and rc.source:
                    rc_json = json.dumps({
                        "amount": rc.amount, "source": rc.source, "url": rc.url,
                        "retrieved_at": rc.retrieved_at, "converted": rc.converted,
                        "condition_assumed": rc.condition_assumed,
                    })
                uv = await self.pricing.price_book_used(
                    resolved.title, resolved.author, resolved.isbn, country
                )
                if uv.amount and uv.source:
                    uv_json = json.dumps({
                        "amount": uv.amount, "source": uv.source, "url": uv.url,
                        "retrieved_at": uv.retrieved_at, "converted": uv.converted,
                        "condition_assumed": uv.condition_assumed,
                    })
            except Exception as e:
                log.warning("pricing failed for %s: %s", resolved.title, e)

        book_id = f"bk_{uuid.uuid4().hex[:10]}"
        storage.upsert_book_candidate(
            id=book_id, sweep_id=sweep_id, frame_id=str(frame_path.name),
            shelf=shelf_hint, position=position,
            bbox_json=json.dumps(bbox),
            ocr_text=spine.get("visible_text", ""),
            ocr_title=ocr_title, ocr_author=ocr_author, ocr_publisher=ocr_publisher,
            spine_height_cm=spine_h, spine_thickness_cm=spine_t,
            resolved_title=resolved.title if resolved else "",
            resolved_author=resolved.author if resolved else "",
            resolved_edition=resolved.edition if resolved else "",
            resolved_isbn=resolved.isbn if resolved else "",
            id_confidence=resolved.confidence if resolved else 0.0,
            status=status, rare_flag_reason=rare_flag_reason,
            replacement_cost_json=rc_json, used_value_json=uv_json,
            dedup_key=dk,
        )

        updates["new_books"].append({
            "id": book_id,
            "title": resolved.title if resolved else "",
            "author": resolved.author if resolved else "",
            "status": status,
            "id_confidence": resolved.confidence if resolved else 0.0,
            "spine_height_cm": spine_h,
            "spine_thickness_cm": spine_t,
            "scale_method": scale_method,
        })

    async def _process_item(
        self, sweep_id: str, frame_path: Path, item: dict[str, Any],
        country: str, updates: dict[str, Any],
    ) -> None:
        needs_appraisal = bool(item.get("needs_appraisal", False))
        category = item.get("category", "other")
        if category == "artwork" and not item.get("description", "").lower().startswith("print"):
            needs_appraisal = True

        dedup_k = item_dedup_key(category, item.get("description", ""), item.get("brand_model", ""))
        if storage.book_exists_by_dedup(sweep_id, dedup_k):  # reuse the lookup; items share no dedup table check — accept duplicates
            pass  # don't early-return, item_candidates isn't checked by this helper

        status = "needs_appraisal" if needs_appraisal else "range"
        rc_json = None
        if not needs_appraisal:
            try:
                rng = await self.pricing.price_item_range(
                    category, item.get("description", ""), item.get("brand_model", ""), country
                )
                if rng.get("source"):
                    rc_json = json.dumps(rng)
                    status = "range" if rng["low"] != rng["high"] else "priced"
            except Exception as e:
                log.warning("item pricing failed: %s", e)

        item_id = f"it_{uuid.uuid4().hex[:10]}"
        storage.upsert_item_candidate(
            id=item_id, sweep_id=sweep_id, frame_id=str(frame_path.name),
            category=category, description=item.get("description", ""),
            brand_model=item.get("brand_model", ""),
            dims_json=json.dumps({
                "w": item.get("approx_w_cm", 0),
                "h": item.get("approx_h_cm", 0),
                "d": item.get("approx_d_cm", 0),
            }),
            status=status, replacement_cost_json=rc_json,
            confidence=0.5, dedup_key=dedup_k,
        )
        updates["new_items"].append({
            "id": item_id, "category": category,
            "description": item.get("description", ""),
            "brand_model": item.get("brand_model", ""),
            "status": status,
            "appraisal_reason": item.get("appraisal_reason", "") if needs_appraisal else "",
        })

    def record_plane(self, sweep_id: str, plane: dict[str, Any]) -> None:
        p = PlaneAnchor(
            kind=plane.get("kind", "other"),
            area_m2=float(plane.get("area_m2", 0) or 0),
            width_m=float(plane.get("width_m", 0) or 0),
            height_m=float(plane.get("height_m", 0) or 0),
        )
        self._planes.setdefault(sweep_id, []).append(p)

    def finalize_room(self, sweep_id: str) -> dict[str, Any]:
        planes = self._planes.get(sweep_id, [])
        agg = aggregate_room(planes)
        scale_method = "arkit_scene_reconstruction" if planes else "none"
        confidence = 0.8 if planes else 0.0
        storage.update_room(
            sweep_id,
            length_m=agg["length_m"], width_m=agg["width_m"], height_m=agg["height_m"],
            floor_area_m2=agg["floor_area_m2"], wall_area_m2=agg["wall_area_m2"],
            scale_method=scale_method, confidence=confidence,
        )
        if not planes:
            storage.add_review(sweep_id, "room", "no ARKit plane anchors received — room geometry unknown")
        return agg
