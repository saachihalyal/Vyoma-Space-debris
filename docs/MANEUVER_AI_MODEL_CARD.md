# ORION Maneuver Research-Pc Reduction Ranker

## Purpose and current use

Version 2.0.0 predicts `log10(Pc_zero_burn / Pc_candidate)` to order simulated maneuver candidates. Positive values predict lower candidate research Pc under the configured assumptions. It is a surrogate of physics-generated labels, not an independent orbital solver or a model validated against observed maneuver outcomes. Every candidate is recalculated by the physics path. The current held-out evaluation does not beat the deterministic lowest-delta-v baseline on mean regret, so the service records the model output for research but uses deterministic physics ranking for the displayed order.

## Training data and evaluation

Training used 256 candidate scenarios from 49 distinct real parent conjunction events in saved CelesTrak screening snapshot `08c33d64c8d34ddfb6838a565d3c0db3`, created `2026-10-19T09:43:03.120187+00:00`. The scenario CSV is `backend/ml_data/maneuver_pc_reduction_v1.csv`, SHA-256 `7285d4f73d3c8660be16e3bdc29b1dbaa891ff2be009cf83f6ad8cbe36d619af`. Parent events were split with fixed seed 1501: training 34 parents / 178 candidates, validation 7 / 40, and test 8 / 38. Parent IDs and counts are in the model metadata and split manifest.

On the eight held-out test parents, MAE was 0.03467 and RMSE 0.06040 log10-ratio units. Mean within-parent Spearman was 0.46964 and top-1 agreement with the physics-best candidate was 0.625. Mean selection regret was 0.03114, compared with 0.01771 for the deterministic baseline. The median-target baseline had MAE 0.04259 and RMSE 0.07135. These results show reasonable target prediction on this small grouped sample, while candidate selection does not outperform the simpler baseline.

## Features and training procedure

Twenty inputs encode primary TCA TEME position and velocity, relative secondary-minus-primary TCA position and velocity, burn magnitude, lead time, and six one-hot signed RTN directions. The estimator is `RandomForestRegressor(n_estimators=240, max_depth=14, min_samples_leaf=3, random_state=1501, n_jobs=1)`. It is trained offline by `.venv\\Scripts\\python.exe -m app.ai.maneuver_training`; inference does not train during requests.

Labels use ORION's TLE-age-baseline Foster 2D research-Pc assessment at each calculated TCA, with the same selected covariance and hard-body-radius policy for the zero-burn and candidate cases. The baseline can reuse the event's stored automatic research-Pc result when its policy and scale match. Candidate reductions are computed from exact log probabilities, avoiding underflow at very low Pc.

For a saved encounter with baseline miss `0.236239063 km`, a `0.01 m/s` along-track burn with 300 seconds lead moved the simulated miss to `0.238668749 km`. Recomputing covariance in a new local RTN frame at candidate TCA reproduced an apparent Pc change from `2.55415e-7` to `7.29721e-10`. That comparison changed both the mean geometry and the covariance matrix. The corrected comparison freezes the baseline TEME covariance matrices and HBR, changing only the mean relative state: Pc changed from `2.55415e-7` to `2.52718e-7` (about a 1.06% decrease). This saved-event replay is close to, but not byte-identical with, the earlier reported `2.97e-7` baseline; the model-card values are the reproduced calculation from the current saved record and configuration.

## Limitations and safeguards

The maneuver propagator is an Earth two-body point-mass RK4 approximation. It omits J2, drag, third-body effects, control constraints, and burn execution uncertainty. Covariance is assigned using the same TLE-age policy at each TCA; covariance is not dynamically propagated from the TLE epoch or through the burn. Research Pc is not operationally validated. Training cycles through four lead times and four burn magnitudes, with six signed RTN directions; generalization beyond this limited envelope is unknown. The service keeps the physics calculation authoritative and falls back to deterministic physics ordering when the ranker is not useful or inputs are unavailable.

The Maneuver Assessment page accepts a canonical `ConjunctionAssessmentEvent` JSON file or a one-row CSV with an `event_json` cell containing that JSON. Uploaded records must declare `user_supplied` provenance and include valid UTC TCA, matching TEME state epochs, both object IDs, finite position and velocity vectors in km and km/s, and each object's TLE element epoch. The upload form supplies burn lead, magnitude, RTN direction, and optional paired mass/Isp inputs. Invalid or incomplete uploads return a specific validation reason; the service does not fill missing states.
