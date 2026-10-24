# Pc reference classification

## ORION physics score and final class

ORION carries a separate project risk assessment with each available event-specific Foster Pc or assumption-based research Pc. It records `risk_score` (0–100), `physics_risk_class`, `final_risk_class`, the Pc channel used, and policy version `orion-physics-pc-risk-v2`. The configurable score window defaults to log10(Pc) = −12 through −2: `clip(((log10(Pc) + 12) / 10) × 100, 0, 100)`. Thus Pc 1e-7 scores 50 and Pc 1e-4 scores 80. The High (≥1e-4) and Medium (≥1e-7) cutoffs are project policy, not universal standards. Geometry review priority and AI outputs are reported separately and do not change this class.

The score is `clip(((log10(Pc) + 8) / 4) * 100, 0, 100)`. Classes use inclusive lower bounds: High for `Pc >= 1e-4`, Medium for `1e-7 <= Pc < 1e-4`, and Low for `Pc < 1e-7`. The defaults can be overridden with `ORION_RISK_HIGH_PC` and `ORION_RISK_MEDIUM_PC` when `0 < medium < high <= 1`; invalid configuration makes the risk assessment unavailable without suppressing the underlying Pc. These are ORION research-policy thresholds, not universal safety standards.

The score is evaluated in log space, so a positive research Pc below binary64's representable range keeps its score and class from the scientific-notation result. Numeric Pc `0` uses the mathematical `Pc -> 0` limit (score `0`, Low class) without creating a positive Pc. A missing or invalid probability has no score or class. Restored archives are deep-copied and receive the same current, versioned risk derivation as fresh events; original archive records are not rewritten.

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
