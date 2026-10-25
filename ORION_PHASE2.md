# ORION PHASE 2 — DIRECTIVE FOR CODEX

Read this together with ORION_SPEC.md. Both are mandatory. If they conflict, follow the rule that is stricter about scientific honesty and about not fabricating results, and mention the conflict in your report.

---

## 0. FIXED ENVIRONMENT

* Repository: `outputs\space-debris-ssa-platform`, branch `feature/orion-completion`.
* Frontend: **http://127.0.0.1:5173** (Vite).
* Backend: **http://127.0.0.1:8001** (uvicorn `app.main:app`, started from `backend\` with `backend\.venv`).
* Use exactly these ports. Never silently switch ports.
* Before any browser or HTTP check, call `GET http://127.0.0.1:8001/api/version` and confirm it matches this working tree. A stale server on port 8001 already produced false "Not Found / Unavailable" screens once. If port 8001 is held by a process that is not this repo's backend, report the PID and ask me. Do not use another port.
* Space-Track stays out of the workflow. Data sources are CelesTrak, user uploads, and the saved snapshot.
* Do not commit secrets, virtual environments, caches, or large generated data.

## 1. APPROVAL PROTOCOL (STRICT)

Work in the numbered stages below. After each stage:

1. Run that stage's checks.
2. Commit only that stage's files.
3. Update `STATUS.md`.
4. Send the report using the template in section 5.
5. **STOP and wait for me to reply "approved".** Never start the next stage without that reply.

## 2. CREDIT AND TIME RULES

My previous credits ran out during a PDF-rendering task that ran for hours and tried to download a 63 MB wheel.

* No new heavy dependencies. No large downloads. Do not download browsers or renderers. If a tool is not already installed, say so.
* If a sub-task fails twice or runs longer than about 15 minutes, stop it and report instead of continuing.
* Do not re-audit the repository. Do not print whole files. Keep test output to summaries.
* Run focused tests during a stage. Run the full backend and frontend suites plus the production build only at the end of Stages 2, 5, 7 and 8.
* Extend existing code. Do not rewrite working components. Preserve Globe, Heat Map, CDM/Foster calculator, archived-job restoration, and Show in Globe.

## 3. DEFECTS I FOUND IN THE RUNNING APP

Fix each in the stage indicated.

**D1 (Stage 2).** Pc is displayed with absurd exponents, for example `1.74132e-8788` (also repeated as a percentage), and a sensitivity range like `9.9e-229782 to 2.2e-217`. The numbers imply an encounter-plane sigma of only about 0.07–0.11 km, roughly ten times smaller than typical TLE position error (order 1 km). This is probably the ESA-archive prior being applied to TLE-derived states. Verify this. It also destroys the Pc regression target (previous validation MAE was 646 log10 units against a 670 baseline), makes the sensitivity range meaningless, and makes every event score 0.0/100.

**D2 (Stage 2).** Every event is Low with a score of 0, so the page shows nothing informative. With realistic uncertainty most real events will honestly be Low, so ranking and display must still be informative (see 2.5).

**D3 (Stage 2).** Probable duplicate encounter: SL-3 R/B 10114 vs ISS (Zarya), ISS (Nauka), Poisk and Progress MS-34 all show the identical TCA, miss distance (21.842 km) and relative speed (12.0468 km/s). Verify and group.

**D4 (Stage 4).** On Maneuver Assessment, "Selected Conjunction Context" shows research Pc as "Unavailable – model inputs unavailable" for CA-5656FB1C8EF601C27F23 (SL-3 R/B vs POISK), while Collision Analysis shows a research Pc for the same pair.

**D5 (Stage 4).** Earlier maneuver example: a 0.01 m/s burn changed miss distance by about 2.4 m (0.236239 → 0.238669 km), yet Pc dropped from 2.97e-7 to 7.30e-10 (about 400×). This is implausible unless covariance or encounter-plane geometry differs between before and after. Find the cause.

**D6 (Stage 6).** The Smart Filter page leads with the old catalog heuristic (900 → 809 globes). Its ML status says "Artifact available · inference unavailable" (that is the old ESA model). The Stage 4 physics-supervised filter is not the main content. Review-priority bands labelled LOW/MEDIUM (for example 29.6/100, 46.7/100) conflict with the Pc-based class.

**D7 (Stage 3 and 5).** "AI queue 29.6/100" is actually the deterministic geometry/speed fallback, so it must not be called AI. The largest badge on each event is that review priority instead of the Pc-derived risk score.

**D8 (Stage 5).** Foster Pc and source-reported Pc are shown as bold red "Unavailable" blocks. They are simply not provided by the screening data and must not look like errors.

**D9 (Stages 5–7).** The layout is congested: tiny text, full-width thin strips, a two-column mini-table "report preview" with long text, and long explanatory paragraphs inside numeric cells.

---

## 4. STAGES

### STAGE 1 — Environment and housekeeping (small)

1. Confirm the environment (section 0). Print repo root, branch, `git log --oneline -8`, `git status --short`.
2. Commit the Phase A work (version endpoint, version badge, launcher, Smart Filter deep-copy fix and tests) as its own commit. Leave the unfinished report work (Stage 6 of the old plan) uncommitted. List those files in your report.
3. Make `scripts/start-dev.ps1` reliable: it opens two visible PowerShell windows (backend on 8001, frontend on 5173), fails loudly if either port is busy, waits for `/api/version`, and prints both URLs and the commit. Add a `scripts/stop-dev.ps1` that stops only the processes it started. Document both in the README.
4. Create or update `STATUS.md`.

Report, then STOP.

### STAGE 2 — Uncertainty model and Pc numerics (the root cause)

**2.1 Compare covariance policies on the same real events.** The policies are (a) the current ESA-prior policy, (b) the baseline TLE-age model (radial 0.1 km + 0.1 km/day, in-track 0.5 km + 1.5 km/day, cross-track 0.2 km + 0.2 km/day, age measured at TCA), and (c) policy (b) scaled 2×. For the 10 closest events print: miss distance, encounter-plane sigmas, miss/sigma ratio, and log10(Pc) under each policy. Choose the default for TLE-derived states with a written justification based on physical realism, not on which policy gives bigger numbers. Keep the other policies selectable and labelled. Do not describe any of them as measured uncertainty.

**2.2 Log-domain Pc.** Compute and store `log10_pc` as a finite number. Use the full numerical Foster integral where it is well-conditioned. For large Mahalanobis distance (HBR much smaller than sigma), use the log-domain small-HBR form `log10(HBR² / (2·sqrt(det Σ2d))) − (m²/2)/ln(10)`, and verify that both agree in the overlapping regime. Never produce, store, or serialize a float that underflows to 0 or a string with an exponent beyond ±300.

**2.3 Floor and display policy.** Add a configurable `LOG10_PC_FLOOR = -30` and a `negligible` flag. For `log10_pc < -30` the primary display is "< 1e-30 (negligible)", the percentage is "< 1e-28 %", the risk score is 0, the class is Low, and the exact `log10_pc` is kept in technical details. Otherwise display like `2.6 × 10⁻⁷`, with the percentage and "about 1 in N" odds. The sensitivity range (p10/p50/p90) uses the same log-domain values and floor.

**2.4 Score scale.** Change the default score window from the old -8 to -4 to `risk_score = clip((log10 Pc + 12) / 10 × 100, 0, 100)`, so Pc 1e-7 scores 50 and Pc 1e-4 scores 80. Keep it configurable and versioned, update tests and docs, and state that the thresholds (High ≥ 1e-4, Medium ≥ 1e-7) are project policy, not universal standards.

**2.5 Ranking and display for a mostly-Low catalog.** Sort by exact (unfloored) `log10_pc` descending, with miss/sigma ratio as a tie-breaker, so negligible events stay ordered. Add a compact distribution of log10 Pc across events (histogram) and counts by class. Add an "Uncertainty scale" what-if control (0.5×, 1×, 2×, 3×) that recomputes research Pc through the existing estimator and is clearly labelled as a what-if. If it is not cheap to add, report that and skip it.

**2.6 Valid-event coverage.** Report the current counts: total events, valid events, events with a research Pc, events with a reason code. Every valid event must have either a numeric research Pc or a plain-language reason code (code in details). Fix defects that cause missing values.

**2.7 Encounter groups (D3).** Detect likely co-located objects (shared object in the pair, same TCA to the millisecond, same miss distance and relative speed to at least 4 significant digits). Verify this on the current data. Show one card per group with "+N co-located objects" and keep all raw events in the data and exports. Report the before/after event count. Do not delete events.

**Acceptance.** Real output: the 10-closest-events table (all three policies), the final counts, one event's full Pc record, and proof that no number or string in the API contains an exponent beyond ±300. Run the full backend and frontend suites and the build. Commit. STOP.

### STAGE 3 — AI models on corrected targets

1. **Training scenarios.** Generate variants from real parent events by varying covariance scale (0.5×–3×), HBR proxy, TLE age, and **miss-distance scale (0.01×–1×)**, so the data covers Low, Medium and High. Label every generated row as a synthetic scenario variant. Compute every label with the physics calculator. Split by parent event ID with a fixed seed and persist the split. Report the number of real parent events versus scenario rows. Never present scenarios as independent real conjunctions.
2. **Model 1 (Pc surrogate).** Target is `max(log10_pc, -30)`. Report MAE and RMSE on all held-out data and separately on the non-negligible subset, with a baseline (median and linear). Mark the model usable only if it beats the baseline on held-out parents. Otherwise show the deterministic fallback labelled as a fallback.
3. **Model 2 (risk class).** Labels come from the same physics policy. Report the confusion matrix, per-class precision/recall/F1, macro-F1, and the majority baseline.
4. **Smart Filter classifier.** Retrain on the new labels. Keep the independent safety guard (miss-distance threshold, any-scenario Pc ≥ significant threshold, invalid or uncertain events retained). Report recall on significant events and the false-negative count.
5. **Maneuver surrogate.** Retrain the Pc-reduction ranker on the consistent covariance policy from Stage 4's design (before and after use the same uncertainty). If Stage 4 is not yet done, retrain it in Stage 4 and say so.
6. **One command.** `scripts/retrain_all.ps1` plus a Python entry point regenerates the scenarios, retrains all four models, saves artifacts with version metadata, writes `docs/MODEL_METRICS.json`, and prints the metrics. Training never runs during a user request.
7. **Labels.** Rename the rule-based queue to "Review priority (rule-based)". Show "AI" only for trained-model output, and show "fallback" labels explicitly.

**Acceptance.** Real metrics table with parent counts and scenario counts, API output for 3 events showing physics Pc beside AI output, and model status. Commit. STOP.

### STAGE 4 — Maneuver science

1. **One Pc source.** The Maneuver page and Collision Analysis must read the same research-Pc record for the same event (D4). Add a test: for every valid event, baseline Pc on the maneuver endpoint equals the Collision Analysis research Pc.
2. **Identical uncertainty.** The baseline and every candidate use the same covariance policy and HBR. Only the mean relative state changes, plus an explicitly documented burn-execution term if used (default: documented and small, or zero, stated in the UI). Find and fix the cause of D5 and report the corrected example.
3. **No dashes.** For every candidate show numeric: new TCA, miss distance, relative velocity, before/after Pc, absolute reduction, percentage reduction, and fuel. Fuel uses `dm = m(1 − exp(−Δv/(Isp·g0)))` with defaults 500 kg and 220 s labelled "estimated from default assumptions". For a negligible baseline show a numeric statement ("Baseline log10 Pc = −X: already negligible, no maneuver required") and report Δlog10 Pc as the reduction measure. Define and document the percentage-reduction policy for that regime.
4. **Sanity checks.** Compare the in-track burn along-track shift with `3·Δv·Δt` and state its limits. Add a regression test so tiny burns cannot produce huge Pc changes without a geometric explanation.
5. **Event choice and what-if.** Default to the event with the highest exact log10 Pc. Support the same Uncertainty scale what-if as Stage 2, applied equally to before and after.
6. **User input.** Keep the form and CSV/JSON upload, with strict validation (frame, units, epochs, object identity). Provide a downloadable sample input file exported unmodified from a real screened event.
7. Retrain the maneuver surrogate if Stage 3 deferred it.

**Acceptance.** One real maneuver example (before/after miss, Pc, reduction, fuel with assumptions, AI rank versus physics-confirmed rank), the D4 equality test passing, and the D5 explanation. Commit. STOP.

### STAGE 5 — Design system, app shell, Collision Analysis, Home

**Design language: "Nebula Glass".** Build once, reuse everywhere.

* **Type.** Body 16px, secondary 14px, never below 12px. System font stack (Inter, Segoe UI, system-ui). Line-height 1.5. `font-variant-numeric: tabular-nums` for numbers. Pc hero value 40–48px.
* **Background.** Deep navy to violet (`#05070F` → `#0B1026`) with fixed layered radial-gradient nebula blobs (violet, cyan, magenta at low alpha) and two or three subtle star layers (CSS or a lightweight throttled canvas) with a very slow drift. A soft cursor glow (about 400px radial gradient, alpha about 0.12) driven by CSS variables updated in `requestAnimationFrame`. Disable the glow and drift on the Globe and Heat Map pages, when the tab is hidden, on touch devices, and under `prefers-reduced-motion`.
* **Cards.** Translucent gradient fill, `backdrop-filter: blur(16px) saturate(140%)`, 1px border `rgba(255,255,255,0.10)`, radius 20px, padding 24px, soft shadow, hover lift with a thin cyan-to-violet gradient border.
* **Color.** Accents cyan and violet. Risk colours Low green, Medium amber, High red, all with at least 4.5:1 contrast on their background. Visible keyboard focus rings.
* **Components.** KPI stat card, risk chip, circular score gauge (SVG, 0–100), provenance chips (read / derived / assumed / missing, each a distinct colour), accordion, tabs, compact table with sticky header, pagination, plain-language empty/loading/error states, info tooltips explaining Pc, TCA, HBR and covariance in simple words.
* **Shell.** Left sidebar (240px, collapsible to 72px, icon + label), top bar (search, data-source chip, backend-version chip), content max-width 1440px centred, 8px spacing scale. Two-panel layouts at ≥1280px, list as a drawer at 900–1279px, stacked below 900px. No horizontal scroll at ≥1280px.

**Collision Analysis page.**

```
┌ sidebar ┐ ┌ top bar: search · source chip · version chip ───────────────┐
│ Home    │ │ Collision Analysis                       [Start Screening]  │
│ Globe   │ │ [Total] [Valid] [Non-negligible] [High/Medium]  KPI cards   │
│ Filter  │ │ ┌ Event list 380px ┐ ┌ Selected event ─────────────────────┐│
│ Collis. │ │ │ search · sort ·  │ │ Hero: names/IDs/types, BIG Pc,      ││
│ Maneuv. │ │ │ class chips      │ │ percentage, odds, score gauge /100, ││
│ Reports │ │ │ compact cards,   │ │ class chip, "Research Pc – Assumed  ││
│         │ │ │ own scroll       │ │ Inputs" badge                       ││
│         │ │ └──────────────────┘ │ Tiles: miss · rel. speed · TCA      ││
│         │ │                      │ Tabs: Overview | Uncertainty | AI | ││
│         │ │                      │ Report   Buttons: Globe · Maneuver  ││
└─────────┘ └──────────────────────┴─────────────────────────────────────┘
```

* Each list card shows: colour bar by class, pair names, class chip, Pc, score /100, TCA. The sort policy is visible.
* The hero shows the Pc-derived score as the headline. "Review priority (rule-based)" is a small secondary label. The "negligible" display follows 2.3.
* Foster Pc and source-reported Pc live in an "Other Pc channels" accordion as muted rows ("Not in screening data — upload conjunction data to compute"), never red "Unavailable" blocks.
* Uncertainty tab: covariance, HBR, sensitivity, what-if control. AI tab: AI log10 Pc versus physics Pc, AI class versus physics class, model status or fallback label. Long explanations go into tooltips or "Why this value?" accordions.
* Remove the tiny two-column "Selected Collision Report Preview" from this page. It moves to Reports in Stage 7.
* Keep Show in Globe and Assess Maneuver working, with event ID and TCA preserved. Remove the horizontal scroll.

**Home.** Dashboard with KPI cards, class-count chart, the log10 Pc histogram, and links to each page.

**Checks.** Add a static check script that fails if any CSS declares `font-size` below 12px. Add presentation-function tests: no numeric cell string longer than 40 characters, no Pc string with an exponent beyond ±300. If Chromium or Playwright is **already installed**, save screenshots at 1366×768 and 1920×1080 at 100% browser zoom for each redesigned page to `docs/screenshots/`. If not, do not download anything. Say so and give me manual steps.

**Acceptance.** Tests, static check, build, and the manual verification steps. Commit. STOP.

### STAGE 6 — Maneuver and Smart Filter pages

**Maneuver.** Left card: inputs (burn lead, Δv, RTN direction, optional mass and Isp, Uncertainty scale, upload). Right: a Before vs After hero comparison (two large cards with an arrow, Pc and miss distance, a large reduction figure), a fuel card with its assumption label, a top-5 candidate table with "Show all", AI rank next to physics-confirmed rank, expandable assumptions, and optional chart of Pc against Δv. All values numeric per Stage 4.

**Smart Filter.** Lead with the physics-supervised filter: a funnel of three large stats (Before → Kept → Filtered), a kept/filtered toggle list with a reason chip and model confidence per pair, the safety-guard result, pagination, and CSV export. Add a model card (name, version, recall, precision, false negatives, split sizes, training-data provenance, trained versus fallback status). Move the old 900 → 809 catalog view into a collapsed, clearly labelled secondary section ("Catalog overview, not the collision filter"). Fix the LOW/MEDIUM wording conflict by calling those values "review priority", never a risk class. Show the physics-supervised result at the top of the page and verify it renders there with no "Not Found".

**Acceptance.** Tests, build, static check, screenshots or manual steps. Commit. STOP.

### STAGE 7 — Reports, Upload, Globe, Heat Map

* **Reports.** A Reports page with an on-screen document view (sections of label/value tiles, not tiny rows) and PDF/CSV/JSON downloads for both collision and maneuver reports. The content follows ORION_SPEC.md section 10. Finish the unfinished report work in the working tree. Re-render the PDFs to images with a tool that is already installed. Check for clipped text, overflow, column widths, page breaks and units. Inspect the CSV/JSON contents. Add tests.
* **Upload.** "Upload Conjunction Data" and "Calculate Collision Probability" labels, with no organization names in user-facing text. Dropzone card, 3-step indicator (Upload → Validate → Results), a downloadable sample file (use the bundled reference CDM fixture, named `sample_conjunction_data.cdm`), results with provenance chips (read / derived / assumed / missing), and report downloads. Test valid, malformed, incomplete and incompatible-frame files.
* **Globe and Heat Map.** Apply the theme without frame-rate loss. The heat-map metric is explicitly named and defaults to clipped −log10 Pc or miss/sigma. Verify selected-event handoff and invalid values never being replaced by fabricated ones.

**Acceptance.** Full backend and frontend suites and build, real PDF page checks, one real uploaded-file calculation with field provenance. Commit. STOP.

### STAGE 8 — Final regression and delivery

* Full backend and frontend suites and the production build.
* `docs/METHODOLOGY.md` with real numbers only, covering data sources, screening, covariance policies and the chosen default, Pc formulas (including the log-domain form), score scale, thresholds, scenario generation, model targets and metrics, maneuver and fuel equations, Smart Filter policy and guard, and limitations.
* Save one real screening job as a snapshot labelled "saved snapshot" for demos.
* Final report as in ORION_SPEC.md section 5: five real conjunctions, model metrics with parent-event counts, a maneuver example, a Smart Filter example, PDF validation results, a requirement matrix (done / partial / not done with evidence), and exact browser steps with which ones you actually executed.

STOP after the report.

---

## 5. REPORT TEMPLATE (EVERY STAGE)

1. Repo path, branch, commit hash(es).
2. Files changed (grouped, short).
3. Tests run with counts, and build result.
4. Real output required by the stage.
5. Limitations and blockers.
6. "Awaiting your approval for Stage N+1."

## 6. STANDING RULES

* All honesty rules in ORION_SPEC.md apply. Never fabricate samples, metrics, test results or browser verification.
* Never label a rule-based result as AI. Never label research Pc as operational Pc.
* Never show a dash or "Unavailable" for a quantity that the documented model can calculate. Genuinely invalid inputs get a specific reason code and plain-language message.
* Do not claim browser verification unless you actually drove a browser.
