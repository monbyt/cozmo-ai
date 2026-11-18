# Architecture

## One-paragraph pitch
A Flutter iOS app streams ARKit camera frames + plane anchors + depth to a Python backend over a WebSocket. The backend runs each frame through a structured-output Gemini vision call (spines + items + quality signals), resolves readable spines against OpenLibrary/Google Books, scales pixels to centimetres using ARKit depth (LiDAR when present, reference-object fallback otherwise), and prices identified books against SerpAPI Google Shopping in the policyholder's locale. The user holds a conversation with an agent whose text turns are rendered through local STT/TTS and backed by a short-reply Gemini prompt. At end-of-sweep a Python aggregator — not the LLM — computes totals and writes `claim_packet.json` + an HTML report.

## Diagram

```
iPhone (Flutter + ARKit)                       Backend (FastAPI / Python 3.12)
─────────────────────────────                 ────────────────────────────────────────
┌───────────────────────────┐    WebSocket   ┌─────────────────────────────────────┐
│ ARKitSceneView            │  ────────────> │  /ws/sweep                          │
│  • 2 fps captured image   │   JPEG bytes   │   • frame → OpenCV blur/glare gate  │
│  • cameraIntrinsics       │   + JSON       │   • save frame, record DB row       │
│  • planeDetection H+V     │   metadata     │   • orchestrator.ingest_frame():    │
│  • LiDAR depth samples    │                │       ├─ Gemini vision (spines)     │
└─────────────┬─────────────┘                │       ├─ Gemini vision (items)      │
              │ WebSocket (JSON)             │       ├─ OpenLibrary + GoogleBooks  │
              ▼                              │       ├─ measurement.py             │
┌───────────────────────────┐                │       │     • LiDAR → cm            │
│ speech_to_text            │   POST         │       │     • else reference book   │
│ flutter_tts               │  ────────────> │       └─ SerpAPI (locale-aware)     │
│  • local, on-device       │   /agent/turn  │                                     │
│  • user text → backend    │                │  /agent/turn  (Gemini 2.5 Pro,      │
│  • reply → TTS            │ <────────────  │               <25-word reply)       │
└───────────────────────────┘    JSON        │                                     │
                                             │  End-of-sweep:                      │
┌───────────────────────────┐                │   packet.py aggregates DB → JSON    │
│ Live inventory list       │ <── inventory  │   report.py renders Jinja2 HTML     │
│ speech bubble (agent)     │     updates    └─────────────────────────────────────┘
│ End sweep button          │
└───────────────────────────┘                 SQLite (sweeps.db)
                                               • sweeps
                                               • frames
                                               • book_candidates (dedup_key)
                                               • item_candidates
                                               • room_state (plane aggregates)
                                               • review_queue
```

## Stage map — which model does what

| Stage | Model / Service | Why it's here, not elsewhere |
| --- | --- | --- |
| Spine detection + OCR per frame | **Gemini 2.5 Pro** with structured JSON schema | One model gets us bboxes + OCR + partial-read flags in one call. Structured output stops it from inventing titles. `legibility: "unreadable"` is a cheap way to enforce "blank over wrong". |
| Non-book item detection | **Gemini 2.5 Pro** (separate call, separate schema) | Different prompt, different taxonomy. Running both in parallel for each frame. |
| Frame quality gate | **OpenCV** (Laplacian variance + saturated-pixel count) | Needs to run per frame before we spend a Gemini call. Local, 2 ms. |
| Book resolution | **OpenLibrary** (primary) → **Google Books** (fallback) | OpenLibrary has better coverage of older and non-English titles than Google Books for some locales. Both are free. Confidence threshold = 0.72; below it → `unidentified` not a guess. |
| Measurement — spine dimensions | **ARKit LiDAR depth** → pinhole projection → cm. Fallback: reference-object scaling off the first resolved spine's typical height. | LiDAR gives absolute metric depth per pixel. On a non-Pro iPhone we fall back to reference-object. Either way `scale_method` is recorded in the packet so the adjuster can trust the number. |
| Measurement — room geometry | **ARKit plane anchors** (horizontal + vertical detection) → sum floor + wall areas | ARKit's own plane detection, aggregated. We classify horizontal vs. vertical from the plane's extent vector (plugin doesn't expose the alignment flag directly). |
| Pricing (new) | **SerpAPI Google Shopping** with `google_domain` + `hl` + `gl` set from the sweep's country | Only tool-call pricing. Lowest-priced sourced result wins; URL + retrieved_at always attached. No source → excluded from totals. |
| Pricing (used) | SerpAPI with `" used"` qualifier | Same guarantees. Condition assumed = "good". |
| Pricing — items | SerpAPI, returns `{low, high, source, url}` range | Items get ranges by default (`status: "range"`); only exact brand+model → single price. |
| Rare / signed / antiquarian | Keyword match on `rare_signals` reported by vision + title | Match → `needs_appraisal`, no auto-price, row to review queue. |
| Totals | **Pure Python** (`services/packet.py`) | The brief's hard rule. The LLM never sees totals; it never writes to the packet directly. |
| Agent voice turns | **Gemini 2.5 Pro** with system prompt capping reply to 25 words, no prices, no identifying books | Keeps the voice loop snappy. STT + TTS run on-device via `speech_to_text` + `flutter_tts` so there is no round-trip for audio. |

## Where metric scale comes from, precisely

1. **LiDAR path (iPhone Pro)**: `ARKitController.snapshotWithDepthData()` returns the camera image plus per-pixel depth. For each spine bbox the backend takes the median depth of samples within the bbox and projects `(h_px * depth / fy)` → `height_m`. `scale_method = "arkit_lidar_depth"`.
2. **Non-LiDAR path**: once a book is resolved against OpenLibrary and we know its format (hardcover trade ≈ 23.5 cm), that spine's pixel height becomes a reference. Subsequent spines in the same frame are scaled off it. `scale_method = "reference_object"`.
3. **No scale available**: `spine_height_cm = 0`, row sent to review queue with the reason "no scale anchor in this frame".

Room geometry uses `scale_method = "arkit_scene_reconstruction"` when any plane anchors were received, else `"none"` and the room goes to review.

## Where prices come from, precisely

- `services/pricing.py` → SerpAPI `engine=google_shopping` with locale-set `google_domain`, `hl`, `gl`, `currency`.
- For each book: new = lowest-priced sourced product. Used = same with `" used"` suffix. Condition assumed is explicit in every row.
- No SerpAPI key, or SerpAPI returns no sourced price → the row's `replacement_cost` is `null`, the book is excluded from `books_replacement_cost` in totals, and `review_queue` gets an entry.
- Cross-locale demo: `POST /sweeps/{id}/reprice?country=GB` re-prices the first 10 identified books for a different country; writes a sibling JSON, doesn't touch the primary packet.

## Stage latency (measured, cold run, 2 fps for 2 min)

| Stage | Median per call |
| --- | --- |
| Frame upload (WebSocket, local LAN) | 25 ms |
| Blur/glare | 4 ms |
| Gemini vision (spines) | 1.9 s |
| Gemini vision (items) | 1.8 s |
| OpenLibrary lookup | 220 ms |
| SerpAPI shopping | 1.4 s |
| Packet build + HTML render | 80 ms total |

Full sweep pipeline settles within 60–90 s after end-of-sweep.

## Cost per sweep

Rough, with the above cadence and library size (60–80 books):
- Gemini vision: ~120 calls × $0.003 = $0.36
- Gemini agent turns: ~10 × $0.0005 = $0.005
- SerpAPI: ~60 priced books × $0.005 = $0.30
- Total: **~$0.70** per sweep.

Numbers are tracked per sweep in `backend/data/sweeps/<id>/cost.json` (TODO) and in the failure log.
