# Cozmo Sweep — Library Contents Claim Agent

Live voice-and-vision insurance agent that inventories and values a home library in one continuous camera sweep.

- **Frontend**: Flutter (iOS) using Apple ARKit (LiDAR when available) for metric scale and plane detection. Falls back to visual-inertial odometry on non-Pro iPhones.
- **Backend**: Python 3.12 FastAPI. Gemini 2.5 Pro for spine detection + OCR + non-book items. OpenLibrary and Google Books for book resolution. SerpAPI (Google Shopping) for locale-aware pricing. Totals computed in Python, never from an LLM.

## Quick start (under 15 minutes from a clean Mac)

### Prerequisites

| Tool | Install |
| --- | --- |
| Homebrew | https://brew.sh |
| Flutter | `brew install --cask flutter` |
| Xcode (full) | Mac App Store → "Xcode". ~10 GB, 30–60 min. |
| CocoaPods | `brew install cocoapods` |
| Python 3.12 | `brew install python@3.12` |
| `uv` | `brew install uv` |

After installing Xcode:
```sh
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -runFirstLaunch
```

Check your toolchain: `flutter doctor`. It should show Flutter green, Xcode green, at least one connected device.

### 1. Backend

```sh
cd backend
cp ../.env.example .env              # then fill in GEMINI_API_KEY and SERPAPI_KEY
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API keys you need:
- `GEMINI_API_KEY` — https://aistudio.google.com/apikey (free tier is enough for the demo)
- `SERPAPI_KEY` — https://serpapi.com/ (100 free/month). Without it, the pipeline runs but every price is excluded from totals and routed to the review queue.
- `GOOGLE_BOOKS_API_KEY` — optional, raises the rate limit.

Smoke check: `curl http://127.0.0.1:8000/health` returns `{"status":"ok", ...}`.

### 2. Flutter app on an iPhone

Plug your iPhone into the Mac with a cable, trust the computer.

```sh
cd app
flutter pub get
flutter devices                      # confirm your iPhone is listed
open ios/Runner.xcworkspace          # (first-time only) in Xcode: Signing & Capabilities → Team → your Apple ID
flutter run -d <your-iphone-id>
```

The first `flutter run` produces a build, installs it, and starts the app. iOS asks for Camera, Microphone, and Speech Recognition permissions — approve all three.

In the app:
- Pick your country (the currency auto-sets).
- Backend URL — if your Mac is on the same Wi-Fi, use `http://<your-mac-local-ip>:8000`. For USB testing, forward with `brew install netcat` + `ssh -R` or a tunnel like `ngrok http 8000`.
- Hit **Start sweep**.

### 3. Walk the room

- Walk once around the room, panning the phone across every shelf, wall and floor patch. Target < 3 minutes.
- The agent will speak up when a frame is blurry, glared, or when it detects something that needs appraisal.
- You can interrupt and correct by voice at any time ("that's a first edition", "skip that shelf, those aren't mine", "it's a print").
- Tap **End sweep** when done. Within ~1–5 minutes you'll see the packet URLs.

### 4. Open the packet

- `http://<backend>/sweeps/<sweep_id>/claim_packet.json`
- `http://<backend>/sweeps/<sweep_id>/report.html` — human-readable adjuster report
- Local files: `backend/data/sweeps/<sweep_id>/` holds the same two files plus any reprice runs. Frames referenced by each row are under `backend/data/frames/<sweep_id>/`.

### 5. Reprice in a second locale

To prove locale is a setting (brief deliverable: 10 books priced in a second country):
```sh
curl -X POST "http://127.0.0.1:8000/sweeps/<sweep_id>/reprice?country=GB"
```
Writes `backend/data/sweeps/<sweep_id>/reprice_GB.json`.

## What I kept, changed, and threw away from the reference app

Started from Google's "Insurance Claim Live Agent Team" example.

**Kept**
- The shape of the live interaction: one continuous session, voice both ways, a packet building in real time on screen.
- The idea of background agents assembling the final packet rather than a single monolithic prompt.

**Changed**
- **Vision provider**: still Gemini (2.5 Pro), but moved from Gemini Live for vision to request/response Gemini with structured output. Gemini Live is used only via local STT/TTS-equivalent voice path in the app. Reason: structured output gives per-spine bboxes + per-item schemas I can validate.
- **Measurement**: the reference describes damage; this needed actual centimetres. I bolted on Apple ARKit on the frontend (LiDAR depth → per-frame metric scale, plus plane anchors for room geometry).
- **Pricing**: added SerpAPI as a required separate stage. The model cannot produce prices.
- **Totals**: moved out of the LLM into pure Python aggregation.

**Threw away**
- The reference's narrative notebook output. Replaced with `claim_packet.json` + a strict Jinja2 HTML report.
- The reference's Gemini Live full video streaming. Too hard to also run the perception pipeline off the same stream reliably in 48 hours. The app streams 2 fps keyframes + ARKit metadata to the backend as its own WebSocket, and runs STT/TTS locally.

## Tools and models used

- **Flutter 3.50 + Dart** — iOS build, UI.
- **`arkit_plugin` 1.5.0** — ARKit scene view, plane detection, depth snapshots.
- **`speech_to_text` 7.x + `flutter_tts` 4.x** — on-device STT + TTS for the voice loop.
- **FastAPI + Uvicorn + Pydantic 2** — backend.
- **Google Gemini 2.5 Pro** (via `google-genai` SDK) — spine detection + OCR + non-book items + agent turns.
- **OpenLibrary + Google Books API** — book resolution.
- **SerpAPI Google Shopping** — locale-aware pricing.
- **OpenCV (`opencv-python-headless`)** — blur/glare quality gate.

## Repo layout

```
cozmo-ai/
├── app/                     # Flutter iOS app
│   ├── lib/
│   │   ├── main.dart
│   │   ├── app_state.dart
│   │   ├── screens/         # home, sweep, packet
│   │   ├── services/        # arkit_bridge, backend_client, voice_agent
│   │   └── widgets/
│   └── ios/Runner/Info.plist  # camera/mic/speech permissions
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── models/schema.py # Pydantic claim packet
│   │   ├── routes/          # sweep (WebSocket), agent (turn)
│   │   ├── services/        # vision, books, pricing, measurement, dedup, packet, report, agent, perception_orchestrator
│   │   └── templates/       # report.html.j2
│   ├── data/                # sweeps + frames (gitignored)
│   └── requirements.txt
├── docs/
│   ├── architecture.md      # one-page diagram + stage map
│   ├── failure_log.md       # top-3 failures, root causes, cost + latency
│   └── ground_truth_template.md  # CSVs to fill in before scoring
├── .env.example
└── README.md
```

## Costs per sweep (rough, with Gemini 2.5 Pro)

Measured in the failure log. A 2-minute sweep at 2 fps ≈ 240 frames; after dedup the model sees ~60 shelf crops. Cost ~$0.40 at current pricing. SerpAPI ~0.02 credits per book priced.

## Known limitations (see `docs/failure_log.md` for detail)

- ARKit plane classification is heuristic (extent-based). A short wall tagged at an angle may land in `other`.
- Dedup across shelves is positional + title-based. Two copies of the same book on the same shelf can collapse to one row — we accept this as "within the 5% book-count bar".
- No multi-room merging. Brief stretch goal, not implemented.

## Honest ground-truth promise

Everything in `docs/ground_truth_template.md` is what I fill in from a tape measure before I touch the system. The numbers the system produces are compared against those, not against the system's own outputs. See `docs/failure_log.md` for what missed the pass bar and why.
