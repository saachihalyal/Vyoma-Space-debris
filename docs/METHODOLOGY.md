# ORION screening and model methodology

This document describes the checked-in model record `docs/MODEL_METRICS.json` and the code policy current on 2026-10-25. Model labels come from ORION's physics assumptions; they are not observed collision outcomes. The event-bearing demo archive is job `fcec3945251c45f38f215485ecbb5605`, finished partial with 109 rows. It is an archived research snapshot.

## Data and split

The training manifest covers 10 saved jobs, 220 valid parent events selected from real CelesTrak inputs, 142 connected physical encounter groups, and 3,958 generated scenarios. Two scenarios were rejected as `PC_LOG10_PC_MISMATCH`. Dataset version is `orion-collision-scenarios-v5`; seed is `20261024`; encounter groups are kept intact across splits. Train: 147 parents / 99 groups / 2,644 scenarios. Validation: 36 / 21 / 648. Test: 37 / 22 / 666. Variants from one parent are correlated and do not increase the independent encounter count.

Each parent generates up to 18 deterministic scenarios: six encounter-plane miss-vector multipliers (`0.01x`, `0.1x`, `0.5x`, `1x`, `2x`, `3x`) crossed with three covariance/HBR configurations. Relative velocity is held fixed. Scenario labels use the `tle_age_baseline` covariance policy and assumed combined hard-body radius (HBR).

## Covariance, HBR, Pc, score, and class

The default research position sigmas in local radial, in-track, and cross-track axes at TCA are `(0.1 + 0.1a, 0.5 + 1.5a, 0.2 + 0.2a) km`, where `a` is TLE age in days, with configured orbital-band multipliers. The diagonal RTN covariance is rotated to TEME at TCA; independent object covariances are summed. Covariance is not propagated from the TLE epoch. Alternatives are `esa_population_prior` and `tle_age_baseline_2x`. Combined HBR is an assumed radius from an explicit size override or ESA population size prior, not a live measured dimension.

Foster Pc is the bivariate Gaussian probability mass inside the encounter-plane collision disk of radius HBR. Deterministic Gauss-Legendre integration checks convergence; poorly represented tails use stable natural-log calculations. The small-disk limit is `log(Pc) ~= log(pi R^2) - log(2 pi) - 0.5 log(det(Sigma)) - 0.5 mu^T Sigma^-1 mu`. Exact `log10 Pc` is retained; display floors do not replace it. Model targets clip values below `-30` to `-30`.

The physics score is `clip(100 * (log10(Pc) + 12) / 10, 0, 100)` using the configured `[-12,-2]` log10 window. ORION policy class is Low for `Pc < 1e-7`, Medium for `1e-7 <= Pc < 1e-4`, and High for `Pc >= 1e-4`. These are project thresholds, not universal safety limits. Geometry review priority, source-reported Pc, event-specific Foster Pc, research Pc, and AI predictions are separate channels; the rule-based review score is not AI.

## Held-out model results

All figures below are read from `docs/MODEL_METRICS.json`, test split only. Collision artifacts are version 2.3.0. The Pc surrogate has MAE/RMSE `0.076534 / 0.232037` log10 units over 666 rows; median baseline `9.329969 / 14.379786`; linear baseline `5.060958 / 6.719851`. For 459 non-negligible rows (`log10 Pc > -30`), model MAE/RMSE is `0.109856 / 0.278332`, median baseline `2.303366 / 4.492052`, and linear baseline `3.369555 / 4.613590`. The features `miss_sigma_ratio` and the log-HBR term almost determine log-domain Pc, so this low error demonstrates formula reproduction as a fast surrogate, not independent predictive skill or validation against collisions.

The physics risk classifier test support is Low/Medium/High `272/236/158`; accuracy `0.980480`, macro-F1 `0.980113`, versus training-majority macro-F1 `0.193319`. Its classes reproduce the Pc-derived project policy and are not calibrated collision outcomes.

The Smart Filter test support is insignificant/significant `508/158`; confusion matrix (true rows, predicted columns) `[[508,0],[6,152]]`; significant precision `1.0`, recall `0.962025`, and macro-F1 `0.987387`. Majority and deterministic 1 km baseline macro-F1 are `0.432709` and `0.676876`. There are 6 false negatives; the deterministic guard has none. Runtime independently retains events within 1 km, events with any uncertainty scenario Pc at least `1e-4`, and failed or uncertain inputs. The model does not override this guard. Its output is an AI classification, not a rule-based review score.

## Maneuver search and fuel estimate

The bounded search uses a 300-second burn lead, coarse magnitudes `0.01` and `0.05 m/s`, six signed RTN directions, and two-body point-mass RK4 propagation (`mu = 398600.4418 km^3/s^2`, 5-second coarse step); closest approach is refined to `0.01 s`. Search ends 1,800 seconds after original TCA with bounded local refinements. Comparisons freeze baseline TEME covariance matrices and HBR; only relative mean state changes.

The newest-job highest-Pc event recorded in the prior run was `CA-50F4A7C3AEA73F27B191`: baseline research Pc `5.51515e-7`, miss `3.0315536657 km`; selected `0.05 m/s` radial-negative candidate research Pc `5.29001e-7`, miss `3.0291397470 km`, estimated reduction `4.0823145%`. The recorded candidate TCA was `2026-10-25T21:22:11.871898+00:00`. This is bounded two-body simulation evidence, not maneuver feasibility or guidance. Fuel estimate uses `dm = m0 * (1 - exp(-delta-v / (Isp*g0)))`, defaults 500 kg, 220 s, and `g0=9.80665 m/s^2`; it omits execution, propulsion, and feasibility constraints.

Maneuver ranker v2.0.0 is not used at runtime (`ranking_used=false`). Its test set is 8 parents / 38 candidates; mean regret is `0.031142` log10 Pc-reduction units versus `0.017708` for the deterministic lowest-delta-v baseline. Runtime ranking remains the deterministic physics fallback.

## Limitations

The saved snapshots are finite; scenario variants are correlated; size and covariance are priors; cross-object covariance is omitted; and TCA covariance is not propagated. Pc, classes, scores, maneuvers, and fuel are research outputs, not calibrated collision predictions, operational advice, or feasible commands. The archived demo snapshot is partial and read-only. Space-Track is not used. Browser interaction and visual PDF inspection have not been verified in this final pass.
