# ORION SSA Stage 2A Conjunction Screening Method

## Scope

Stage 2A screens the selected TLE catalog for candidate close approaches, propagates common-time object states, refines time of closest approach (TCA), and reports miss distance and relative state at TCA. It does not calculate covariance, hard-body radius, collision probability (Pc), maneuver effects, or ML predictions.

TCA and miss distance are physical trajectory quantities within the chosen SGP4 model and finite screening horizon. They are not equivalent to an operational conjunction assessment and do not establish collision risk.

## Inputs and provenance

The screening path consumes the original TLE records and the already-established valid object identities. It propagates those TLEs directly; it does not use rounded UI positions, altitude or inclination similarity, risk cells, or proxy scores as physical state inputs. Duplicate catalog IDs with conflicting TLE hashes are excluded and reported. Exact duplicate records are reduced to one deterministic input. Synthetic visualization objects are never propagated as physical tracks. The service has a test-only opt-in for explicitly marked synthetic fixtures; the production API does not enable it.

Each returned TCA state contains the object's source, source type, TLE epoch, TLE hash, propagation epoch, SGP4 implementation/version, WGS-72 configuration, TEME frame, and km / km/s units. Pair-level provenance includes both object IDs and input hashes. A TLE source may be live or bundled fallback; fallback results stay marked as fallback. Current propagation success does not establish that an old TLE remains accurate.

## Horizon and defaults

The default screening window begins at the UTC instant when the request starts and ends 24 hours later. The caller may supply `start_utc` with an explicit timezone offset and select `horizon_hours` from 0.01 through 72 hours. The exact UTC start and end are returned in `screening` metadata and in every physical result.

The default coarse step is 60 seconds; API requests may set 10–300 seconds. The default close-approach threshold is 25 km; API requests may set a positive value up to 1,000 km. A request that would require more than 10,000 sample epochs is rejected with HTTP 422, even when its individual horizon and step values are inside their ranges. These are explicit research/demo configuration values, not NASA CARA operational screening volumes or risk thresholds. A boundary result only describes the minimum at the requested interval edge; it makes no claim about times before or after the horizon.

The search uses a configured maximum relative-speed bound of 30 km/s. If any propagated object has a sampled speed greater than 15 km/s, assessments involving that track are invalidated because the broad-phase bound is not applicable. The output records the bound and the expanded search radius:

```text
broad_phase_radius = screening_threshold + max_relative_speed_bound * maximum_sample_gap / 2
```

This makes the sampling guard explicit. Candidate completeness remains conditional on the speed bound, the time samples, the selected catalog, and successful SGP4 propagation; it is not a guarantee for unmodeled or extreme trajectories.

## Propagation, frame, and time conventions

The existing `python-sgp4` SGP4/SDP4 implementation is retained with WGS-72 gravity constants. Every object is evaluated at the same sequence of UTC instants. Datetimes are converted to split Julian dates for SGP4. No TEME transformation is applied, so both objects remain in the common TEME output frame at each epoch. No Earth-orientation data are used in this Stage 2A computation.

Position is km from the Earth-centered origin and velocity is km/s. Relative state uses the documented convention:

```text
r_rel = r_secondary - r_primary
v_rel = v_secondary - v_primary
miss_distance = norm(r_rel)
```

Object roles are canonicalized by catalog ID for deterministic event identity; “primary” here does not designate a protected spacecraft. The UI labels the result as a research trajectory assessment.

SGP4 errors and non-finite states are retained as reason codes. Error states, including decay/error code 6, are not treated as valid encounter geometry. If an object has an SGP4 error anywhere in the requested horizon, a nearby candidate involving it is returned as invalid without a claimed TCA or miss distance. Such incomplete tracks make the overall screening run partial.

## Candidate generation

At each sampled epoch, valid positions are placed into a three-dimensional spatial hash with cell width equal to the expanded broad-phase radius. The service checks the object’s own and 26 adjacent cells and retains pair samples whose instantaneous separation is within that radius. Self-pairs are excluded. No full-catalog pair matrix is constructed.

Expected work is `O(N*T + Q)`, where `N` is the number of catalog tracks, `T` is the number of sample epochs, and `Q` is the number of nearby-cell pair checks. A dense spatial cell can still approach quadratic local work. To keep that case bounded, the implementation has explicit candidate-pair, total local-minimum, and per-pair local-minimum caps. If a cap is reached, the API marks the run `partial`; omitted candidates are not represented as screened or safe.

For each pair, consecutive broad-phase samples are grouped and their local minimum samples are retained. A short coarse bracket around each retained sample is then evaluated with the original TLE propagators. This broad phase is a trajectory-space filter; it does not use the existing heuristic risk ranking.

## TCA refinement and verification

For each sampled local-minimum candidate, the service brackets TCA using the preceding and following coarse sample epochs, clipped to the screening horizon. Before minimization, it evaluates 17 evenly spaced epochs (16 subdivisions) across the bracket, groups adjacent sampled plateau minima, and identifies up to four sampled candidate basins. Each basin is refined separately with bounded golden-section search, up to 80 iterations and a 0.01 s time tolerance. More than four sampled basins, failed propagation, or non-convergence produces an explicit invalid assessment rather than a selected TCA. When multiple refined minima have indistinguishable minimum distances within the flat-distance tolerance, the distance remains available but TCA is unavailable. The final state fields for a uniquely selected basin all come from the same evaluated epoch.

Screening method version `1.2` identifies these event-identity semantics. Valid event IDs use canonical UTC TCA at Python datetime's microsecond precision, which preserves distinct returned minima within the same second without formatting floating-point offsets. Refinement-invalid IDs include the sample bracket and its absolute UTC endpoint epochs, so matching sample indices in screenings with different start epochs remain distinct. IDs remain deterministic for the same inputs, configuration, and method version. Archived jobs retain their stored historical IDs and provenance; they are not recomputed or migrated.

The refined miss distance is checked against neighboring propagated times at 0.1 s (or a larger value derived from the bracket when necessary). The reported convergence metadata includes the method, iteration count, final bracket width, time tolerance, neighbor-check offset, and pass/fail state. Non-finite states, propagation errors, failed convergence, or failed neighbor checks produce invalid results without fabricated numeric fields.

The 17 subdivision probes also check distance variation across the full bracket. If their range is at most `1e-9 km` (one micrometre), the distance is treated as numerically flat at the resolution of the double-precision propagated states: the assessment is `invalid` with reason `non_unique_tca_flat_distance`, the minimum probe separation remains available, and TCA and TCA-dependent states remain unavailable. The same tolerance is used to detect equal refined minima at distinct epochs (`non_unique_tca_multiple_minima`). This tolerance is far below the configured kilometre-scale screening thresholds; a unique minimum with variation below this numerical resolution is intentionally not assigned a precise TCA. The finite subdivision is bounded; it can still miss a narrower feature between probes. If the sampled basin count exceeds four, the solver reports the bounded basin limit rather than asserting a unique minimum.

If refined TCA is within the 0.01 s solver tolerance of the exact horizon start or end, the result status and `tca_status` are `boundary`, and `horizon_boundary_solution` is included. Otherwise the event status is `valid`. Only refined minima at or below the configured screening threshold are returned as physical close approaches.

## API and proxy compatibility

`GET /api/conjunctions` now returns trajectory assessments with `result_kind: physics_assessment`, request-specific status, horizon, threshold, frame, method, provenance, and result fields. `valid_empty` means screening completed for the available tracks and no refined minimum met the configured threshold. `partial` means exclusions, propagation errors, or a candidate cap affected completeness. `unavailable` means no usable TLE tracks were available. An HTTP success response alone does not imply a scientifically valid assessment.

The earlier heuristic workflow remains available separately through `GET /api/screening-proxies` and `/api/smart-filter`. Proxy records remain visibly typed as `screening_proxy`; they do not contain a trajectory assessment. Proxy CSV is available from `/api/reports/screening-proxies.csv`. `/api/reports/conjunctions.csv` exports physical Stage 2A fields and Stage 2B Pc status/provenance.

Stage 2B exposes Pc as a separate structured result. Current TLE-only inputs have no covariance or measured hard-body radius, so normal events report Pc unavailable with reason codes; no category-based object-size heuristic is used. See `COLLISION_PROBABILITY_METHODS.md` for the method and data limitations.

## Failure states

The result contract uses `valid`, `boundary`, `invalid`, and `unavailable` for event physics status. A failed individual pair has no numeric TCA or miss distance and carries a reason code, except non-unique minima where the bounded minimum distance is retained but TCA remains unavailable. `invalid_assessment_count` counts distinct invalid assessment records in the returned run after event-ID deduplication. Distinct non-unique candidate brackets include a stable candidate discriminator in their event IDs, so repeated flat minima for one object pair remain separate diagnostics. Screening metadata reports rejected object IDs/reasons, SGP4 errors, candidate/refinement counts, limits, and overall run status. Invalid timestamps, unsupported sampling configurations, and invalid query parameters return an HTTP 422 response. API transport or server failures remain API failures rather than scientific empty results.

## Limitations

- A TLE and SGP4 trajectory are a model input and propagation method, not a high-accuracy orbit determination product. TLE age, catalog coverage, drag/model error, and object maneuver history affect trajectory fidelity.
- The screen is limited to the chosen input catalog, UTC interval, distance threshold, sample interval, configured relative-speed bound, and resource caps. It does not imply that no close approach exists outside those constraints.
- The broad-phase guarantee is conditional on the configured relative-speed bound. Sampled speed checks cannot prove a continuous speed bound between epochs.
- The bounded subdivision detects multiple minima only when represented by its finite probes; a narrower unsampled feature can still be missed. Golden-section search assumes each isolated sampled basin is sufficiently well behaved. Tests cover deterministic synthetic multi-minimum cases but do not establish broad-phase recall or validate against independent operational conjunction data.
- There is no frame transformation, Earth-orientation correction, covariance, hard-body radius, Pc, maneuver optimization, or ML in this stage.
- A numerically converged result is not operationally or flight certified. The project remains a research/academic prototype.

## Tests and scientific references

The deterministic tests include the Vallado/Vanguard SGP4 reference state, analytical linear relative-motion minima, identical trajectories, sign convention, time reversal, horizon boundary, invalid/non-finite inputs, injected SGP4 error codes, units/frame/provenance, valid empty screening, duplicate IDs, stable event IDs, order invariance, and repeatability. These tests verify implementation behavior; they do not establish model accuracy for live conjunction events.

Backend verification completed with 27 passing tests and Python compile checks. The frontend production build was attempted but could not run because this delivered working copy does not include installed `node_modules` (Vite is unavailable). The Stage 2A frontend edits therefore remain unverified by a production build.

- [CelesTrak SGP4 software tutorial](https://www.celestrak.org/software/tutorials/sgp4.php) — SGP4 input use and implementation guidance.
- [CelesTrak TEME coordinate FAQ](https://www.celestrak.org/columns/v04n05/) — SGP4/SDP4 Cartesian output frame.
- [python-sgp4 documentation](https://github.com/brandon-rhodes/python-sgp4) — SatrecArray batch propagation, km and km/s outputs, Julian-date handling, and error codes.
- [CCSDS Conjunction Data Message Blue Book](https://ccsds.org/Pubs/508x0b1e2c2.pdf) — standardized close-approach state, frame, and provenance-related data exchange; ORION does not claim to produce a CDM.
- [NASA Spacecraft Conjunction Assessment and Collision Avoidance Best Practices Handbook](https://www.nasa.gov/wp-content/uploads/2023/07/oce-51.pdf) — separation between screening, risk assessment, and mitigation.
- [NASA CARA publications](https://www.nasa.gov/cara/cara-publications/) — screening and risk-analysis background. Stage 2A does not implement CARA operational algorithms or thresholds.
