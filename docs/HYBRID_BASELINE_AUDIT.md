# ORION SSA Hybrid Baseline Audit

**Audit date:** 2026-10-04  
**Scope:** Read-only audit of the supplied ORION SSA archive; no application source was modified.  
**Source archive:** the project space pt 2 updated almost final.zip  
**Audited application root inside archive:** outputs/space-debris-ssa-platform/

## Executive finding

The repository is a React/Three.js frontend backed by FastAPI. It has a real SGP4 propagation path for catalog records when CelesTrak data is available, plus deterministic formulas, rules, and synthetic fallbacks. It does **not** contain a trained or loaded ML model, ML training/evaluation pipeline, calibrated uncertainty model, or LLM integration. UI and API labels such as “AI,” “confidence,” “prediction,” and “Foster 2D Pc” overstate what the underlying calculations establish.

Most critically, conjunction records are not the output of a time-dependent close-approach screen. Candidate pairs are selected from altitude/inclination/risk groupings; miss distance, relative velocity, TCA, and covariance are then assigned by formulas or constants. A Gaussian area integral is applied to those inputs and named a collision probability. Maneuver fields are then optimized against that synthetic event geometry. As a result, the current conjunction, Pc, covariance, and maneuver values are not scientifically supportable event assessments.

The app is suitable as a visualization and software-flow prototype, with SGP4-backed catalog states when inputs are live. It is not an operational conjunction assessment system. This distinction is consistent with NASA CARA’s description of screening versus risk assessment and its published caveat that TLEs are not sufficient for mitigation decisions. [NASA CARA, Step 2](https://www.nasa.gov/cara/step-2-close-approach-risk-assessment/) · [NASA CARA R&D findings](https://www.nasa.gov/cara/research-and-development-2/)

## 1. Audit method and scope

I inspected the application source under backend/app, src, project configuration, generated-report code, README, TODOs, and implementation/audit reports in the archive. A source-only inspection copy was placed under the workspace’s work/ directory. The archive’s bundled node_modules, Python virtual environment, Git internals, and generated dist bundle were treated as dependencies/build artifacts rather than authoritative application source. The frontend source, backend source, and project documentation were inspected; no build, endpoint smoke test, or test suite was run as part of this read-only audit.

The archive contains empty .agents/ and .codex/ directories and no AGENTS.md or other repository instruction file. README, TODO, and implementation-report text inside the supplied archive was treated as project documentation and evidence about prior claims, not as instructions that override this audit request. Historical test/check claims in those documents were not independently rerun.

## 2. System inventory and implementation classification

Classification uses the requested terms: **physics** means a calculation based on a physical model or propagator; **mathematical** means deterministic numerical arithmetic; **deterministic heuristic** and **rule based** mean hand-coded scoring, thresholds, or selection logic; **real ML** requires a trained/inferred model; **LLM** requires language-model generation; **visualization only** means display, interaction, or visual animation; **synthetic/fallback** means generated or substitute data. A function may combine categories.

### Application shell and shared behavior

| Area | Components / behavior | Classification and notes |
|---|---|---|
| Navigation shell | Sidebar, TopBar, conditional page rendering in src/App.jsx | UI/rule based. Seven in-app page states; no React Router URL routes. Sidebar status consumes health fields and defaults to “ready” if absent. |
| Refresh/data load | App load effect, 90-second refresh, forecast-time catalog reload | API orchestration plus fallback. Loads catalog and forecast, then health, analytics, conjunctions, and Smart Filter. Errors can leave prior state visible with a generic cached-state notice. |
| Search | TopBar input, buildSearchSuggestions, filterSnapshot | Deterministic string matching and visualization filtering only. Suggestions are made from the current catalog; search does not call an API or an AI model. |
| Watchlist / selection | selected event/object/risk, Show in Globe, localStorage watchlist | UI state and local persistence. Not a scientific calculation. |
| Operational ordering | applyOperationalPrioritization and identityModel.computeOperationalPriority | Deterministic rule-based score using pair type, risk category, miss-distance and relative-velocity fields. It adds operational_priority_score and reorders the UI; it does not train a model. |
| Identity and pair labels | identityModel.js, objectClassification.js | Deterministic metadata mapping, name heuristics, ID matching, and integrity checks. It validates basic identity shape, not physical conjunction validity. |

### Required pages

| Page | Functional components and values | Current classification / caveat |
|---|---|---|
| **Home** | Hero and “AI Mission Briefing”; KpiGrid; Live Alerts/EventList; risk distribution/BarList; page navigation | UI plus deterministic summary strings, counts, and aggregates. “Live” and “AI” language does not imply streaming observations or model inference. AI confidence KPI is a formula output or hard-coded fallback. |
| **Visualization** | SSAScene; Earth; OrbitShells; SatelliteField; RiskHeatmap; RadarSweep; CameraFocusController; ControlPanel; AnalyticsPanel; TimelinePanel; TelemetryStrip; global filters/search | Primarily visualization only, plus UI and deterministic geometry. Backend object fields enter the scene, but SatelliteField animates positions from orbit.visual_radius, phase, angular_rate, inclination, and RAAN using a simplified circular visual model. It does not render the returned SGP4 position vector. Heatmap cells are risk-score regions. Earth/cloud textures, stars, radar sweep, orbit reference shells, and shimmer particles are procedural visual effects. |
| **Smart AI Filter** | Before/after SceneComparison; workload-reduction percentage; Pipeline; AI Confidence; event list | Deterministic threshold filtering and visualization, not AI/ML. Backend AI class is a fixed mapping from a thresholded risk label. Frontend buildSmartSnapshot applies its own event/object/risk-cell thresholds, so the “after” scene does not represent a model inference result. Displayed comparison counts are retained-event counts while the mini-scenes contain object snapshots. |
| **Collision Analysis** | Prioritized EventList; RiskBadge; priority/Pc/miss-distance/relative-velocity/confidence metrics; CovarianceView; AI explanation/FactorList; ObjectPair; watchlist pinning; Show in Globe; PDF/CSV actions | UI over deterministic event construction and heuristic scores. The displayed Pc, TCA, miss distance, covariance, confidence, and contributor values are not sourced from a valid event state/covariance screen. The AI explanation is a string template. |
| **Maneuver** | Delta-V, burn direction/time, fuel estimate, before/after Pc and miss distance, trajectory comparison, event PDF action | Deterministic search applied to heuristic event geometry, plus a second local implementation when the API fails. No orbit state is propagated after a burn; displayed effects are synthetic calculations, not maneuver dynamics. |
| **Historical Analytics** | Band distribution, “Risk Trend” line, RiskMatrix, Scatter | Deterministic aggregation and visualization. Backend risk_timeline comes from a 168-hour forecast formula on the current catalog; there is no historical event store or time-series query. The chart’s T1… labels are forecast frames, not historical times. RiskMatrix maps categorical labels to hand-assigned scores and bins them. |
| **Reports** | Mission PDF, conjunction CSV, mission JSON, selected-event PDF, briefing summary | Server-side formatting/export. Reports serialize the same synthetic/heuristic fields and often label them as AI or Pc. CSV/PDF do not include per-value provenance/method; event PDF does not include a data-source field. Mission JSON has a top-level snapshot source but no per-record derivation provenance. |

### Visualization and shared child components

- **SSAScene / Earth / OrbitShells / RadarSweep:** display-only scene composition, procedural Earth/cloud textures, approximate shells, and animation. Orbit reference radii and scale are for presentation, not a coordinate-to-scale astrodynamics mapping.
- **SatelliteField / positionSharing:** interaction and per-frame Three.js transformations. positionSharing correctly shares one rendered position for selection/camera focus, but that position is a visual orbit calculation, not the backend TEME SGP4 state. Orbit eccentricity is not used in orbitPositionTo’s position calculation.
- **RiskHeatmap:** renders risk-cell values. Its “untracked shimmer” creates synthetic-looking points from seeded procedural positions and cell values; these are decoration, not individual debris observations or a debris population simulation.
- **AnalyticsPanel / AiBlock:** object/risk readouts and templated prose. AiBlock shows a fixed 82% model confidence and 168-hour forecast horizon. These are not model outputs. Global-risk prose is static.
- **ControlPanel / TimelinePanel / TelemetryStrip:** visibility controls and telemetry-style presentation. Timeline selects formula-generated forecast frames; displayed latency is actually cache age. “Sensor Stack” is not backed by sensor observations in this repository.
- **KpiGrid / EventList / CovarianceView / FactorList / BeforeAfter / RiskMatrix / Scatter / BarList / TrendLine:** presentation components over fields computed elsewhere. Scatter uses AI confidence as opacity and defaults to 0.82 if absent. RiskMatrix’s continuous score comes from a hand-coded mapping of risk labels, not Pc or an independent model.

## 3. Numerical-value provenance trace

The backend’s response models in backend/app/models.py contain no per-value source, method, frame, epoch, model version, synthetic flag, or uncertainty provenance fields. CatalogSnapshot has a single snapshot-level source string and first-record TLE epoch. That is inadequate once live, fallback, propagated, and generated records can coexist.

| Displayed / returned value | Current source function and path | Audit classification / limitation |
|---|---|---|
| TLE records | TleProvider.get_catalog → _fetch_live / parse_tle_text; fallback constants in tle_provider.py | Live CelesTrak GP/TLE or hard-coded historical fallback records. The request source is global, not retained per object. Fallback records include epochs from 2000 and 2024. No TLE checksum/age or per-record provenance is returned. |
| Propagated state | orbit.propagate_records calls sgp4.api.Satrec.sgp4(jd, fr) | Physics/astrodynamics propagation for valid real TLE input. SGP4 errors are silently skipped. The code does not expose the reference frame or gravity-model/configuration provenance. CelesTrak emphasizes using a compatible SGP4 implementation and publishes verification material. [SGP4 tutorial](https://www.celestrak.org/software/tutorials/sgp4.php) · [SGP4 verification tutorial](https://www.celestrak.org/software/tutorials/sgp4-verification.php) |
| Altitude and speed | orbit.propagate_records: vector norm, subtract EARTH_RADIUS_KM=6378.137, clamp altitude to at least 120 km; velocity vector norm | Deterministic derived values from the SGP4 return state only for propagated records. The clamp hides lower computed altitudes. Frame and epoch are not attached to the result. Synthetic records instead use generated altitude and speed. |
| Band, orbit type, visual radius | classify_band, orbit_type_for, visual_radius_for_altitude | Deterministic thresholds/scaling. “GEO” includes all altitudes from 30,000 to 45,000 km in this classifier; visual radius is a UI-scale mapping rather than a physical coordinate transform. |
| Angular rate / visual phase | orbit.propagate_records then frontend orbitPhase/orbitPositionTo | Deterministic visual approximation; angular_rate is clamped abs(no_kozai)*0.35. It is not a second SGP4 propagation of the future scene state. |
| Object debris_density | orbit.estimate_local_debris_density; duplicated approximation in fallbackData.debrisDensity | Deterministic altitude/inclination Gaussian-shaped heuristic with category offset. No physical population, sensor, catalog count-per-volume, or size distribution is used. “Density” is a unitless score, but UI labels it as local debris density. |
| Per-object collision_probability | orbit.estimate_collision_probability; fallbackData buildObjects | Rule/formula score from debris_density, altitude pressure, inclination crossing, category, and (in frontend fallback) seeded random term. It is not a conjunction-specific probability of collision. |
| Per-object future_risk | orbit.propagate_records / build_synthetic_objects; frontend buildObjects | Deterministic formula for propagated input and seeded synthetic formula otherwise. Not a calibrated forecast. |
| Risk-cell density / debris ratio / untracked_density | risk.build_risk_cells; frontend fallbackData.buildRiskCells | Deterministic bin counts and formula proxies. untracked_density is not measured untracked population density. |
| RiskCell probability / global risk | risk.score_probability; main.build_snapshot averages top cells | Deterministic index. When Torch is installed, score_probability applies a fixed weighted sigmoid. Without Torch it returns a different fixed weighted linear score. Torch is not trained or used for inference; optional dependency availability changes the value and possibly thresholds. These values are not Pc. |
| RiskCell uncertainty | risk.build_risk_cells formula: baseline + untracked proxy + forecast_hours/420 | Deterministic placeholder score, not propagated covariance or calibrated uncertainty. Explanations claim untracked centimeter-scale uncertainty without a size-specific population model. |
| Forecast frames / forecast_trend | risk.forecast_growth and build_forecast | Scenario formula over the same current object list. A sinusoidal congestion term and altitude/inclination proxies change by forecast hour; no future orbit integration, time-varying observations, or historical data is used. tracked_density is len(objects)/1200. |
| Candidate event pair | conjunction.build_conjunctions | Rule-based screening surrogate: group by band, risk cells, altitude and inclination; if too few members, pair top-risk objects or adjacent ranked objects. It does not compute closest approach of two propagated trajectories. |
| Miss distance | conjunction._event_from_pair | Fabricated geometric proxy from altitude difference, inclination difference, phase gap, and risk pressure, lower-bounded at 42 m. Frontend buildLocalConjunctions instead uses 300 + 40*i meters. Neither is a propagated closest-approach distance. |
| Relative velocity | conjunction._event_from_pair | Formula from scalar speed difference plus inclination term; no relative velocity vector at a TCA. Frontend fallback uses abs(speed difference)+1 km/s. |
| TCA | conjunction._event_from_pair | now plus an hour chosen from event/cell indices and horizon. No minimization of relative separation over time. Frontend fallback uses now+(i+2) hours. |
| Hard-body radius and covariance | conjunction._event_from_pair | HBR starts from 10 m plus category constants. Radial/in-track/cross-track sigmas are constants plus risk-cell proxy terms and altitude/inclination differences. No object dimensions or OD covariance input exists. Frontend fallback uses fixed 80/320/130 m; local maneuver has additional 50/250/100 m defaults. |
| Event Pc | conjunction.foster_2d_probability | A 44×44 raster integration of a Gaussian over a circular region, using the synthetic miss distance/HBR/sigmas. Sigma axes are built from heuristic terms. A velocity_scale multiplier modifies the integral. It is not the NASA CARA SDK implementation and has no validation suite here. Frontend local events use mean per-object collision score divided by 1400 with a 1e-9 floor. |
| Risk class, AI class, priority, confidence | classify_probability, AI_CLASS_BY_RISK, confidence_from_features, build_smart_filter | Fixed thresholds/mappings and equations. Confidence is forced into 58–98% from inputs that are themselves heuristic; not calibrated and not AI. Contributors are normalized heuristic feature weights. |
| Smart Filter reduction / pipeline | build_smart_filter and frontend buildSmartSnapshot/buildLocalSmart | Counts and threshold selection. No trained classifier. Frontend local fallback reports avg_confidence_pct=82. Backend retained-event count and frontend object-scene filtering use different criteria. |
| Maneuver delta-V / Pc-after / miss-after | conjunction.optimize_maneuver; App.computeLocalManeuver | Search increments delta-V by 0.01 m/s and shifts miss distance by delta-V × lead time × 0.42; it does not apply a burn to an orbital state or propagate relative trajectories. It reuses heuristic event covariance/Pc. Backend and frontend trajectory arrays use different formulas. |
| Maneuver fuel / direction / time / impact | optimize_maneuver and computeLocalManeuver | Rocket-equation estimate uses fixed wet mass (420 or 260 kg) and Isp=305 s. Burn direction is a 6-degree inclination-difference rule. Burn time is a 45-minute/TCA-minus-two-hour rule. “Low fuel impact” is fixed text. These values are not vehicle-specific or maneuver-validated. |
| Historical analytics | main.analytics → build_forecast | The risk timeline is a future forecast sampled from the current snapshot, not stored history. There is no database/time-series persistence. |
| Cache latency | TleProvider.latency_seconds → SnapshotStats.data_latency_seconds → TelemetryStrip | Reports seconds since the cache was written, not request/network latency. UI labels it “LATENCY.” |

NASA CARA describes Pc as arising from uncertain predicted ephemerides and covariance, miss distance, and hard-body radius; close-approach screening alone is not a risk assessment. NASA also publishes usage boundaries/tests for 2D Pc and public CARA algorithms. The repository’s heuristic inputs do not meet those prerequisites. [NASA CARA Step 2](https://www.nasa.gov/cara/step-2-close-approach-risk-assessment/) · [CARA publications](https://www.nasa.gov/cara/cara-publications/) · [CARA 2D Pc SDK](https://software.nasa.gov/software/GSC-18016-1)

## 4. Synthetic and fallback quantities

| Location | Generated/substitute values | Labeling and risk |
|---|---|---|
| backend/app/services/tle_provider.py | Seven embedded TLE triplets; source “offline fallback” plus synthetic expansion | Snapshot source is visible at top level, but individual values do not retain record-level provenance. Embedded epochs are historical. |
| backend/app/services/orbit.py | build_synthetic_objects fills the catalog when fewer than min(120, limit) objects propagate, adding enough objects to approach the requested limit | If some live TLEs propagate but fewer than 120 objects survive, generated objects are mixed into the result while TleProvider.source remains “CelesTrak live GP/TLE.” UI can therefore show “Live” for a mixed snapshot. Synthetic states have position [0,0,0] and generated orbit fields/speeds. |
| src/data/fallbackData.js | A deterministic 760-object feed, generated IDs/names, altitudes, velocities, object risk scores and risk cells | source says “Synthetic offline SSA training feed”; visible on Visualization as Sim. Other pages do not reliably show a synthetic banner. Names and NORAD-like numbers are synthetic, not catalog matches. |
| src/App.jsx buildLocalConjunctions | Pairing of top-risk objects, Pc proxy, index-based TCA/miss distance, relative speed, fixed covariance, fixed 82% confidence, fixed priority, templates | Invoked whenever API conjunction list is empty, including a valid empty response. It silently turns “no events” into generated events and sends them to Collision, Maneuver, analytics, and Smart Filter pages without a synthetic badge. |
| src/App.jsx computeLocalManeuver | Local recalculation on missing/failed maneuver API result | Same result shape as backend without a source/method field, so the UI cannot distinguish it; its trajectory profile differs from backend’s. |
| backend/app/services/conjunction.py _cell_from_objects | Synthetic risk cell to enable fallback pairing | “SYN-CELL” ID exists in the data, but the final event does not expose a clear source/method field. |
| RiskHeatmap UntrackedShimmer and procedural scene | Seeded point positions, procedural Earth/cloud texture, visual satellite/debris markers and orbital motion | Visualization-only, not physical untracked-debris observations. UI text can imply density/plume values even though points are decorative. |

## 5. API endpoint inventory and consumers

All API routes are defined in backend/app/main.py. The client is src/api/ssaClient.js; page-level calls originate in src/App.jsx. Responses are mostly untyped dicts; only catalog models have a Pydantic response model. No endpoint accepts or emits a CDM in the current frontend/backend source.

| Endpoint | Backend behavior | Frontend consumer / status |
|---|---|---|
| GET /api/health | Builds a snapshot; reports ai_status=ready and in-memory cache | No frontend call found. |
| GET /api/system-health | Builds snapshot/events; reports dataset_loaded=True and ai_status=ready; says “development SQLite-ready cache layer” | getSystemHealth → Sidebar/TopBar. “ready” is not tied to any model; no SQLite database is implemented. |
| GET /api/catalog | TLE acquisition, SGP4/synthetic object creation, risk cells, stats | getCatalog → App initial/periodic load and forecast slider reload; used by all pages. |
| GET /api/forecast | Repropagates current records and creates formula-based frames | getForecast → App initial load; Visualization TimelinePanel selects nearest frame. |
| GET /api/objects | Catalog filtering by q/band/category | No consumer found. |
| GET /api/analytics | Counts, averages, distributions, and current-snapshot risk forecast timeline | getAnalytics → Home KPI/charts and Historical Analytics. |
| GET /api/conjunctions | Rebuilds candidate events; optional min_pc/risk filters | getConjunctions → App load. Empty list is replaced by buildLocalConjunctions in frontend. |
| GET /api/conjunctions/{event_id} | Rebuilds event list and looks up current ordinal ID | No frontend consumer found. IDs are assigned by sort order, not a stable event key. |
| GET /api/conjunctions/{event_id}/maneuver | Rebuilds events, then calls optimize_maneuver | getManeuver → selected-event effect; frontend substitutes local optimizer on null/error. |
| GET /api/smart-filter | Returns deterministic build_smart_filter result | getSmartFilter → Home/Smart Filter/Reports. |
| GET /api/heatmap | Returns catalog risk cells and echoes mode | No frontend consumer found; Visualization uses cells in catalog/forecast responses. |
| GET /api/reports/mission.pdf | Rebuilds event context, separately calls analytics, generates lightweight PDF | Reports button. It can combine data from separately rebuilt snapshots. |
| GET /api/reports/conjunctions.csv | Rebuilds events and exports event fields | Collision Analysis CSV action / Reports page. Contains AI confidence and no source/method columns. |
| GET /api/reports/mission.json | Serializes snapshot, Smart Filter, events | Reports page. Top-level snapshot source only; no event-level provenance. |
| GET /api/reports/{event_id}.pdf | Rebuilds events, looks up ordinal ID, recomputes maneuver and PDF | Collision, Maneuver, Visualization selected-event report actions. Rebuilt ordinal IDs can refer to a different event after input/order changes. |

Endpoint contract notes:

- README lists these API routes and additionally describes pages absent from the current NAV: Mission Control, Documentation, and Settings. Current NAV/page render paths are Home, Visualization, Smart AI Filter, Collision Analysis, Maneuver, Historical Analytics, and Reports.
- /api/heatmap accepts mode but does not branch on it; mode is only echoed.
- /api/conjunctions?limit allows up to 200, but build_event_context asks build_conjunctions for at most 120.
- System-health values dataset_loaded=True, ai_status=ready, browser WebGL as “GPU status,” and SQLite-ready status do not reflect the repository’s actual ML/database infrastructure.
- No request/result schema carries immutable provenance for live, fallback, propagated, synthetic, or derived values. Report and UI consumers therefore cannot enforce that separation.

## 6. Mislabeling and overwrite/substitution paths

### UI/API labels unsupported by implementation

| Label | Actual implementation |
|---|---|
| API title/description “AI” and “AI-inspired” | No model inference. |
| “AI Engine ready” / ai_status=ready | Hard-coded health response; there is no AI runtime or availability probe. |
| “Smart AI Filter,” “AI Classification,” “Explainable Predictions” | Fixed class lookup from Pc threshold and hand-coded retain rules. |
| “AI Confidence,” “model confidence,” 82% | Backend confidence formula and frontend literal 82%/0.82 fallback. No calibration data. |
| “AI Explanation,” “AI Mission Briefing,” “AI Contributors” | Template strings and hand-coded contribution formulas; no LLM. |
| “Foster 2D Pc” / “Collision Probability” | Local Gaussian raster integral, but source states are not a conjunction event and covariance/HBR are generated. Object-level field is a risk score, not Pc. |
| “Historical Analytics,” “event history,” “prediction-confidence views” | Current catalog aggregations plus prospective 168-hour formula frames; no event history or ML prediction-confidence dataset. |
| “Live” feed | Based on source string containing CelesTrak; can coexist with synthetic expansion and has no per-object live/synthetic indicator. |
| “Sensor Stack” / “Debris Density” / “untracked centimeter-scale debris” | TLE sources and unitless formula proxies, no radar sensor data or calibrated physical density distribution. |
| “Latency” | Time since cache write, not acquisition/request latency. |
| “GPU status: browser WebGL” | UI rendering capability, not evidence of backend model/GPU computation. |

### Substitution / mutation risk paths

1. **Catalog and forecast fallback:** getCatalog/getForecast return synthetic frontend snapshots/frames on network or server errors. This replaces the corresponding response in App state. The visualization source string is the main cue; Collision/Maneuver/report surfaces lack a consistent fallback banner.
2. **Empty conjunction response:** App uses buildLocalConjunctions when the backend list is empty, whether the backend is offline or correctly found no events. It replaces the empty event result with synthetic local events. This is the clearest live-result overwrite path.
3. **Maneuver fallback:** when API data is null or request fails, computeLocalManeuver populates the same maneuver state/object shape. Its provenance is not retained, and it can be mistaken for backend output.
4. **Analytics/Smart Filter fallback:** missing backend payloads are replaced by local formulas/threshold rules with the same UI shape.
5. **Torch availability:** risk.py changes the formula branch for the same field named RiskCell.probability depending on optional Torch import. This is not ML fallback; it is two different deterministic formulas.
6. **Mixed backend catalog:** synthetic objects can be appended after successful CelesTrak retrieval while the source remains “CelesTrak live GP/TLE.” This causes source classification to imply a fully live catalog.
7. **Independent physics/AI results are absent:** conjunction response is one dict combining heuristic “physics” values and “AI” fields. physics_risk aliases a threshold class, while ai_class aliases a deterministic mapping from the same class. There are not separate immutable PhysicsResult and AIResult objects. The UI’s operational priority sort is a separate ranking field and currently leaves event Pc unchanged, but all upstream event geometry/Pc fields are already synthetic/heuristic.
8. **Ordinal event identity:** backend event IDs are assigned CJ-0001… after sorting on each rebuild. Detail, maneuver, and report endpoints independently rebuild the list. A changed catalog/order can make the same ID point to another pair; no persistent event key or CDM identifier exists.

## 7. Scientific assumptions and limitations

1. **SGP4 input/output boundary:** SGP4 is the correct family of propagator for GP/TLE input; CelesTrak publishes a tutorial, verification data, and cautions to pair elements with a compatible SGP4 implementation. The app should record the implementation/configuration, epoch, frame, and input record. It currently drops record-level source and does not validate against the public reference cases. [CelesTrak SGP4 tutorial](https://www.celestrak.org/software/tutorials/sgp4.php) · [CelesTrak verification](https://www.celestrak.org/software/tutorials/sgp4-verification.php)
2. **Catalog quality and intended use:** TLE-based visual propagation is not equivalent to high-accuracy owner/operator ephemerides and covariance for mitigation decisions. NASA CARA explicitly lists TLEs as insufficient for CA mitigation and describes risk assessment as a separate stage after screening. [NASA CARA R&D](https://www.nasa.gov/cara/research-and-development-2/) · [NASA CARA process](https://www.nasa.gov/cara/training-materials-and-documentation/)
3. **No closest-approach screen:** No propagation of two states through a common future interval, relative position/velocity time history, minimization for TCA, screening-volume result, or CDM ingestion is present. Same-band proximity in averaged elements is not a conjunction.
4. **Pc inputs/algorithm not defensible:** no event OD covariance, covariance frame/transformation, cross-correlation, validated hard-body radius, or state at TCA. The implemented integral is not tested against NASA CARA reference/benchmark cases and adds a speed multiplier. NASA CARA publishes an open-source 2D Pc SDK and usage-boundary guidance. CCSDS CDM defines the exchanged event fields and format; it does not standardize the calculation algorithms. [NASA CARA Pc SDK](https://software.nasa.gov/software/GSC-18016-1) · [NASA CARA publications](https://www.nasa.gov/cara/cara-publications/) · [CCSDS 508.0-B-1 CDM](https://ccsds.org/publications/bluebooks/entry/3064/)
5. **Risk proxy names:** density, risk-cell probability, collision probability, uncertainty, and forecast growth are scores/proxies with arbitrary scales. They should not be interpreted as collision likelihood, physical number density, covariance uncertainty, or validated future risk.
6. **No provenance or reproducibility:** inputs, config version, data acquisition time, library/model versions, frame, algorithm version, synthetic flag, and fallbacks are not attached to individual results. Current TLE epoch takes the first propagated record, not an event-specific epoch selection.
7. **Maneuver limitations:** no target spacecraft mass/properties, thrust vector, maneuver epoch state, orbital-element/state transition, propagation, constraints, operational planning inputs, or validation reference. Reported fuel and Pc improvement are not flight-commandable recommendations.
8. **No historical baseline:** “Historical Analytics” has no persisted observations or historical conjunctions. Current TLE source cache is in-memory and short-lived.
9. **Scope of standards:** CCSDS CDM is a data-interchange standard, not a Pc algorithm certification. NASA CARA guidance and tools are useful reference implementations/test sources, not evidence that this application is operationally validated.
10. **Status boundary:** nothing in source or reports demonstrates independent reference-data validation or operational/flight-certified accuracy. It must be described as a research/academic prototype.

## 8. Existing test coverage and gaps

**Automated tests found:** none in the archive’s application source tree. There is no tests/ directory, test/spec file, pytest configuration, or npm test script. package.json exposes dev, build, and preview only. backend/requirements.txt does not declare a test runner. No reproducible test cases or evaluation scripts are included.

**Documentation claims:** README and implementation reports say prior build/import/API/report smoke checks passed, and SHOW_IN_GLOBE_IMPLEMENTATION.md describes manual UI checks. These are historical claims, not test artifacts; they were not rerun. TODO and identity audit notes still contain unchecked manual test items.

**Missing coverage:**

- SGP4 agreement with CelesTrak/Vallado public verification vectors, epoch/time conversion, error codes, stale TLE handling, and frame/unit contracts.
- Synthetic/live source separation, mixed-source labeling, minimum-catalog fill behavior, and malformed/invalid TLE handling.
- Deterministic unit tests for band/category mapping and score formulas, with score fields explicitly not named Pc.
- Actual relative-state conjunction-screen reference cases, event identity stability, TCA/miss distance calculations, frame transforms, and covariance transformations.
- Pc tests against NASA CARA SDK/public test vectors and defined 2D applicability/usage-boundary cases; hard-body radius and covariance edge cases; monotonicity tests.
- Maneuver propagation/constraints/reference cases and consistency between backend and frontend fallback implementations.
- API schema/consumer contract tests, source/method provenance assertions, response stability, empty-result behavior, and generated report consistency.
- Frontend labeling tests ensuring synthetic/fallback/unavailable states are shown and no UI says AI when there is no model.
- If ML is added later: event-grouped train/test split, independent labels, leakage checks, reproducible evaluation, calibration/uncertainty tests, artifact/version verification, and model-unavailable isolation.

## 9. Dependency graph

~~~mermaid
flowchart TD
  C[CelesTrak GP/TLE groups] --> TP[TleProvider cache/parser]
  F[Embedded fallback TLEs] --> TP
  TP --> O[orbit.propagate_records / SGP4]
  O --> SO[SpaceObject records]
  O -. fill below minimum .-> SY[build_synthetic_objects]
  SY --> SO
  SO --> R[risk.build_risk_cells / formula scores]
  R --> S[CatalogSnapshot]
  S --> AC[/api/catalog]
  SO --> FC[risk.build_forecast / formula frames]
  FC --> AF[/api/forecast]
  SO --> CJ[conjunction.build_conjunctions / heuristic pairs and geometry]
  R --> CJ
  CJ --> SF[build_smart_filter / fixed rules]
  CJ --> MV[optimize_maneuver / miss-shift search]
  S --> AN[/api/analytics / current snapshot plus forecast]
  CJ --> EP[/api/conjunctions and reports]
  SF --> SP[/api/smart-filter]
  MV --> MP[/api/conjunctions/id/maneuver and event PDF]
  AC --> CL[src/api/ssaClient.js]
  AF --> CL
  AN --> CL
  CJ --> CL
  SP --> CL
  MP --> CL
  CL --> APP[src/App.jsx page state]
  APP --> UI[Home / Smart / Collision / Maneuver / Analytics / Reports]
  APP --> VIS[SSAScene / visualization panels]
  APP -. API errors or empty events .-> FB[src/data/fallbackData and local App formulas]
  SO --> VIS
  R --> VIS
  VIS --> ORB[orbitPositionTo visual orbit animation]
  VIS --> SH[procedural heatmap shimmer / scene graphics]
  ST[(No historical database)] -. absent .- AN
  ML[(No trained ML model)] -. absent .- SF
  LLM[(No LLM integration)] -. absent .- UI
~~~

## 10. Proposed target hybrid architecture — not implemented

Keep the existing SGP4/catalog physics path and introduce a separate ML path with explicit data contracts. Do not call current formula scores “AI.” Until an eligible labeled dataset and validation set exist, report AI as unavailable and operate in physics-only/research mode.

1. **Data acquisition and normalization:** ingest live GP/TLE for visualization and propagator-compatible use; ingest authoritative CDM/owner-operator ephemeris and covariance for close-approach assessment. Preserve each record’s source, source timestamp, epoch, units, reference frame, catalog/event IDs, raw input hash, live/fallback/synthetic status, and transformation history. Parse/export the current CCSDS CDM revision without treating the format as a calculation algorithm. [CCSDS CDM standard](https://ccsds.org/publications/bluebooks/entry/3064/)
2. **Physics/astrodynamics engine:** keep SGP4 as the GP/TLE propagation path and add explicit frame/time/unit handling. Implement screening, TCA, miss distance, relative state, covariance transformation, HBR, and Pc only from applicable state/covariance inputs. Prefer NASA CARA public algorithms and benchmark/test cases for Pc; gate 2D Pc when assumptions fail. Preserve algorithm/version/config provenance. [CelesTrak SGP4 verification](https://www.celestrak.org/software/tutorials/sgp4-verification.php) · [NASA CARA tools](https://ntrs.nasa.gov/citations/20240005634) · [NASA CARA Pc SDK](https://software.nasa.gov/software/GSC-18016-1)
3. **Immutable PhysicsResult:** return physics event, orbit state, covariance, TCA, miss distance, Pc, and risk context as a distinct object with source/method/validity metadata. Never put formula proxies into fields named Pc/covariance/TCA; unsupported fields are null/unavailable with reason codes.
4. **Feature engineering:** derive ML features from versioned, documented inputs only. Keep the physics result immutable and include the physics result identifier as a feature/source reference where allowed; do not train a predictor on labels generated from the same formula it is expected to independently predict, except an explicitly named surrogate model.
5. **Independent ML engine and MLResult:** only add a model after dataset provenance, model/version, feature schema, deterministic preprocessing, training-data description, event-level split, independent test/reference labels, validation metrics, calibration/uncertainty, saved artifact, reproducible evaluation script, and inference function are present. For sequential CDMs, split by conjunction event, not message. Model outputs may be risk ranking, event triage, or another independently labeled prediction; they must not overwrite physics values. If model/data is missing or inference fails, expose status “unavailable” and retain physics-only operation.
6. **Comparison/validation:** compare separate PhysicsResult and MLResult by stable event key and shared input reference. Emit a new ComparisonResult with consistency deltas, applicability flags, validation status, and provenance. Comparison must not mutate either result; agreement is consistency, not proof of correctness.
7. **Decision support:** use explicit policy over validated physics plus independently evaluated ML outputs. Expose source and applicability to the operator, maintain operational thresholds as versioned rules, and block maneuver recommendations unless valid state/covariance and a propagated maneuver solution exist.
8. **Optional explanation layer:** an LLM may interpret user language or explain existing, already-computed values. It must be unable to compute/alter orbit states, covariance, Pc, TCA, or maneuver physics; explanations must cite their input result IDs and be labeled as generated text.
9. **Fallback/UI/report contract:** keep PhysicsResult and MLResult separate through API, frontend, and reports. Label all synthetic/demo/fallback data; preserve a “physics-only / AI unavailable” mode; never let API empty results trigger invented conjunctions. Add per-value provenance and consistent source badges to every page/export.

## A. Critical issues

1. Conjunction events are not produced by propagated relative trajectories or a TCA minimization; key fields are synthetic/rule-generated.
2. Covariance and hard-body radius are constants/proxies, yet drive a Pc calculation and maneuver optimization.
3. Frontend local conjunction generation replaces a valid empty backend event list with fabricated events and labels them as AI/Pc.
4. Backend can mix synthetic expansion into a CelesTrak-labeled live catalog.
5. API/UI claim an AI engine is ready and display confidence, although there is no ML model or LLM.
6. Event IDs are ordinal per rebuilt ranking, so detail/maneuver/report lookups are not stable event identity.

## B. Scientific issues

1. Existing genuine physics is limited to SGP4 propagation of valid TLEs; the derived event model is not an astrodynamics conjunction assessment.
2. The Pc calculation is fed invented geometry/covariance/HBR, includes a non-standard velocity scale, and has no reference-case validation.
3. Debris density, untracked density, risk-cell probability, uncertainty, future risk, and forecast trend are deterministic unitless proxies with probability-like labels.
4. Maneuver response is a scalar miss-distance shift, not a propagated impulse maneuver with spacecraft properties/constraints.
5. SGP4 data source, epoch/frame/configuration and synthetic status are not attached per object; fallback elements are old.
6. “Historical Analytics” contains no historical data; future values come from a formula over the current catalog.

## C. Architecture issues

1. Result schemas combine multiple origins in one object and have no per-value provenance or explicit synthetic/fallback status.
2. API failure and valid empty results share frontend fallback logic; synthetic values can replace API state.
3. Backend and frontend duplicate maneuver/fallback formulas and disagree on trajectory profile.
4. Several API routes are unused; endpoint responses are mostly untyped dictionaries, and reports rebuild results independently.
5. Health fields report “AI ready” and SQLite-ready despite no model or database.
6. The entire application is in-memory; no event store, stable event identity, CDM ingestion, model registry, or evaluation artifact is present.
7. Permissive CORS is configured with all origins and credentials; review before any deployment beyond local research use.

## D. AI/ML issues

1. No trained model, training code/data, feature schema, model artifact, inference version, evaluation metrics, calibration, or uncertainty implementation exists.
2. Torch is only used for a hand-weighted sigmoid calculation and has a different non-Torch fallback; this is deterministic formula code, not AI/ML.
3. AI class is a fixed map from risk label; confidence is a hand-tuned formula or constant; explanation and briefing are templates.
4. No LLM is present. Nothing generates free-form text from a language model.
5. No independent labeled target or event-grouped train/test evaluation exists. Do not train a model against current formula-generated Pc/risk labels and call it an independent predictor.

## E. UI issues

1. “AI Confidence” is hard-coded/formula-generated and repeated on Home, Smart Filter, Collision Analysis, AnalyticsPanel, Scatter, and reports.
2. Smart Filter “before/after” counts do not match the number of rendered objects; the frontend filter criteria differ from backend filter rules.
3. Collision and maneuver pages lack persistent live/synthetic/fallback/source badges, so fabricated event values look operational.
4. Historical Analytics is forecast-only; “Live Alerts” are periodically refreshed candidate records, not a live stream.
5. The globe is a useful schematic visualization but uses stylized radii/circular animation, procedural Earth texture, and synthetic shimmer points; it must not be read as an ephemeris display.
6. Telemetry says latency for cache age; object and risk panels label heuristic scores as collision probability/density/uncertainty.
7. README advertises Mission Control, Documentation, and Settings, which are not present in the current seven-page navigation.

## F. Recommended implementation order

1. **Freeze and specify current contracts:** document units, frames, source fields, data status, endpoint consumers, and which existing SGP4 fields are genuine. Add a static synthetic/live status contract before any model work.
2. **Stop ambiguous substitution:** distinguish API unavailable from valid empty results; preserve empty physics results; mark frontend/local fallback explicitly; prevent mixed live/synthetic catalogs from reporting one global “live” status. Keep fallback mode visibly labeled.
3. **Establish reproducible baseline tests:** SGP4 reference vectors and state/time/frame checks; deterministic tests for current heuristics under score names; API schemas/fallbacks/report provenance. Remove unsupported tests/accuracy claims from report language until measurable.
4. **Build a validated conjunction physics path:** define supported input requirements; ingest/parse CDMs and owner/operator state/covariance; implement frame transforms, screening, TCA, miss distance, and valid HBR/covariance handling against NASA CARA public algorithms and cases. Leave unsupported events unavailable rather than filling numbers.
5. **Separate immutable output contracts:** PhysicsResult, MLResult, ComparisonResult, and optional ExplanationResult. Update every backend/frontend/report consumer together, retaining the existing page structure and style.
6. **Create a genuine labeled ML research dataset/evaluation plan:** source/version documentation, deduplicate by event, event-group train/validation/test split, independent targets, leakage audit, baseline metrics, calibration and uncertainty, saved artifacts, and reproducible evaluation script. Do not infer labels from the same scoring formula.
7. **Add a model only after evidence exists:** include model name/version, feature schema, training data, metrics, uncertainty/calibration, deterministic preprocessing, artifact, and inference function. Test AI unavailability and failure isolation in physics-only mode.
8. **Add comparison and decision support:** comparison is non-mutating and reports consistency only; operator-facing decision policy must rely on validated inputs and preserve source/status.
9. **Correct labels and report provenance:** rename heuristic scores, remove unsupported confidence/AI labels, add per-value source/method/model version, and label generated visualization/demo data.
10. **Validate end-to-end:** run SGP4 and Pc reference suites, endpoint/consumer tests, report consistency checks, frontend build/type checks, plus documented independent-data evaluation before making accuracy claims.

## References

- CelesTrak, [SGP4 Software Tutorial](https://www.celestrak.org/software/tutorials/sgp4.php) and [SGP4 Verification Tutorial](https://www.celestrak.org/software/tutorials/sgp4-verification.php).
- CCSDS, [508.0-B-1 Conjunction Data Message](https://ccsds.org/publications/bluebooks/entry/3064/) (current record notes technical corrigenda through October 2021; CDM defines message format and content, not the algorithms producing the values).
- NASA CARA, [Conjunction Assessment](https://www.nasa.gov/cara/), [Step 2 Close Approach Risk Assessment](https://www.nasa.gov/cara/step-2-close-approach-risk-assessment/), [CARA Publications](https://www.nasa.gov/cara/cara-publications/), [Research and Development findings](https://www.nasa.gov/cara/research-and-development-2/), [CARA SDK 2D Pc calculation](https://software.nasa.gov/software/GSC-18016-1), and [NASA CARA Tools record](https://ntrs.nasa.gov/citations/20240005634).
