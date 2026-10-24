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
