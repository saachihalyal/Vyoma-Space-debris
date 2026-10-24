# Stage 3 ML Model Card

## Intended use and scope

ORION's Stage 3 model estimates the **final event risk label in log10 space** from an earlier CDM-like encounter feature vector. It is an experimental research estimator. It is not a collision-probability (`Pc`) model, does not calculate orbital mechanics, and must not be used to make operational conjunction or maneuver decisions. Its output remains an independent `MLResult`; it does not replace, alter, or validate the Stage 2A physics result or Stage 2B Pc result.

The UI labels the derived `10 ** predicted_log10_risk` value as an exponentiated ESA-scale event-risk estimate, explicitly **not Pc**. This conversion mirrors the dataset's log10 target scale; it is not a calibrated probability of collision.

## Model identity

- Name: `ORION ESA event final log10-risk estimator`
- Version: `2.0.0`
- Primary: `Ridge(alpha=1, solver="lsqr")`, selected on validation MAE, fixed seed 42
- Candidate: `HistGradientBoostingRegressor`, recorded for model comparison
- Feature schema: `1.0.0`; exact ordered schema is in the artifact metadata and `backend/app/ai/features.py`.
- Artifact: `backend/app/ai/artifacts/esa_event_log10_risk.joblib`
- Metadata and measured evaluation: adjacent `.metadata.json` file
- Rebuild and evaluation: from `backend`, run `python -m app.ai.training` with `backend/requirements-optional.txt` installed.

The model uses median imputation and missingness indicators fitted on training rows only. Ridge additionally standardizes its features. HGB's built-in early stopping is disabled to avoid an estimator-internal random row split that could place CDMs from one event in both subsets. Training weights give each event total weight one across its earlier CDMs.

Estimator references: [scikit-learn Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html) and [HistGradientBoostingRegressor](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html).

## Data and target

The supplied archive is ESA's Collision Avoidance Challenge `train_data.csv` in `backend/ml_data/train_data.zip`. The training reader streams the CSV from the ZIP without extracting it. The archive SHA-256 is recorded in the sidecar metadata. The official ESA dataset page describes 162,634 CDM rows across 13,154 events and cautions that the challenge dataset is selected and over-represents high-risk events: [ESA challenge data](https://kelvins.esa.int/collision-avoidance-challenge/data/).

The target for each event is the `risk` value on its final/latest CDM. The final row is selected by minimum `time_to_tca`, with last file occurrence resolving ties. Every row before that final row is a training feature example; the final row is never used as an input. Evaluation uses one latest pre-final CDM per held-out event. Input features exclude `risk`, IDs, maximum-risk fields, and covariance-derived fields. Rows with invalid event time are excluded; events with only one valid-time CDM cannot contribute a forecast. These semantics are reflected in the generated metadata.

Features and units:

1. `time_to_tca_days` â€” day
2. `miss_distance_m` â€” m
3. `relative_speed_m_s` â€” m/s
4. `relative_position_r_m`, `relative_position_t_m`, `relative_position_n_m` â€” m
5. `relative_velocity_r_m_s`, `relative_velocity_t_m_s`, `relative_velocity_n_m_s` â€” m/s

Live features are adapted from the existing Stage 2A TEME state and relative state. The adapter projects relative position and velocity onto the primary object's instantaneous RTN basis at TCA, with explicit SI conversions and consistency checks. Missing/invalid physics inputs produce an unavailable ML result; live features are not imputed.

## Split and evaluation protocol

Unique mission IDs are shuffled deterministically with Python `random.Random(42)` after sorting, then split 70/15/15. Events with missing or ambiguous mission assignments are excluded. No mission or event appears in more than one split. Split hashes, counts, preprocessing, software versions, and metrics are stored in the metadata. This is a grouped holdout, not a temporal or independent-source validation set; the dataset contains only 19 missions.

The ESA challenge input rule excludes CDMs within two days of TCA. The corrected protocol uses the inclusive rule `time_to_tca_days >= 2.0`: all eligible pre-final rows from training events may be fitted, while validation and test use the closest-to-TCA eligible pre-final row per event. Events with no eligible input are excluded and never fall back to a closer, ineligible row. Eligibility counts (total/eligible/excluded events, eligible rows, and high/low-risk event labels) are reported for each split. Fitting/scoring stops with an explicit error when training has fewer than two eligible events or an evaluation split has fewer than two eligible events or lacks either label class.

The v2 artifact uses the inclusive two-day input rule, mission-grouped splits and event-balanced sample weights. The reader found 162,634 rows and 13,154 event IDs; 13,143 had a valid time row, and 12,917 events were forecastable. The split has 13/2/4 train/validation/test missions. The eligible held-out test includes 3,832 events, of which 145 are at or above the fixed `log10 risk = -6` threshold. Ridge was selected by validation MAE from Ridge and HGB candidates, then evaluated once on the held-out test missions.

| Mission-held-out test metric | Ridge (selected) | HGB candidate |
|---|---:|---:|
| MAE (log10 risk) | 6.8935 | 6.8489 |
| RMSE (log10 risk) | 8.4036 | 8.5801 |
| R² | 0.1745 | 0.1395 |
| Spearman correlation | 0.4424 | 0.3510 |
| Average precision for thresholded high risk | 0.1271 | 0.0794 |
| Predicted high-risk events at fixed threshold | 0 / 3,832 | 0 / 3,832 |
| High-risk recall | 0 / 145 | 0 / 145 |

Regression and ranking signal are modest; the selected model missed all 145 test events above the fixed threshold. The threshold flag is not suitable for alerting or risk classification. These metrics belong to the mission-grouped v2 artifact identified by the sidecar SHA-256, not the previous v1 artifact. Metrics are not attached to live predictions.

## Runtime behavior and separation

- Optional ML packages and artifact load lazily; physics-only operation continues if either is missing or incompatible.
- Artifact SHA-256, exact scikit-learn version, and feature schema are checked before inference.
- Inference failures are returned as explicit unavailable/error ML results and do not fail physics screening.
- Live ESA-model inference is applicable only when `time_to_tca_days >= 2.0`; equality is accepted. A below-threshold input returns `status=unavailable`, no prediction, and reason `ESA_INPUT_TIME_TO_TCA_BELOW_MINIMUM`. Missing, invalid, or inconsistent time inputs fail closed with `ESA_INPUT_TIME_TO_TCA_UNAVAILABLE_OR_INVALID`. The event's physics and separate Pc result remain intact.
- The live time-to-TCA feature is elapsed UTC days from the requested screening horizon start to the selected event TCA. Historical eligibility describes a pre-final CDM at least two days before its event TCA. This gate enforces the input-window rule only; it does not establish equivalence between ESA CDMs and live TLE-derived conjunction features.
- A comparison result marks ESA log-risk and Foster Pc as `not_comparable`; it does not report agreement or validation.
- API consumers can inspect `/api/system-health`, `/api/conjunctions`, and `/api/smart-filter` for model status and results. Proxy-only events receive no ML prediction.
- Selected-event and mission CSV reports carry ML provenance and mark the estimate as not Pc.
- CSV compatibility fields `ml_predicted_risk_probability_deprecated_alias_not_calibrated` and `ml_high_risk_deprecated_alias_unvalidated` preserve old values under names that disclose their deprecated semantics. Use `ml_exponentiated_esa_event_risk_estimate` and `ml_threshold_flag_at_log10_minus_6` instead. The exponentiated ESA-scale estimate is not a calibrated probability, and the threshold flag is not a validated operational alert.
- Live inference results contain predictions and the exact nine input feature values only when applicable; held-out test metrics are recorded in the artifact metadata and are not attached to live `MLResult` objects. An unavailable live result has no numeric prediction and no evaluation metrics.

## Limitations and risks

- ESA risk labels are not equivalent to Foster Pc and their exact calibration/semantics must be verified before interpreting as probabilities.
- The ESA challenge sample was selected and over-represents high-risk events; deployment distribution shift is expected.
- Historical CDM features may differ from live Stage 2A encounters formed from public TLEs beyond the enforced two-day input window. Live state uncertainty, covariance, object hard-body radii, and TLE errors are not model inputs.
- The model is not calibrated, and no uncertainty interval is provided. Regression signal does not establish high-risk classification utility.
- Validation and test use two and four missions respectively; this small number of groups makes generalization estimates uncertain. There is no independent external reference set or temporal holdout.
- Live inference no longer emits an ESA estimate inside the two-day window. Broader historical/live feature-domain equivalence, calibration, and independent validation remain unresolved; the threshold gate alone does not prove live model validity.
- No operational, safety, maneuver, or flight-certified accuracy claim is made.
- Joblib artifacts use Python pickle semantics; load only the bundled, hash-verified artifact from a trusted source. See [scikit-learn model persistence guidance](https://scikit-learn.org/stable/model_persistence.html).

