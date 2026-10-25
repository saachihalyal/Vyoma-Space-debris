# ORION Collision AI Models

## Purpose and limits

These offline trained surrogates reproduce ORION's corrected TLE-age-baseline research Pc and physics risk policy. Labels are physics generated, not observed collision outcomes. Research Pc remains authoritative, and the models are not operationally calibrated.

## Dataset and leakage-controlled split

Source: saved CelesTrak screening job `08c33d64c8d34ddfb6838a565d3c0db3` with 118 valid parent events. An audit of all 10 saved screening-job files found 260 valid physical event rows and no duplicate event IDs. Applying ORION's existing co-located encounter grouping rule across jobs (same TCA to the millisecond, miss distance and relative speed rounded to four significant digits, and a shared object ID) maps those 118 parents to 62 physical encounter groups. The initial parent-only split leaked 20 groups (48 parent IDs) across partitions. Dataset v3 now assigns every parent and all generated variants in an encounter group to one fixed-seed partition. The saved split has zero group intersections: train 43 encounter groups / 75 parents / 900 scenarios; validation 9 / 20 / 240; test 10 / 23 / 276.

The generator produced 1,416 synthetic scenario variants using covariance scales 0.5, 1, 2, 3; HBR scales 0.75, 1, 1.5; TLE-age scales 0.5, 1, 2; and encounter-plane miss-distance scales 0.01, 0.1, 0.5, 1.0. Miss distance is varied while relative velocity is fixed. TLE age changes the assumed element epoch for the uncertainty model while keeping the saved state fixed. Regression target: `max(log10(Pc), -30)`; class labels use `orion-physics-pc-risk-v2`. Dataset version is `orion-collision-scenarios-v3`; the split is `backend/ml_data/orion-collision-scenarios-v3-splits.json`.

## Research Pc regression

Random forest version `2.1.0`, with median imputation fitted on train only. Test MAE was `0.05791` and RMSE `0.09754` log10(Pc), Spearman `0.98697`, across 276 rows from 10 independent encounter groups / 23 parent events. Every test row was non-negligible (`log10 Pc > -30`), so all-data and non-negligible metrics are identical. Training-median baseline MAE/RMSE were `0.57685` / `0.71345`; train-fitted linear baseline MAE/RMSE were `0.18637` / `0.25597`. The model beat both baselines and is usable for inference with the physics fallback retained.

## Physics risk classifier

Class balanced random forest version `2.1.0`. Test accuracy was `0.94203`, macro F1 `0.62319`, weighted F1 `0.94203`; the majority baseline accuracy was `0.66667`, macro F1 `0.26667`. Class order Low, Medium, High; confusion matrix (true rows, predicted columns): `[[0,0,0],[0,176,8],[0,8,84]]`. Test counts: Low 0, Medium 184, High 92. Per-class precision/recall/F1: Low `0/0/0` (no Low test examples); Medium `0.95652/0.95652/0.95652`; High `0.91304/0.91304/0.91304`. It beat the majority baseline on macro F1 and is enabled; the test set contains no Low examples, so Low performance is not evaluated.

## Artifacts, fallbacks, and limitations

Artifacts: `backend/app/ai/artifacts/orion_research_pc_surrogate.joblib` and `orion_physics_risk_classifier.joblib`, version `2.1.0`; feature schema `orion-collision-features-v2`. Sidecars record artifact hashes, target, feature schema, encounter-group split, training time, calculator/policy versions, baseline comparison, and measured metrics. `backend/app/ai/train_all.py` and `scripts/retrain_all.ps1` regenerate T5 outputs. Models load only when their measured held-out checks pass; otherwise inference uses the labelled rule-based physics fallback.

The 62 encounter groups, not the 1,416 variants, are the independent source units. Evaluation measures reproduction of the physics policy on 10 held-out groups, not observed collisions. The bounded parameter grid does not establish operational calibration. Low-risk test performance cannot be estimated from a test set with no Low examples.
