# ORION Physics-Supervised Smart Filter Model Card

## Intended use

This classifier prioritizes conjunction records for analyst review by estimating whether the ORION research probability of collision (Pc) reaches `1e-4` under a configured set of covariance and hard-body-radius (HBR) assumptions. It operates on CelesTrak object data and ORION's research Pc estimator. It does not replace the independent safety guard, the physics Pc value, source-reported Pc, or human review.

The classifier is used only in the physical conjunction workflow. The existing catalog proxy review remains a separate heuristic view. User-uploaded conjunction data remain an independent input path.

## Training data and label

- Dataset: `backend/ml_data/orion-collision-scenarios-v1.jsonl`.
- SHA-256: `f0b9ee1b77694e7b41aad69461e1542830310f90aca1f68c2224e32349d25d65`.
- 804 valid assumption scenarios from 67 independent parent conjunctions.
- Labels are `significant` when the physics-generated research Pc is at least `1e-4`; otherwise `insignificant`.
- Variants from the same parent event are grouped together, so no parent conjunction appears across train, validation, or test partitions.
- Fixed random seed: `20261024`. Partition counts: train 46 parent events / 552 scenarios; validation 10 / 120; test 11 / 132.
- The classifier is a median-imputation and balanced random-forest pipeline, with preprocessing fit on the training partition only.

These are physics-generated assumption scenarios, not observed conjunction outcomes or collision labels. Scenario rows are not independent observations; the independent sample count is 67 parent events.

## Held-out test results

Class order in the confusion matrix is `insignificant`, `significant`; rows are true classes and columns are predicted classes.

| Measure | Result |
| --- | ---: |
| Accuracy | 0.9621 |
| Macro F1 | 0.8895 |
| Significant precision | 1.0000 |
| Significant recall | 0.9590 |
| Significant false negatives | 5 of 122 |
| Confusion matrix | `[[10, 0], [5, 117]]` |

The test set's majority-class baseline has accuracy 0.9242 and macro F1 0.4803. It predicts all scenarios as significant, so it has no false negatives but cannot identify insignificant scenarios. The classifier has stronger macro F1 and filters some scenarios, but its five false negatives mean classifier output must not be used as the sole safety decision.

The validation set had accuracy 0.9917, significant recall 0.9882, and one significant false negative among 85 significant scenarios. These results are estimates on the saved grouped split; the small count of parent events limits generalization claims.

## Saved-screening-job integration example

The TestClient request to `/api/conjunction-jobs/08c33d64c8d34ddfb6838a565d3c0db3/smart-filter` evaluated the saved CelesTrak-based screening snapshot (120 events): 111 retained, 9 filtered, and 111 retained by the independent guard. The CSV endpoint returned HTTP 200 with all 120 decisions and reason/guard fields.

| Example | Pair / event | TCA UTC | Miss distance | Result |
| --- | --- | --- | ---: | --- |
| Guard retained | CSS (TIANHE) / CSS (WENTIAN), `CA-2AACC2E88E86C68D31FD` | `2026-10-19T09:43:03.119986+00:00` | 0.023985 km | Retained: noninterior/invalid TCA, miss-distance guard, and uncertain scenarios; no model prediction. |
| Model filtered | COSMOS 2251 DEB / SL-8 R/B, `CA-A3380BA915D228925A87` | `2026-10-19T13:40:43.219621+00:00` | 20.379826 km | Filtered: 12/12 scenarios calculated, max research Pc `1.18320e-7`, model vote fraction 0.000658, prediction insignificant, no guard trigger. |

These are computed outputs from a saved screening snapshot, not observed collision outcomes. The first example is intentionally retained because the boundary/invalid assessment and close miss make model filtering unsafe.

## Runtime policy and safety guard

For each conjunction, runtime inference evaluates all 12 combinations of covariance scales `[0.5, 1, 2, 3]` and HBR scales `[0.75, 1, 1.5]`. It derives the maximum significant-class random-forest vote fraction across scenarios. This vote fraction is not a calibrated probability.

The independent deterministic guard retains an event if any of these conditions holds:

- Miss distance is at or below 1.0 km.
- Any scenario Pc reaches `1e-4`.
- TCA/event state is invalid or noninterior, miss distance is unavailable, or any required scenario/features cannot be evaluated.

Only events that pass every guard and have all 12 scenarios calculated can be filtered by a model prediction of `insignificant`. If the artifact is missing, mismatched, or fails inference, the API labels the deterministic fallback and retains uncertain or guard-triggering cases. Guard decisions and reasons are exported in the CSV.

## Artifact and monitoring

- Model version: `1.0.0`.
- Artifact: `backend/app/ai/artifacts/orion_smart_filter_classifier.joblib`.
- Artifact SHA-256 is recorded in the adjacent metadata JSON and verified at load time.
- Dataset hash, feature schema, split membership, test metrics, and guard policy are recorded in that metadata.
- `/api/collision-models` and the application health response expose model availability and evaluation metadata.

## Limitations

- Labels are generated by ORION's research Pc method and share its assumptions and failure modes.
- The 67 independent parent conjunctions are a small dataset; performance can shift for different catalog populations, geometries, and covariance/HBR behavior.
- The 12 assumption variants per parent do not increase the independent parent-event sample size.
- Test-set false negatives are nonzero. The classifier is a review-prioritization aid, not collision-avoidance authority or a replacement for the safety guard.
- The score called confidence is a maximum vote fraction, not a calibrated event probability.
- Any unavailable scenario, invalid event, or guard threshold hit causes retention regardless of the classifier prediction.
