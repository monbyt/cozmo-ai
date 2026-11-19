# Cozmo Sweep — Library Contents Claim Agent

Live voice-and-vision insurance agent that inventories and values a home library in **one continuous camera sweep**.

- **Frontend**: Flutter (iOS) with Apple ARKit for plane detection + camera. Mic/speaker stream PCM to Gemini Live.
- **Backend**: Python 3.12 FastAPI. Gemini Live for real-time voice+vision logging. OpenLibrary / Google Books for book resolution. SerpAPI (Google Shopping) for locale-aware pricing. Totals computed in Python, never by an LLM.

## Quick start

### Prerequisites

| Tool | Install |
| --- | --- |
| Homebrew | https://brew.sh |
| Flutter | `brew install --cask flutter` |
| Xcode (full) | Mac App Store → Xcode |
| CocoaPods | `brew install cocoapods` |
| Python 3.12 | `brew install python@3.12` |
| `uv` | `brew install uv` |

```sh
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -runFirstLaunch
flutter doctor
```

### 1. Backend

```sh
cd backend
cp ../.env.example .env              # fill GEMINI_API_KEY + SERPAPI_KEY
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API keys:
- `GEMINI_API_KEY` — https://aistudio.google.com/apikey (**billed** project required; free tier cannot run a full sweep)
- `SERPAPI_KEY` — https://serpapi.com/ (100 free/month). Without it, prices go to the review queue.
- `GOOGLE_BOOKS_API_KEY` — optional

Smoke check: `curl http://127.0.0.1:8000/health`

### 2. Flutter app on an iPhone

```sh
cd app
flutter pub get
flutter devices
open ios/Runner.xcworkspace          # Signing & Capabilities → Team → your Apple ID
flutter run -d <your-iphone-id>
```

In the app: pick country/currency. Backend URL defaults to the live deploy:

`wss://cozmo-claim-agent.fly.dev`

(For local backend use `ws://<your-mac-lan-ip>:8000`.) Hit **Start sweep**.

### Live demo for reviewers (web — no install)

**Send this link:** https://cozmo-claim-agent.fly.dev

Phone browser → allow camera + mic → pick country → **Start sweep**. Backend is baked in. No ARKit / no TestFlight.

| | |
| --- | --- |
| Web app | https://cozmo-claim-agent.fly.dev |
| Health | https://cozmo-claim-agent.fly.dev/health |
| Live WS | `wss://cozmo-claim-agent.fly.dev/ws/live` |
| Packet | `https://cozmo-claim-agent.fly.dev/sweeps/<id>/claim_packet.json` |

Redeploy web+API: `cd web && npm run build && cd ../backend && fly deploy -a cozmo-claim-agent`

### 3. Walk the room

- One continuous pass under ~3 minutes. Agent logs from video, asks you to slow down / step closer when needed.
- Interrupt by voice: "that's a first edition", "skip that shelf, those aren't mine", "it's a print".
- Tap **End sweep**. Packet within ~1–5 minutes.

### 4. Open the packet

- `http://<backend>/sweeps/<id>/claim_packet.json`
- `http://<backend>/sweeps/<id>/report.html`
- Frames: `http://<backend>/sweeps/<id>/frames/<frame_name>.jpg`
- Cost/latency: `backend/data/sweeps/<id>/cost.json`

### 5. Reprice in a second locale

```sh
curl -X POST "http://127.0.0.1:8000/sweeps/<sweep_id>/reprice?country=GB"
```

## What I kept, changed, and threw away from the reference app

Started from Google's **Insurance Claim Live Agent Team** example. Ran it before writing code.

**Kept**
- Live interaction shape: continuous session, voice both ways, inventory building on screen in real time.
- Background agents assembling the final adjuster packet (not one monolithic prompt).

**Changed**
- **Vision + voice**: Gemini Live streams audio+video and calls tools (`log_book_spine`, `log_non_book_item`, `apply_correction`, `sync_inventory`). Identification and pricing run as separate background stages.
- **Measurement**: ARKit plane anchors → floor/wall area. Spine dimensions from **standard book formats** (height + thickness tables) when LiDAR bbox depth is not on the Live path; method recorded as `standard_book_format`. Room geometry method = `arkit_plane_detection`.
- **Pricing**: SerpAPI only. Median of physical listings; digital/ebook results filtered. No LLM prices.
- **Totals**: pure Python in `services/packet.py`.

**Threw away**
- Reference narrative notebook → replaced with `claim_packet.json` + Jinja2 HTML report.
- Forking the reference and only changing the prompt (explicitly disallowed).

## Tools and models used

| Piece | Choice |
| --- | --- |
| Live voice+vision | Gemini Live (`gemini-3.8-live`) |
| Book resolve | OpenLibrary → Google Books (confidence ≥ 0.72) |
| Pricing | SerpAPI Google Shopping, locale `gl`/`hl`/`google_domain` |
| Room metric | ARKit plane detection |
| Spine metric | Standard book format tables (brief-allowed) |
| Frame quality (legacy `/ws/sweep`) | OpenCV blur/glare |
| Client | Flutter + `arkit_plugin` |

## Repo layout

```
cozmo-ai/
├── app/                 # Flutter iOS client (Gemini Live WS)
├── backend/             # FastAPI — /ws/live, packet, pricing, report
├── web/                 # Optional browser Live client (no ARKit)
├── docs/
│   ├── architecture.md
│   ├── failure_log.md
│   ├── ground_truth_template.md
│   └── deliverables_checklist.md
├── .env.example
└── README.md
```

## Deliverables checklist

See `docs/deliverables_checklist.md` for what's coded vs what you still need to capture (demo video, filled ground truth, committed sample packet).

## Known limitations

See `docs/failure_log.md`. Highlights: ARKit plane classification is extent-heuristic; SerpAPI can still surface marketplace outliers (mitigated with median + digital filter); Live path does not yet stream LiDAR depth samples per spine bbox.
