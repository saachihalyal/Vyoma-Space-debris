# ORION Collision AI Models

## Purpose and limits

These models are fast surrogates for ORION's own research-Pc calculation. They are trained on physics-generated scenarios and have not been validated against observed collision outcomes. The research Pc from the physics calculation remains authoritative. Model outputs do not replace it and are not operational collision-avoidance predictions.

## Fixed training snapshot and generated scenarios

The offline trainer is `backend/app/ai/collision_training.py`, run from `backend` with:

```powershell
.\.venv\Scripts\python.exe -m app.ai.collision_training
```

The source is saved screening job `08c33d64c8d34ddfb6838a565d3c0db3`, created `2026-10-19T09:43:03.120187+00:00`. Its `120` records contain `118` valid physical events. The snapshot hash is `5c54434b021dc9370e574ac55f9525d130758830f9ae444fe8e47229540fb026`. Each eligible conjunction is derived from two nonsynthetic live object records whose retained input URLs point to CelesTrak. This provenance is recorded per scenario.

The generator calculates research Pc with the ORION Foster 2D pipeline while varying covariance scales `0.5`, `1`, `2`, and `3`, and HBR scales `0.75`, `1`, and `1.5`. Every target comes from the physics output. Out of `1,416` attempted variants from the `118` valid parents, `804` variants from `67` distinct parent events passed calculation and feature validation; `612` were rejected as `FOSTER_PRIOR_CALCULATION_PC_METHOD_NOT_APPLICABLE`.

All variants from a parent event stay in one fixed-seed (`20261024`) shuffled parent-ID split:

| Partition | Parent events | Scenario variants |
|---|---:|---:|
| Train | 46 | 552 |
| Validation | 10 | 120 |
| Test | 11 | 132 |

The generated JSONL and split manifest are saved under `backend/ml_data/`. Preprocessing uses median imputation fitted inside each model pipeline on training rows only. The feature schema is `orion-collision-features-v1` and includes miss distance, relative speed, TLE ages at TCA, object altitude/inclination and categories, assumed HBR, and scenario scales. The exact names, units, hashes, parent IDs, calculator version, input provenance, and generated targets are recorded in the dataset and metadata files.

## Model 1: research-Pc surrogate

Target: `log10(research_pc)`. The estimator is a `RandomForestRegressor` with `300` trees, maximum depth `12`, minimum leaf size `2`, and the fixed seed. It is evaluated in log10(Pc) units against a training-set median baseline.

| Split | Scenarios | Parent events | Model MAE | Model RMSE | Median baseline MAE | Median baseline RMSE |
|---|---:|---:|---:|---:|---:|---:|
| Validation | 120 | 10 | 646.0338 | 2905.6762 | 670.7326 | 3163.4291 |
| Test | 132 | 11 | 0.4235 | 1.2963 | 0.8233 | 1.5527 |

Validation performance is extremely weak because the generated log10(Pc) targets include rare extreme-tail values below `-20,000`. The validation MAE is hundreds of orders of magnitude in log10 units, so the modest gain over its median baseline does not establish useful generalization. The test split is much less extreme and is not representative enough to override that limitation. The API exposes this model's output only with its model identity and marks it as a research surrogate; users must rely on the accompanying physics Pc.

## Model 2: physics risk classifier

Target: Low, Medium, or High, derived from the same generated research Pc under `orion-physics-pc-risk-v1`. The estimator is a class-balanced `RandomForestClassifier` with `300` trees, maximum depth `12`, minimum leaf size `2`, and the fixed seed. Test class order is Low, Medium, High.

Test results on `132` scenarios from `11` parent events:

* Accuracy: `0.9545`; macro-F1: `0.7535`; weighted-F1: `0.9582`.
* Majority-class baseline (High): accuracy `0.9242`; macro-F1 `0.3202`.
* Confusion matrix (rows actual, columns predicted; Low, Medium, High): `[[2, 2, 0], [0, 6, 0], [1, 3, 118]]`.
* Low: precision `0.6667`, recall `0.5000`, F1 `0.5714`, support `4`.
* Medium: precision `0.5455`, recall `1.0000`, F1 `0.7059`, support `6`.
* High: precision `1.0000`, recall `0.9672`, F1 `0.9833`, support `122`.

Validation accuracy is `0.9750` and macro-F1 is `0.8921` on `120` scenarios from `10` parent events. Its majority baseline accuracy is `0.7083` and macro-F1 is `0.2764`. Scenario class counts are imbalanced; generated scenario counts are not independent conjunction counts.

## Live inference and fallback

Inference runs only with saved, locally validated artifacts. The API checks the SHA-256, feature schema version, and ordered feature names before loading an estimator. Training is never invoked during a user request. Status and persisted evaluation metrics are exposed at `GET /api/collision-models` and in health responses. Each event keeps `collision_ai_assessment` separate from event-specific Foster Pc, research Pc, physics class, and the deterministic geometry queue index.

When an artifact is missing, corrupt, incompatible, or cannot infer from valid features, the output is explicitly marked `fallback` or `unavailable`. The deterministic reference values use the physics research Pc/classification fields and leave AI prediction fields null. They are not labeled as AI predictions.

## Reproducibility and known limits

The saved source snapshot and split manifest make this two-model training run reproducible. The generated scenario data and both versioned artifact metadata files contain the dataset/split/artifact hashes. Only `67` independent parent events produced scenarios, with `11` held out for testing. Most variants were rejected by the current Foster applicability rules. The regression validation result shows that this sample does not support a broadly reliable live Pc surrogate; additional independently sourced parent events and better tail-aware model evaluation are needed. Both tasks reproduce the declared research-Pc assumptions, not real collision outcomes.
