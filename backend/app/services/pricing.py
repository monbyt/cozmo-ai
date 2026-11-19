"""Locale-aware pricing via SerpAPI (Google Shopping) and used-book sources.

Hard rules per brief:
- Every price carries source, retrieved_at, URL, condition.
- No source → row excluded from totals, sent to review queue.
- Rare/signed/antiquarian → needs_appraisal, no auto-price.
- Locale is a setting; we reprice the same book under a second locale for the demo deliverable.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

# Minimal country -> {google_domain, hl, gl, currency} map. Extend as needed.
LOCALES: dict[str, dict[str, str]] = {
    "US": {"google_domain": "google.com", "hl": "en", "gl": "us", "currency": "USD"},
    "GB": {"google_domain": "google.co.uk", "hl": "en", "gl": "uk", "currency": "GBP"},
    "DE": {"google_domain": "google.de", "hl": "de", "gl": "de", "currency": "EUR"},
    "FR": {"google_domain": "google.fr", "hl": "fr", "gl": "fr", "currency": "EUR"},
    "ES": {"google_domain": "google.es", "hl": "es", "gl": "es", "currency": "EUR"},
    "IT": {"google_domain": "google.it", "hl": "it", "gl": "it", "currency": "EUR"},
    "NL": {"google_domain": "google.nl", "hl": "nl", "gl": "nl", "currency": "EUR"},
    "CA": {"google_domain": "google.ca", "hl": "en", "gl": "ca", "currency": "CAD"},
    "AU": {"google_domain": "google.com.au", "hl": "en", "gl": "au", "currency": "AUD"},
    "TR": {"google_domain": "google.com.tr", "hl": "tr", "gl": "tr", "currency": "TRY"},
    "IN": {"google_domain": "google.co.in", "hl": "en", "gl": "in", "currency": "INR"},
    "JP": {"google_domain": "google.co.jp", "hl": "ja", "gl": "jp", "currency": "JPY"},
}


RARE_SIGNAL_KEYWORDS = {"first edition", "1st edition", "signed", "limited", "numbered", "antiquarian", "rare"}

# Digital / non-physical product markers — exclude from replacement cost.
_DIGITAL_MARKERS = (
    "ebook", "e-book", "kindle", "nook", "kobo", "audiobook", "audio book",
    "digital", "pdf", "epub", "mp3", "download",
)

# Preferred physical retailers per locale (lowercased substrings). Soft preference only.
_RETAILER_PREFER = {
    "US": ("amazon", "barnes", "bookshop", "powell", "books-a-million", "walmart", "target"),
    "GB": ("amazon", "waterstones", "blackwell", "whsmith", "bookshop", "foyles"),
    "DE": ("amazon", "thalia", "hugendubel"),
    "CA": ("amazon", "indigo", "chapters"),
    "AU": ("amazon", "booktopia", "dymocks"),
}


@dataclass
class PriceResult:
    amount: float
    source: str
    url: str
    retrieved_at: str
    currency: str
    converted: bool = False
    condition_assumed: str = ""
    error: str = ""  # populated if no reliable price found
    thumbnail: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_rare(signals: list[str], ocr_title: str = "") -> tuple[bool, str]:
    blob = " ".join(signals + [ocr_title]).lower()
    for kw in RARE_SIGNAL_KEYWORDS:
        if kw in blob:
            return True, f"matched '{kw}'"
    return False, ""


_NUM_RE = re.compile(r"(\d+[\.,]?\d*)")


def _parse_price_string(s: str) -> float | None:
    if not s:
        return None
    # Normalize European decimal format: "€12,99" -> "12.99"
    s = s.replace("\xa0", " ").strip()
    # Remove thousands separators heuristically
    # If both "," and "." present, the last one is the decimal separator
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # If only comma: assume decimal if 1-2 digits after
        tail = s.split(",")[-1]
        if len(tail) <= 2 and tail.isdigit():
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    m = _NUM_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


class PricingService:
    def __init__(self):
        self.key = get_settings().serpapi_key
        self.http = httpx.AsyncClient(timeout=15.0)

    async def close(self):
        await self.http.aclose()

    def _locale(self, country: str) -> dict[str, str]:
        return LOCALES.get(country.upper(), LOCALES["US"])

    async def _serpapi_shopping(self, query: str, country: str) -> list[dict[str, Any]]:
        if not self.key:
            return []
        loc = self._locale(country)
        params = {
            "engine": "google_shopping",
            "q": query,
            "api_key": self.key,
            "google_domain": loc["google_domain"],
            "hl": loc["hl"],
            "gl": loc["gl"],
        }
        try:
            r = await self.http.get("https://serpapi.com/search", params=params)
            r.raise_for_status()
            data = r.json() or {}
            return data.get("shopping_results", []) or []
        except Exception as e:
            log.warning("serpapi shopping failed for %r: %s", query, e)
            return []

    def _is_digital(self, r: dict[str, Any]) -> bool:
        blob = " ".join([
            str(r.get("title") or ""),
            str(r.get("source") or ""),
            str(r.get("snippet") or ""),
            str(r.get("product_link") or ""),
            str(r.get("link") or ""),
        ]).lower()
        return any(m in blob for m in _DIGITAL_MARKERS)

    def _pick_physical(self, results: list[dict[str, Any]], country: str) -> tuple[float, str, str, str] | None:
        """Median of top physical listings, preferring known retailers. Never returns digital."""
        prefer = _RETAILER_PREFER.get(country.upper(), _RETAILER_PREFER["US"])
        picks: list[tuple[float, str, str, str, int]] = []
        for r in results[:12]:
            if self._is_digital(r):
                continue
            price = _parse_price_string(
                r.get("extracted_price") and str(r["extracted_price"]) or r.get("price", "")
            )
            url = r.get("product_link") or r.get("link", "")
            source = r.get("source", "") or "google_shopping"
            thumb = r.get("thumbnail") or r.get("thumb") or ""
            if not price or not url:
                continue
            boost = 1 if any(p in source.lower() for p in prefer) else 0
            picks.append((price, source, url, thumb, boost))
        if not picks:
            return None
        # Prefer retailer-matched, then take median of up to 5 cheapest remaining.
        picks.sort(key=lambda x: (-x[4], x[0]))
        top = picks[:5]
        top.sort(key=lambda x: x[0])
        mid = top[len(top) // 2]
        return mid[0], mid[1], mid[2], mid[3]

    async def price_book_new(self, title: str, author: str, isbn: str, country: str) -> PriceResult:
        if not (title or isbn):
            return PriceResult(0, "", "", now_iso(), self._locale(country)["currency"], error="no_query")
        # Prefer physical hardcover/paperback wording to push ebooks down.
        base = isbn or f"{title} {author}".strip()
        query = f"{base} hardcover paperback book"
        results = await self._serpapi_shopping(query, country)
        if not results:
            results = await self._serpapi_shopping(base, country)
        if not results:
            return PriceResult(0, "", "", now_iso(), self._locale(country)["currency"], error="no_results")

        picked = self._pick_physical(results, country)
        if not picked:
            return PriceResult(0, "", "", now_iso(), self._locale(country)["currency"], error="no_sourced_price")
        price, source, url, thumb = picked
        return PriceResult(
            amount=price,
            source=source or "google_shopping",
            url=url,
            retrieved_at=now_iso(),
            currency=self._locale(country)["currency"],
            converted=False,
            condition_assumed="new",
            thumbnail=thumb,
        )

    async def price_book_used(self, title: str, author: str, isbn: str, country: str) -> PriceResult:
        # SerpAPI Google Shopping with "used" qualifier. Condition assumed = "good".
        query = (isbn or f"{title} {author}").strip() + " used book"
        results = await self._serpapi_shopping(query, country)
        picked = self._pick_physical(results, country) if results else None
        if not picked:
            return PriceResult(0, "", "", now_iso(), self._locale(country)["currency"], error="no_sourced_price")
        price, source, url, thumb = picked
        return PriceResult(
            amount=price,
            source=source or "google_shopping_used",
            url=url,
            retrieved_at=now_iso(),
            currency=self._locale(country)["currency"],
            converted=False,
            condition_assumed="good",
            thumbnail=thumb,
        )

    async def price_item_range(self, category: str, description: str, brand_model: str, country: str) -> dict[str, Any]:
        """Non-book items: return low/high range plus the best single source URL.
        Status will be 'range' unless brand_model is specific and we hit a single clear SKU."""
        query = " ".join([brand_model, description]).strip() or category
        results = await self._serpapi_shopping(query, country)
        if not results:
            return {"low": 0, "high": 0, "source": "", "url": "", "retrieved_at": now_iso(),
                    "error": "no_results"}
        prices = []
        src = ""
        url = ""
        thumb = ""
        for r in results[:10]:
            p = _parse_price_string(r.get("extracted_price") and str(r["extracted_price"]) or r.get("price", ""))
            if p:
                prices.append(p)
                if not url:
                    url = r.get("product_link") or r.get("link", "")
                    src = r.get("source", "google_shopping")
                    thumb = r.get("thumbnail") or r.get("thumb") or ""
        if not prices:
            return {"low": 0, "high": 0, "source": "", "url": "", "thumbnail": "",
                    "retrieved_at": now_iso(), "error": "no_sourced_price"}
        prices.sort()
        # Trim outliers at the ends
        n = len(prices)
        lo = prices[max(0, n // 10)]
        hi = prices[min(n - 1, int(n * 0.9))]
        return {"low": lo, "high": hi, "source": src, "url": url, "thumbnail": thumb,
                "retrieved_at": now_iso()}
