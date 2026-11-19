# Architecture

## One-paragraph pitch

A Flutter iOS app streams ARKit camera JPEG + microphone PCM + plane anchors to a Python FastAPI backend over `/ws/live`. The backend proxies audio+video into **Gemini Live**, which tool-calls spines and non-book items as the user walks. Background coroutines resolve books (OpenLibrary → Google Books) and price them (SerpAPI) without blocking the Live turn. ARKit planes aggregate into room floor/wall area; spine height/thickness come from standard book-format tables (brief-allowed scale source) and are labelled `standard_book_format`. At end-of-sweep, pure Python builds `claim_packet.json` + HTML report + `cost.json`. Totals are never written by a language model.

## Diagram

```
iPhone (Flutter + ARKit)                         Backend (FastAPI / Python 3.12)
─────────────────────────                        ────────────────────────────────
┌───────────────────────┐   WebSocket /ws/live   ┌──────────────────────────────┐
│ ARKitSceneView        │ ─────────────────────> │  Gemini Live proxy            │
│  • JPEG ~2 fps        │   audio PCM 16 kHz     │   tools:                      │
│  • plane anchors      │   video JPEG           │    log_book_spine             │
│  • mic PCM uplink     │   plane JSON           │    log_non_book_item          │
│  • speaker PCM down   │ <───────────────────── │    apply_correction           │
└───────────┬───────────┘   inventory_update     │    sync_inventory             │
            │               audio / transcript   │                               │
            ▼                                    │  Background (per log):        │
┌───────────────────────┐                        │   ├─ BookResolver             │
│ Live inventory UI     │ <── inventory_update   │   └─ PricingService (SerpAPI) │
│ Room map chip         │ <── plane aggregates   │                               │
│ End-sweep summary     │ <── packet_ready       │  packet.py → JSON + HTML      │
└───────────────────────┘                        │  cost_tracker → cost.json     │
                                                 └──────────────────────────────┘
                                                          │
                                                          ▼
                                                 SQLite + data/sweeps/<id>/
                                                 data/frames/<id>/f_XXXX.jpg
```

Legacy `/ws/sweep` still exists (structured Gemini vision + optional LiDAR depth per bbox) for offline smoke tests; the shipped Flutter client uses `/ws/live`.

## Stage map — which model does what

| Stage | Model / Service | Notes |
| --- | --- | --- |
| Live capture direction + OCR logging | **Gemini Live** | Sees video; tools only — no prices spoken |
| Book resolution | OpenLibrary → Google Books | Confidence &lt; 0.72 → `unidentified`, never a guess |
| Spine dimensions | Standard format tables | `scale_method = standard_book_format` |
| Room geometry | ARKit planes | `scale_method = arkit_plane_detection` |
| Book / item pricing | SerpAPI Shopping | Median of physical listings; ebooks filtered |
| Rare / signed / art | Keyword + category rules | `needs_appraisal`, no auto-price |
| Voice corrections | `apply_correction` tool | Mutates SQLite rows |
| Totals | Pure Python `packet.py` | Hard rule |
| Cost / latency | `cost_tracker.py` | Written to `cost.json` |

## Where metric scale comes from

1. **Room**: ARKit horizontal/vertical plane anchors → floor area (largest floor), wall area (sum of walls), L/W/H. Method: `arkit_plane_detection`.
2. **Spines (Live path)**: format hint → typical height + thickness cm. Method: `standard_book_format` (explicitly allowed by the brief).
3. **Spines (legacy `/ws/sweep`)**: LiDAR depth under bbox, else reference-object from a resolved trade hardcover.
4. **Shelved wall area**: sum of `w×h` of items with `category=shelving` when dims were logged; else 0 + review note.

## Where prices come from

- SerpAPI `engine=google_shopping` with locale `google_domain` / `hl` / `gl`.
- Digital markers (ebook, kindle, nook, …) excluded.
- Median of up to 5 physical hits; soft preference for known retailers.
- No source → excluded from totals + review queue.
- Second locale: `POST /sweeps/{id}/reprice?country=GB`.

## Stage latency + cost (modelled)

| Stage | Typical |
| --- | --- |
| Live tool log (persist + UI push) | &lt; 50 ms |
| OpenLibrary resolve | ~200–400 ms |
| SerpAPI shopping | ~1–2 s |
| Packet + HTML | &lt; 100 ms |
| Time to packet after End | usually &lt; 2 min (bg enrich) |

Cost per ~2 min sweep (~60 books): ~$0.50–0.90 modelled (Live minutes + SerpAPI). Exact counters land in `backend/data/sweeps/<id>/cost.json`.
