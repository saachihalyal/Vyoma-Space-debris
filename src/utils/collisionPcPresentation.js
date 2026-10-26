import { isUsablePc } from "../components/UI/CollisionPcSummary.js";

const SUPERSCRIPT = Object.freeze({ "-": "⁻", "+": "⁺", "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹" });

export const compactPcText = (value) => String(value ?? "No Pc value in event data").replace(/([\d.]+)e([+-]?\d+)/i, "$1 x 10^$2");

export function formatPriorProbability(value, exponentShift = 0) {
  if (typeof value === "string" && /^< 1e[+-]?\d+$/i.test(value.trim())) {
    const exponent = Number(value.trim().slice(4)) + exponentShift;
    if (!Number.isFinite(exponent)) return "Invalid probability value";
    if (exponent < -300) return "< 1e-300";
    if (exponent > 300) return "> 1e300";
    return `< 1e${exponent}`;
  }
  if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
    if (value === 0) return "0";
    return formatPriorProbability((value * (10 ** exponentShift)).toExponential(3));
  }
  if (typeof value !== "string" || !value.trim()) return "No probability value in event data";
  const match = value.trim().match(/^([+-]?(?:\d+(?:\.\d*)?|\.\d+))[eE]([+-]?\d+)$/);
  if (!match) {
    const numeric = Number(value);
    if (Number.isFinite(numeric) && numeric >= 0) return formatPriorProbability(numeric, exponentShift);
    return value;
  }
  const exponent = Number(match[2]) + exponentShift;
  const mantissa = Number(match[1]);
  if (!Number.isFinite(exponent) || !Number.isFinite(mantissa)) return "Invalid probability value";
  if (exponent < -300) return "< 1e-300";
  if (exponent > 300) return "> 1e300";
  if (mantissa === 0) return "0";
  const exponentText = exponent === 0 ? "" : `e${exponent}`;
  return `${match[1]}${exponentText}`;
}

export function researchPcPresentation(assessment) {
  if (assessment?.status !== "prior_based_research_estimate") {
    const reasonCodes = assessment?.reason_codes || [];
    const reasonDetail = [assessment?.reason_message, reasonCodes.length ? `Reason code: ${reasonCodes.join(", ")}.` : null]
      .filter(Boolean).join(" ");
    return {
      value: "No valid research Pc estimate",
      percentage: "No percentage value",
      sensitivity: "No sensitivity result",
      reason: assessment?.status === "event_specific_foster_available"
        ? assessment?.reason_message || "Not applicable: a validated event-specific Foster Pc is available; no assumption-based substitute was generated."
        : reasonDetail || (assessment?.status === "not_estimable"
          ? "The configured research-Pc inputs did not produce a valid numerical estimate."
          : assessment?.status === "not_applicable"
            ? "The event is not eligible for a prior-based estimate."
            : "No valid assumption-based research estimate for this event"),
    };
  }
  // Preserve the backend's full significant digits where it provides the
  // canonical scientific string; binary64 JSON floats may round small Pc.
  const pc = assessment.estimated_pc_scientific
    ? formatPriorProbability(assessment.estimated_pc_scientific)
    : formatPriorProbability(assessment.estimated_pc);
  const percentage = assessment.percentage_scientific
    ? `${formatPriorProbability(assessment.percentage_scientific)}%`
    : `${formatPriorProbability(assessment.percentage)}%`;
  const low = assessment.lower_sensitivity_pc_scientific
    ? formatPriorProbability(assessment.lower_sensitivity_pc_scientific)
    : formatPriorProbability(assessment.lower_sensitivity_pc);
  const high = assessment.upper_sensitivity_pc_scientific
    ? formatPriorProbability(assessment.upper_sensitivity_pc_scientific)
    : formatPriorProbability(assessment.upper_sensitivity_pc);
  const lowPercent = assessment.lower_sensitivity_pc_scientific
    ? formatPriorProbability(assessment.lower_sensitivity_pc_scientific, 2)
    : formatPriorProbability(assessment.lower_sensitivity_pc, 2);
  const highPercent = assessment.upper_sensitivity_pc_scientific
    ? formatPriorProbability(assessment.upper_sensitivity_pc_scientific, 2)
    : formatPriorProbability(assessment.upper_sensitivity_pc, 2);
  return {
    value: assessment.negligible ? `${pc} (negligible)` : pc,
    percentage,
    sensitivity: `${low} to ${high} Pc (${lowPercent}% to ${highPercent}%)`,
    reason: assessment.sensitivity_reason || "Prior-based p10/p50/p90 scenario range; not a confidence interval.",
  };
}

export function physicsPcRiskPresentation(assessment) {
  if (assessment?.status !== "classified"
      || !Number.isFinite(assessment.risk_score)
      || !["Low", "Medium", "High"].includes(assessment.final_risk_class)
      || !["event_specific_foster_pc", "research_pc"].includes(assessment.risk_score_pc_channel)) {
    return { value: "No class without a valid physics Pc", basis: null };
  }
  return {
    value: `${assessment.risk_score.toFixed(1)} / 100 · ${assessment.final_risk_class} · based on ${assessment.risk_score_pc_channel}`,
    basis: typeof assessment.classification_basis === "string" ? assessment.classification_basis : null,
  };
}

export function operationalFosterStatus(event, computedMatchesEvent = false) {
  if (computedMatchesEvent && isUsablePc(event?.collision_probability)) {
    return "Available (event-specific Foster Pc)";
  }
  const pc = event?.collision_probability;
  const reasons = new Set(pc?.reason_codes || []);
  if (pc?.status === "available" && pc.event_id !== event?.id) {
    return "Rejected: Pc event identity mismatch";
  }
  if (event?.physics_result?.status === "invalid") {
    return "No Pc value: invalid physics assessment";
  }
  const missing = [];
  if (reasons.has("NO_COVARIANCE")) missing.push("event-matched covariance for both objects");
  if (reasons.has("HBR_UNAVAILABLE")) missing.push("a sourced hard-body radius (HBR)");
  if (reasons.has("INVALID_COVARIANCE")) missing.push("valid positive-definite event-matched covariance");
  if (reasons.has("INVALID_HBR")) missing.push("a valid sourced HBR");
  if (missing.length) {
    return `No Foster Pc: missing ${missing.join(" and ")}.`;
  }
  const codes = [...reasons];
  return `No Foster Pc: ${codes.length ? codes.join(", ") : pc?.reason || "event-matched covariance and HBR were not supplied"}.`;
}

export function hasValidEventFosterPc(event) {
  return isUsablePc(event?.collision_probability) && event.collision_probability.event_id === event.id;
}
