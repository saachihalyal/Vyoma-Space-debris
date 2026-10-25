# ORION SPECIFICATION — READ ALL THREE PARTS

This file contains ONE specification in three parts. All three parts are mandatory.

* PART 1 — Main Directive (Stages 0 to 10)
* PART 2 — Mandatory Addendum (numerical completeness, training data, UI coverage, stage control, final report)
* PART 3 — Additional Clarifications (Section 6, items A to G)

---

# PART 1 — MAIN DIRECTIVE

# ORION SSA — FINAL IMPLEMENTATION DIRECTIVE

## 1. ROLE AND MISSION

Act as a senior full-stack developer, orbital mechanics engineer, collision-probability specialist, machine-learning engineer, test engineer, and technical UI designer.

You are working on an EXISTING final-year project:

**ORION SSA — Space Debris Collision Prediction and Heat Map Analysis System**

Your mission is to complete the existing application, not create a separate demonstration or replace the working system.

The application must integrate:

1. Orbital conjunction screening.
2. Numerical collision-probability calculations.
3. Documented research estimates when measured inputs are missing.
4. Risk scoring and classification.
5. Two physics-supervised ML models for Pc prediction and risk classification.
6. An ML-assisted Smart AI Filter with a safety guard.
7. Maneuver assessment, fuel estimation, and candidate ranking.
8. Optional conjunction-data upload.
9. Collision and maneuver reports displayed on screen and downloadable as PDF, CSV, and JSON.
10. Globe, heat-map, and event-selection integration.
11. A polished, futuristic, accessible interface.
12. Reliable restoration of archived screening jobs.

The application must work end to end.

**A passing unit-test suite alone does not prove the application is complete.** API integration, real output, numerical correctness, and user-facing behavior must also be verified.

---

# 2. EXISTING PROJECT AND PRESERVATION RULES

The existing repository already contains or has contained:

* CelesTrak GP/TLE ingestion and orbital screening.
* TCA, miss-distance, and relative-velocity calculations.
* A Foster-style 2D collision-probability calculator.
* An automatic research-Pc estimator using assumed uncertainty inputs and an ESA-archive-derived prior.
* CDM upload and reference assessment.
* Historical screening-job restoration and paginated API responses.
* An ESA historical log-risk model.
* Deterministic AI-priority fallback logic.
* Globe visualization and heat-map components.
* Collision Analysis, Smart Filter, and Maneuver Assessment pages.
* Research maneuver calculations.
* Existing backend and frontend tests.

Inspect the actual current code before modifying it. These capabilities may have changed since previous reports.

Preserve working implementations, existing user changes, and established API contracts wherever possible.

Do not:

* Replace the orbital propagation engine without evidence of a defect.
* create duplicate calculators or disconnected demo endpoints.
* remove the globe, heat map, CDM upload, Foster calculator, research-Pc estimator, or archived-job restoration.
* delete or reset unrelated Git changes.
* fabricate sample conjunctions, model metrics, test results, or browser-verification claims.
* silently modify scientific inputs to make a test pass.

Reuse existing components when suitable.

---

# 3. SCIENTIFIC HONESTY AND NUMERICAL CONTRACTS

These rules apply to every stage.

## 3.1 Separate probability channels

Maintain distinct values for:

* `source_reported_pc`
* `event_specific_foster_pc`
* `research_pc`
* `ai_predicted_log10_pc`
* `risk_score`
* `ai_risk_class`
* `physics_risk_class`
* `final_risk_class`

Reuse the existing schema where equivalent fields already exist; avoid unnecessary duplicate names.

Definitions:

**Source-reported Pc:** a value supplied by an input source.

**Event-specific Foster Pc:** a calculation using compatible event-specific covariance, HBR, frame, and epoch information.

**Research Pc:** a numerical estimate calculated using explicitly documented assumed covariance and/or proxy HBR.

**AI-predicted log10(Pc):** a model output trained against a defined physics-generated research-Pc target. It is not automatically the authoritative Pc.

**Risk score:** a documented 0–100 transformation of the selected physics Pc channel.

**AI risk class:** the output of the separately trained risk classifier.

**Physics risk class:** a class calculated from the selected physics Pc and configured thresholds.

The displayed classification policy must explicitly state which result controls the final displayed class. Never silently combine unrelated outputs.

## 3.2 Required numerical behavior

For every valid conjunction whose research calculator succeeds, return:

* Numeric Pc in scientific notation.
* Pc as a percentage.
* Risk score from 0 to 100.
* Low, Medium, or High classification.
* TCA, miss distance, and relative velocity.
* Calculation method and input provenance.
* Covariance and HBR assumptions.
* AI outputs and their status, when applicable.

Extremely small positive probabilities must not silently become misleading zeros.

Do not put explanatory paragraphs in numeric Pc fields.

For malformed or physically invalid events, return a structured validation error with a specific reason code. Do not invent a numeric Pc.

For a valid event where the numerical estimator unexpectedly fails, report the calculation failure clearly, log the cause, and add a regression test. Do not substitute an arbitrary constant.

## 3.3 Provenance

Record:

* Input source and timestamp.
* Object identifiers.
* TLE epochs and ages.
* Covariance source, units, frame, and epoch.
* HBR source and units.
* Assumed parameters and configuration version.
* Calculation method and software/model version.
* Numerical quality and validation status.

Use explicit provenance categories such as:

* `event_specific`
* `assumed_research`
* `estimated_proxy`

Keep technical source attribution in documentation and expandable technical details.

User-facing upload controls must not explicitly name external organizations.

---

# 4. STAGE 0 — AUDIT AND BASELINE CHECKPOINT

Before modifying files:

1. Inspect the repository, current Git branch, `git status`, and existing uncommitted changes.
2. Trace ingestion → propagation → conjunction events → Pc → classification → API → frontend.
3. Locate every code path where Pc becomes null, missing, zero, or unavailable.
4. Inspect archive restoration and pagination.
5. Inspect the existing Foster calculator and research-Pc estimator.
6. Inspect the current AI artifacts, actual training targets, feature schema, preprocessing, and evaluation metrics.
7. Inspect Smart Filter, globe, heat map, maneuver, upload, and report workflows.
8. Identify stale API contracts, duplicate implementations, and tests that assert only superficial rendering.
9. Establish baseline backend tests, frontend tests, and production build status.

Produce a concise audit identifying concrete defects and the implementation order.

Then continue to implementation; do not stop after the audit.

### Checkpoint 0

Report:

* Git branch and initial working-tree state.
* Relevant files and their responsibilities.
* Baseline test/build results.
* Highest-impact defects.

Commit only audit artifacts if creating them is genuinely useful. Do not create a meaningless code commit simply to satisfy the checkpoint.

---

# 5. STAGE 1 — CONJUNCTION ENGINE AND RESEARCH-PC PIPELINE

## 5.1 Existing conjunction engine

Reuse the existing SGP4 and screening pipeline.

Verify that valid events include:

* Object IDs, names, and types.
* TCA in UTC.
* Miss distance in km and m.
* Relative velocity in km/s.
* Relative position and velocity at TCA.
* Available orbital elements and altitude.
* TLE epochs and age at TCA.
* Event validity and provenance.

Check the screening window and event-generation logic. Keep the existing configuration unless evidence justifies changing it.

Do not create artificial events to make the output look populated.

## 5.2 Covariance assumptions

Extend the existing research-Pc estimator.

Consolidate covariance settings in a documented configuration.

An illustrative baseline may use:

* Radial sigma: `0.1 km + 0.1 km/day × TLE age`
* In-track sigma: `0.5 km + 1.5 km/day × TLE age`
* Cross-track sigma: `0.2 km + 0.2 km/day × TLE age`

Compare this baseline against the existing ESA-archive-derived prior before selecting the default.

Requirements:

* State whether age is measured at TCA.
* Use consistent units.
* Rotate covariance into the correct frame at the appropriate epoch.
* Combine independent object covariances only under an explicit independence assumption.
* Reject invalid, non-finite, non-positive-definite, incompatible-frame, or inconsistent-epoch inputs.
* Include configurable uncertainty scaling and sensitivity analysis.
* Preserve valid event-specific covariance.

These parameters are research assumptions, not measured orbital uncertainties.

## 5.3 HBR proxy

Use actual compatible event HBR when available.

Otherwise, configure and document a proxy policy. Candidate initial radii are:

* SMALL: 0.12 m
* MEDIUM: 0.4 m
* LARGE: 1.3 m
* Unknown: 1.0 m

These are assumed proxy values. RCS_SIZE is not a direct measurement of physical radius.

Record the proxy and selection rationale. Do not describe it as measured object geometry.

## 5.4 Pc calculation

Use the existing Foster-style 2D probability calculation where its assumptions are satisfied.

The research calculation must:

1. Form a combined relative-position covariance.
2. Construct the encounter plane perpendicular to relative velocity.
3. Project covariance onto that plane.
4. Integrate the 2D Gaussian over the HBR collision disc.
5. Preserve numerical stability in extreme tails.
6. Include an independent small-HBR approximation.
7. Include Monte Carlo cross-checks for representative cases.

Keep event-specific Foster Pc and research Pc separate.

## 5.5 Required Pc tests

Test:

* Valid Pc remains within [0, 1].
* Large miss distance relative to uncertainty produces a suitably tiny Pc.
* With fixed covariance and HBR, moving the mean closer to the collision center produces non-decreasing Pc in tested geometries.
* The small-HBR approximation agrees within its valid regime.
* Monte Carlo agrees within statistically justified tolerance for representative cases.
* Invalid covariance and HBR are rejected.
* Extreme tails do not silently underflow into misleading values.

### Checkpoint 1

Run focused backend tests.

Print five actual valid conjunctions from the available dataset, including TCA, miss distance, relative velocity, Pc channels, provenance, covariance, and HBR.

If the dataset contains fewer than five valid events, report the actual count.

Commit the completed stage only after tests pass and the sample output is verified.

Report changed files, test results, numerical output, and any limitations.

---

# 6. STAGE 2 — RISK SCORE AND CLASSIFICATION

Use the selected physics Pc channel, normally research Pc when event-specific Foster Pc is unavailable.

A configurable baseline score is:

`risk_score = clip(((log10(Pc) + 8) / 4) * 100, 0, 100)`

Handle the Pc = 0 boundary through a documented limiting/log-domain policy without inventing a positive probability.

Configurable research classification thresholds:

* High: Pc >= 1e-4
* Medium: 1e-7 <= Pc < 1e-4
* Low: Pc < 1e-7

These are project policy thresholds, not universal safety standards.

Requirements:

* Show Pc and score separately.
* Identify the Pc channel used for scoring.
* Keep geometry priority, AI predictions, and physics classification separate.
* Make ranking deterministic and testable.
* Ensure archived jobs receive the same versioned derived calculations as fresh jobs.
* Do not mutate original source records during archive restoration.

### Checkpoint 2

Run focused backend and frontend tests.

Print a real event showing Pc, percentage, score, class, and classification basis.

Commit the stage and report results.

---

# 7. STAGE 3 — TWO AI MODELS FOR COLLISION ANALYSIS

Implement two separate ML tasks.

## 7.1 Model 1: Pc surrogate

Target: `log10(research_pc)`.

Candidate features:

* Miss distance.
* Relative speed.
* TLE ages.
* Altitude and inclination.
* Object type and available RCS category.
* HBR proxy.
* Covariance parameters or uncertainty summaries.

Train on physics-generated targets using grouped train/validation/test splits to prevent near-duplicate scenarios leaking between sets.

Fit preprocessing only on training data.

Report:

* Model name and version.
* Dataset size and target definition.
* Grouping strategy and split counts.
* MAE and RMSE in log10(Pc) units.
* Baseline metrics.
* Feature schema and preprocessing.
* Known limitations.

The model learns to reproduce physics-generated estimates. It is not independently validated against observed collisions.

## 7.2 Model 2: risk classifier

Target: Low, Medium, or High labels derived consistently from the same physics-generated Pc policy.

Report:

* Accuracy.
* Confusion matrix.
* Per-class precision, recall, and F1.
* Class balance.
* Majority-class baseline.
* Grouped split strategy and counts.

Address class imbalance. Do not report accuracy alone.

## 7.3 Integration

Integrate both models into the live screening pipeline.

Persist model artifacts, preprocessing, schema, and version metadata.

Expose model status and provenance through the API.

If an artifact is missing or unsuitable:

* Use a clearly labeled deterministic fallback.
* Do not call the fallback AI.
* Do not fabricate model metrics.
* Do not overwrite physics Pc with a model prediction.

The authoritative numerical Pc remains the physics calculation. AI predictions can support rapid estimation and triage.

### Checkpoint 3

Run model tests and integration tests.

Show real held-out metrics, split details, and one real API event with physics Pc and AI predictions side by side.

Commit the stage after verification.

---

# 8. STAGE 4 — SMART AI FILTER

Replace the undocumented current filter behavior with a genuine ML-assisted triage workflow.

## 8.1 Training

Train a classifier to predict significant versus insignificant conjunctions.

Derive labels from the documented research-Pc model under several covariance-scale scenarios. Document the Pc threshold and label-generation policy.

Use grouped splits to prevent scenario leakage.

Report:

* Recall.
* Precision.
* False-negative count.
* Confusion matrix.
* Majority-class baseline.
* Grouped split sizes.
* Model name/version.
* Label-generation policy.

The model learns physics-derived labels, not observed collision outcomes.

## 8.2 Safety guard

The filter must never remove a pair from the retained set if:

* Its miss distance is below the configured safety threshold; OR
* Any configured covariance/HBR scenario produces Pc at or above the significant threshold; OR
* Its assessment is invalid or uncertain enough that filtering it out would be unsafe.

Retain invalid or insufficiently assessed events for review rather than silently dropping them.

The guard must be applied independently of the ML prediction.

## 8.3 UI

Show:

* Total events before filtering.
* Kept events.
* Filtered events.
* Reason for each decision.
* Model prediction and confidence, if available.
* Safety-guard result.
* Model metrics and fallback status.

If the model is unavailable, use a deterministic rule filter with an explicit fallback label.

### Checkpoint 4

Test classifier inference, leakage controls, guard behavior, and end-to-end filter results.

Print real before/after counts and examples of retained and filtered events with reasons.

Commit the stage after verification.

---

# 9. STAGE 5 — MANEUVER ASSESSMENT, FUEL, AND AI RANKING

Preserve and complete the existing maneuver implementation.

## 9.1 Inputs

Support:

* Selected conjunction.
* Burn epoch or burn lead time relative to TCA.
* Delta-v magnitude in m/s.
* RTN direction/components.
* Optional spacecraft mass and specific impulse.
* Optional user-supplied conjunction/state data in CSV or JSON.

Preserve object IDs and TCA during handoff from Collision Analysis.

Validate identity and reject mismatched events.

## 9.2 Physics

Compute a zero-burn baseline and candidate maneuvers.

For each valid candidate, calculate:

* Burn epoch.
* RTN delta-v.
* New propagated state.
* Before/after miss distance.
* Before/after relative velocity.
* Before/after TCA when the encounter-search method supports recalculating it.
* Before/after Pc.
* Absolute Pc reduction.
* Percentage Pc reduction.
* Candidate ranking and trade-offs.

Use a documented propagator and numerical assumptions. Apply a burn at the correct epoch, transform RTN delta-v consistently, and propagate the modified state to the new encounter.

Do not assume a burn always reduces Pc.

## 9.3 Consistent covariance

Before and after Pc must use the same documented uncertainty policy and HBR for the same comparison.

The mean state changes with the burn; covariance must be propagated or approximated consistently under a documented model.

If modeling burn-execution error, define its covariance and how it is added to the post-burn uncertainty.

Do not compare before/after Pc values calculated using unrelated uncertainty assumptions.

## 9.4 Fuel

Use Tsiolkovsky:

`dm = m * (1 - exp(-delta_v / (Isp * g0)))`

Use:

* `g0 = 9.80665 m/s²`
* User-entered mass and Isp when supplied.
* Configurable defaults of 500 kg and 220 s when actual values are missing.

Default fuel results must be labeled **estimated from default assumptions**.

Display the mass, Isp, delta-v, and assumptions used. Never present assumed spacecraft properties as actual data.

## 9.5 Along-track sanity check

Validate against the approximate along-track displacement relation:

`delta_s ≈ 3 * delta_v * delta_t`

Use consistent units and state the near-circular, short-lead-time assumptions and limitations. Do not apply this approximation universally.

## 9.6 Maneuver AI surrogate

Train a model to predict post-burn Pc reduction for rapid candidate ranking using documented physics-generated maneuver scenarios.

Use grouped train/test splits.

Report:

* Target definition.
* Dataset and split sizes.
* MAE/RMSE for regression, or appropriate ranking metrics if ranking is the target.
* Baseline comparison.
* Limitations.

Use AI only to rank candidates quickly. Recalculate and confirm the leading candidates with the physics engine.

If the surrogate is unavailable, rank using physics calculations and label the fallback.

Do not claim that a surrogate is an independent orbital-mechanics solver.

## 9.7 User-input maneuver workflow

Support a form and CSV/JSON upload.

Validate:

* Required state vectors and units.
* Coordinate frame.
* Epochs and TCA.
* Object identity.
* Mass and Isp, if supplied.
* Burn time and delta-v components.

Calculate and export results when the supplied data support the calculation. Missing mandatory state data must trigger explicit validation rather than invented states.

### Checkpoint 5

Test burn application, RTN transforms, covariance consistency, fuel calculation, zero-burn baseline, event identity, AI ranking, and file-upload validation.

Show one actual maneuver example with before/after miss distance, Pc, reduction, delta-v, fuel assumptions, and result provenance.

Commit the stage after tests and numerical checks pass.

---

# 10. STAGE 6 — REPORTS: SCREEN AND DOWNLOAD

Implement report generation for Collision Analysis and Maneuver Assessment.

Every report must be:

* Displayed on screen before or alongside download.
* Downloadable as PDF.
* Downloadable as CSV.
* Downloadable as JSON.

Use the existing report framework if present. Do not introduce unnecessary dependencies.

## 10.1 Collision report

Include:

* Object 1 and object 2: name, ID, type.
* TCA in UTC.
* Miss distance with units.
* Relative velocity with units.
* Source-reported Pc, event-specific Foster Pc, and research Pc as separate fields.
* Pc percentage.
* Risk score and class.
* Covariance values with units, frame, epoch, and source.
* HBR with units and source.
* AI prediction/classification and model status.
* Method, provenance, assumptions, sensitivity, and limitations.

## 10.2 Maneuver report

Include:

* Selected event identity and TCA.
* Burn epoch and burn lead time.
* RTN delta-v components and magnitude.
* Before/after miss distance.
* Before/after relative velocity and TCA, when calculable.
* Before/after Pc using the same documented uncertainty model.
* Absolute and percentage Pc reduction.
* Fuel consumption, mass, Isp, and whether actual or assumed.
* AI ranking and physics confirmation.
* Assumptions and limitations.

## 10.3 PDF validation

PDF requirements:

* Consistent column widths.
* Wrapped text.
* Readable font sizes.
* No clipped text or overflowing tables.
* Correct page breaks.
* Repeated table headers where appropriate.
* Units in numerical fields.
* Page numbering and report metadata.

Do not claim a PDF is validated simply because it was generated.

Render actual PDFs to images or use an available PDF inspection tool. Check representative pages for clipping and overflow. Add tests for report contents and page generation.

### Checkpoint 6

Generate real collision and maneuver reports.

Verify PDF layout and inspect CSV/JSON contents.

Commit the stage after verification.

---

# 11. STAGE 7 — OPTIONAL CONJUNCTION-DATA UPLOAD

Preserve the current upload path and improve its user experience.

Use neutral labels:

* **Upload Conjunction Data**
* **Calculate Collision Probability**

Do not explicitly name external organizations in user-facing labels.

Support the existing compatible CDM format and any other formats already supported by the repository. Add CSV/JSON only where the data schema is unambiguous.

After upload, show:

* Object identities.
* TCA.
* Miss distance and relative velocity, if supplied or calculable.
* Covariance values and frame.
* HBR.
* Source-reported Pc, if present.
* Computed event-specific Foster Pc when inputs are valid.
* Research Pc when the documented estimator can calculate it.
* Percentage, score, and classification.
* AI outputs.
* Values read, derived, assumed, and missing.
* Validation errors and provenance.

Do not silently fill missing CDM fields with assumed values and then label the result as event-specific Pc.

Allow users to inspect the result and download the reports.

### Checkpoint 7

Test valid, malformed, incomplete, and incompatible-frame uploads.

Show one real uploaded-file calculation and its field provenance.

Commit the stage after verification.

---

# 12. STAGE 8 — COLLISION ANALYSIS AND MANEUVER UI REDESIGN

Create a polished, futuristic, professional space-science interface.

The current giant horizontal table filled with long explanations is not acceptable.

## 12.1 Collision Analysis

Use a responsive two-panel layout.

### Left: prioritized conjunction list

Each compact event card should show:

* Object pair.
* Risk class.
* Primary Pc value.
* Risk score /100.
* TCA.

Sort by the configured priority policy and make that policy visible.

Include total, valid, invalid, and displayed-event counts.

### Right: selected event

Show:

* Primary Pc prominently in scientific notation.
* Pc percentage.
* Approximate odds when meaningful.
* Risk score /100.
* Low/Medium/High class.
* Miss distance.
* Relative velocity.
* TCA.
* AI Pc prediction and AI class, clearly distinguished.
* Covariance/HBR provenance badges.
* A compact explanation of why the event has its ranking.

Provide expandable technical details for:

* Covariance.
* HBR.
* Research assumptions.
* Sensitivity analysis.
* Model metadata.
* Numerical diagnostics.

Never place a long explanatory paragraph inside a numeric Pc cell.

The selected event must remain synchronized with Globe and Maneuver Assessment actions.

## 12.2 Maneuver page

Use a readable before/after comparison:

* Before/after Pc.
* Before/after miss distance.
* Pc reduction.
* Delta-v.
* Burn timing.
* Fuel.
* Candidate ranking.

Keep detailed assumptions and diagnostics expandable.

## 12.3 Globe and heat map

Preserve existing features.

Verify:

* Event selection sends the correct object IDs, TCA, and available states to the globe.
* The globe highlights the selected pair.
* The heat map explicitly identifies whether it displays Pc, research risk score, or event density.
* Invalid values are not replaced with fake high/low values.
* The visualization does not become sluggish due to UI effects or repeated rerendering.

### Checkpoint 8

Run focused frontend tests and production build.

Verify event selection, details, globe handoff, heat-map metric, responsive layout, and absence of horizontal overflow at representative viewport sizes.

Commit the stage after verification.

---

# 13. STAGE 9 — NEBULA THEME AND ACCESSIBILITY

Apply a consistent, elegant space theme across all pages.

Requirements:

* Deep nebula-style background.
* Subtle layered stars.
* Tasteful cursor-following glow.
* Consistent glassmorphism cards.
* Clear typography and spacing.
* Readable tables and forms.
* Accessible color contrast meeting WCAG AA for normal text.
* Visible keyboard focus.
* Responsive layout.
* `prefers-reduced-motion` support.
* No heavy external dependency solely for decorative effects.
* No frame-rate degradation on the globe page.

Prefer CSS gradients and lightweight local effects. If using canvas, throttle updates and pause or simplify effects when the tab is hidden or the globe is active.

Do not sacrifice readability for decoration.

### Checkpoint 9

Run frontend tests and production build.

Check contrast, keyboard focus, reduced-motion behavior, overflow, and globe responsiveness.

Commit the stage after verification.

---

# 14. STAGE 10 — FULL REGRESSION AND DELIVERY

Run the complete backend and frontend test suites and production build.

Test:

* Fresh screening.
* Archived-job restoration.
* Pagination.
* Numerical Pc and provenance.
* Risk scoring and classification.
* Both collision AI models.
* Smart AI Filter and safety guard.
* CDM upload.
* User-provided maneuver data.
* Maneuver physics and fuel.
* Maneuver AI ranking.
* Collision and maneuver reports in PDF, CSV, and JSON.
* Globe and heat-map handoff.
* Invalid/malformed records.
* API/frontend contract consistency.

Run real end-to-end API checks against the current application where possible.

If browser access is available, test the actual browser workflow. If it is unavailable, state that limitation and provide exact manual verification steps. Do not present server-rendered markup or unit tests as proof of interactive browser verification.

## Required final deliverables

### A. Files and commits

List files changed by stage and the commit hash for each completed stage.

### B. Tests

Report exact backend/frontend test counts, failures, and production build results.

### C. Five actual conjunction examples

Provide up to five real records with:

* Object pair and IDs.
* TCA.
* Miss distance.
* Relative velocity.
* Event-specific Foster Pc, if calculable.
* Research Pc.
* Pc percentage.
* Risk score.
* Physics class.
* AI Pc prediction and AI class.
* Covariance/HBR provenance.
* Model/fallback status.

Do not fabricate records or omit a calculation failure from the report.

### D. Model metrics

Include dataset sizes, grouped split strategy, MAE/RMSE, confusion matrix, per-class metrics, majority baseline, and target definitions for each trained model.

### E. Maneuver example

Show:

* Selected event.
* Burn time and RTN delta-v.
* Before/after miss distance.
* Before/after Pc.
* Absolute and percentage reduction.
* Fuel and its input assumptions.
* AI ranking versus physics-confirmed results.

### F. Requirement completion matrix

For every mandatory requirement, report:

* Fully implemented and verified.
* Partially implemented.
* Not implemented.
* Verification evidence.
* Remaining blocker.

### G. Browser verification

Provide exact steps for checking the UI manually. Do not claim interactive browser verification unless actually performed.

---

# 15. HARD EXECUTION AND GIT CHECKPOINT RULES

Implement the stages in order:

0. Audit and baseline.
1. Conjunction and research-Pc pipeline.
2. Risk score and classification.
3. Collision AI models.
4. Smart AI Filter.
5. Maneuver physics, fuel, input, and AI ranking.
6. Reports.
7. Upload workflow.
8. Collision Analysis, globe, and heat-map UI.
9. Nebula theme and accessibility.
10. Full regression and final report.

At every stage:

1. Make actual code changes, not just a plan.
2. Run the focused tests.
3. Print or save actual representative output.
4. Inspect the output for numerical and schema correctness.
5. Review the Git diff.
6. Commit only that stage's changes after its acceptance checks pass.
7. Report changed files, tests, sample output, commit hash, and unresolved blockers.
8. Continue to the next stage when its acceptance criteria pass.

Before committing:

* Inspect `git status`.
* Preserve all pre-existing user changes.
* Stage only files belonging to the current stage.
* Do not use destructive Git commands.
* Do not amend, reset, or rewrite unrelated commits.
* Do not include secrets, credentials, virtual environments, caches, or generated bulk data.
* If the repository has no Git metadata, report that blocker instead of claiming a commit.
* If tests fail, fix the defect or report the blocker. Do not commit a stage as complete while silently ignoring a required failing test.

Do not repeat audits indefinitely. Do not stop after adding a component that is disconnected from the live workflow.

If a scientific calculation cannot be completed with available inputs, identify the exact missing physical quantity, the relevant method limitation, and the safe fallback. Never fabricate a result.

**Start with Stage 0, then proceed through the stages sequentially. The objective is a working, integrated ORION SSA system—not a report claiming that one exists.**

---

# PART 2 — MANDATORY ADDENDUM

# MANDATORY ADDENDUM — NUMERICAL COMPLETENESS, TRAINING DATA, UI COVERAGE, AND STAGE CONTROL

This addendum is mandatory and extends the existing ORION SSA implementation specification. It does not replace or weaken any earlier phase, scientific-integrity rule, acceptance criterion, or delivery requirement.

## 1. NUMERICAL COMPLETENESS — NO PLACEHOLDERS FOR CALCULABLE QUANTITIES

### 1.1 Collision Analysis

For every valid conjunction with sufficient state information, calculate and display:

* Miss distance, with units.
* Relative velocity, with units.
* Time of closest approach (TCA), in UTC.
* Research collision probability (Pc), in scientific notation and percentage.
* Risk score out of 100.
* Risk classification: Low, Medium, or High.
* Applicable method, model provenance, and whether inputs were measured, read from a file, derived, or assumed.

When event-specific covariance or HBR is absent, use the documented research uncertainty estimator and estimated HBR model. Label the result **Research Pc — Assumed Inputs**.

Do not replace a valid research Pc with a dash or the word "unavailable" merely because operational covariance or HBR is missing.

Keep these channels separate:

1. Source-reported Pc.
2. Event-specific Foster Pc.
3. Assumption-based research Pc.
4. AI-predicted log10(Pc).
5. AI or deterministic risk classification.

Never silently substitute one channel for another.

If an event lacks valid states, a valid TCA, or other indispensable inputs, return a specific validation error and reason code. Do not fabricate an event or a numerical Pc to satisfy the display requirement.

### 1.2 Maneuver Assessment

For valid maneuver inputs, calculate and display numerical values wherever the documented model supports calculation:

* Baseline and post-burn miss distance.
* Baseline and post-burn relative velocity.
* Baseline and post-burn TCA.
* Baseline and post-burn Pc under the same documented uncertainty model.
* Absolute Pc reduction: Pc_before − Pc_after.
* Percentage Pc reduction, with a defined zero-baseline policy.
* Delta-v magnitude and RTN components.
* Fuel estimate when mass and specific impulse are available or when an explicitly configured default is used.

Use the same covariance propagation or assumed covariance model, HBR, encounter-plane construction, and Pc integration method for the baseline and every maneuver candidate. Only the physical state changes caused by the maneuver and explicitly documented burn-execution uncertainty may differ.

Do not infer Pc reduction from miss-distance change alone.

If a numerical solver fails to locate a new TCA, perform a bounded local closest-approach search around the original TCA. Report the resulting TCA and search method when successful. If the search also fails, return a specific solver error rather than a fabricated value.

For fuel calculations, use the Tsiolkovsky equation:

`fuel_mass = initial_mass * (1 - exp(-delta_v / (Isp * g0)))`

Use consistent SI units. If default mass or Isp values are used, make them configurable, identify them as assumptions, and label the fuel output as an estimate based on those defaults.

### 1.3 Meaning of "No Placeholders"

The requirement is to calculate all values supported by valid inputs and the declared model—not to invent data.

For every valid event, ORION should attempt the appropriate research calculation. If a genuine numerical or input failure prevents calculation, expose a concise, specific validation error with its reason. Never conceal the failure behind a generic placeholder.

A numerical research estimate is not equivalent to an operationally validated probability. Preserve that distinction throughout the API, UI, exports, and reports.

## 2. PHYSICS-GENERATED TRAINING DATA — PARENT-EVENT ISOLATION

Apply this requirement to:

* Model 1: log10(Pc) regression.
* Model 2: Low/Medium/High classification.
* Smart AI Filter classifier.
* Maneuver candidate-ranking surrogate.

The number of independent real conjunctions may be limited. Generate scenario variants from real parent events using documented, configurable variations such as:

* Covariance scale, including the specified 0.5×–3× range.
* TLE age and uncertainty growth.
* HBR proxy and object-size category.
* Relevant orbital and encounter parameters.
* For maneuver scenarios, burn timing, RTN direction, and delta-v magnitude.

Every generated label must be calculated by the physics pipeline. Do not manufacture labels independently of the physics calculations.

Record, at minimum:

* Parent event ID.
* Scenario/variant ID.
* Original event provenance.
* Applied covariance scale.
* Applied HBR assumptions.
* TLE age and relevant orbital features.
* Physics calculator and configuration version.
* Generated Pc and classification label.
* Maneuver parameters and resulting before/after metrics, where applicable.

### 2.1 Prevent Data Leakage

Split data by parent event ID. All variants derived from one parent event must remain in a single train, validation, or test partition.

Do not randomly split individual variants when that would place variants of the same parent event in different partitions.

Use fixed random seeds and persist the split definition so evaluations are reproducible.

### 2.2 Required Evaluation

For regression, report:

* MAE and RMSE in log10(Pc) space.
* Evaluation sample count.
* Number of independent parent events.
* Scenario count.
* Comparison against a simple baseline.

For classification, report:

* Confusion matrix.
* Accuracy.
* Per-class precision, recall, and F1.
* Macro-F1 and weighted-F1.
* Majority-class baseline.
* Evaluation sample count and parent-event count.

For the Smart AI Filter, additionally report recall for significant events and the number of significant events incorrectly filtered out.

For the maneuver surrogate, evaluate its ability to rank candidates against physics-calculated outcomes. Report ranking quality and the physics-confirmation results for selected candidates.

Clearly distinguish independent parent events from generated scenario variants. Never present thousands of generated scenarios as thousands of independent real conjunctions.

These models learn physics-derived labels under the configured assumptions. They are surrogates, not models validated against observed collisions. Do not describe them as operationally calibrated collision predictors.

If a trained model is unavailable, corrupt, incompatible, or fails validation, use the documented deterministic fallback and label it explicitly as a fallback. Never label a fallback result as an AI prediction.

## 3. FULL-APPLICATION UI COVERAGE

Apply the approved futuristic space theme consistently across the entire application:

1. Dashboard/Home.
2. Collision Analysis.
3. Smart AI Filter.
4. Maneuver Assessment.
5. Reports.
6. Conjunction Data Upload and Pc Calculator.
7. Globe.
8. Heat Map.
9. Any shared navigation, dialogs, forms, and detail panels.

The visual system should include:

* Deep-space or nebula-inspired backgrounds.
* Subtle star layers and restrained visual effects.
* Consistent glass-style cards.
* Readable typography, spacing, and hierarchy.
* Accessible text contrast meeting WCAG AA where applicable.
* Responsive layouts.
* No clipped content, overlapping cards, or unusable horizontal scrolling.
* Respect for `prefers-reduced-motion`.
* No unnecessary heavy dependencies or effects that degrade globe rendering.

Do not redesign every component independently. Establish reusable styles and components, then integrate them incrementally.

Preserve all working globe, heat-map, event-selection, archive-restoration, CDM-upload, Foster Pc, research-Pc, and maneuver functionality.

### 3.1 Collision Analysis Layout

Use a prioritized event list on the left and a selected-event detail panel on the right on suitable desktop layouts.

Sort the event list by a documented priority rule. Show a concise summary for each pair, including:

* Object pair.
* Miss distance.
* Research Pc.
* Risk score out of 100.
* Risk class.
* Priority rank.

On selection, show detailed numerical results, uncertainty assumptions, covariance/HBR provenance, AI outputs, and calculation methods in a readable detail panel.

Do not place lengthy explanations inside table cells. Put technical details in expandable sections.

Retain the **Show in Globe** action and ensure it focuses the globe on the selected conjunction. Verify that event IDs and TCA survive the handoff.

### 3.2 Smart AI Filter Visibility

The Smart AI Filter page must show:

* Total events before filtering.
* Events kept.
* Events filtered out.
* Model name and version.
* Evaluation metrics and training-data provenance.
* The reason each event was filtered.
* Model confidence or score, with a clear definition.
* Whether the safety guard retained the event.
* Whether the result came from a trained model or deterministic fallback.

Provide CSV export of filtered events and their reasons.

Never filter out a pair that meets the configured safety guard—for example, a pair whose miss distance is below the configured threshold or whose research Pc exceeds the configured threshold under any required uncertainty scenario.

Define all thresholds in configuration and documentation. Report false negatives explicitly.

## 4. STAGE CONTROL AND CHECKPOINTS

Complete the existing ten stages in order:

1. Audit.
2. Pc pipeline and provenance.
3. Risk score and classification.
4. AI models for Pc and classification.
5. Smart AI Filter.
6. Maneuver physics, fuel, user inputs, and AI ranking.
7. Reports: on-screen presentation, PDF, CSV, and JSON.
8. CDM upload and calculator polish.
9. Application-wide UI and nebula theme.
10. Full regression, production build, and final report.

Do not skip a stage silently or mark a stage complete merely because its code exists.

### Mandatory checkpoint after EVERY stage

1. Run the relevant backend tests.
2. Run the relevant frontend tests.
3. Run a production build when frontend code or build configuration changes.
4. Run targeted integration tests for the feature implemented.
5. Print actual sample output from the running implementation or a reproducible local test.
6. Report the exact files changed.
7. Report passed and failed tests with counts.
8. Report known limitations and unresolved blockers.
9. Commit the completed stage to Git, provided the workspace is a valid Git repository and the commit can be made safely.
10. Record the commit hash and checkpoint status.

Never claim a test, build, browser workflow, external comparison, or commit succeeded unless the corresponding command or operation actually completed successfully.

If Git is unavailable, the workspace is dirty in a way that prevents safe commits, or a commit fails, preserve existing work and report the precise blocker. Do not reset, force-stage, or discard unrelated changes to make a checkpoint appear successful.

### 4.1 Context and Handoff Management

If context, token budget, or execution time is running low:

1. Finish the current stage as far as safely possible.
2. Run its tests.
3. Commit the completed stage if safe.
4. Create or update `STATUS.md` at the project root.
5. Record completed stages, commit hashes, tests, next stage, open blockers, and exact next actions.
6. Stop at the checkpoint and continue from `STATUS.md`.

Never skip a stage silently. Never claim the entire project is finished when only a subset of stages has been completed.

## 5. FINAL ACCEPTANCE REPORT

At the end of Stage 10, provide:

* A completed/partial/not-completed checklist for every original requirement and this addendum.
* Files changed, grouped by stage.
* Commit hashes for completed stages.
* Backend and frontend test results.
* Production build result.
* Five real, reproducible conjunction examples with object IDs, TCA, miss distance, relative velocity, research Pc, percentage, risk score, classification, priority, AI outputs, and input provenance.
* A clear distinction between real observed data, calculated values, assumed inputs, and generated training scenarios.
* Training, validation, and test split details grouped by parent event ID.
* Regression and classification metrics, including the baselines.
* A maneuver example with before/after geometry, Pc, Pc reduction, delta-v, fuel estimate, and assumptions.
* A Smart Filter example showing before/kept/filtered counts, safety-guard behavior, and CSV export.
* PDF report rendering and overflow-validation results.
* Exact browser steps for verifying Collision Analysis, selected-event details, Show in Globe, Smart AI Filter, Maneuver Assessment, reports, and upload.
* An explicit statement identifying which browser steps were actually executed and which were not.

If five valid conjunction examples cannot be generated from the available data, explain why and show all valid examples that were successfully calculated. Do not fabricate extra examples to reach five.

If a requirement cannot be completed, identify the precise blocker, its impact, and the next action needed. Do not disguise an incomplete feature as complete.

**Final rule:** Preserve scientific integrity, existing working functionality, and all earlier requirements. Implement incrementally, verify with evidence, and report honestly.

---

# PART 3 — ADDITIONAL CLARIFICATIONS

## 6. ADDITIONAL CLARIFICATIONS

A. STAGE NUMBERING: The main directive's numbering (Stage 0 to Stage 10) is authoritative. Where this addendum lists stages differently, follow the main directive's order and treat this addendum as extra requirements for those stages.

B. REPRODUCIBILITY: Provide one documented command (script or Makefile target) that regenerates the scenario dataset with fixed seeds, retrains all four models (Pc regressor, risk classifier, Smart Filter classifier, maneuver surrogate), saves the artifacts with version metadata, and prints the metrics.

C. DOCUMENTATION: Create docs/METHODOLOGY.md covering: data sources, conjunction screening method, covariance and HBR assumptions and their limits, Pc formulas, risk score and thresholds, scenario generation, model targets and metrics, maneuver and fuel equations, Smart Filter policy and guard, and all limitations. Every number in it must come from real output, not placeholders.

D. DEMO DATASET: Save one real screening job as a fixed demo dataset (with its provenance and timestamp) so the application can be demonstrated without depending on live data. Label it clearly as a saved snapshot.

E. START SAFELY: Before changing any code, create and switch to a new branch (for example, feature/orion-completion). Do all work and commits on that branch.

F. CONFLICT RULE: If any two instructions in this specification appear to conflict, follow the one that is stricter about scientific honesty and about not fabricating results, and note the conflict in your checkpoint report.

G. PERFORMANCE: Model training and scenario generation must run offline through the reproducibility command, never during a user request. Live API calls must only run inference with saved artifacts, and pages must load without noticeable delay.
