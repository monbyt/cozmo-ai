# Deliverables checklist vs the brief

Status after the Nov 2026 engineering pass. Fill the **You still need** column before submission.

| # | Deliverable | Code / docs status | You still need |
| --- | --- | --- | --- |
| 1 | Private GitHub repo + README + `.env.example` | Done — stranger can run backend in minutes; Flutter needs Xcode | Share private repo with reviewers |
| 2 | Demo video ≤ 6 min, one unedited take | Not in repo | Record full sweep with agent voice + live inventory + packet |
| 3 | `claim_packet.json` + HTML report + saved frames from the video sweep | Pipeline produces all three under `backend/data/sweeps/<id>/` | Copy the video-sweep packet into `deliverables/` and keep frames |
| 4 | Ground truth + results sheet | Template: `docs/ground_truth_template.md` | Fill before tuning; save as `docs/ground_truth_run_YYYYMMDD.md` with pass-bar deltas |
| 5 | Architecture note (1 page) | `docs/architecture.md` | Keep in sync if pipeline changes |
| 6 | Failure log (1 page) | `docs/failure_log.md` | Replace template slot #1 with a real post-sweep failure |

## Capability pass bars (code support)

| Capability | Supported in code? | Caveat |
| --- | --- | --- |
| 1 Live sweep agent | Yes — `/ws/live`, inventory UI, capture nudges, `apply_correction` | Quality of direction depends on Live model |
| 2 Books from spine | Yes — title/author/publisher tools, unidentified if blank, format dimensions, shelf run | Live path uses standard formats, not LiDAR per bbox |
| 3 Book valuation | Yes — replacement + used, source/url/date, rare flagged, reprice endpoint | Needs SerpAPI key; median filter reduces ebook false hits |
| 4 Non-book contents | Yes — categories, dims fields, art → needs_appraisal, local ranges | Dims are approx from vision tool args |
| 5 Surface area | Yes — floor/wall m²+ft², shelved area when shelving dims present | Accuracy depends on ARKit plane quality |
| 6 Claim packet | Yes — schema + HTML + review queue + Python totals + frame_ref | Frames saved ~1/s during Live video |

## Submission email bundle

1. Repo link  
2. Demo video link  
3. Architecture note  
4. Failure log  
5. Ground truth + results  
6. Claim packet + report + frames from the video sweep  
