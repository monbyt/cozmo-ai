# Ground-truth template

Fill this out **before** tuning anything on the test space. The system's numbers are scored against *these* values, not against the system's own earlier outputs. Save your filled-in copies as `docs/ground_truth_run_<YYYYMMDD>.md`.

The space must have: ≥ 60 books across ≥ 2 shelving units, ≥ 8 non-book items, one enclosed room.

## 1. Room tape measurements

| Field | Value | How measured |
| --- | --- | --- |
| Length (m) | | tape, longest wall |
| Width (m) | | tape, perpendicular wall |
| Ceiling height (m) | | tape, floor to ceiling |
| Floor area (m²) | | length × width, or sum of rectangles if not rectangular |
| Wall area (m²) | | perimeter × height, minus large openings |
| Shelved wall area (m²) | | sum of shelving-unit widths × heights |
| Room shape notes | | |

## 2. True book count

| Shelf / unit | Count | Notes |
| --- | --- | --- |
| Unit A shelf 1 | | |
| Unit A shelf 2 | | |
| Unit B shelf 1 | | |
| ... | | |
| **Total** | | |

## 3. Hand-read titles (every legible spine)

| # | Shelf | Title (as read) | Author | Publisher (if visible) | Edition / year |
| --- | --- | --- | --- | --- | --- |
| 1 | | | | | |
| 2 | | | | | |
| ... | | | | | |

A spine is "legible" if a person standing 30 cm from it can read the full title. Illegible spines are counted in the book count but not here.

## 4. 20 hand-measured spines

Measure 20 spines you expect to be representative (mix of hardcover/paperback/stacked).

| # | Title | Height (cm) | Thickness (cm) |
| --- | --- | --- | --- |
| 1 | | | |
| 2 | | | |
| ... | | | |
| 20 | | | |

## 5. 15 hand-checked prices

Pick 15 identified books; look each up on the primary retailer in your country **on the same day as your sweep** and record the price. The system is scored against *this* source, not against whatever cheaper marketplace listing SerpAPI surfaces.

| # | Title | Country | Primary retailer | New price | Used price (if listed) | Date |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | | | | | | |
| ... | | | | | | |
| 15 | | | | | | |

## 6. Non-book item list

| # | Item (description) | Category | Approx dimensions (W×H×D cm) | Brand/model (if any) |
| --- | --- | --- | --- | --- |
| 1 | | | | |
| ... | | | | |

## 7. Score sheet (filled in after running your sweep against this truth)

| Pass bar | Target | Your system | Pass? |
| --- | --- | --- | --- |
| Book count within 5% | ±5% | | |
| Title ID ≥ 70% of legible correct | ≥ 70% | | |
| Title ID ≤ 3% confidently wrong | ≤ 3% | | |
| Spine dims within 15% (sample of 20) | ≤ 15% | | |
| Book prices within 25% (sample of 15) | ≤ 25% | | |
| Non-book items ≥ 80% found, correct category | ≥ 80% | | |
| Floor area within 10% | ≤ 10% | | |
| Wall area within 15% | ≤ 15% | | |
| Time to packet < 5 min | < 300 s | | |

Compute the deltas in both directions and quote them. If a pass bar fails, quote the failure in the architecture note's failure log.
