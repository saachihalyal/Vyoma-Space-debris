# Stage 2 covariance policy comparison

## Live screening used

The October 24 app job named in the directive (1,932 pairs, 84 events, SL-3 R/B 10114 vs ISS modules at 2026-10-24T17:01:21Z) was not present in the backend job list or exports. Following the directive's fallback, a fresh CelesTrak screening was run through the API on port 8001. Job `391e7c01617f4a229d38b2b3da7e6f57` completed at 2026-10-24T13:47:05Z; it screened 178 candidate events (requested candidate limit 200) and was marked partial because the candidate-minima cap was reached. The table below uses ten closest valid interior-TCA events from that job. It is live screening data, not either archived October snapshot.

## Policy definition and choice

All policies use each event's same mean state and the same ESA population HBR p50. ESA-prior covariance is the existing archive-derived population mapping. The TLE-age baseline assigns radial, in-track, and cross-track position sigmas at TCA as `0.1 + 0.1d`, `0.5 + 1.5d`, and `0.2 + 0.2d` km respectively, where `d` is TLE age in days. It rotates the diagonal RTN covariance into TEME and does not propagate covariance from epoch. The 2× policy doubles each sigma (and therefore multiplies covariance by four). None is measured object-specific uncertainty.

The default is **TLE-age position-sigma baseline**. It is explicitly parameterized for TLE-derived states and grows with element age; its scale is physically more plausible for TLE position uncertainty than the ESA population mapping's approximately 0.01–0.11 km encounter-plane sigmas. This is a configurable research prior, not calibrated covariance. ESA prior and 2× TLE-age remain selectable and carry distinct labels.

## Ten closest events

`σmin/σmax` are the two encounter-plane principal-axis standard deviations in km. `m/σ` is the Mahalanobis miss distance. Pc is exact `log10(Pc)` before the display floor. Several raw pairs share identical encounter geometry and therefore have identical results; they remain separate events.

| Rank | Event / object pair | Miss km | ESA σmin/σmax | m/σ | log10 Pc | TLE σmin/σmax | m/σ | log10 Pc | TLE 2× σmin/σmax | m/σ | log10 Pc |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | CA-60A46255FDC220452CC3 — DRAGON CRS-35 / SL-3 R/B | 1.57306 | 0.0099958 / 0.11006 | 68.29 | -990.59 | 0.23907 / 1.3789 | 2.988 | -5.8394 | 0.47814 / 2.7577 | 1.494 | -4.9878 |
| 2 | CA-69ACD5DB896BB6B3876E — SL-3 R/B / ISS (NAUKA) | 1.57306 | 0.0099958 / 0.11006 | 68.29 | -990.59 | 0.23907 / 1.3789 | 2.988 | -5.8394 | 0.47814 / 2.7577 | 1.494 | -4.9878 |
| 3 | CA-70B2B784DC9148D3FE64 — SOYUZ-MS 29 / SL-3 R/B | 1.57306 | 0.0099958 / 0.11006 | 68.29 | -990.59 | 0.23907 / 1.3789 | 2.988 | -5.8394 | 0.47814 / 2.7577 | 1.494 | -4.9878 |
| 4 | CA-9AFF3CD30AB3686DF260 — SL-3 R/B / PROGRESS-MS 34 | 1.57306 | 0.0099958 / 0.11006 | 68.29 | -990.59 | 0.23907 / 1.3789 | 2.988 | -5.8394 | 0.47814 / 2.7577 | 1.494 | -4.9878 |
| 5 | CA-DF471911F3C5188C8287 — SL-3 R/B / POISK | 1.57306 | 0.0099958 / 0.11006 | 68.29 | -990.59 | 0.23907 / 1.3789 | 2.988 | -5.8394 | 0.47814 / 2.7577 | 1.494 | -4.9878 |
| 6 | CA-E4544E5AE5B891552C00 — CREW DRAGON 13 / SL-3 R/B | 1.57306 | 0.0099958 / 0.11006 | 68.29 | -990.59 | 0.23907 / 1.3789 | 2.988 | -5.8394 | 0.47814 / 2.7577 | 1.494 | -4.9878 |
| 7 | CA-F559494A7148A1542711 — SL-3 R/B / ISS (ZARYA) | 1.57306 | 0.0099958 / 0.11006 | 68.29 | -990.59 | 0.23907 / 1.3789 | 2.988 | -5.8394 | 0.47814 / 2.7577 | 1.494 | -4.9878 |
| 8 | CA-FFC8E1AD686300E9466F — PROGRESS-MS 35 / SL-3 R/B | 1.57306 | 0.0099958 / 0.11006 | 68.29 | -990.59 | 0.23907 / 1.3789 | 2.988 | -5.8394 | 0.47814 / 2.7577 | 1.494 | -4.9878 |
| 9 | CA-2A00592676A1622936B4 — SL-3 R/B / ISS (NAUKA) | 4.63118 | 0.010138 / 0.10987 | 385.6 | -32142 | 0.28016 / 1.7344 | 14.00 | -46.626 | 0.56033 / 3.4688 | 7.001 | -15.313 |
| 10 | CA-4AAE0DBA576FFD738421 — SL-3 R/B / PROGRESS-MS 34 | 4.63118 | 0.010138 / 0.10987 | 385.6 | -32142 | 0.28016 / 1.7344 | 14.00 | -46.626 | 0.56033 / 3.4688 | 7.001 | -15.313 |

The live fallback job contains a geometry near the directive's example (miss 21.84765 km, relative speed 12.04677 km/s), but it does not reproduce the requested 21.842 km event or the 1,932/84 job. The exact original job was unavailable, so this comparison is transparently based on the newly screened live job above.

## Catalog ranking, coverage, and co-located groups

The exact-log-Pc ranking, histogram, class counts, coverage, grouping, and what-if use this same fresh live job. Research-Pc records were recalculated with the committed version 2.0.0 assessor from each event's saved live physics state; the original temporary job records were not mutated.

- Coverage: 178 total records; 140 valid interior-TCA records; 140 with finite research `log10_pc`; 0 requiring a reason code; 0 valid events without either; 0 TCA-boundary records. The other 38 records were not valid interior-TCA assessments and remain outside research-Pc ranking.
- Classes: 0 High, 8 Medium, 132 Low. Exact-log histogram: `< -30`: 108; `-30 to -20`: 8; `-20 to -12`: 8; `-12 to -7`: 8; `-7 to -4`: 8; `≥ -4`: 0.
- Likely co-located encounters: 13 geometry groups collapse to 13 representative cards from 104 raw events, with each group's eight pair records retained in the expandable member list. This is display grouping only; the job data and exports retain all 178 raw events.
- At 2026-10-24T17:01:31.258995Z, miss 21.847650 km and speed 12.046773 km/s, eight connected records (including SL-3 R/B paired with Zarya, Nauka, Poisk, Progress, Crew Dragon, Soyuz, and Dragon objects) collapse into one likely co-located display group. This is the fresh job's nearby analogue; it is not the exact 21.842 km app event.
- The Uncertainty scale selector (0.5×, 1×, 2×, 3×) calls the existing research-Pc scenario endpoint for the selected event and explicitly labels the result as a what-if. Boundary TCA assessments are visibly marked and excluded from ranking.


## Add-on repairs: fresh current-checkout run (2026-10-25)

The backend was restarted on port 8001 and `/api/version` returned `d09d9ee`, matching HEAD at the time. A fresh 200-object CelesTrak run completed **partially** because the 10,000 candidate-minimum cap was reached. Its evidence is saved in `stage2-fresh-addon-summary.json`.

- 109 assessment rows: 70 valid physical close approaches, 69 with a finite research `log10_pc`, one valid record with a reason code, 38 invalid assessments, and one boundary TCA. All 38 invalid assessments report `identical_propagation_parameters_for_distinct_catalog_ids`; the UI now lists each returned event ID/pair and explains the reason in plain language. This fresh run therefore has 38 invalid records, not the 16 described for the prior acceptance dataset.
- Grouping: 70 valid interior-TCA rows become 49 representatives; 3 connected co-located groups contain 24 raw rows. Raw rows remain in exports. Pc class KPIs count groups and include raw-event counts.
- Sensitivity case: IRIDIUM 33 (24946) vs COSMOS 2251 DEB (33757), TCA `2026-10-25T15:11:09.655935Z`, miss `4.761498 km`. The TLE-age covariance is held fixed in the displayed ESA span-only p10/p50/p90 sensitivity range; all three combined HBR quantiles are `0.002 km`, so the displayed endpoints coincide at `8.60665e-21`. This is not a covariance-scale range. After a backend restart, the archived-event what-if endpoint returned finite log10 Pc values for 0.5x/1x/2x/3x covariance scales: `-63.7962`, `-20.0652`, `-9.58371`, and `-7.88338`. The range explanation and separate control now state this distinction explicitly.
- HBR size assumption effect on the highest exact-Pc event involving an ISS module: SL-3 R/B (10114) vs ISS (NAUKA) (49044), TCA `2026-10-25T04:38:40.186462Z`, miss `4.631177 km`, relative speed `12.243068 km/s`. Without the name-based Nauka size override, combined HBR is `0.00555 km` and exact log10 Pc is `-47.062165`; with the assumed `0.015 km` Nauka radius, combined HBR is `0.016 km` and exact log10 Pc is `-46.112901`, an increase of about 0.95 log10 units (about 8.9x). Both remain below the configured `1e-30` display floor; exact values remain in details.
- The object-size radii and their assumed status are documented in `docs/HBR_SIZE_ASSUMPTIONS.md`. Research covariance/HBR fields are included in selected-event JSON/CSV/PDF and full trajectory CSV, including events whose displayed Pc is negligible.
