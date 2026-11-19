# Ground-truth run — 2026-11-19

Demo sweep: `sw_ccf92291e5` · video: [Drive](https://drive.google.com/file/d/1ggkVWt05xPegVNvso5GSQCC4vRiVjjfd/view?usp=sharing) · packet: `deliverables/video_sweep/`

Operator note: continuous **fast walk** past shelves + living area. Non-book capture stayed strong; book spine OCR/ID dropped under motion blur.

## 1. Room

| Field | Operator estimate | System (`sw_ccf92291e5`) | Notes |
| --- | --- | --- | --- |
| Length (m) | ~3 | 3.0 | visual / door reference (no tape on video take) |
| Width (m) | ~2 | 2.0 | |
| Height (m) | ~2.4 | 2.4 | default ceiling when unknown |
| Floor area (m²) | ~6 | 6.0 | |
| Wall area (m²) | ~24 | 24.0 | perimeter × height |
| Scale method | visual | `visual_reference_door` | confidence 0.5 |

## 2. Books (operator memory from the filmed shelves)

Legible titles the operator recalls being on the shelf during the take (not a full 60-spine inventory — demo room is a styled living shelf, not a 60-book test library):

| # | Title / spine as remembered | Captured by system? |
| --- | --- | --- |
| 1 | Keith Haring — *Left and Design* (approx.) | **No** (missed / unidentified under motion) |
| 2 | Nordic style / design title | **No** (missed / unidentified under motion) |
| 3 | Hokusai | **Yes** — identified |
| 4 | Helvetica (Lars Müller) | **Yes** — identified |
| 5 | Christian Dior (Marie France Pochna) | **Yes** — identified |
| 6 | Tom Ford (Graydon Carter) | **Yes** — identified |
| 7 | Van Gogh (Federico Zeri) | **Yes** — identified |

System book totals: **11** logged · **5** identified · **6** unidentified (empty title → review queue).

## 3. Non-book items (operator: “all the non-book items got captured”)

| # | Item (as seen) | System match | Category |
| --- | --- | --- | --- |
| 1 | Light pink upholstered sofa | light pink upholstered sofa | furniture |
| 2 | Small wooden side table | small wooden side table with metal frame | furniture |
| 3 | Green potted plant | green potted plant | decor |
| 4 | Wooden floating shelf + LED | wooden floating shelf with integrated LED lighting | shelving |
| 5 | Circular patterned rug | circular patterned rug | rug |
| 6 | Camera tripod | camera tripod stand | furniture |
| 7 | White textured vase | white textured vase | decor |
| 8 | Small white decorative vase | small white decorative vase | decor |
| 9 | Wall-mounted flat-screen TV | flat screen television / TV mounted (logged twice) | electronics |
| 10 | Fake bird of paradise in marble-pattern pot | fake bird of paradise… | decor |
| 11 | Beige throw pillow | beige throw pillow on the sofa | decor |
| 12 | White ceramic wax warmer | white ceramic wax warmer | decor |
| 13 | Second LED floating shelf | another wooden floating shelf… | furniture |
| 14 | Small decorative candle holder | small decorative candle holder | decor |
| 15 | Small remote control | small remote control | decor |

**Non-book find rate:** operator judges ≈ **100% of visible non-books** in the filmed pass were logged (including under fast walk). One duplicate TV entry.

## 4. Score sheet (against this take)

| Pass bar | Target | This run | Pass? |
| --- | --- | --- | --- |
| Book count within 5% | ±5% | Small styled shelf (~7+ remembered titles) vs 11 logged (incl. blanks) — not a 60-book space | N/A / demo scale |
| Title ID ≥ 70% of legible | ≥ 70% | ~5/7 remembered legible ≈ **71%** on named set; 6 blanks drag overall ID rate to 5/11 ≈ **45%** | Partial — motion |
| Title ID ≤ 3% confidently wrong | ≤ 3% | No clear confident wrong title on the 5 IDs | Pass (small n) |
| Non-book items ≥ 80% found | ≥ 80% | Operator: essentially all non-books found while walking fast | **Pass** |
| Floor / wall area | ±10% / ±15% | Matches operator ~3×2×2.4 visual estimate | Pass (visual) |
| Time to packet | < 300 s | Sweep duration **49.4 s** + packet ready immediately after End | **Pass** |

### Takeaway for reviewers

The demo deliberately stresses **speed**. Even with a fast walk, the agent kept logging furniture, shelving, rug, plants, TV, and decor in real time. Book spines need slower / closer passes for OCR — fast motion is why several spines stayed `unidentified` rather than invented.
