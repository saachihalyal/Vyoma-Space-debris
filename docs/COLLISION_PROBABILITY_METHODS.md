# ORION SSA Collision Probability and Uncertainty (Stage 2B)

## Purpose and current capability

Stage 2B adds a reference-tested research implementation of the established Foster 2D analytic conjunction-probability method. It is **not independently validated against operational conjunction data**, is not NASA operational collision probability software, and is not a collision-certainty predictor. Stage 2A trajectory fields remain independent; each physical event carries a separate `collision_probability` result.

The current live provider requests CelesTrak `FORMAT=tle`, parses the name and two element lines, and stores no covariance. The bundled fallback is also TLE-only. ORION has no measured object dimensions from which to form an HBR. Consequently, the event-specific `collision_probability` Foster result remains `unavailable` for ordinary TLE-only events with `NO_COVARIANCE` and `HBR_UNAVAILABLE`; it is not set to zero. A separate `automatic_research_pc_assessment` can contain an explicitly prior-based estimate, described below. That estimate is not source-reported, event-specific-covariance-backed, calibrated against live TLE truth, or operationally validated. TLE/GP elements alone do not provide the full uncertainty information required for a defensible operational collision probability [NASA CARA Step 2](https://www.nasa.gov/cara/step-2-close-approach-risk-assessment/).

## Automatic ESA-prior research estimate

For valid interior-TCA SGP4 events without matching event-specific covariance/HBR, the screening pipeline builds a separate research estimate using the existing Foster 2D disk integral. Its population prior artifact is reproducibly generated from `backend/ml_data/train_data.zip` by `backend/app/ai/build_research_uncertainty_prior.py`; the artifact records the source SHA-256 and component-wise p10/p50/p90 distributions. The ESA values are CDM-derived challenge-population statistics, not calibrated uncertainty for ORION's current TLE catalog.

The implementation explicitly assumes ESA `r/t/n` sigmas map to each object's local RTN frame and rotates that position covariance to TEME using the SGP4 state at TCA. The six-state prior is diagonal, assigned at TCA, and omits ESA correlations and cross-object covariance. Active/payload objects use the ESA target population; debris, rocket body, and unknown objects use the ESA chaser population. The span input is assumed to be a diameter and halved to form per-object radius before summing HBR. These role, frame, and span mappings are assumptions, not source-confirmed live object properties.

Configurable default sigma multipliers are: age `1 + 0.05 * TLE_age_days` capped at `10`; orbit-band factors LEO `1.0`, MEO `1.25`, GEO `1.5`, HEO `1.5`; eccentricity factor `1 + e`; and BSTAR factor `1 + 0.25 * min(abs(BSTAR)/0.0001, 10)`. The JSON environment override `ORION_RESEARCH_PC_PRIOR_CONFIG` can set these values for controlled sensitivity experiments; changed configuration is recorded with every estimate. These multipliers are analyst-selected scenario controls, not empirically calibrated constants. Component-wise ESA p10/p50/p90 joint scenarios produce the displayed sensitivity range, which is not a confidence interval or a guaranteed bound.

If probability-domain Foster quadrature underflows or fails to converge for a validated prior scenario, the research path retries the same 2D circular Gaussian integral in log space and reports scientific notation rather than substituting zero. Values below binary64's range have no ordinary JSON floating-point representation; the API carries those values in the scientific-notation field while the numeric float field is null. The strict event-specific Foster result and its established failure behavior are unchanged.

### Prior choice comparison on an archived CelesTrak event

The existing ESA-derived component prior remains the research estimator default. Before retaining it, the implementation was compared against the illustrative age-based RTN sigma model from the project directive, using the same event state and HBR so the covariance policy was the changed input. On archived live-TLE event `CA-6768F0762B5B4098E4C8` (objects `54216` and `69049`, TLE ages at TCA `0.2056` and `0.4616` days), the illustrative model uses object-specific `(radial, in-track, cross-track)` sigmas of `(0.120563, 0.808442, 0.241126) km` and `(0.146155, 1.192327, 0.292310) km`. With the same assumed combined HBR of `0.0091 km`, its calculated Pc is `7.77648e-5`; the ESA-prior default gives `2.55415e-7`. These are model-dependent research outputs, not measured uncertainty or calibrated truth. The roughly 304-fold difference demonstrates that choosing the baseline as the default would materially change the result; the implementation retains the source-derived ESA population prior and records its limitations rather than presenting either model as measured covariance. The illustrative comparison is not a second live event Pc channel.

### Independent approximation and Monte Carlo checks

The module exposes `small_hbr_pc_approximation(mean, covariance, HBR)`, which calculates the collision-disc area times the bivariate Gaussian density at the disc center. Its small-disc assumption is that the density varies negligibly over the disc; the function is an independent approximation and is not used to replace the full Foster integral. For a `0.001 km` HBR, encounter mean `(0.4, 0) km`, and isotropic `1.2 km` standard deviation, the focused regression test checks agreement with the full disk integral to relative tolerance `1e-6`.

Seeded Monte Carlo cross-checks use `300,000` draws each. The centered isotropic case (`sigma=2 km`, `HBR=1 km`) yields observed disk fraction `0.117440` versus analytic/full-integral reference `0.117503097`, a difference of `0.000063097`. The off-center case (mean `(1.2, 0) km`, `sigma=0.75 km`, `HBR=0.4 km`) yields `0.039756667` versus `0.040235079`, a difference of `0.000478412`. Both differences are within five binomial standard errors for their respective event probabilities. These fixed-seed checks are numerical cross-checks for synthetic geometries, not operational validation data.

## Required inputs and contracts

The `CovarianceInput` contract accepts either a 3×3 position covariance in km² or a 6×6 state covariance ordered `[x, y, z, vx, vy, vz]` with position in km, velocity in km/s, and the corresponding position, velocity, and cross-term covariance units. Each input carries object ID, frame, epoch, source, source type, source timestamp, input hash, validity state, and synthetic flag. Covariance is required at the TCA epoch. The Foster calculation does not transform covariance, convert frames, or propagate covariance in time. The restricted CDM importer has one specific preprocessing operation: it rotates each CDM RTN 3×3 position-covariance block into that object's declared CDM reference frame using the object's TCA state. It does not transform the TCA state between frames, perform general TEME/ITRF/GCRF conversions, or propagate covariance to TCA.

The `HardBodyRadiusInput` contract requires an explicit positive **combined** HBR in km and records whether it is supplied, configured, or synthetic, with source description and timestamp. Object class, name, risk score, and catalog category are never used to infer object dimensions.

Both objects' covariance matrices must be finite, correctly dimensioned, symmetric within a strict roundoff tolerance, and positive definite. Matrices outside the symmetry tolerance or with non-positive uncertainty are rejected. Tiny asymmetry within the declared tolerance is symmetrized and the operation is recorded in covariance provenance. A 6×6 covariance's top-left position block is used by Foster 2D; velocity and cross terms are retained in input provenance but do not enter the method's position-only calculation.

Relative position covariance is `P_rel = P_1 + P_2` only after the caller explicitly enables the independence assumption. Unknown cross-correlation is not inferred; without explicit independence authorization the method returns `unsupported` with `RELATIVE_COVARIANCE_CORRELATION_UNKNOWN`.

## Encounter plane and Foster 2D integral

Inputs are the Stage 2A positions and velocities evaluated at TCA in one common frame. The relative convention is secondary minus primary. The relative velocity defines the encounter-plane normal. The first in-plane axis is the normalized TCA miss vector after projection perpendicular to relative velocity; the second is the cross product of the velocity axis and the first axis. The position covariance is projected using this orthonormal basis. At zero nominal miss, a deterministic least-aligned Cartesian axis fixes the in-plane coordinates; the basis choice is recorded as a warning, and the resulting probability is invariant under a consistent rotation within the plane.

The method evaluates the bivariate Gaussian position density integrated over a circular combined-HBR collision region. This is the Foster and Estes 2D formulation described in NASA's handbook and CARA's public reference implementation [NASA Handbook, Appendix N](https://www.nasa.gov/wp-content/uploads/2023/07/oce-51.pdf), [NASA CARA `Pc2D_Foster.m`](https://github.com/nasa/CARA_Analysis_Tools/blob/master/DistributedMatlab/ProbabilityOfCollision/Pc2D_Foster.m). The implementation diagonalizes the 2×2 encounter covariance, evaluates the inner normal interval with stable `erfc` differences, and integrates the remaining angular form using deterministic Gauss-Legendre quadrature. Successive orders must converge to a relative tolerance of `1e-8` (maximum order 1024 by default). Non-convergence, underflow to zero for positive HBR, non-finite values, or a result above 1 by more than `1e-12` returns `invalid` / `NUMERICAL_FAILURE`. An estimate above 1 only within that roundoff bound is set to 1, and the numerical correction is included in the result warnings.

## Independent synthetic numerical references (Phase 2.2B)

The focused tests add fixed synthetic references independent of ORION's production quadrature. For the non-analytic cases, the reference calculation conditions a bivariate normal on its x-coordinate, integrates the conditional y probability over each vertical slice of the collision disk, and applies SciPy QUADPACK adaptive integration to x over `[-R, R]`. It uses the original encounter-plane covariance (including any off-diagonal term), the conditional-normal identity, and normal CDF values; it does not call ORION or use its angular transformation, Gauss-Legendre nodes, or successive-order convergence logic. Reference values were checked at `epsabs=epsrel=1e-12` and `1e-14`; reported estimates agreed to the displayed precision. This reference is a numerical cross-check for these synthetic cases, not an authoritative operational reference or proof for all inputs. SciPy is used only to derive the fixed constants; the regression tests themselves require no SciPy import.

All positions, means, radii, and standard deviations below are in km; covariance entries are in km². `R` is the explicit combined HBR (the disk radius), not a per-object radius. Comparison tolerance is `2e-10` absolute for the fixed references.

| Case | Encounter-plane mean | Covariance `Σ` | `R` | Independent expected Pc | Reference and convergence |
|---|---:|---:|---:|---:|---|
| Centered isotropic (existing analytic case) | `(0, 0)` | `diag(4, 4)` | `1.0` | `0.11750309741540454` | Rayleigh CDF `1-exp(-R²/(2σ²))`; analytic. |
| Centered anisotropic | `(0, 0)` | `diag(0.25, 4)` | `0.7` | `0.19394188550444136` | Adaptive Cartesian slices; estimates `0.1939418855044414` (`1e-12`) and `0.19394188550444136` (`1e-14`), reported quadrature errors `2.28e-14` and `1.72e-15`. |
| Isotropic off-centre | `(1.2, 0)` | `diag(0.5625, 0.5625)` | `0.4` | `0.040235078885898626` | Adaptive Cartesian slices; both tolerances produced `0.040235078885898626` (reported error `5.91e-15`). |
| Anisotropic off-centre | `(1, 0)` | `[[0.25, 0.25], [0.25, 2.89]]` | `0.45` | `0.01881386057219643` | Adaptive Cartesian slices; both tolerances produced `0.01881386057219643` (reported error about `7.07e-15`). |
| Strongly anisotropic off-centre stress | `(0.3, 0)` | `diag(0.0064, 6.25)` | `0.5` | `0.12241465361254343` | Adaptive Cartesian slices; estimates `0.12241465361254342` (`1e-12`) and `0.12241465361254343` (`1e-14`), reported errors `4.26e-14` and `3.94e-15`. |

The test suite also checks a tiny but representable centered probability, a large HBR-to-sigma ratio with a bounded probability, an intentionally underflowing probability (which must remain an explicit `NUMERICAL_FAILURE`, not zero), object-swap symmetry, and a strongly correlated positive-definite covariance. The last case is accepted by covariance validation but does not converge within the configured production quadrature budget and returns `NUMERICAL_FAILURE`; this is an exposed bounded-method limitation, not a fabricated result. There is no explicit numeric condition-number cutoff, so “near conditioning edge” here means a positive-definite matrix close to singularity, not a documented accepted cutoff.

## Applicability checks and assumptions

The calculation requires a valid interior TCA, finite relative state, relative speed above `1e-8 km/s`, a transverse miss vector within `1e-3` normalized radial residual, two valid same-frame covariance inputs at the exact TCA epoch, an explicitly authorized independence assumption, and positive combined HBR. Boundary TCAs, near-zero relative speed, mismatched frames/epochs, and degenerate geometry do not produce Pc.

When CDM inputs are attached to a stored event, object designators, the normalized TCA instant, and reference frame must match the event exactly. The TCA comparison has zero time tolerance: different timestamp strings representing the same UTC instant match, while any distinct instant returns `CDM_TCA_MISMATCH`. The CDM's source-reported Pc remains a separately labelled source field and is not substituted for ORION's Foster calculation.

Foster 2D assumes approximately Gaussian TCA position error, locally linear relative motion, and approximately constant relative covariance during the encounter. The current inputs contain only a TCA state and covariance, so ORION cannot independently establish the Gaussian, linearity, or covariance-constancy assumptions. These are explicitly listed as assumptions and warnings; the reported relative speed alone is not treated as proof of applicability. NASA documents cases where 2D Pc can be inaccurate when these assumptions fail [NASA CARA 2D usage-boundaries paper](https://ntrs.nasa.gov/api/citations/20190028900/downloads/20190028900.pdf).

## Statuses, API, and provenance

Each physical conjunction event returns a top-level `collision_probability` object alongside the unchanged `physics_result`:

- `available`: Pc is present and in `(0,1]` for the supplied inputs. Underflow to zero is a numerical failure, never a reported zero probability.
- `unavailable`: required covariance/HBR/encounter state is absent.
- `invalid`: covariance, HBR, configuration, or numerical result failed validation.
- `unsupported`: method assumptions, correlation, frame/epoch, or geometry prevent calculation.

Machine-readable reasons include `NO_COVARIANCE`, `INVALID_COVARIANCE`, `COVARIANCE_OBJECT_ID_MISMATCH`, `HBR_UNAVAILABLE`, `INVALID_HBR`, `INSUFFICIENT_ENCOUNTER_STATE`, `PC_METHOD_NOT_APPLICABLE`, `COVARIANCE_EPOCH_MISMATCH`, `COVARIANCE_FRAME_MISMATCH`, `RELATIVE_COVARIANCE_CORRELATION_UNKNOWN`, `DEGENERATE_ENCOUNTER_GEOMETRY`, and `NUMERICAL_FAILURE`. Event-bound CDM validation errors are returned as structured HTTP 422 details with stable reason codes such as `CDM_OBJECT_ID_MISMATCH` and `CDM_TCA_MISMATCH`. Proxy records are not given a Pc result; exports label them `PROXY_ONLY`.

The Pc result records method/version, object IDs, TCA, miss distance, HBR and its provenance, each covariance source/frame/epoch/units/hash/synthetic flag, independence and model assumptions, applicability, numerical tolerance/evaluations, warnings, reason codes, and calculation provenance. Test/demo covariance and HBR fixtures are marked synthetic and exist only in unit tests; the production API provides no route to submit or promote them as live inputs.

The conjunction JSON includes the per-event result. The existing CSV and selected-event PDF include Pc status/value, method, HBR, covariance provenance, assumptions, warnings, and failure reasons. Missing Pc remains blank/null and is described as unavailable, never as zero. Project Pc values are not equated with heuristic severity or operational attention thresholds.

## Limitations and references

- No live Pc is available from the current TLE-only CelesTrak path because it supplies neither covariance nor HBR.
- The internal method has analytic-reference and property tests; it has not been validated against operational conjunction datasets or run through the NASA CARA SDK validation suite.
- There is no covariance propagation, correlation model, 3D Pc, Monte Carlo Pc, HBR estimation, maneuver optimization, ML, or LLM calculation.
- TEME is used as supplied by Stage 2A. No frame or epoch conversion is attempted.
- Results are research/academic outputs, not flight-certified or operational collision assessments.

Additional references: [NASA CARA publications](https://www.nasa.gov/cara/cara-publications/) and [CelesTrak GP data formats](https://www.celestrak.org/NORAD/documentation/gp-data-formats.php).
