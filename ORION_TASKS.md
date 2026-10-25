# ORION SSA - REMAINING TASKS (ONE AT A TIME)

Do the task I name. Report using the format at the bottom. Wait for "next".

## T5 - Retrain the AI models on the corrected targets

1. Sensitivity range. The research-Pc sensitivity (p10/p50/p90) currently varies only the hard-body radius, so some events show a single value. Make it also span covariance scale 0.5x to 3x, computed in log10 space.
2. Scenario data. Use the real screened events saved in backend/exports/screening-job-*.json as parent events (read them with a script, do not print them). Generate scenario variants by varying covariance scale (0.5-3x), HBR proxy, TLE age, and miss-distance scale (0.01-1x) so Low, Medium and High all appear. Label every generated row as a synthetic scenario variant. Compute every label with the physics calculator. Split by parent event ID with a fixed seed and save the split.
3. Models. (a) Pc regressor, target max(log10 Pc, -30). (b) Risk classifier (Low/Medium/High from the same policy). (c) Smart Filter classifier (significant vs insignificant) plus an independent safety guard that always retains an event if its miss distance is below the configured threshold, if any scenario gives Pc at or above the significant threshold, or if the assessment is invalid or uncertain. (d) Maneuver Pc-reduction ranker (do after T6 if it needs the new consistent covariance).
4. Metrics. Report the number of real parent events versus scenario rows, MAE/RMSE versus a baseline (on all held-out data and on the non-negligible subset), confusion matrix, per-class precision/recall/F1, macro-F1, majority baseline, Smart Filter recall on significant events and its false-negative count. A model is usable only if it beats its baseline on held-out parents; otherwise the app must show a labelled rule-based fallback.
5. One command. scripts\retrain_all.ps1 regenerates scenarios, retrains, saves artifacts with version metadata, writes docs/MODEL_METRICS.json, and prints the metrics.
6. Labels. Rename the rule-based queue to "Review priority (rule-based)". Only trained-model output may be called AI.

## T6 - Maneuver fixes

1. The Maneuver page and Collision Analysis must read the same research-Pc record for an event. Add a test that compares them for every valid event.
2. The baseline and every candidate use the identical covariance and HBR. Only the mean relative state changes, plus a documented burn-execution term if used.
3. Every candidate shows numbers for new TCA, miss distance, relative velocity, before/after Pc, absolute and percentage reduction, and fuel. For a negligible baseline show a numeric explanation and the change in log10 Pc, and document the percentage policy.
4. Investigate why a 0.01 m/s burn changed miss distance by about 2.4 m but changed Pc by about 400x, find the cause, fix it, and report the corrected example.
5. Add the same Uncertainty-scale what-if applied equally to before and after. Default the page to the event with the highest exact log10 Pc.
6. Keep the form and CSV/JSON upload with strict validation. Provide a sample input file exported unmodified from a real screened event.
7. Compare an in-track burn's along-track shift with 3*dv*dt and state the limits.

## T7 - Design system and Collision Analysis page

* Style "Nebula Glass". Deep navy-violet background with layered radial-gradient nebula blobs and subtle star layers. Soft cursor glow (about 400px radial gradient, low alpha, driven by CSS variables and requestAnimationFrame), turned off on Globe and Heat Map pages, when the tab is hidden, on touch devices, and under prefers-reduced-motion. Cards: translucent fill, backdrop-filter: blur(16px), 1px light border, 20px radius, 24px padding, soft shadow. Accents cyan and violet. Risk colours green, amber, red with WCAG AA contrast. Visible focus rings.
* Type. Body 16px, secondary 14px, never below 12px. System font stack. Tabular numbers. Pc headline 40-48px.
* Shell. Left sidebar (collapsible), top bar (search, data-source chip, backend-version chip), content max-width 1440px.
* Collision Analysis. KPI cards (counts of encounter groups, not raw rows), then two panels. Left (about 380px, own scroll, search, sort, class chips): compact event cards with pair names, class chip, Pc, score/100, TCA. Right: hero (names, IDs, true object types, large Pc, percentage, odds, score gauge, class chip, "Research Pc - Assumed Inputs" badge), tiles (miss distance, relative speed, TCA), tabs Overview / Uncertainty / AI / Report, buttons Show in Globe, Assess Maneuver, downloads. Foster and source-reported Pc go in a muted "Other Pc channels" accordion. No explanatory paragraphs in numeric cells. Responsive: stacked below 900px.
* Cosmetic bugs to fix here. Sidebar "ML MODEL: unavailable" must read the current collision models' status. The unit is doubled ("km/s km/s"). The footer version message is doubled. "AI-prioritized events" wording must not describe the rule-based score.
* Checks. Add a script that fails if any CSS font-size is below 12px. Add tests that no numeric cell string is longer than 40 characters.

## T8 - Maneuver and Smart Filter pages

* Maneuver: inputs card; Before vs After hero comparison (Pc, miss distance, reduction); fuel card with assumption label; top-5 candidates with "show all"; AI rank next to physics-confirmed rank; expandable assumptions.
* Smart Filter: lead with the physics-supervised filter (Before / Kept / Filtered as large stats; reason chip, confidence and guard result per pair; CSV export; model card with metrics, split sizes, false negatives, trained vs fallback status). Move the old catalog heuristic (900 to 809) to a collapsed secondary section called "Catalog overview, not the collision filter".

## T9 - Reports, upload, Globe, Heat Map

* Reports: a Reports page with an on-screen formatted document and PDF/CSV/JSON downloads for collision and maneuver reports. Contents: object names, IDs and types, TCA, miss distance, relative speed, each Pc channel separately, percentage, score and class, covariance and HBR with units, frame, epoch and source, AI outputs, method, assumptions, sensitivity, limitations. Check PDF pages for clipped text and overflow with a renderer that is already installed.
* Upload: labels "Upload Conjunction Data" and "Calculate Collision Probability", with no organization names in user-facing text. Dropzone, 3-step indicator, sample file, provenance chips (read / derived / assumed / missing). Test valid, malformed, incomplete and incompatible-frame files.
* Globe and Heat Map: apply the theme with no frame-rate loss. Name the heat-map metric. Keep Show in Globe working with event ID and TCA preserved.

## T10 - Final

Full backend and frontend suites and the build (with logs). Write docs/METHODOLOGY.md with real numbers only (data sources, screening, covariance policies, Pc formulas including the log-domain form, score scale, thresholds, scenario generation, model targets and metrics, maneuver and fuel equations, Smart Filter guard, limitations). Save one real screening job as a demo snapshot labelled "saved snapshot". Final report: five real conjunctions, model metrics with parent counts, a maneuver example, a Smart Filter example, and a table of requirements done / partial / not done.

## REPORT FORMAT (after each task)

1. Commit hash and files changed.
2. Commands run with real results (test counts, build status).
3. The real output the task asked for.
4. Problems or limits.
5. "Waiting for next."
