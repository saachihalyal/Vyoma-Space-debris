# ORION geometry-only review priority

## Scope

`orion-geometry-review-v1` is an internal queueing policy for valid Stage 2A
interior-TCA assessments. Its labels are **review priority**, not physical
collision-risk levels, collision probabilities, or NASA/ESA operational
thresholds. The policy uses only the valid miss distance and the screening
threshold recorded on the same event. It does not use Pc, ML output, relative
speed, object type, or time-to-TCA. Those fields remain separately visible.

The normalized geometry measure is

```text
miss_distance_fraction = miss_distance_km / screening_threshold_km
```

Default, configurable category boundaries are:

| Category | ORION rule |
| --- | --- |
| CRITICAL | fraction `<= 0.05` |
| HIGH | `0.05 <` fraction `<= 0.20` |
| MEDIUM | `0.20 <` fraction `<= 0.60` |
| LOW | fraction `> 0.60` |

The thresholds are internal review-queue choices tied to the configured
screening threshold; they do not claim a physical collision likelihood.
`REVIEW_REQUIRED` is returned for invalid, boundary, or non-valid trajectory
assessments. `UNCLASSIFIED` is returned when required geometry, screening
threshold, or policy configuration is unavailable or invalid.

## Configuration and versioning

Set these backend environment variables to override defaults:

- `ORION_REVIEW_POLICY_VERSION` (default `orion-geometry-review-v1`)
- `ORION_REVIEW_CRITICAL_MAX_FRACTION` (default `0.05`)
- `ORION_REVIEW_HIGH_MAX_FRACTION` (default `0.20`)
- `ORION_REVIEW_MEDIUM_MAX_FRACTION` (default `0.60`)

The three fractions must be finite and strictly increasing in `(0, 1]`.
Invalid configuration produces `UNCLASSIFIED` with an explicit reason. Every
event stores the policy version, applied rule, input signals, supporting
geometry, limitations, and deterministic explanation. The same fields are
serialized in event APIs and included in CSV/PDF reports.

## Interpretation limits

The categories order events for human review only. They do not state whether
an event will collide, replace missing Pc, or authorize a maneuver. Live Pc
requires event-specific compatible covariance and hard-body-radius inputs.
ESA model output remains separate and is excluded from this policy unless a
future version explicitly establishes and tests a compatible semantic use.

## Collision Analysis evidence ordering

The Collision Analysis table uses a separate deterministic evidence ordering
(`collisionEventPriority` in `src/utils/collisionEventDisplay.js`):

1. A positive, finite computed Pc tied to the exact event ID, sorted by
   descending Pc. Numeric outputs with a mismatched event ID are withheld.
2. A valid source-reported Pc tied to the exact event ID, sorted by descending
   source value. This is a separate tier and is not treated as verified or
   directly comparable to the computed-Pc tier.
3. When neither Pc tier applies, valid geometry review categories in the order
   CRITICAL, HIGH, MEDIUM, LOW.
4. Events without qualifying Pc or geometry evidence are last and remain
   unclassified. Missing Pc is never converted to zero or a low-risk label.

Equal values within a probability tier and equal geometry categories are
ordered by ascending event ID for stable, reproducible output. The table also
shows the tier or geometry reason for each row. These ranks organize review;
they are not a calibrated risk scale. The ESA log-risk regression model is not
a live conjunction classifier and is excluded from ranking.
