import React from "react";

const number = (value, digits = 6) => Number.isFinite(value) ? value.toFixed(digits) : "Unavailable";
const vector = (value) => Array.isArray(value) && value.length === 3 ? value.map((x) => number(x, 6)).join(", ") : "Unavailable";
const pc = (value) => Number.isFinite(value) && value < 1e-30 ? "< 1e-30" : Number.isFinite(value) ? value.toExponential(6) : "Unavailable";

function geometryRow(row, label, baseline = false) {
  const fuel = row?.fuel?.status === "estimated"
    ? `${number(row.fuel.propellant_consumption_kg, 8)} kg${row.fuel.assumption_status === "estimated_from_default_assumptions" ? "*" : ""}`
    : "Not calculated";
  return React.createElement("tr", { key: label },
    React.createElement("td", null, label),
    React.createElement("td", null, baseline ? "Zero burn" : `${row?.direction || "Unavailable"} RTN · ${number(row?.delta_v_m_s, 5)} m/s`),
    React.createElement("td", null, row?.maneuver_epoch_utc || "—"),
    React.createElement("td", null, row?.closest_approach_utc || row?.tca_utc || "Unavailable"),
    React.createElement("td", null, number(row?.predicted_miss_distance_km ?? row?.miss_distance_km)),
    React.createElement("td", null, baseline ? "0.000000" : number(row?.change_from_zero_burn_km)),
    React.createElement("td", null, baseline ? "0, 0, 0" : vector(row?.delta_v_rtn_m_s)),
    React.createElement("td", null, row?.relative_velocity_km_s?.map?.((x) => number(x)).join(", ") || "Unavailable"),
    React.createElement("td", null, fuel),
    React.createElement("td", null, pc(row?.research_pc_after?.pc)));
}

export function ManeuverBaselineComparison({ comparison, stage2aReference, zeroBurnBaseline, candidates = [], stage2aPhysics, probabilityBefore, probabilityAfter, probabilityComparison }) {
  const ref = stage2aReference || {};
  const baseline = zeroBurnBaseline?.candidate || zeroBurnBaseline || {};
  const baselineEvaluated = zeroBurnBaseline?.status === "evaluated" && Number.isFinite(zeroBurnBaseline?.miss_distance_km);
  const pcBefore = probabilityBefore?.status === "available"
    ? `${pc(probabilityBefore.pc)} · Vyoma research Pc · zero-burn baseline`
    : `Unavailable · ${probabilityBefore?.reason_code || "research Pc inputs unavailable"}`;
  const pcAfter = probabilityAfter?.status === "available"
    ? `${pc(probabilityAfter.pc)} · Vyoma research Pc · candidate TCA`
    : `Unavailable · ${probabilityAfter?.reason_code || "comparable research Pc unavailable"}`;
  const reduction = probabilityComparison?.status === "available" && Number.isFinite(probabilityComparison?.risk_reduction_pct)
    ? `${probabilityComparison.risk_reduction_pct.toFixed(2)}%`
    : `Unavailable · ${probabilityComparison?.reason_code || "comparable numerical Pc values unavailable"}`;
  const rows = candidates.filter((row) => row?.direction !== "zero-burn baseline");
  const baselineStatus = comparison?.status === "within_comparison_tolerance"
    ? "Within configured diagnostic thresholds; not scientific validation"
    : comparison?.status === "discrepancy"
      ? "Discrepancy against original SGP4 event; interpret simulated candidate geometry cautiously"
      : "SGP4-to-two-body baseline comparison unavailable";
  const comparisonTable = React.createElement("div", { className: "table-scroll" }, React.createElement("table", null,
    React.createElement("thead", null, React.createElement("tr", null, ...["Scenario", "RTN burn", "Burn UTC", "Predicted TCA", "Miss (km)", "Delta miss vs baseline (km)", "RTN delta-v (m/s)", "Relative velocity (km/s)", "Fuel", "Research Pc"].map((heading) => React.createElement("th", { key: heading }, heading)))),
    React.createElement("tbody", null,
      ...(baselineEvaluated ? [geometryRow({ ...baseline, predicted_miss_distance_km: baseline.miss_distance_km ?? baseline.predicted_miss_distance_km, research_pc_after: probabilityBefore }, "Zero-burn baseline", true)] : []),
      ...rows.map((row, index) => geometryRow(row, `Candidate ${index + 1}`)))));
  return React.createElement("section", { className: "panel maneuver-baseline-comparison", "aria-live": "polite" },
    React.createElement("div", { className: "panel-heading" }, React.createElement("h2", null, "Zero-Burn and Candidate Comparison")),
    React.createElement("p", { className: "muted" }, `Selected event Stage 2A SGP4 reference: TCA ${ref.tca?.value || comparison?.reference_tca_utc || "Unavailable"}; miss ${number(ref.miss_distance?.value ?? comparison?.reference_miss_distance_km)} km; relative speed ${stage2aPhysics?.relative_speed_at_tca?.status === "available" ? `${number(stage2aPhysics.relative_speed_at_tca.value)} km/s` : "Unavailable"}.`),
    React.createElement("p", { className: "muted" }, `Zero-burn comparison: ${baselineStatus}.`),
    React.createElement("div", { className: "maneuver-pc-comparison" },
      React.createElement("span", null, "Baseline research Pc", React.createElement("strong", null, pcBefore)),
      React.createElement("span", null, "Candidate research Pc", React.createElement("strong", null, pcAfter)),
      React.createElement("span", null, "Pc reduction", React.createElement("strong", null, reduction)),
      ),
    React.createElement("p", { className: "muted" }, "Before and after use the same declared research covariance/HBR policy assigned at each calculated TCA. Covariance is not propagated from the TLE epoch, and burn-execution error is omitted. This is a consistent research approximation, not an operational Pc estimate. Fuel uses the Tsiolkovsky equation; an asterisk marks results estimated from configurable default mass/Isp assumptions."),
    baselineEvaluated || rows.length ? comparisonTable : React.createElement("p", { className: "muted" }, "Run the bounded search to generate a zero-burn baseline and compare candidate geometry and Pc."));
}
