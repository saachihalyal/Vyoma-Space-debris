# ORION screening and model methodology

This note records the methods and measured counts in the checked-in backend and `docs/MODEL_METRICS.json` as of the 2026-10-25 retraining pass. Model labels are generated from ORION's own physics assumptions; they are not observations of collisions.

## Data and screening

Training parents come from saved screening job `fcec3945251c45f38f215485ecbb5605`, created at `2026-10-25T04:00:50.959219+00:00`. The saved job is partial: 109 assessment rows, 70 valid interior-TCA physical events used as real parents, all required to retain two non-synthetic live CelesTrak GP/OMM-XML object inputs. Grouping was calculated across all saved screening jobs, including connected co-located object encounters and duplicate saved-job rows. Of the 70 parents, 49 independent encounter groups yielded at least one valid scenario. Scenario generation rejected one row (`PC_LOG10_PC_MISMATCH`) and retained 1,259 rows.

The held-out split has 34 encounter groups / 48 parents / 863 scenarios in train; 7 / 7 / 126 in validation; and 8 / 15 / 270 in test. The seed is `20261024`. A physical encounter group is the split unit; all parent rows and all generated variants mapped to that group remain in one partition.

The newest saved job contains valid research-Pc records for 69 events; 65 have exact `log10 Pc < -30`. On the 10 smallest saved log10 Pc values, the largest is `-590.9776439200073`; each is below the saved research display floor of `-30` and each physics label is Low. Exact per-event model outputs are stored in `docs/MODEL_METRICS.json` under `newest_saved_job_evaluation`.

## Covariance and hard-body radius

The default research covariance policy is `tle_age_baseline`. It assigns position sigmas in local radial, in-track, and cross-track axes at TCA as `(0.1 + 0.1a, 0.5 + 1.5a, 0.2 + 0.2a) km`, where `a` is the object's TLE age in days, with configured orbital-band multipliers. The diagonal RTN covariance is rotated into TEME using the propagated state at TCA. The two object position covariances are treated as independent and summed. No covariance propagation from the TLE epoch is performed. Alternative selectable policies are `esa_population_prior` and `tle_age_baseline_2x`.

The HBR is a combined assumed hard-body radius. The source may be an explicit large-object override or the ESA population size prior; the ESA spans are treated as diameters and converted to radii. It is not a live measured dimension. Maneuver comparisons reuse the selected baseline event's exact TEME covariance matrices and combined HBR for all candidates; only the candidate relative mean state changes.

## Collision probability and score

For encounter-plane mean vector `mu`, covariance `Sigma`, and combined HBR radius `R`, the Foster 2D probability is the bivariate Gaussian mass inside the collision disk:

`Pc = integral over x^2 + y^2 <= R^2 of [ exp(-0.5 (z-mu)^T Sigma^-1 (z-mu)) / (2 pi sqrt(det(Sigma))) ] dz`.

The disk integral uses deterministic Gauss-Legendre quadrature, with convergence required between successive orders. In poorly representable tails, the same calculation is evaluated in natural-log space using stable normal-interval differences and log-sum-exp. The checked small-disk limit is `log(Pc) ~= log(pi R^2) - log(2 pi) - 0.5 log(det(Sigma)) - 0.5 mu^T Sigma^-1 mu`. Saved exact `log10 Pc` is not replaced by the display floor; model regression targets are clipped at `-30`.

The ORION risk score uses the configured log10 window `[-12, -2]`:

`score = clip(100 * (log10(Pc) + 12) / 10, 0, 100)`.

The project policy classifies Low for `Pc < 1e-7`, Medium for `1e-7 <= Pc < 1e-4`, and High for `Pc >= 1e-4`. These are ORION policy thresholds, not universal safety thresholds. The score and class derive from physics Pc; they are separate from geometry review priority and the ESA log-risk estimate.

## Scenario generation and models

Each real parent produces up to 18 deterministic physics variants: six encounter-plane miss-distance multipliers (`0.01x`, `0.1x`, `0.5x`, `1x`, `2x`, `3x` of that parent's original miss vector), with three covariance/HBR configurations per multiplier. Relative velocity is held fixed. Covariance, HBR, and TLE-age assumptions vary as recorded in the dataset manifest. The old generator set absolute kilometer distances despite naming the field a scale; v4 now applies the value as a true multiplier. The saved v4 dataset has 1,259 scenarios.

The Pc regressor target is `max(log10(research Pc), -30)` under the same TLE-age covariance and HBR policy. Test MAE/RMSE are `2.4314126 / 5.1188891` log10 units over 270 rows, versus `10.6563267 / 15.6548770` for the training-median baseline and `7.5303332 / 8.4492872` for the fitted linear baseline. Among 134 test rows with exact `log10 Pc > -30`, MAE/RMSE are `4.0816145 / 6.8720788`; the median baseline is `21.4717031 / 22.2217954`. The model beats both baselines on held-out MAE and RMSE and is marked usable.

The risk classifier predicts Low/Medium/High from the same generated Pc and policy labels. Test support is Low 183, Medium 79, High 8; the rows-true/columns-predicted confusion matrix is `[[178,5,0],[6,73,0],[0,0,8]]`; macro-F1 is `0.9666545` against majority baseline `0.2693157`. It is marked usable because held-out macro-F1 exceeds the majority baseline. The 10 lowest-Pc real events in the newest job were all predicted Low by this model.

The Smart Filter target is significant when physics-generated Pc is at least `1e-4`. Its saved v4 test support is insignificant 262 / significant 8; confusion matrix is `[[262,0],[2,6]]`; significant precision is `1.0`, recall `0.75`, and false negatives `2`. Macro-F1 is `0.9266703`, versus majority baseline `0.4924812` (8 false negatives) and deterministic 1 km baseline `0.5616883` (2 false negatives). The model beats the baselines on macro-F1 and majority false negatives.

## Maneuver search and fuel

The default bounded maneuver search uses a 300-second burn lead, coarse magnitudes `0.01 m/s` and `0.05 m/s`, and all six signed RTN axes. The primary is impulsively burned and both TCA states are propagated with Earth two-body point-mass RK4 (`mu = 398600.4418 km^3/s^2`, 5-second coarse step); closest approach is refined to `0.01 s`. The finite search runs from burn epoch through 1,800 seconds after the original TCA, with bounded local candidate refinements. It does not model J2, drag, third bodies, execution errors, attitude, or propulsion feasibility.

For the highest-Pc valid event in the newest job (`CA-50F4A7C3AEA73F27B191`), baseline research Pc is `5.51515e-7` at a two-body zero-burn miss of `3.0315536657 km`. The lowest-Pc candidate in the bounded search is a `0.05 m/s` radial-negative burn. It yields miss `3.0291397470 km`, research Pc `5.29001e-7`, and a `4.0823145%` Pc reduction; its TCA is `2026-10-25T21:22:11.871898+00:00`. The comparison holds both baseline covariance matrices and HBR `0.002 km` fixed. The two covariance SHA-256 values match baseline to candidate in the maneuver result.

Default fuel assumptions are initial mass `500 kg`, specific impulse `220 s`, and standard gravity `9.80665 m/s^2`. The ideal single-impulse estimate is `propellant = m0 * (1 - exp(-delta-v / (Isp * g0)))`; this candidate's estimate is `0.01158755 kg`. It omits burn duration, efficiency, tank margin, residual propellant, and feasibility constraints.

## Smart Filter guard

Runtime uncertainty inference evaluates 12 scenarios: four covariance multipliers (`0.5x`, `1x`, `2x`, `3x`) crossed with three HBR multipliers (`0.75x`, `1x`, `1.5x`). A `1 km` miss-distance guard independently retains close events. Any scenario with Pc at or above `1e-4`, any failed scenario, or uncertain input also retains the event. The classifier threshold is `0.5` on its maximum significant-class vote fraction across scenarios; the vote fraction is not calibrated probability. Classifier output never overrides the independent guard.

## Limitations

The saved jobs are small finite snapshots; scenario variants are correlated within parent events and do not increase independent encounter count. Labels are generated from ORION's own assumptions rather than observed collision outcomes. Covariance and size mappings are priors, cross-object covariance is omitted, and TCA covariance is not propagated. PC and risk class are research outputs, not calibrated collision predictions or operational advice. Maneuver trajectories and fuel are bounded research simulations, not maneuver feasibility or control guidance. A restored demo snapshot is read-only archived job data.

The newest archive with status `complete` is empty (`94d8039d80d44064a7d97417156119e5`, zero event rows). The event-bearing demo file is therefore the newest finished snapshot with screening records, job `fcec3945251c45f38f215485ecbb5605`; it finished with partial status and 109 rows. The backend archive loader accepts this file from `backend/exports/demo/` through the normal restore endpoint.
