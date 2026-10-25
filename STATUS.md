# ORION Completion Status

## Backend pass: Low-class coverage, maneuver replay, methodology, and demo snapshot (2026-10-25)

- Collision scenario dataset v4 now applies miss-distance values as multipliers of the saved parent encounter-plane vector. It covers `0.01x`, `0.1x`, `0.5x`, `1x`, `2x`, and `3x`; each multiplier has three covariance/HBR/TLE-age combinations. Retrained through `scripts/retrain_all.ps1`, fixed seed `20261024`, using newest saved job `fcec3945251c45f38f215485ecbb5605` (partial, 109 rows; 70 valid real parents). Across saved jobs, 49 encounter groups had scenarios. One of 1,260 proposed variants was rejected for `PC_LOG10_PC_MISMATCH`; 1,259 remained. Group split is disjoint: train 34 groups / 48 parents / 863 scenarios; validation 7 / 7 / 126; test 8 / 15 / 270.
- Test risk-class support (Low/Medium/High): `183 / 79 / 8`; confusion rows true, columns predicted: `[[178,5,0],[6,73,0],[0,0,8]]`; macro-F1 `0.966655` vs majority baseline `0.269316`. The Pc regressor and risk classifier are usable on held-out data. Pc test MAE/RMSE are `2.431413 / 5.118889` log10 units; among 134 rows above the `-30` floor: `4.081615 / 6.872079`. Smart Filter test macro-F1 is `0.926670`, significant precision/recall `1.0 / 0.75`, 2 false negatives of 8, versus majority macro-F1 `0.492481` and 8 false negatives. Details are saved in `docs/MODEL_METRICS.json`.
- The newest job has 69 valid saved research-Pc outputs, of which 65 are below log10 Pc `-30`. The 10 lowest outputs were evaluated with the final v2.2.0 artifacts; all ten risk-class predictions are Low. The regressor predictions and exact source values are in `docs/MODEL_METRICS.json` under `newest_saved_job_evaluation`.
- Default maneuver search ran on highest-Pc valid event `CA-50F4A7C3AEA73F27B191`. Selected `0.05 m/s` radial-negative candidate: two-body miss `3.031553666 -> 3.029139747 km`; research Pc `5.51515e-7 -> 5.29001e-7`; reduction `4.082314%`; candidate TCA `2026-10-25T21:22:11.871898+00:00`; default fuel estimate `0.01158755 kg` (500 kg, 220 s). Baseline and candidate used the same two covariance matrix hashes and HBR `0.002 km`. The maneuver result remains a bounded research simulation with an unvalidated baseline-comparison warning.
- Added [docs/METHODOLOGY.md](docs/METHODOLOGY.md) with saved counts, covariance policies, Foster and log-domain Pc formulas, score scale/thresholds, scenario targets/split, model metrics, maneuver/fuel equations, Smart Filter guard, and limitations.
- Demo archive is `backend/exports/demo/screening-job-fcec3945251c45f38f215485ecbb5605.json` (finished partial job, 109 rows). All three archives marked `complete` are empty; this newest finished event-bearing job is the usable snapshot. Backend archive loading now checks `exports/demo/` after the archive root. In the app, open **Reports**, enter job ID `fcec3945251c45f38f215485ecbb5605` in the archive restore field, and select **Restore and select archive**.
- Backend suite with 600-second timeout: **340 passed**, 2 warnings, 107 subtests, 84.75 seconds. Log: `backend/backend-suite-next-pass-final.log`.
- This pass changed backend code/tests, model artifacts/data, docs, and the demo archive only. No `src/` or frontend files were changed in this pass. Pre-existing dirty frontend and live-cache changes remain untouched.

## T5 encounter-group retraining and T6 maneuver consistency (2026-10-25)

- Leakage audit across all 10 saved screening-job files found 260 valid physical event rows, 260 distinct event IDs, and 62 encounter groups represented by the 118 T5 parent events. Encounter grouping uses same TCA rounded to milliseconds, matching four-significant-digit miss distance and relative speed, and a shared object ID; it joins co-located ISS-complex encounters across saved jobs. The original parent-only split leaked 20 groups / 48 parent IDs across partitions. Dataset v3 and all three T5 models were retrained by physical encounter group with seed 20261024. New split: train 43 groups / 75 parents / 900 rows; validation 9 / 20 / 240; test 10 / 23 / 276. The saved encounter-group manifest has zero train/validation/test intersections.
- Saved test metrics (`docs/MODEL_METRICS.json`): Pc model MAE/RMSE `0.057914 / 0.097542` log10 Pc versus training-median `0.576851 / 0.713449` and fitted-linear `0.186370 / 0.255968`. All 276 test rows are non-negligible (`log10 Pc > -30`), so the all-data and non-negligible metrics match. The Pc model beat both baselines and is usable.
- Risk classifier test: confusion matrix in Low/Medium/High order `[[0,0,0],[0,176,8],[0,8,84]]`; test support Low 0, Medium 184, High 92; macro-F1 `0.623188` versus majority `0.266667`, accuracy `0.942029` versus `0.666667`. Per-class P/R/F1: Low `0/0/0` (no test examples), Medium `0.956522/0.956522/0.956522`, High `0.913043/0.913043/0.913043`. It beat the majority baseline; Low-class performance is not evaluated.
- Smart Filter test: confusion matrix insignificant/significant `[[176,8],[10,82]]`; significant precision `0.911111`, recall `0.891304`, 10 false negatives among 92 significant rows, macro-F1 `0.926225`. Majority baseline macro-F1 `0.400000` with 92 false negatives; deterministic 1 km baseline macro-F1 `0.382826` with zero false negatives. It beats both baselines on macro-F1 and beats majority on false negatives. The independent 1 km / any-scenario-Pc guard / invalid-or-uncertain retention remains active.
- T5 artifact versions: collision Pc and risk `2.1.0`, Smart Filter `2.1.0`; dataset `orion-collision-scenarios-v3`. Scenario data remains local and is excluded from commits.
- T6 now freezes the selected baseline TEME covariance matrices and HBR for every candidate; only the relative mean state changes. Baseline Pc reuses the selected Collision Analysis research-Pc record at scale 1. A 118-parent regression test compares the Maneuver baseline against Collision Analysis for every valid saved parent. Candidate log10 Pc is read from the exact log-domain result, including when formatted Pc is below the display floor.
- D5 investigation: on the saved event with miss `0.236239063 km`, the old per-candidate covariance re-assignment reproduced Pc `2.55415e-7 -> 7.29721e-10` at miss `0.238668749 km`. The covariance matrix was rotated/rebuilt at candidate TCA, so the comparison changed uncertainty as well as mean geometry. With the baseline matrix and HBR frozen, the same `0.01 m/s` along-track, 300-second-lead replay gives `2.55415e-7 -> 2.52718e-7` (about 1.06% lower). This current saved-record replay is close to, not identical with, the earlier reported `2.97e-7` baseline.
- Maneuver ranker v2.0.0 was retrained with frozen comparison covariance. It remains a labelled physics fallback: test mean regret `0.031142` versus deterministic baseline `0.017708` log10 units (8 held-out parents / 38 candidates).
- Final checks, each run separately: backend full suite **337 passed**, 121.51 s (`backend/backend-full-final.log`); frontend **187 passed**, 5.86 s (`frontend-full-final.log`); production build succeeded in 89 s (`production-build-final.log`) with Vite's existing >500 kB chunk warning. The run commands were supervised with a 10-minute limit.
- No T7 work was started. The remaining Stage 2 completion and later report/UI stages stay at their earlier status; this checkpoint makes no claim that those separate requirements are complete.

## Phase 2 checkpoints

| Stage | Status | Evidence |
|---|---|---|
| 1. Environment and housekeeping | Complete | Code commits `a8e1300` and `e1e6573` on `feature/orion-completion`; the Stage 1 checkpoint record is this commit. |
| 2. Uncertainty model and Pc numerics | In progress (partial checkpoint) | Added the declared Pc display floor and revised, configurable risk-score window. Remaining acceptance work is listed below; no Stage 2 completion is claimed. |

## Stage 2 partial checkpoint (not complete)

### Stage 2B — covariance policy

- Added three selectable research covariance policies and chose the age-adjusted TLE baseline as the TLE-derived default, with physical justification and all ten same-job comparisons in `docs/ORION_STAGE2_COVARIANCE_COMPARISON.md`.
- Source job: fresh live CelesTrak screening `391e7c01617f4a229d38b2b3da7e6f57` on 2026-10-24, because the specified in-app job was absent from the job list and exports. The fallback job is partial (178 events; candidate-minima cap reached) and does not claim to reproduce the specified 1,932-pair/84-event snapshot.
- Stage 2B changes are checkpointed separately. Full Stage 2 acceptance remains in progress; do not start Stage 3.

### Stage 2C — logarithmic Pc and serialization bounds

- The numerical Foster disk integral and small-HBR log-domain expression agree in their overlap (unit test); the log form is selected only when its stated conditioning checks pass.
- The scenario API exposes covariance policy and scale choices. Its API test exercises all three policies and scans serialized numeric scientific exponents, requiring every exponent to stay within ±300; invalid policies return 422.
- Focused verification: `test_automatic_research_pc.py` and `test_research_pc_scenario_api.py`: 9 passed.

### Stage 2D — research-Pc ranking and catalog view

- Collision Analysis defaults to exact, unfloored `log10_pc` descending, then miss/sigma ascending. Events without a valid interior TCA cannot rank ahead of valid events; boundary solutions receive a visible window-edge caveat and no rank.
- Added catalog histogram, research-Pc class counts, valid/Pc/reason coverage, and co-located encounter groups. Group cards show one representative and keep expandable raw event identities; data and exports remain uncollapsed.
- Added an Uncertainty scale what-if selector (0.5×, 1×, 2×, 3×) backed by the scenario endpoint and labelled as a what-if.
- On fresh live job `391e7c01617f4a229d38b2b3da7e6f57`, current-assessor coverage is 178 total, 140 valid interior TCA, 140 with finite research Pc, 0 requiring reason codes, 0 uncovered valid records, 0 boundary TCA. Class counts: 0 High, 8 Medium, 132 Low. Exact-log histogram counts and 13 encounter groups are recorded in `docs/ORION_STAGE2_COVARIANCE_COMPARISON.md`.
- The 17:01:31.258995Z group near the requested case has eight connected raw pairs, including ISS module connections; these collapse to one representative card with all eight records available in its detail list. This fresh job's miss was 21.847650 km, so it does not reproduce the requested 21.842 km event.
- Analytics utility tests: 2 passed. Production build passed after stopping the managed ORION dev servers to free memory; Vite emitted only its existing large-chunk warning.

- Added finite exact `log10_pc` and a `negligible` flag to the research-Pc record. Primary Pc and sensitivity displays use the configurable default `LOG10_PC_FLOOR=-30`; the exact log10 value remains in the technical record. Percent display uses the corresponding `< 1e-28%` floor.
- Revised the default risk score to `clip(((log10 Pc + 12) / 10) × 100, 0, 100)`, version `orion-physics-pc-risk-v2`; High ≥ 1e-4 and Medium ≥ 1e-7 remain project policy. The score window is configurable via `ORION_RISK_SCORE_LOG10_FLOOR` and `ORION_RISK_SCORE_LOG10_CEILING`.
- Focused checks: backend probability-classification and automatic-research-Pc tests: 12 passed; frontend Pc presentation tests: 6 passed.
- Archive evidence: `screening-job-8fa7230ce99e4182afc2c1a8506130bf` (saved snapshot dated 2026-10-13) contains 52 events and a repeated SL-3 R/B group against four ISS modules at TCA `2026-10-13T12:56:17.152617Z`, miss `1.764890 km`, speed `7.202890 km/s`. This verifies an identical-geometry co-location pattern in this snapshot, but not the directive's stated 21.842 km case. Other groups in this snapshot vary by TCA and geometry and are not grouped by this evidence alone.
- The larger 2026-10-19 snapshot contains 120 records, including 118 valid-status records, but its closest records include boundary solutions and legacy records lack the current research-Pc fields. Restore/backfill was attempted through the current local API; the response still did not attach research-Pc records, so it cannot support the requested comparable 10-event table yet.
- This was the pre-Stage-2D status. The fresh Stage 2 acceptance attempt and remaining full-suite blockers are recorded below. Do not begin Stage 3 before Stage 2 acceptance and user approval.

### Current Stage 2 acceptance attempt (2026-10-24)

- Current checkout: branch `feature/orion-completion`, HEAD `d09d9ee`. Acceptance evidence/repair files: `STATUS.md`, `stage2-fresh-job-summary.json`, `stage2-policy-table.json`, `stage2-full-pc-record.json`, `backend/app/services/ai_risk_prioritization.py`, the relevant backend ranking/report tests, and the Collision Analysis summary test. Other dirty report, cache, and UI work remains preserved and uncommitted.
- Started the managed servers on the required ports. `/api/version` returned `d09d9ee`, matching HEAD; the frontend returned HTTP 200 on `127.0.0.1:5173`.
- Fresh current-code job `b10de1f092d5457da604249c725efefd` completed as **partial** (200 catalog objects; candidate-minimum cap reached). Pagination exposes 180 assessment rows: 142 valid interior-TCA, 142 with finite research `log10_pc`, 0 reason-code cases, 0 valid events without Pc or a reason, and 0 boundary records.
- Recomputed the 10 closest events under all three covariance policies through the fresh API. The policy table is in untracked `stage2-policy-table.json`; the full returned research-Pc record is in `stage2-full-pc-record.json`. The leading group has 8 pair records at a shared TCA; catalog-wide grouping found 13 groups covering 104 raw events (180 raw records displayed as 89 representatives, with source rows retained).
- Scanned both paginated assessment API payloads (180 rows) using bounded numeric-lexeme matching: 4,034 scientific-notation tokens, maximum absolute exponent 261, and none beyond ±300.
- Bounded final suites/build (10-minute command timeout each): backend **327 passed, 1 failed, 101 subtests passed** in 71.94s; frontend **186 passed, 0 failed** in 5.43s; production build passed in 53.59s with the existing large-chunk warning. Logs: `backend/backend-tests.log`, `frontend-tests.log`, and `build.log`.
- Remaining backend failure: `ResearchManeuverTests.test_maneuver_api_uses_valid_event_and_bounded_configuration` expects `Maneuver ML held-out evidence: 9 parents / 51 candidates`, but this report fixture supplies no maneuver evaluation metadata and the current report therefore cannot produce those counts. This is existing maneuver/report work outside Stage 2; no fabricated evaluation values were added. Other four initially failing assertions are now passing: exact-log-Pc ranking, the source-matched research-Pc rank fixture, report TCA text handling, and the frontend coverage/presentation checks.
- Stage 2 is still **incomplete**; no Stage 2 commit was made because a required backend assertion remains failing. Do not start Stage 3. The fresh job remains partial because the candidate-minimum cap was reached.

## Stage 1 verification

- Repository root: `C:/Users/NARSINH K/Documents/Codex/2026-10-04/you-are-modifying-an-existing-research/outputs/space-debris-ssa-platform`; branch: `feature/orion-completion`.
- A stale server on port 8001 returned `404 Not Found` for `/api/version` before this phase. The fixed-port launcher now refuses busy ports, starts visible PowerShell windows, waits for backend version and frontend readiness, and verifies the backend commit.
- A current-checkout completed screening job exposed a Smart Filter failure: deep-copying the job attempted to copy its process-local `asyncio.Task` and raised `TypeError: cannot pickle '_asyncio.Task' object`. The Smart Filter now copies only data fields and has a regression test.
- The current Smart Filter endpoint returned `result_type=physics_smart_filter`, with 3 events before, 3 kept, 0 filtered on a short real run. A full-day run produced 19 events, 13 valid; one valid event's maneuver endpoint returned 4 candidates and baseline Pc status `available`.
- `node --test tests/apiRouteContract.test.js`: 1 passed, 0 failed.
- `pytest tests/test_smart_filter.py -k process_local`: 1 passed, 4 deselected; two environment/dependency warnings (Starlette httpx deprecation and pytest cache creation).
- PowerShell parser: both launcher scripts valid. Launcher start succeeded on 8001/5173; `/api/version` reported `e1e6573`, matching `git rev-parse --short HEAD`, with 7 model artifact versions; frontend returned HTTP 200. Stop/start cycle released both ports (0 listeners) and restarted both successfully.
- No production build or full suites were run, per Phase 2 section 2's credit rule (full suites/build are reserved for the ends of Stages 2, 5, 7, and 8).

## Preserved unfinished report work

The pre-existing Stage 6 report changes remain uncommitted and must be completed in Phase 2 Stage 7. Current report-work paths include `backend/app/services/reports.py`, `backend/tests/test_report_status.py`, `src/components/UI/ManeuverUserUpload.jsx`, `src/styles.css`, `tests/reportDownloads.test.js`, and `.stage6_qa_preview/`, plus report-only hunks in `backend/app/main.py` and `src/App.jsx`. The live-cache file change is preserved separately.

## Scope and limitations

- The backend and frontend are started only at `127.0.0.1:8001` and `127.0.0.1:5173`; the launcher fails if either port is occupied.
- Current launcher commit: `e1e6573`; current Stage 1 code commit: `a8e1300`.
- No browser visual verification is claimed.
- Space-Track remains out of the workflow.

### All-saved-job model refresh (2026-10-25)

- Backend-only. Corrected training input selection from the prior newest-job-only 70-parent run to all 10 saved screening jobs. The archive has 260 valid-status unique event rows; 220 pass the current valid interior-TCA and real CelesTrak input screen. The other 40 do not meet that provenance screen.
- Grouped split uses 142 physical encounter groups: train 99 groups / 147 parents / 2,644 scenarios; validation 21 / 36 / 648; test 22 / 37 / 666. Dataset v5 has 3,958 scenarios from 220 parents; 2 labels were rejected for Pc/log mismatch.
- Added v3 physics features `miss_sigma_ratio`, its square, and `log10(HBR^2 / (2*sqrt(det(sigma2D))))`. Retrained with `scripts/retrain_all.ps1`; generated metrics and artifacts are in `docs/MODEL_METRICS.json` and `backend/app/ai/artifacts/`.
- Pc test MAE/RMSE: all rows 0.0765338 / 0.2320370; median baseline 9.3299688 / 14.3797862; linear baseline 5.0609578 / 6.7198512. Non-negligible rows (459): 0.1098556 / 0.2783319; median 2.3033657 / 4.4920524; linear 3.3695553 / 4.6135896. Beats both baselines in both subsets; app model status is available (2.3.0).
- Risk test: support Low/Medium/High 272/236/158; confusion `[[272,0,0],[7,229,0],[0,6,152]]`; macro-F1 0.9801134 vs majority 0.1933191; usable.
- Smart Filter test: support insignificant/significant 508/158; confusion `[[508,0],[6,152]]`; significant precision 1.0, recall 0.9620253, FN 6; macro-F1 0.9873872 vs majority 0.4327087 (FN 158), deterministic 1 km baseline 0.6768758 (FN 0). Model beats both macro-F1 baselines and majority FN count; the independent 1 km/physics guard remains enabled.
- Method and final results: `docs/METHODOLOGY.md`, `docs/MODEL_METRICS.json`. No frontend files changed.

## Backend hygiene and nebula theme commit (2026-10-25)

- Added the Pc-surrogate limitation: `miss_sigma_ratio` and log-HBR nearly determine log-domain Pc, so low error reflects formula reproduction and is not independent predictive skill or validation against observed collisions.
- Corrected the backend policy label to `2x TLE-age position-sigma baseline`. Rocket-body name designations now override a conflicting generic payload type; the SL-3 R/B (10114) path is covered by classification tests. Saved archive payloads were not opened during this pass, so no direct newest-job event-type inspection is claimed.
- Refreshed stale backend assertions for the all-saved-jobs training data and uncertainty guard: backend full suite **340 passed**, 1 warning, 107 subtests; `backend/backend-suite-requested.log`.
- Frontend suite: **187 passed, 0 failed**, `frontend-suite-requested.log`. Production build succeeded; existing large-chunk warning, `production-build-requested.log` (stderr in matching `.err.log`). Each command had a 600-second timeout.
- Commit `cfc7891 Add nebula theme base` contains only `src/main.jsx` and `src/og-theme.css`. The live cache remains uncommitted. Backend fixes, tests, methodology, and this status update are committed as `492c173 Fix backend research hygiene checks`.
- Metrics from `docs/MODEL_METRICS.json` (all 10 saved jobs, test split): risk support Low/Medium/High `272/236/158`; confusion matrix true rows/predicted columns `[[272,0,0],[7,229,0],[0,6,152]]`; per-class P/R/F1: Low `0.974910/1.000000/0.987296`, Medium `0.974468/0.970339/0.972399`, High `1.000000/0.962025/0.980645`; macro-F1 `0.980113`, majority baseline `0.193319`.
- Pc regressor v2.3.0: MAE/RMSE `0.076534/0.232037` log10 Pc over 666 rows; among 459 non-negligible rows `0.109856/0.278332`. Smart Filter v2.3.0: support insignificant/significant `508/158`, confusion `[[508,0],[6,152]]`, significant precision/recall `1.000000/0.962025`, macro-F1 `0.987387`, majority macro-F1 `0.432709`, deterministic 1 km macro-F1 `0.676876`.
- Maneuver ranker v2.0.0 test regret is `0.031142` versus baseline `0.017708` log10 Pc-reduction units (8 parents / 38 candidates); `ranking_used=false`, deterministic physics ranking remains in use.
## Nebula Glass Maneuver Workbench (2026-10-25)

- Rebuilt Maneuver Assessment in `src/components/UI/ManeuverWorkbench.jsx` and wired it to the existing event selection, maneuver request, report download, screening context, and upload handlers. It defaults to the existing highest exact-log10-Pc valid event, provides 5 min / 30 min / 90 min (5,400 s) / 3 hour presets, shows before/after research Pc and geometry, fuel assumptions, RTN values, ranked candidates, model ranking status, and the shared-covariance / along-track sanity disclosure. PDF/CSV/JSON report buttons remain available.
- The existing 1,800 s lead-time ceiling blocked the requested 5,400 s and 10,800 s presets. Raised maneuver search and upload bounds to 10,800 s (3 hours); kept the post-TCA horizon at 1,800 s. Maximum propagation grid is 2,521 samples. This is the minimal backend change for the requested presets.
- Frontend suite: **189 passed, 0 failed**; log `frontend-workbench-suite.log`. Production build succeeded with the existing >500 kB chunk warning; log `maneuver-workbench-build.log`. Backend focused lead-bound tests: **3 passed**, 33 deselected, 1 warning, 6 subtests; log `backend/maneuver-lead-bounds.log`. Commands used a 600-second timeout.
- No browser interaction was performed, so the requested 90-minute live click-through and resulting event-specific numeric output have not been verified in the UI.