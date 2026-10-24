# ORION SSA Physics and Data Model

**Status:** The Stage 1 data/provenance foundation and Stage 2A trajectory screening remain in place. Stage 2B includes the research Foster 2D Pc calculation, a restricted user-supplied CCSDS CDM XML ingestion route, and a separate explicit-assumption scenario route. TLE-only screening provides neither covariance nor HBR, so an imported-input Pc cannot be evaluated unless matching external data is supplied. Imported originator/source claims are not authenticated by ORION. Covariance propagation and operationally validated maneuver optimization are not implemented; the separate two-body maneuver sweep is exploratory and reports baseline consistency warnings.

## Scope and scientific status

ORION currently retrieves public GP/TLE records from CelesTrak when available, propagates valid records with the Python `sgp4` implementation, and derives explicitly heuristic catalog scores. The app is a research and visualization prototype. Its candidate-pair records are **screening proxies**, not close-approach events. Nothing in this contract establishes operational or flight-certified accuracy.

The reference frame and interpretation of SGP4 output follow the propagator interface and CelesTrak guidance: SGP4 produces a state in TEME, and that state is not an Earth-fixed or inertial J2000 state. Any future frame transformation must name its target frame, transform, time scales, Earth orientation inputs, and implementation/version. See [CelesTrak's SGP4/TEME FAQ](https://celestrak.org/publications/AIAA/2006-6753/faq.php) and the [python-sgp4 implementation documentation](https://github.com/brandon-rhodes/python-sgp4).

## Provenance model

`backend/app/models.py` defines typed `Provenance` and `SourceSummary` models. Provenance is attached to catalog objects, invalid/unavailable records, heuristic score outputs, risk cells, summary statistics, forecast frames, and screening proxy events.

`Provenance` carries, when applicable:

- `source`, `source_type`, `source_timestamp`, and `input_hash`
- TLE source-record diagnostics: source URL/group, retrieval HTTP status/time, raw-response and raw-record hashes, original and normalized line strings, normalized-record hash, parsed catalog ID, and SGP4 propagation parameters. Full provider response bodies are not retained.
- `catalog_id` and `object_id`
- raw `element_epoch` and UTC `propagation_epoch`
- `reference_frame` and a field-to-unit map
- propagator name, package version, and configuration
- method/version, validity status, reason code, and synthetic/fallback flags

`source_type` is one of `live`, `fallback`, `synthetic`, `derived`, or `unavailable`. The per-record provenance is authoritative for the record; the snapshot `source_summary` is an aggregate. Snapshot status can be `all_live`, `mixed_live_fallback`, `mixed_live_synthetic`, `fallback`, `synthetic_demo`, or `unavailable`. A `derived` value records its input source in its provenance and preserves synthetic/fallback flags where relevant.

### Source states

| Data | Source/status | Interpretation |
|---|---|---|
| CelesTrak GP/TLE | `live` | Retrieved catalog elements with retrieval timestamp and input hash; this is catalog data, not a direct tracking measurement stream. |
| Bundled TLE sample | `fallback` | Static sample elements used only when live retrieval yields no records; it is not current catalog coverage. |
| Invalid/unpropagated TLE | source remains `live` or `fallback`, `validity_status=invalid` | Retained in `unavailable_objects` with an error reason; no state vector is fabricated. |
| Offline browser objects and frames | `synthetic` | Seeded visualization/demo records. Names are prefixed `[DEMO]`; the object state vectors are null and the displayed orbital attributes are generated demo values. |
| Scores, cells, analytics | `derived` | Deterministic formulas/rules applied to identified inputs, with method/version metadata. `derived` does not imply validated physics or ML. |
| Missing model or unsupported assessment | `unavailable` or `not_implemented` | No numeric substitute is provided. The reason code states what input or implementation is absent. |

`source_timestamp` is the retrieval/load time recorded by the application. For bundled fallback records it means when the fallback was selected, not when the original TLE was published. `element_epoch` remains the epoch encoded by the element set. `propagation_epoch` is the UTC epoch at which the state was requested.

## Catalog propagation

`backend/app/services/tle_provider.py` obtains CelesTrak GP/TLE groups and falls back to a small bundled TLE sample only when live retrieval returns no records. It does not append demo objects to a successful live result. `TleRecord.input_hash` is SHA-256 over the object name and both TLE lines.

`backend/app/services/orbit.py::propagate_records` uses `sgp4.api.Satrec.twoline2rv` with the explicitly selected `WGS72` gravity constants and then calls `Satrec.sgp4(jd, fr)`. WGS-72 matches the python-sgp4 default and the SGP4/TLE convention documented by the implementation; making it explicit records the existing configuration. The output position is km and velocity is km/s in TEME. Altitude is computed from the norm of that position minus the fixed WGS-84 equatorial radius constant 6378.137 km; this is a simplified spherical altitude convention, not geodetic altitude. Inclination, RAAN, and eccentricity are read from SGP4's initialized TLE model. Visualization radius, phase, and angular rate are display parameters and are not a full osculating orbit representation.

The provenance records the installed `sgp4` package version and the use of `Satrec.twoline2rv` defaults. SGP4 error codes and malformed/mismatched TLE identifiers become invalid records with reason codes. No invalid result is converted to a synthetic state. SGP4/TLE propagation has the accuracy and time-span limitations of its element set and model; it is not a high-precision numerical ephemeris.

## Heuristics and derived values

Object scores keep the original deterministic formulas but use names that disclose their status:

- `heuristic_debris_pressure_score` is not debris number density or physical flux.
- `heuristic_risk_score` and `heuristic_forecast_score` are unitless heuristic indices; neither is collision probability.
- UI readouts show these indices as unitless decimals (0.000–1.000), not percentages. Percentages are reserved for actual count ratios such as filter reduction.
- `heuristic_score_provenance` identifies the legacy orbital-shell formulas separately from SGP4 state provenance.
- Risk cells and forecast summaries carry derived method/version provenance. Forecast frames extrapolate heuristic scores; they do not propagate each orbit forward in time.
- Screening proxy `risk_score` and `priority_score` rank catalog-level candidate pairs selected by shell/risk similarity. Pair construction does not evaluate relative trajectories, close approach geometry, TCA, miss distance, or Pc.
- The Smart Filter reduction refers to the heuristic proxy review list, not to a reduction in physical conjunctions or total catalog objects. It is null when there are no proxy events to compare.

These scores retain legacy rules/formulas for prototype continuity and are not trained ML outputs. A name, icon, or deterministic logistic-shaped formula does not make a result ML.

## Event result contracts

Object classification uses reported catalogue metadata first: supported `source_classification`, `object_type`, and `category` fields must agree. Conflicting or unsupported metadata produces `UNKNOWN` while retaining the raw source value. A curated CelesTrak group is a fallback only when those fields are absent; display names are never classification evidence.

`ScreeningProxyEvent` has a stable internal `SP-<hash>` ID derived from the canonical object pair and input hashes. It is marked `event_identity_type=internal_deterministic`; it is not a CDM event ID. Sorting and report generation do not depend on list position. Changed element inputs can change the key because the event's inputs changed.

Each proxy event carries independent result objects:

- `PhysicsResult`: currently `status=unavailable`, applicability `candidate_pair_only`; TCA, miss distance, covariance, hard-body radius, and probability of collision are null/unavailable with reason codes.
- `MLResult`: contract only; `status=not_implemented`, with no model, prediction, uncertainty, or validation metrics.
- `ComparisonResult`: contract only; no agreement/validation claim is emitted. Its validation claim is fixed to `none`.

These proxy result objects remain separate. Physical `ConjunctionAssessmentEvent` results additionally carry an independent top-level `collision_probability` object alongside `physics_result`; the comparison stage may read either result but must not mutate them. `backend/app/services/collision_probability.py` implements the Foster 2D encounter-plane integral only when callers supply two valid same-frame, same-TCA covariance inputs, a supplied combined HBR, and explicitly authorize the independence assumption. The Foster function does not transform covariance or frames. The restricted CDM importer rotates the CDM RTN position covariance block into the CDM-declared frame before calling it. The Stage 2A TLE screen supplies no covariance/HBR, so its unaugmented event Pc status is unavailable and `pc` remains null. This research implementation has analytic reference/property tests but is not validated against operational conjunction datasets or the NASA CARA SDK suite. `/maneuver` remains unavailable with null numerical outputs because validated maneuver dynamics are absent.

### Supplying event-bound Pc inputs

`POST /api/conjunction-jobs/{job_id}/events/{event_id}/cdm` accepts a user-supplied CCSDS CDM XML document in the JSON field `cdm_xml`, with a `source_label` and explicit `assume_independent_covariances` boolean. The importer currently supports **TEME only**. It requires exactly two CDM segments, distinct `OBJECT_DESIGNATOR` identifiers matching the selected Stage 2A event, exact UTC TCA match, matching supported CDM `REF_FRAME` values, Cartesian covariance type, complete positive-definite 6x6 covariance matrices, complete TCA state vectors, a combined `HARD_BODY_RADIUS`, and recognized units. For this path, each TCA state vector is interpreted in TEME, the covariance entries are interpreted in the local R/T/N basis at that object's TCA state, and the RTN position block is rotated into TEME using that state vector. The importer does not transform the CDM state between TEME and another frame. A matching frame-name string alone does not establish that the input data actually use that convention. Foster uses the CDM TCA states and rotated position blocks, not the Stage 2A TLE mean state. The CDM result is therefore a separate imported assessment attached to the same object pair and exact TCA. No frame transform between CDM and TLE frames, or covariance propagation, is performed. Missing, unsupported, or mismatched frames and other incompatible structure, units, identifiers, TCA, or covariance are rejected.

Imported values are marked `user_supplied`; CDM originator/source text is retained as a user claim, not authenticated provenance. The raw document hash is stored with covariance and HBR provenance. Because cross-object correlation is not provided by this path, Foster Pc is emitted only when the caller explicitly authorizes the existing independence assumption. The enriched event is stored in that backend process's in-memory screening job; it is lost when that process exits or the job expires. No real CDM was present in the project when this path was added; only test fixtures exercise the importer.

### Separate research scenario

`POST /api/conjunction-jobs/{job_id}/events/{event_id}/scenario-pc` accepts two explicit 3x3 position covariance matrices in km^2, an explicit combined HBR in km, a written assumption basis, and the explicit covariance-independence choice. Frame and epoch are taken from the selected valid interior-TCA event. The inputs are marked synthetic/assumed. The result is written only to `scenario_collision_probability` and `scenario_assumptions`; it never overwrites the event's source-supported `collision_probability` or Stage 2A `physics_result`. This output is a sensitivity scenario, not an observed or calibrated real-world collision probability. Empty inputs do not receive defaults.

The importer supports a restricted subset of the CCSDS Conjunction Data Message (CDM) XML structure described in [CCSDS 508.0-B-1](https://ccsds.org/publications/bluebooks/entry/3064/); it is not a general CDM implementation. TEME is the only supported `REF_FRAME`; other frame conventions, unsupported CDM versions, alternate covariance types, or units are rejected rather than guessed. Broader frame support requires verified frame-specific state and covariance interpretation and regression references.

NASA CARA material distinguishes screening from conjunction risk assessment and documents the data, covariance, and algorithm considerations needed for Pc work. This stage intentionally does not implement those algorithms. See [NASA CARA publications](https://www.nasa.gov/cara/cara-publications/), [NASA CARA research and development](https://www.nasa.gov/cara/research-and-development-2/), and NASA's [CARA software package listing](https://software.nasa.gov/software/GSC-18016-1). These references are guidance and validation targets, not a claim that ORION implements or is endorsed by NASA CARA.

## API and frontend semantics

- `/api/catalog` returns valid propagated objects, separately listed invalid/unavailable records, and aggregate source summary.
- `/api/conjunctions` and `/api/conjunction-jobs` return Stage 2A trajectory assessments; `/api/screening-proxies` returns heuristic-only candidate pairs. A valid empty physical list stays empty. API errors/unavailability are distinct from empty results.
- The job-bound `/cdm` and `/scenario-pc` routes accept event-specific source inputs and explicit research assumptions respectively; the scenario result is serialized separately from source-supported physical Pc.
- `/api/conjunctions/{event_id}/maneuver` returns a bounded exploratory two-body candidate sweep for a valid stored event; all results carry `available_with_warning` because the existing baseline thresholds are diagnostic, not scientifically validated. Discrepant or unavailable comparisons are explicit, and candidates are not verified maneuver improvements.
- `/api/smart-filter`, analytics, and reports identify heuristic result types and provenance. Missing aggregates remain null/unavailable instead of being presented as numeric zero.
- Offline browser fallback objects are labeled synthetic demo data and do not generate local conjunction or maneuver results. The top bar carries the aggregate source-status chip on every page.
- System health reports ML unavailable, GPU not used by the backend, and no persistent database unless one is actually configured.

The existing seven page states and visualization components remain. The Smart Filter label omits “AI” because this stage has no trained model. Physics-only operation does not depend on an ML runtime.

## Current limitations and next-stage interfaces

Not implemented in this stage: automatic or authenticated covariance feeds; covariance propagation/transform or cross-correlation modelling; a catalog HBR source; 3D Pc; operationally validated Pc or maneuver optimization; model calibration; and LLM explanations. A separate bounded two-body impulsive-burn sweep is exploratory only and is not operational flight dynamics. Foster 2D is a research calculation whose applicability assumptions cannot be established from current TLE inputs. The CDM parser is intentionally narrow; unsupported formats, units, frames, epochs, and covariance types remain unavailable rather than being transformed by assumption.

The typed result contracts and screening-proxy boundary are intended as insertion points for those future modules. Any future numerical method needs authoritative references, deterministic reference-case tests, provenance, explicit applicability checks, and independent validation data. Passing software tests establishes only tested software behavior; it does not establish orbital prediction accuracy.
