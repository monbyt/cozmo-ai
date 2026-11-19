"""Book/item dedup across overlapping Live frames.

Pragmatic keys + fuzzy title match so the same spine logged twice while panning
does not create two claim rows.
"""
from __future__ import annotations
import hashlib
import re


_PUNCT = re.compile(r"[^a-z0-9\s]")
_SPACE = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    s = (s or "").lower().strip()
    s = _PUNCT.sub(" ", s)
    s = _SPACE.sub(" ", s).strip()
    # Drop leading articles that OCR/voice often flip.
    for art in ("the ", "a ", "an "):
        if s.startswith(art):
            s = s[len(art):]
            break
    return s


def book_dedup_key(resolved_title: str, resolved_author: str, shelf: str, position: int) -> str:
    title = normalize_text(resolved_title)
    author = normalize_text(resolved_author)
    if title:
        base = f"{title}|{author}"
        return "r:" + hashlib.sha1(base.encode()).hexdigest()[:12]
    shelf_n = normalize_text(shelf) or "_"
    return f"u:{shelf_n}:{position}"


def item_dedup_key(category: str, description: str, brand_model: str) -> str:
    cat = normalize_text(category)
    brand = normalize_text(brand_model)
    desc = normalize_text(description)
    # Prefer brand+category; else first ~6 tokens of description.
    core = brand or " ".join(desc.split()[:6])
    base = f"{cat}|{core}"
    return "i:" + hashlib.sha1(base.encode()).hexdigest()[:12]


def titles_similar(a: str, b: str, *, threshold: float = 0.72) -> bool:
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) >= 5 and (na in nb or nb in na):
        return True
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return False
    return (len(ta & tb) / len(ta | tb)) >= threshold


def descriptions_similar(a: str, b: str, *, threshold: float = 0.65) -> bool:
    return titles_similar(a, b, threshold=threshold)


def find_matching_book(
    existing: list[dict],
    *,
    title: str,
    author: str,
    shelf: str,
) -> dict | None:
    """Return an existing book row that is the same physical spine, if any."""
    title_n = normalize_text(title)
    author_n = normalize_text(author)
    shelf_n = normalize_text(shelf)
    for row in existing:
        et = normalize_text(row.get("resolved_title") or row.get("ocr_title") or "")
        ea = normalize_text(row.get("resolved_author") or row.get("ocr_author") or "")
        es = normalize_text(row.get("shelf") or "")
        if title_n and et and titles_similar(title_n, et):
            # Same title: treat as dup even across shelves (user panned back).
            if not author_n or not ea or titles_similar(author_n, ea) or author_n in ea or ea in author_n:
                return row
        if not title_n and not et and shelf_n and shelf_n == es:
            # Two unidentified spines on the same shelf hint — collapse.
            return row
    return None


def find_matching_item(
    existing: list[dict],
    *,
    category: str,
    description: str,
    brand_model: str,
) -> dict | None:
    cat = normalize_text(category)
    brand = normalize_text(brand_model)
    desc = normalize_text(description)
    for row in existing:
        if normalize_text(row.get("category") or "") != cat:
            continue
        rb = normalize_text(row.get("brand_model") or "")
        rd = normalize_text(row.get("description") or "")
        if brand and rb and (brand == rb or brand in rb or rb in brand):
            return row
        if desc and rd and descriptions_similar(desc, rd):
            return row
    return None
