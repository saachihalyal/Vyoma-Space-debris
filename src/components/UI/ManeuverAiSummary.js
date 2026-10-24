import React from "react";

const fmt = (value) => Number.isFinite(value) ? value.toFixed(4) : "unavailable";

export function ManeuverAiSummary({ result }) {
  const status = result?.status || "unavailable";
  const model = result?.model_name
    ? `${result.model_name}${result.model_version ? ` v${result.model_version}` : ""}`
    : "Unavailable";
  const evaluation = result?.evaluation_summary;
  return React.createElement("div", { className: "maneuver-ai-summary", "data-status": status },
    React.createElement("span", null, "Maneuver ranker status ", React.createElement("strong", null, `${status} · ${result?.reason_code || "MANEUVER_MODEL_RESULT_NOT_RETURNED"}`)),
    React.createElement("span", null, "Model ", React.createElement("strong", null, model)),
    React.createElement("span", null, "Training target ", React.createElement("strong", null, "Physics-generated log10(Pc zero-burn / Pc candidate) from saved real CelesTrak parent events; no observed maneuver outcomes.")),
    React.createElement("span", null, "Candidate ordering ", React.createElement("strong", null, result?.ranking_used ? "AI ranks candidates first; physics recalculates and confirms the candidate outputs." : "Deterministic physics research-Pc ordering is used; AI scores do not control selection.")),
    React.createElement("span", null, "Score meaning ", React.createElement("strong", null, `${result?.score_name || "Unavailable"} (${result?.score_units || "units unavailable"}); a positive log10 ratio predicts lower candidate Pc.`)),
    status === "unavailable" ? React.createElement("span", null, "Fallback ", React.createElement("strong", null, "AI artifact unavailable or invalid; candidates are ranked using calculated physics research Pc.")) : null,
    evaluation ? React.createElement("span", null, "Held-out parent-grouped evidence ", React.createElement("strong", null, `${evaluation.held_out_scenario_count ?? "unavailable"} parents / ${evaluation.held_out_candidate_count ?? "unavailable"} candidates; within-parent Spearman ${fmt(evaluation.mean_within_scenario_spearman)}; top-1 agreement ${Number.isFinite(evaluation.top1_agreement_with_physics_best) ? `${(evaluation.top1_agreement_with_physics_best * 100).toFixed(1)}%` : "unavailable"}; model regret ${fmt(evaluation.model_mean_regret_log10_pc_reduction)} vs baseline ${fmt(evaluation.baseline_mean_regret_log10_pc_reduction)} log10 units.`)) : null,
    result?.provenance?.screening_job_id ? React.createElement("span", null, "Screening job ", React.createElement("strong", null, result.provenance.screening_job_id)) : null,
  );
}
