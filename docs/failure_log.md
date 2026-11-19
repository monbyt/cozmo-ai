# Failure log

_Filled during build + early Live sweeps. Slot #1 must be replaced with numbers from your filled ground-truth run before submission._

## Pre-sweep failures (caught during backend smoke tests)

**A. Gemini 2.5-pro returned 404 for a brand-new API key.**  
Shipped with a retired model name. Fix: list live catalogue; Live path uses `gemini-3.8-live`, resolve/agent use flash-lite. Lesson: never ship a model id without a live `models.list` against a representative key.

**B. Free-tier daily request limit cannot run a sweep.**  
README now requires a billed Gemini project. Cost modelled ~$0.50–0.90/sweep.

**C. Agent fabricated insurance coverage.**  
Fix: hard refusal in the agent/Live system prompts — never invent policy. Verified on "Is this shelf covered?".

**D. SerpAPI lowest-price surfaced a Nook ebook ($0.99) for Gatsby.**  
Confirmed live. **Mitigation shipped**: digital-marker filter + median of up to 5 physical listings + soft retailer preference. Re-check against the 15-book hand price sample before claiming the ±25% bar.

---

## 1. Fast-walk demo (`sw_ccf92291e5`) — book spines go unidentified; non-books hold

**What broke**  
On the submission video take the operator walked the room quickly. The agent logged **11** book slots but only **5** with titles (Hokusai, Helvetica, Christian Dior, Tom Ford, Van Gogh). Remembered spines such as a Keith Haring design title and a Nordic-style design book never resolved. Non-book contents (sofa, shelves, rug, plants, TV, decor) were captured throughout the same fast pass.

**Root cause**  
Live spine OCR needs a stable, closer look. Motion blur + short dwell time leaves `legibility` weak; the pipeline correctly refuses to invent titles → empty `unidentified` rows instead of hallucinations. Item vision (larger objects) tolerates speed much better.

**Measured impact against the pass bar**  
- Identified/title rate on logged books: 5/11 ≈ **45%** (below the ≥70% legible-ID bar if every blank is treated as a miss).  
- On the operator’s short list of remembered legible titles ≈ **5/7 (~71%)**.  
- Non-book find rate: operator reports **≈100%** of visible non-books logged while walking fast (pass ≥80%).  
- Packet time: **49 s** sweep (pass ≪ 5 min).  
- Pricing side issue on same packet: circular rug SerpAPI range blew out to **$20,900** high — marketplace outlier still leaking into `items_replacement_cost_high`.

**Fix with two more weeks**  
- Capture nudge when blur/speed is high: “slow for spines” only, keep silent on furniture.  
- Multi-frame spine voting before commit.  
- Hard cap / IQR filter on non-book shopping highs (same spirit as the ebook filter for books).  

---

## 2. ARKit plane classification lumps non-cardinal walls into `other`

**What broke**  
A wall tilted ~12° off-axis (alcove) tagged `kind="other"` and excluded from `wall_area_m2`.

**Root cause**  
Frontend classifies by extent axis magnitude, not plane normal from the transform.

**Measured impact**  
Wall area under-reported ~1.4 m² in a test room — enough to threaten the 15% wall-area bar in non-rectangular rooms.

**Fix with two more weeks**  
Classify from plane normal (angle to world-Y &lt; 20° → horizontal). Plugin exposes `transform: Matrix4`.

---

## 3. Pricing: marketplace / digital listings distort "new"

**What broke**  
Replacement costs 30–50% below mass-market retail when the lowest Shopping hit was a reseller or ebook.

**Root cause**  
SerpAPI doesn't reliably tag new vs used; lowest-price-wins was naive.

**Measured impact**  
On a 15-book sample, −22% vs hand-checked retail (inside ±25% but fragile).

**Fix shipped (partial)**  
Median of top physical hits + ebook/digital filter + retailer preference.  
**Still with two more weeks**: per-locale retailer allowlist hard-fail, AbeBooks for used, keep raw result list in the packet.

---

## Cost + latency

Written per sweep to `backend/data/sweeps/<id>/cost.json` by `services/cost_tracker.py` (modelled from call counts × unit prices, not invoices).

Typical Live sweep (~2 min, ~60 spines):
- Gemini Live session: dominant cost
- SerpAPI: ~1 call per priced book/item
- Packet build: &lt; 100 ms
- Target time-to-packet after End: &lt; 5 min (pass bar)

## What else I didn't ship

- LiDAR depth samples on the Live path (format tables used instead — brief-allowed, but weaker on the spine-dim pass bar).
- Multi-room merge, condition grading, independent auditor agent (stretch).
- PDF report (HTML satisfies the brief's PDF-or-HTML).
