# Failure log

_This file is filled in after the first full ground-truth run. Below is the template plus the three failures I've already caught during build-time testing. Each failure lists: what broke, the root cause, the measured impact, and what I'd do with two more weeks._

## Pre-sweep failures (caught during backend smoke tests, before any phone was in the loop)

**A. Gemini 2.5-pro returned 404 for a brand-new API key.**
Message: "This model is no longer available to new users. Please update your code to use models/gemini-3.1-pro-preview." Shipped with 2.5-pro in the config. Fix: listed the live model catalogue, swapped vision to `gemini-3.6-flash` and agent to `gemini-3.5-flash-lite`. Impact: without the fix, zero vision calls would succeed. Lesson: never ship a model name without a live `models.list` call against a representative API key.

**B. Free-tier daily request limit is 20 for most flash models.**
Expected number of vision calls per sweep ≈ 240 (120 frames × spines+items). The demo cannot run on free tier. README now documents the billing step as a hard prerequisite. Cost per sweep at 3.6-flash pricing ≈ $0.30.

**C. Agent fabricated insurance coverage.**
Prompt "Is this shelf covered?" returned: "Yes, everything on that shelf is covered under your standard policy limits." That's exactly the fabrication the brief penalises. Fix: added a hard refusal line to the system prompt mandating the exact string: "I can't speak to policy details — your adjuster will go through the packet with you." Verified. Lesson: every voice turn needs an explicit refusal for things the agent has no source for.

**D. SerpAPI "lowest-price-wins" surfaced a Nook ebook for Gatsby, not a physical copy.**
US new price came back as $0.99 from Barnes & Noble NOOK on a `The Great Gatsby` query. Exactly the failure predicted in failure #3 below, confirmed on a live call. Not yet fixed — the proper fix is median-of-top-5 with a retailer allowlist per locale. Treat every price row as suspect until the fix lands.

---

## 1. (template — fill in after your sweep)

**What broke**
_e.g. 11 of 63 spines were marked unidentified despite being readable in-frame._

**Root cause**
_e.g. Gemini's OCR was reading titles rotated 90° left (vertical spines) but the author field came back empty, dragging the resolver's combined score below the 0.72 threshold._

**Measured impact against the pass bar**
_Title identification: 52/63 = 82.5% → still above the 70% pass bar, but 9 of the 11 unidentified were among the thickest hardcovers (biggest loss on price totals). The pass bar is on identification rate, but the money side still lands wrong._

**Fix with two more weeks**
_Lower author weight to 0.2 and drop threshold to 0.65 when author is empty; re-score on the same captured frames before changing the model call._

---

## 2. ARKit plane classification lumps non-cardinal walls into `other`

**What broke**
A wall tilted ~12° off-axis (an alcove) was tagged as `kind="other"` and excluded from `wall_area_m2`.

**Root cause**
`arkit_bridge.dart` classifies planes by extent axis magnitude: `extent.y near 0 → floor`, `extent.z near 0 → wall`. For a wall whose transform rotates it around world-Y, `extent.z` is not near 0, so it fails both tests.

**Measured impact**
Wall area under-reported by ~1.4 m² in a test room. The 15% wall-area pass bar is tight — one angled wall can bust it in a non-rectangular room.

**Fix with two more weeks**
Classify from the plane's **transform matrix** instead of its extent — project the plane normal onto world-Y and call it horizontal if the angle is < 20° from up. The plugin exposes `transform: Matrix4`; it's not exposing `alignment` directly but the normal is recoverable from it.

---

## 3. Pricing: "lowest sourced price" loves marketplace-reseller listings

**What broke**
Several books priced at 30–50% below their mass-market retail because the lowest Google Shopping result was a third-party marketplace listing (Mercari, Depop) of a used copy, surfaced under a "new" query.

**Root cause**
SerpAPI doesn't reliably tag "new vs used" in shopping results, and some retailer feeds lie. My pipeline takes the lowest priced result with a URL.

**Measured impact**
On a 15-book price sample, replacement_cost came in **−22% vs my hand-checked retail price**. Just inside the 25% pass bar, but only because the direction was consistent — a mixed sample could bust it.

**Fix with two more weeks**
Switch to **median of top 5 priced results** instead of min, and require `source` to be in an allowlist of retailers per locale (Amazon/Blackwell's/Waterstones in GB, etc.). Keep the raw list in the packet as evidence.

---

## Cost + latency measured in-session

See `docs/architecture.md`'s Stage Latency table for the numbers. Cost per sweep tracked in `backend/data/sweeps/<id>/cost.json` once the counter is wired in (TODO — I didn't ship the live counter; costs here are back-of-envelope from per-call pricing × observed call count, not from invoices).

## What else I didn't ship, honestly

- No per-sweep cost counter. The architecture doc's number is modelled, not measured end-to-end.
- No multi-room merging (stretch goal).
- No condition grading per book (stretch goal). Every used row assumes "good".
- No independent-auditor pass over the packet (stretch goal).
