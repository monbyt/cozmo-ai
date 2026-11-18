"""Resolve OCR'd spine text to a canonical work/edition.

Strategy:
1. Query OpenLibrary search with title + author.
2. Rank candidates by string similarity + author match.
3. If top candidate's score is below threshold → status 'unidentified' (we don't guess).
4. Fall back to Google Books if OpenLibrary returns nothing.

Confident wrong > blank, per the brief — err on unidentified."""
from __future__ import annotations
import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

ID_CONFIDENCE_THRESHOLD = 0.72


@dataclass
class ResolvedBook:
    title: str
    author: str
    edition: str
    isbn: str
    confidence: float
    source: str  # "openlibrary" | "googlebooks" | "none"
    rare_signals_from_source: list[str]
    cover_url: str = ""


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


class BookResolver:
    def __init__(self):
        self.gb_key = get_settings().google_books_api_key
        self.http = httpx.AsyncClient(timeout=10.0)

    async def close(self):
        await self.http.aclose()

    async def _openlibrary_search(self, title: str, author: str) -> list[dict[str, Any]]:
        if not title and not author:
            return []
        params = {"limit": 5}
        if title:
            params["title"] = title
        if author:
            params["author"] = author
        try:
            r = await self.http.get("https://openlibrary.org/search.json", params=params)
            r.raise_for_status()
            return (r.json() or {}).get("docs", [])
        except Exception as e:
            log.warning("openlibrary search failed: %s", e)
            return []

    async def _googlebooks_search(self, title: str, author: str) -> list[dict[str, Any]]:
        if not title and not author:
            return []
        q_parts = []
        if title:
            q_parts.append(f'intitle:"{title}"')
        if author:
            q_parts.append(f'inauthor:"{author}"')
        params: dict[str, Any] = {"q": "+".join(q_parts), "maxResults": 5}
        if self.gb_key:
            params["key"] = self.gb_key
        try:
            r = await self.http.get("https://www.googleapis.com/books/v1/volumes", params=params)
            r.raise_for_status()
            return (r.json() or {}).get("items", [])
        except Exception as e:
            log.warning("googlebooks search failed: %s", e)
            return []

    def _score_openlibrary(self, doc: dict[str, Any], title: str, author: str) -> float:
        t_score = _similar(doc.get("title", ""), title) if title else 0.5
        a_list = doc.get("author_name", []) or []
        a_score = max((_similar(a, author) for a in a_list), default=0.0) if author else 0.5
        # Weight title heavier — it's usually what OCR gets best
        return 0.65 * t_score + 0.35 * a_score

    def _score_googlebooks(self, item: dict[str, Any], title: str, author: str) -> float:
        info = item.get("volumeInfo", {})
        t_score = _similar(info.get("title", ""), title) if title else 0.5
        authors = info.get("authors", []) or []
        a_score = max((_similar(a, author) for a in authors), default=0.0) if author else 0.5
        return 0.65 * t_score + 0.35 * a_score

    async def resolve(self, ocr_title: str, ocr_author: str, ocr_publisher: str = "") -> ResolvedBook:
        title = (ocr_title or "").strip()
        author = (ocr_author or "").strip()

        # OpenLibrary first
        ol_docs = await self._openlibrary_search(title, author)
        best_ol = None
        best_ol_score = 0.0
        for doc in ol_docs:
            s = self._score_openlibrary(doc, title, author)
            if s > best_ol_score:
                best_ol_score = s
                best_ol = doc

        if best_ol and best_ol_score >= ID_CONFIDENCE_THRESHOLD:
            isbn_list = best_ol.get("isbn", []) or []
            isbn = isbn_list[0] if isbn_list else ""
            cover_id = best_ol.get("cover_i")
            cover_url = ""
            if cover_id:
                cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
            elif isbn:
                cover_url = f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"
            return ResolvedBook(
                title=best_ol.get("title", ""),
                author=(best_ol.get("author_name") or [""])[0],
                edition=best_ol.get("edition_key", [""])[0] if best_ol.get("edition_key") else "",
                isbn=isbn,
                confidence=round(best_ol_score, 3),
                source="openlibrary",
                rare_signals_from_source=[],
                cover_url=cover_url,
            )

        # Google Books fallback
        gb_items = await self._googlebooks_search(title, author)
        best_gb = None
        best_gb_score = 0.0
        for item in gb_items:
            s = self._score_googlebooks(item, title, author)
            if s > best_gb_score:
                best_gb_score = s
                best_gb = item

        if best_gb and best_gb_score >= ID_CONFIDENCE_THRESHOLD:
            info = best_gb.get("volumeInfo", {})
            isbns = []
            for ident in info.get("industryIdentifiers", []) or []:
                isbns.append(ident.get("identifier", ""))
            images = info.get("imageLinks") or {}
            cover = (images.get("thumbnail") or images.get("smallThumbnail") or "").replace("http://", "https://")
            return ResolvedBook(
                title=info.get("title", ""),
                author=(info.get("authors") or [""])[0],
                edition=info.get("publisher", ""),
                isbn=next((i for i in isbns if i), ""),
                confidence=round(best_gb_score, 3),
                source="googlebooks",
                rare_signals_from_source=[],
                cover_url=cover,
            )

        # Below threshold on both
        best_score = max(best_ol_score, best_gb_score)
        return ResolvedBook(
            title="", author="", edition="", isbn="",
            confidence=round(best_score, 3),
            source="none",
            rare_signals_from_source=[],
        )
