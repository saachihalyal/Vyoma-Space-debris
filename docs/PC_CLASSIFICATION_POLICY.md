# Pc reference classification

ORION reports a **Pc reference category** only when the Foster result is numerically available and in `(0, 1]`. It uses the NASA CARA public Step 2 reference values: Pc above `1e-7` merits attention and Pc above `1e-4` is a mitigation reference for CARA-supported missions. The policy therefore reports:

| Category | Rule |
| --- | --- |
| `AT_OR_BELOW_NASA_ATTENTION_REFERENCE` | `Pc <= 1e-7` |
| `ABOVE_NASA_ATTENTION_BELOW_MITIGATION_REFERENCE` | `1e-7 < Pc <= 1e-4` |
| `ABOVE_NASA_MITIGATION_REFERENCE` | `Pc > 1e-4` |

Source: [NASA CARA, Step 2: Close Approach Risk Assessment](https://www.nasa.gov/cara/step-2-close-approach-risk-assessment/). This is a research presentation of NASA reference bands, not an ORION action threshold or operational risk category. NASA notes that mitigation thresholds depend on the owner/operator's risk tolerance and mitigation capacity; this policy omits event actionability, covariance realism, and collision consequence. The category does not instruct a maneuver.

Categories are carried on the Pc result and shown separately from geometry-only `ReviewPriority` and ESA historical log-risk estimates. Missing, invalid, or unsupported Pc has no category. The historical NASA CARA fixture's source Pc is `1.862e-5`, which falls in the attention band. That comparison does not assert that the historical event would qualify for mitigation.

## Boundary semantics

NASA's reference statements use “greater than”; threshold comparisons are strict. Equality at `1e-7` is in the first band, equality at `1e-4` remains in the middle band. The policy version is `nasa-cara-pc-reference-v1`.
