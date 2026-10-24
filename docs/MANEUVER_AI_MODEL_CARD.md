# ORION Maneuver Research-Pc Reduction Ranker

## Purpose and target

Version 1.0.0 predicts `log10(Pc_zero_burn / Pc_candidate)` for fast candidate ordering. Positive values predict a lower candidate research Pc under the configured assumptions. The model is a surrogate of ORION's physics-generated labels, not an independent orbital solver or an estimate validated against observed maneuver outcomes. The live workflow recalculates candidates with the bounded two-body simulator and uses physics research-Pc ordering whenever the model is unavailable or live Pc cannot confirm its ranking.

## Training data and split

Training used 282 maneuver candidates derived from 54 distinct real parent conjunction events in saved CelesTrak screening snapshot `08c33d64c8d34ddfb6838a565d3c0db3`, created `2026-10-19T09:43:03.120187+00:00`. Each label came from the same ORION prior-based Foster 2D research-Pc method at the zero-burn and candidate TCAs. The saved data is `backend/ml_data/maneuver_pc_reduction_v1.csv`, SHA-256 `4ec5d742f07cb11559f53ea4c5fafde03e51a9416c10d1fd4d0fb2254ea153ec`.

Parent event IDs, not individual candidates, were split with fixed seed 1501: training 37 parents / 189 candidates, validation 8 / 42, test 9 / 51. The exact parent lists are stored in `backend/ml_data/maneuver_pc_reduction_v1-splits.json` and model metadata. Test MAE was 2.2742 and RMSE 5.7129 log10-ratio units, compared with median-target baseline MAE 2.3476 and RMSE 8.3598. Mean within-parent Spearman was 0.4222, top-1 agreement was 0.3333, and mean selection regret was 0.6623 log10 units versus 1.5622 for the lowest-delta-v deterministic baseline. The evaluation covers nine independent test parents; it is not nine independent maneuver outcomes.

## Features and training procedure

Twenty inputs encode primary TCA TEME position and velocity, relative secondary-minus-primary TCA position and velocity, burn magnitude, lead time, and six one-hot signed RTN directions. The estimator is `RandomForestRegressor(n_estimators=240, max_depth=14, min_samples_leaf=3, random_state=1501, n_jobs=1)`. It is trained offline by `.venv\\Scripts\\python.exe -m app.ai.maneuver_training`; inference loads the saved artifact and does not train during requests.

The Maneuver Assessment page also accepts a canonical `ConjunctionAssessmentEvent` JSON file or a one-row CSV with an `event_json` cell containing that JSON. Uploaded records must declare `user_supplied` provenance and include valid UTC TCA, matching TEME state epochs, both object IDs, finite position and velocity vectors in km and km/s, and each object's TLE element epoch. The upload form supplies burn lead, magnitude, RTN direction, and optional paired mass/Isp inputs. Invalid or incomplete uploads return a specific validation reason; the service does not fill missing states.

## Limitations and safeguards

The maneuver model uses the Earth two-body point-mass RK4 approximation. It omits J2, drag, third-body effects, control constraints, and burn execution uncertainty. Covariance and HBR are assigned consistently using the same prior policy at each TCA, but are not dynamically propagated from TLE epoch. The research Pc is not operationally validated. Training scenarios cover six signed RTN directions and the configured burn timing/magnitude cycles. Every candidate is recalculated by the physics path; model ranks do not overwrite Pc or geometry. If the live event lacks valid comparable research Pc, deterministic physics ranking controls the displayed order.
