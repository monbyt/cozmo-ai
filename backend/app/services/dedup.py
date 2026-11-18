"""Book dedup across overlapping frames.

A book seen from multiple frames should collapse to ONE row. Simple approach:
- key = (shelf, position) for resolved books, else a hash of (resolved_title, resolved_author)
- fallback: for unidentified spines, use (shelf, position) alone — same slot across adjacent frames is a repeat

A proper solution tracks spine features across the pose graph; this is the pragmatic version."""
from __future__ import annotations
import hashlib


def book_dedup_key(resolved_title: str, resolved_author: str, shelf: str, position: int) -> str:
    base = (resolved_title or "").strip().lower() + "|" + (resolved_author or "").strip().lower()
    if base.strip("|"):
        return "r:" + hashlib.sha1(base.encode()).hexdigest()[:12]
    return f"u:{shelf}:{position}"


def item_dedup_key(category: str, description: str, brand_model: str) -> str:
    base = (category + "|" + (brand_model or description)).lower()
    return "i:" + hashlib.sha1(base.encode()).hexdigest()[:12]
