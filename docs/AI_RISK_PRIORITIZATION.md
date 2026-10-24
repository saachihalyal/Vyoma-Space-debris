# ORION live-event AI prioritization

## Output meaning

Every valid Stage 2A SGP4 conjunction includes `ai_risk_assessment`. Its score is a deterministic queue index from 0 to 1, not Pc, a probability, or an ESA model prediction. The fallback uses only the event's propagated miss distance, configured screening threshold, and relative speed:

```text
proximity = 1 - min(miss_distance / screening_threshold, 1)
speed_component = min(relative_speed / 15 km/s, 1)
score = 0.75 * proximity + 0.25 * speed_component
```

The 15 km/s value is a normalization reference, not a risk limit. The defaults are configurable with `ORION_AI_GEOMETRY_WEIGHT`, `ORION_AI_SPEED_WEIGHT`, and category boundaries `ORION_AI_MEDIUM_SCORE` (0.35), `ORION_AI_HIGH_SCORE` (0.60), and `ORION_AI_CRITICAL_SCORE` (0.80). They form ordinal display bands on this normalized index: higher labels require a larger combined proximity/speed contribution. They do not correspond to known event outcomes, NASA/ESA alert levels, or calibrated thresholds, and were not tuned to selected objects. Invalid configuration falls back to these defaults. Equal scores are ordered by stable event ID.

The event response separately carries a miss-distance geometry rank, event-specific Foster Pc rank, ESA-prior research Pc rank, and final priority rank. Foster and prior-based Pc ranks are calculated separately. In a multi-event result, a Pc percentile contributes 20% to final priority only if every valid event has a numeric value from the same provenance pathway; otherwise the composite uses AI and geometry only, renormalized to 62.5% and 37.5%. This prevents mixing an event-specific Foster Pc with an assumption-based ESA prior. Percentiles are relative to that screening result and do not calibrate Pc. The ranking explanation identifies which evidence entered the composite.

## ESA model provenance and current disposition

The persisted ESA model target is the final event `risk` value in log10 space, selected from the latest CDM (minimum `time_to_tca`, last file occurrence breaks ties). It is an ESA historical event-risk target; it is not a numerical collision-probability target or Foster Pc. The artifact uses nine encounter features: time to TCA, miss distance, relative speed, relative position R/T/N, and relative velocity R/T/N. `risk`, `max_risk_estimate`, mission/event identifiers, and covariance-derived fields are excluded from features.

The reproducible training/evaluation code is `backend/app/ai/training.py` and the mission-grouped, ESA-protocol evaluation is `backend/app/ai/evaluation_audit.py`; it fits preprocessing on training missions only, uses event rows from before the final CDM, and evaluates one closest-to-TCA eligible forecast (at least two days before TCA) per held-out event. The persisted held-out test comparison in `backend/app/ai/artifacts/esa_event_log10_risk.metadata.json` covers 3,832 events and 145 high-risk labels. Ridge baseline: MAE 6.8935 log10, RMSE 8.4036, Spearman 0.4424, PR average precision 0.1271, fixed-threshold recall 0/145. Histogram gradient boosting: MAE 6.8489, RMSE 8.5801, Spearman 0.3510, PR average precision 0.0794, recall 0/145. The primary estimator modestly lowers MAE but is worse on RMSE, ranking correlation, and high-risk ranking; neither model detects any test high-risk label at the fixed -6 threshold.

From `backend/`, retraining is `python -m app.ai.training`; the read-only evaluation audit is `python -m app.ai.evaluation_audit`. Training writes the persisted artifact/metadata, so retraining should be treated as a deliberate model-artifact update.

The model remains withheld for live events because matching feature names and units do not establish that ESA historical CDM semantics match ORION's TLE-propagated TEME-to-primary-RTN conventions. Inference remains separately represented by `ml_result`; the deterministic fallback does not train on, imitate, or claim the ESA target. The anomaly model is also separate and is not included in the collision queue score.

## Limitations

The fallback is an explainable prioritization policy rather than a learned or calibrated collision predictor. It uses no covariance, object size, Pc, or anomaly score. Rankings are valid only for the returned screening set, and prior-based research Pc remains explicitly assumption-dependent. Operational use would require compatible, representative event-level labels and feature conventions, mission/time-separated validation, calibrated evaluation if the target is probabilistic, and domain review of score weights and category boundaries.
