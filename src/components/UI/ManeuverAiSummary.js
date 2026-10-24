import React from "react";

export function ManeuverAiSummary({ result }) {
  const status = result?.status || "unavailable";
  const model = result?.model_name
    ? `${result.model_name}${result.model_version ? ` v${result.model_version}` : ""}`
    : "Unavailable";
  const meaning = result?.score_name
    ? `${result.score_name} (${result.score_units || "units unavailable"}); diagnostic only, not used to rank candidates.`
    : "No model score is available.";
  const evaluation = result?.evaluation_summary;
  return React.createElement("div", { className: "maneuver-ai-summary", "data-status": status },
    React.createElement("span", null, "Maneuver ML status ", React.createElement("strong", null, `${status} · ${result?.reason_code || "MANEUVER_MODEL_RESULT_NOT_RETURNED"}`)),
    React.createElement("span", null, "Maneuver ML model ", React.createElement("strong", null, model)),
    React.createElement("span", null, "Training target ", React.createElement("strong", null, "Synthetic simulator-generated miss distance; not a real maneuver outcome.")),
    React.createElement("span", null, "Candidate ordering ", React.createElement("strong", null, result?.ranking_used ? "Optional surrogate order" : "Not used; physics sweep order is unchanged.")),
    React.createElement("span", null, "Maneuver ML score ", React.createElement("strong", null, `${meaning} This synthetic simulator surrogate is not Pc, safety, or a verified improvement.`)),
    status === "unavailable" ? React.createElement("span", null, "Maneuver ML unavailable reason ", React.createElement("strong", null, result?.reason_code || "MANEUVER_MODEL_RESULT_NOT_RETURNED")) : null,
    status === "research_only" ? React.createElement("span", null, "Research-only qualification ", React.createElement("strong", null, "Held-out ranking did not outperform the minimum-Δv baseline; displayed scores are diagnostics, not candidate recommendations.")) : null,
    evaluation ? React.createElement("span", null, "Held-out ranking evidence ", React.createElement("strong", null, `${evaluation.held_out_scenario_count ?? "unavailable"} scenarios / ${evaluation.held_out_candidate_count ?? "unavailable"} candidates; within-scenario Spearman ${Number.isFinite(evaluation.mean_within_scenario_spearman) ? evaluation.mean_within_scenario_spearman.toFixed(3) : "unavailable"}; top-1 agreement ${Number.isFinite(evaluation.top1_agreement_with_simulator_best) ? `${(evaluation.top1_agreement_with_simulator_best * 100).toFixed(0)}%` : "unavailable"}; model regret ${Number.isFinite(evaluation.model_mean_regret_km) ? `${evaluation.model_mean_regret_km.toFixed(4)} km` : "unavailable"}; minimum-Δv baseline regret ${Number.isFinite(evaluation.minimum_delta_v_baseline_mean_regret_km) ? `${evaluation.minimum_delta_v_baseline_mean_regret_km.toFixed(4)} km` : "unavailable"}.`)) : null,
    result?.provenance?.screening_job_id ? React.createElement("span", null, "Maneuver ML screening job ", React.createElement("strong", null, result.provenance.screening_job_id)) : null,
  );
}

