from __future__ import annotations

import csv
import io
import math
import textwrap
from datetime import datetime, timezone
from typing import Any

from app.ai.evaluation_audit import eligible_legacy_diagnostic_summary


def _geometry_review_band(category: str | None) -> str:
    return {"CRITICAL": "Band 1", "HIGH": "Band 2", "MEDIUM": "Band 3", "LOW": "Band 4", "REVIEW_REQUIRED": "Review required"}.get(category or "", "Unclassified")


def _geometry_review_criteria(criteria: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(criteria, dict):
        return None
    renamed = {"critical_max_fraction": "band_1_max_fraction", "high_max_fraction": "band_2_max_fraction", "medium_max_fraction": "band_3_max_fraction"}
    return {renamed.get(key, key): value for key, value in criteria.items()}


def mission_report_pdf(
    summary: dict[str, Any],
    events: list[dict[str, Any]],
    analytics: dict[str, Any],
    *,
    physics_events: list[dict[str, Any]] | None = None,
    screening_summary: dict[str, Any] | None = None,
) -> bytes:
    physics_events = physics_events or []
    screening_summary = screening_summary or {}
    completion_status = screening_summary.get("completion_status", "unavailable")
    screening_status = screening_summary.get("status", "unavailable")
    if completion_status == "complete" and screening_status == "valid":
        physical_result_summary = (
            f"Screening completed successfully; {len(physics_events):,} qualifying physical close approaches returned."
        )
    elif completion_status == "partial":
        physical_result_summary = "Screening completed partially; returned events may be incomplete. See screening status and limits."
    elif completion_status == "failed" or screening_status == "unavailable":
        physical_result_summary = "Physical screening failed or was unavailable; no conclusion about close approaches can be drawn."
    else:
        physical_result_summary = "Physical screening status is unavailable; no conclusion about close approaches can be drawn."
    lines = [
        "Vyoma SSA Research Prototype",
        "Hybrid Data and Trajectory Screening Report",
        "",
        f"Generated UTC: {datetime.now(timezone.utc).isoformat()}",
        "Screening scope: fresh run for this report, not the Collision Analysis page's earlier completed job",
        f"Dataset source: {summary.get('source', 'TLE catalog')}",
        f"Source status: {(summary.get('source_summary') or {}).get('status', 'unavailable')}",
        f"Objects tracked: {analytics.get('total_objects', 0):,}",
        f"Unavailable propagation records: {analytics.get('unavailable_objects', 0):,}",
        f"Active satellites: {analytics.get('active_satellites', 0):,}",
        f"Tracked debris: {analytics.get('debris_objects', 0):,}",
        f"Screening proxy pairs: {analytics.get('total_screening_proxy_pairs', 0):,}",
        f"Mean heuristic risk score: {analytics.get('mean_heuristic_risk_score', 'unavailable')}",
        f"Stage 2A trajectory screening status: {screening_summary.get('status', 'unavailable')}",
        f"Stage 2A completion status: {completion_status}",
        f"Trajectory assessments returned: {len(physics_events):,}",
        f"Candidate pairs / minima / refined minima: {screening_summary.get('candidate_pair_count', 'unavailable')} / {screening_summary.get('candidate_local_minimum_count', 'unavailable')} / {screening_summary.get('refinement_count', 'unavailable')}",
        f"Screening horizon: {screening_summary.get('screening_horizon_start', 'unavailable')} to {screening_summary.get('screening_horizon_end', 'unavailable')}",
        f"Screening threshold: {screening_summary.get('screening_threshold_km', 'unavailable')} km",
        "Live covariance and HBR: unavailable for TLE-only inputs; live Pc is not calculated",
        f"ML model status: {summary.get('ml_status', 'unavailable')}",
        "",
        "Prototype Briefing",
        summary.get("briefing", "No briefing available."),
        "",
        "Top Heuristic Screening Proxy Pairs (not physical conjunctions)",
    ]
    for event in events[:10]:
        lines.extend(
            [
                "",
                f"{event['id']} | Heuristic priority {event['priority_score']}/100 | {event['risk_level']}",
                f"Primary: {event['primary']['name']} ({event['primary']['band']})",
                f"Secondary: {event['secondary']['name']} ({event['secondary']['band']})",
                f"Heuristic risk score: {event['risk_score']:.4f}",
                f"Screening method: {event['provenance']['method']} v{event['provenance']['method_version']}",
                "TCA, miss distance, covariance, hard-body radius, and Pc: unavailable",
                "ML model: unavailable",
                f"Suggested action: {event['suggested_action']}",
            ]
        )
    lines.extend(["", "Trajectory-derived close approaches"])
    lines.append(physical_result_summary)
    for event in physics_events[:20]:
        physics = event.get("physics_result") or {}
        pc_result = event.get("collision_probability") or {}
        tca = physics.get("tca", {}).get("value") or "unavailable"
        miss = physics.get("miss_distance", {}).get("value")
        rel_speed = physics.get("relative_speed_at_tca", {}).get("value")
        pc_value = _available_pc_value(pc_result)
        hbr_value = pc_result.get("hbr_km")
        pc_reasons = ", ".join(pc_result.get("reason_codes", [])) or "none"
        covariance_sources = pc_result.get("covariance_sources", [])
        ml_result = event.get("ml_result") or {}
        ml_prediction = ml_result.get("prediction") or {}
        ml_provenance = ml_result.get("provenance") or {}
        ml_event_matches = ml_provenance.get("source_physics_event_id") == event.get("id")
        ml_compatibility_verified = ml_provenance.get("live_feature_semantics_compatibility") == "verified"
        ml_associated = ml_event_matches and ml_compatibility_verified
        anomaly = event.get("anomaly_result") or {}
        anomaly_provenance = anomaly.get("provenance") or {}
        anomaly_associated = anomaly_provenance.get("source_physics_event_id") == event.get("id")
        lines.extend(
            [
                "",
                f"{event.get('id')} | Status {physics.get('status', 'unavailable')}",
                f"Primary: {event.get('primary', {}).get('name', 'unavailable')} ({event.get('primary', {}).get('id', 'unavailable')})",
                f"Secondary: {event.get('secondary', {}).get('name', 'unavailable')} ({event.get('secondary', {}).get('id', 'unavailable')})",
                f"TCA UTC: {tca}",
                f"Miss distance km: {miss if miss is not None else 'unavailable'}",
                f"Relative speed km/s: {rel_speed if rel_speed is not None else 'unavailable'}",
                f"Method: {(physics.get('provenance') or {}).get('method', 'unavailable')} v{(physics.get('provenance') or {}).get('method_version', 'unavailable')}",
                f"Collision probability: {pc_value if pc_value is not None else 'unavailable'} | status {pc_result.get('status', 'unavailable')} | method {pc_result.get('method', 'unavailable')} v{pc_result.get('method_version', 'unavailable')}",
                f"HBR km: {hbr_value if hbr_value is not None else 'unavailable'} | source {pc_result.get('hbr_source', 'unavailable')}",
                f"Covariance status/source: {pc_result.get('covariance_status', 'unavailable')} | {_csv_value(covariance_sources) or 'unavailable'}",
                f"Pc applicability/reasons: {pc_result.get('applicability_status', 'not_assessed')} | {pc_reasons}",
                f"Independence assumption authorized: {pc_result.get('independence_assumption_authorized', 'not recorded')}",
                f"Pc assumptions: {_csv_value(pc_result.get('assumptions')) or 'unavailable'}",
                f"Pc warnings: {_csv_value(pc_result.get('warnings')) or 'none'}",
                "ESA event-risk estimate: not calibrated probability or Foster Pc",
                f"ESA inference status: {ml_result.get('status', 'unavailable') if ml_associated or (ml_event_matches and ml_result.get('status') != 'available') else 'unavailable'}",
                f"ESA unavailable reason: {ml_result.get('reason_code', 'ML_RESULT_NOT_RETURNED') if ml_associated or (ml_event_matches and ml_result.get('status') != 'available') else 'ML_EVENT_ID_MISMATCH' if not ml_event_matches else 'ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED'}",
                f"Exponentiated ESA-scale estimate: {ml_prediction.get('predicted_risk_estimate', 'unavailable') if ml_associated and ml_result.get('status') == 'available' else 'unavailable'}",
                "Orbital anomaly assessment (historical feature unusualness; not collision risk)",
                f"Status: {anomaly.get('status', 'unavailable') if anomaly_associated else 'unavailable'} | reason: {anomaly.get('reason_code', 'ANOMALY_RESULT_NOT_RETURNED') if anomaly_associated else 'ANOMALY_EVENT_ID_MISMATCH'}",
                f"Anomaly score: {anomaly.get('anomaly_score', 'unavailable') if anomaly_associated and anomaly.get('status') == 'available' else 'unavailable'} | classification: {anomaly.get('classification', 'unavailable') if anomaly_associated and anomaly.get('status') == 'available' else 'unavailable'} | definition: {anomaly.get('score_definition', 'unavailable')}",
                f"Anomaly provenance: {_csv_value(anomaly_provenance) or 'unavailable'}",
                "Maneuver effects: unavailable",
            ]
        )
    return simple_pdf([wrapped for line in lines for wrapped in _wrap_report_line(line, 56)], footer="Vyoma SSA | Research Prototype | Not for operational decisions")


def event_report_pdf(event: dict[str, Any], maneuver: dict[str, Any] | None = None, screening_summary: dict[str, Any] | None = None, evaluation_metadata: dict[str, Any] | None = None) -> bytes:
    screening_summary = screening_summary or {}
    if event.get("result_kind") == "physics_assessment":
        return _trajectory_event_report_pdf(event, maneuver, screening_summary, evaluation_metadata)
    lines = [
        "Screening Proxy Event Report",
        f"Internal event key: {event['id']}",
        f"Generated UTC: {datetime.now(timezone.utc).isoformat()}",
        f"Identity type: {event.get('event_identity_type', 'internal_deterministic')}",
        "",
        "Objects",
        f"Primary: {event['primary']['name']} | {event['primary'].get('object_type', 'UNKNOWN')} | {event['primary']['band']} | {event['primary']['altitude_km']} km",
        f"Secondary: {event['secondary']['name']} | {event['secondary'].get('object_type', 'UNKNOWN')} | {event['secondary']['band']} | {event['secondary']['altitude_km']} km",
        f"Classification sources: primary {event['primary'].get('classification_source', 'unavailable')} | secondary {event['secondary'].get('classification_source', 'unavailable')}",
        "",
        "Heuristic screening only",
        f"Heuristic risk score: {event['risk_score']:.4f}",
        f"Heuristic priority score: {event['priority_score']}/100",
        f"Risk class: {event['risk_level']}",
        f"Source type: {event['provenance']['source_type']}",
        f"Method: {event['provenance']['method']} v{event['provenance']['method_version']}",
        f"Input hash: {event['provenance'].get('input_hash') or 'unavailable'}",
        f"Synthetic input: {event['provenance'].get('is_synthetic', False)}",
        f"Fallback input: {event['provenance'].get('is_fallback', False)}",
        "",
        "Physics assessment",
        f"Status: {event['physics_result']['status']}",
        f"Reason codes: {', '.join(event['physics_result']['reason_codes'])}",
        "TCA, miss distance, covariance, hard-body radius, and Pc: unavailable",
        "",
        "ML result",
        f"Status: {event['ml_result']['status']}",
        f"Reason: {event['ml_result']['reason_code']}",
        "Comparison: unavailable; agreement is not a validation claim.",
        "",
        "Recommended review action",
        event["suggested_action"],
    ]
    if maneuver:
        lines.extend(
            [
                "",
                "Maneuver assessment",
                f"Status: {maneuver.get('status', 'unavailable')}",
                f"Reason: {maneuver.get('reason', 'No validated maneuver result available.')}",
            ]
        )
    return simple_pdf([wrapped for line in lines for wrapped in _wrap_report_line(line, 56)], footer="Vyoma SSA | Research Prototype | Not for operational decisions")


def event_report_payload(event: dict[str, Any], maneuver: dict[str, Any] | None = None, *, screening_job_id: str | None = None) -> dict[str, Any]:
    """Build one provenance-preserving report object for screen, JSON, and CSV."""
    physics = event.get("physics_result") or {}
    collision = event.get("collision_probability") or {}
    research = event.get("automatic_research_pc_assessment") or {}
    collision_ai = event.get("collision_ai_assessment") or {}
    research_pc = research.get("estimated_pc")
    research_percentage = research.get("percentage")
    physics_covariance = physics.get("covariance") or {}
    research_sigma = {
        "minimum_km": research.get("encounter_plane_sigma_min_km"),
        "maximum_km": research.get("encounter_plane_sigma_max_km"),
    }
    pc_channels = {
        "source_reported_pc": collision.get("source_reported_pc") if collision.get("source_reported_event_id") == event.get("id") else None,
        "source_reported_pc_event_id": collision.get("source_reported_event_id"),
        "source_reported_pc_method": collision.get("source_reported_pc_method"),
        "event_specific_foster_pc": collision.get("pc") if collision.get("status") == "available" and collision.get("event_id") == event.get("id") else None,
        "event_specific_foster_status": collision.get("status", "unavailable") if collision.get("event_id") == event.get("id") else "unavailable",
        "research_pc": research_pc,
        "research_pc_scientific": research.get("estimated_pc_scientific"),
        "research_pc_percentage": research_percentage,
        "research_pc_percentage_scientific": research.get("percentage_scientific"),
    }
    risk = (research.get("risk_assessment") or collision.get("risk_assessment") or {})
    maneuver = maneuver or {}
    candidates = maneuver.get("physics_candidates", {}).get("candidates") if isinstance(maneuver.get("physics_candidates"), dict) else maneuver.get("candidates")
    return {
        "report_type": "orion_selected_conjunction_report",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "screening_job_id": screening_job_id or event.get("screening_job_id"),
        "event_identity": {"event_id": event.get("id"), "primary": event.get("primary"), "secondary": event.get("secondary"), "pair_type": event.get("pair_type")},
        "trajectory": {
            "status": physics.get("status"), "tca_utc": (physics.get("tca") or {}).get("value"),
            "miss_distance_km": (physics.get("miss_distance") or {}).get("value"),
            "relative_position_at_tca_km": (physics.get("relative_position_at_tca") or {}).get("value"),
            "relative_velocity_at_tca_km_s": (physics.get("relative_velocity_at_tca") or {}).get("value"),
            "relative_speed_at_tca_km_s": (physics.get("relative_speed_at_tca") or {}).get("value"),
            "state_information": physics.get("state_information"),
        },
        "pc_channels": pc_channels,
        "risk_assessment": {"risk_score": risk.get("risk_score"), "physics_risk_class": risk.get("physics_risk_class"), "final_risk_class": risk.get("final_risk_class"), "classification_basis": risk.get("classification_basis"), "policy_name": risk.get("risk_score_policy_name"), "policy_version": risk.get("risk_score_policy_version")},
        "covariance": {
            "status": collision.get("covariance_status") or physics_covariance.get("status") or ("assumed_research_model" if research.get("covariance_method") else None),
            "frame": collision.get("covariance_frame") or research.get("covariance_frame") or physics_covariance.get("frame"),
            "epoch_utc": collision.get("covariance_epoch") or research.get("covariance_epoch_utc") or physics_covariance.get("epoch"),
            "sources": collision.get("covariance_sources") or research.get("covariance_method"),
            "policy": research.get("covariance_policy_name") or research.get("covariance_policy_id"),
            "sigmas_encounter_plane_km": research_sigma,
            "assumptions": collision.get("assumptions") or research.get("assumptions"),
        },
        "hard_body_radius": {
            "value_km": collision.get("hbr_km") if collision.get("hbr_km") is not None else research.get("hbr_km") if research.get("hbr_km") is not None else (physics.get("hard_body_radius") or {}).get("value"),
            "source": collision.get("hbr_source") or research.get("hbr_source"),
            "provenance": collision.get("hbr_provenance") or research.get("hbr_provenance"),
        },
        "ai": {"status": collision_ai.get("status", "unavailable"), "inference_provenance": collision_ai.get("inference_provenance"), "pc_surrogate": collision_ai.get("pc_surrogate"), "risk_classifier": collision_ai.get("risk_classifier"), "queue_priority": event.get("ai_risk_assessment")},
        "methods": {"trajectory": (physics.get("provenance") or {}).get("method"), "trajectory_version": (physics.get("provenance") or {}).get("method_version"), "foster": collision.get("method"), "foster_version": collision.get("method_version"), "research_pc": research.get("method_name"), "research_pc_version": research.get("method_version")},
        "provenance": event.get("provenance"),
        "assumptions": {"research_pc": research.get("assumptions"), "foster": collision.get("assumptions"), "covariance": collision.get("covariance_sources"), "hbr": collision.get("hbr_provenance")},
        "sensitivity": {"status": research.get("sensitivity_status"), "lower_pc_scientific": research.get("lower_sensitivity_pc_scientific"), "upper_pc_scientific": research.get("upper_sensitivity_pc_scientific"), "reason": research.get("sensitivity_reason")},
        "limitations": research.get("limitations") or collision.get("limitations") or [],
        "maneuver": {"status": maneuver.get("status", "not_run"), "event_id": maneuver.get("event_id"), "screening_job_id": maneuver.get("screening_job_id") or screening_job_id, "method": maneuver.get("method"), "probability_before": maneuver.get("probability_before"), "probability_after": maneuver.get("probability_after"), "probability_comparison": maneuver.get("probability_comparison"), "fuel": maneuver.get("fuel"), "assumptions": maneuver.get("assumptions"), "limitations": maneuver.get("limitations"), "baseline": maneuver.get("zero_burn_baseline"), "candidates": candidates or [], "ai_ranker": maneuver.get("ml_result"), "physics_rank_confirmation": maneuver.get("best_candidate")},
        "event_record": event,
    }


def event_report_csv(payload: dict[str, Any]) -> str:
    """Serialize collision channels and optional maneuver candidates as explicit rows."""
    event = payload.get("event_identity") or {}
    trajectory = payload.get("trajectory") or {}
    pc = payload.get("pc_channels") or {}
    risk = payload.get("risk_assessment") or {}
    covariance = payload.get("covariance") or {}
    hbr = payload.get("hard_body_radius") or {}
    ai = payload.get("ai") or {}
    maneuver = payload.get("maneuver") or {}
    headers = ["record_type", "generated_at_utc", "screening_job_id", "event_id", "primary_name", "primary_id", "primary_type", "secondary_name", "secondary_id", "secondary_type", "pair_type", "tca_utc", "miss_distance_km", "relative_velocity_at_tca_km_s", "relative_speed_at_tca_km_s", "source_reported_pc", "source_reported_pc_method", "event_specific_foster_pc", "event_specific_foster_status", "research_pc", "research_pc_scientific", "research_pc_percentage", "risk_score", "physics_risk_class", "final_risk_class", "classification_basis", "covariance_status", "covariance_policy", "encounter_sigma_min_km", "encounter_sigma_max_km", "covariance_frame", "covariance_epoch_utc", "covariance_sources", "hbr_km", "hbr_source", "hbr_provenance", "ai_status", "ai_pc_prediction", "ai_risk_class", "method_provenance", "assumptions", "limitations", "maneuver_status", "candidate_burn_epoch_utc", "candidate_lead_seconds", "candidate_delta_v_rtn_m_s", "candidate_delta_v_m_s", "tca_before_utc", "tca_after_utc", "miss_distance_before_km", "miss_distance_after_km", "relative_velocity_before_km_s", "relative_velocity_after_km_s", "pc_before_scientific", "pc_after_scientific", "absolute_pc_reduction_scientific", "percentage_pc_reduction", "fuel_mass_kg", "initial_mass_kg", "specific_impulse_s", "fuel_assumption_status", "ai_rank", "physics_research_pc_rank"]
    primary, secondary = event.get("primary") or {}, event.get("secondary") or {}
    sigmas = covariance.get("sigmas_encounter_plane_km") or {}
    collision_row = {"record_type": "collision_event", "generated_at_utc": payload.get("generated_at_utc"), "screening_job_id": payload.get("screening_job_id"), "event_id": event.get("event_id"), "primary_name": primary.get("name"), "primary_id": primary.get("id"), "primary_type": primary.get("object_type"), "secondary_name": secondary.get("name"), "secondary_id": secondary.get("id"), "secondary_type": secondary.get("object_type"), "pair_type": event.get("pair_type"), "tca_utc": trajectory.get("tca_utc"), "miss_distance_km": trajectory.get("miss_distance_km"), "relative_velocity_at_tca_km_s": _csv_value(trajectory.get("relative_velocity_at_tca_km_s")), "relative_speed_at_tca_km_s": trajectory.get("relative_speed_at_tca_km_s"), "source_reported_pc": pc.get("source_reported_pc"), "source_reported_pc_method": pc.get("source_reported_pc_method"), "event_specific_foster_pc": pc.get("event_specific_foster_pc"), "event_specific_foster_status": pc.get("event_specific_foster_status"), "research_pc": pc.get("research_pc"), "research_pc_scientific": pc.get("research_pc_scientific"), "research_pc_percentage": pc.get("research_pc_percentage"), "risk_score": risk.get("risk_score"), "physics_risk_class": risk.get("physics_risk_class"), "final_risk_class": risk.get("final_risk_class"), "classification_basis": risk.get("classification_basis"), "covariance_status": covariance.get("status"), "covariance_policy": covariance.get("policy"), "encounter_sigma_min_km": sigmas.get("minimum_km"), "encounter_sigma_max_km": sigmas.get("maximum_km"), "covariance_frame": covariance.get("frame"), "covariance_epoch_utc": covariance.get("epoch_utc"), "covariance_sources": _csv_value(covariance.get("sources")), "hbr_km": hbr.get("value_km"), "hbr_source": hbr.get("source"), "hbr_provenance": _csv_value(hbr.get("provenance")), "ai_status": ai.get("status"), "ai_pc_prediction": (ai.get("pc_surrogate") or {}).get("ai_predicted_log10_pc"), "ai_risk_class": (ai.get("risk_classifier") or {}).get("ai_risk_class"), "method_provenance": _csv_value(payload.get("methods")) + " | " + _csv_value(payload.get("provenance")), "assumptions": _csv_value(payload.get("assumptions")), "limitations": _csv_value(payload.get("limitations")), "maneuver_status": maneuver.get("status")}
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")
    writer.writeheader(); writer.writerow(collision_row)
    before, after = maneuver.get("probability_before") or {}, maneuver.get("probability_after") or {}
    baseline = maneuver.get("baseline") or {}
    baseline_candidate = baseline.get("candidate") or {}
    for candidate in maneuver.get("candidates") or []:
        fuel = candidate.get("fuel") or {}
        row = dict(collision_row, record_type="maneuver_candidate", candidate_burn_epoch_utc=candidate.get("maneuver_epoch_utc"), candidate_lead_seconds=candidate.get("lead_time_seconds"), candidate_delta_v_rtn_m_s=_csv_value(candidate.get("delta_v_rtn_m_s")), candidate_delta_v_m_s=candidate.get("delta_v_m_s"), tca_before_utc=baseline_candidate.get("closest_approach_utc") or baseline.get("tca_utc"), tca_after_utc=candidate.get("closest_approach_utc"), miss_distance_before_km=baseline.get("miss_distance_km"), miss_distance_after_km=candidate.get("predicted_miss_distance_km"), relative_velocity_before_km_s=_csv_value(baseline_candidate.get("relative_velocity_km_s")), relative_velocity_after_km_s=_csv_value(candidate.get("relative_velocity_km_s")), pc_before_scientific=before.get("pc_scientific"), pc_after_scientific=(candidate.get("research_pc_after") or {}).get("pc_scientific"), absolute_pc_reduction_scientific=candidate.get("absolute_research_pc_reduction_scientific"), percentage_pc_reduction=candidate.get("percentage_research_pc_reduction"), fuel_mass_kg=fuel.get("propellant_consumption_kg"), initial_mass_kg=fuel.get("initial_mass_kg"), specific_impulse_s=fuel.get("specific_impulse_s"), fuel_assumption_status=fuel.get("assumption_status"), ai_rank=candidate.get("maneuver_ml_rank"), physics_research_pc_rank=candidate.get("physics_research_pc_rank"))
        writer.writerow(row)
    return buffer.getvalue()


def reference_maneuver_report_pdf(result: dict[str, Any]) -> bytes:
    """Render the standalone CDM maneuver experiment without implying live-job identity."""
    maneuver = result.get("maneuver") or {}
    before = result.get("original_reference_geometry") or {}
    baseline = result.get("zero_burn_two_body_baseline") or {}
    candidate = result.get("candidate_two_body_geometry") or {}
    pc_before = result.get("probability_before") or {}
    pc_after = result.get("probability_after") or {}
    covariance = result.get("covariance") or {}
    hbr = result.get("hard_body_radius") or {}
    lines = [
        "Standalone Reference CDM Maneuver Assessment",
        f"Event ID: {result.get('event_id', 'unavailable')}",
        f"Source: {result.get('source', 'unavailable')}",
        f"Input SHA-256: {result.get('source_input_sha256', 'unavailable')}",
        f"CDM message ID: {result.get('message_id', 'unavailable')}",
        f"Frame: {result.get('reference_frame', 'unavailable')} | position km | velocity km/s",
        f"Reference TCA UTC: {result.get('tca_utc', 'unavailable')}",
        f"Covariance: {covariance.get('status', 'unavailable')} | {covariance.get('frame', 'unavailable')} | {covariance.get('epoch_utc', 'unavailable')} | {covariance.get('units', 'unavailable')}",
        f"Covariance correlation: {covariance.get('cross_covariance', 'unavailable')}",
        f"Combined HBR: {hbr.get('value', 'unavailable')} {hbr.get('units', '')} | {hbr.get('source_type', 'unavailable')} | {hbr.get('description', 'unavailable')}",
        "",
        "Requested impulse",
        "AI ranking not used: this standalone CDM report evaluates one specified impulse, not a candidate-ranking search.",
        f"Object ID: {maneuver.get('object_id', 'unavailable')}",
        f"Burn UTC: {maneuver.get('burn_time_utc', 'unavailable')} | RTN direction: {maneuver.get('direction', 'unavailable')}",
        f"Delta-v: {maneuver.get('delta_v_m_s', 'unavailable')} m/s",
        "",
        "Geometry",
        f"CDM-reported miss distance: {before.get('miss_distance_km', 'unavailable')} km at supplied TCA",
        f"Zero-burn two-body baseline: {baseline.get('miss_distance_km', 'unavailable')} km at {baseline.get('tca_utc', 'unavailable')} | relative speed {baseline.get('relative_velocity_km_s', 'unavailable')} km/s",
        f"Candidate two-body geometry: {candidate.get('miss_distance_km', 'unavailable')} km at {candidate.get('tca_utc', 'unavailable')} | relative speed {candidate.get('relative_velocity_km_s', 'unavailable')} km/s",
        f"Candidate minus zero-burn baseline: {candidate.get('change_from_zero_burn_baseline_km', 'unavailable')} km",
        f"Geometric miss-distance percentage change: {candidate.get('change_from_zero_burn_baseline_percent', 'unavailable')}% | {candidate.get('percentage_change_status', 'unavailable')} | positive means increased miss distance",
        "",
        "Collision probability",
        f"Before Pc (zero-burn two-body): {pc_before.get('pc', 'unavailable')} | status {pc_before.get('status', 'unavailable')}",
        f"After Pc (maneuver candidate): {pc_after.get('pc') if pc_after.get('pc') is not None else 'unavailable'} | status {pc_after.get('status', 'unavailable')}",
        f"Pc reduction: {result.get('probability_change', {}).get('percentage_reduction', 'unavailable')}% | {result.get('probability_change', {}).get('status', 'unavailable')} | shared CDM covariance held fixed; not dynamically propagated",
        "",
        "Assumptions and limitations",
        *[f"- {item}" for item in result.get("assumptions", [])],
        *[f"- {item}" for item in result.get("limitations", [])],
    ]
    return simple_pdf([part for line in lines for part in _wrap_report_line(line, 56)], footer="Vyoma SSA | Research Prototype | Not for operational decisions")


def reference_cdm_report_pdf(result: dict[str, Any]) -> bytes:
    """Render the values from an isolated, source-supplied reference CDM Pc assessment."""
    probability = result.get("collision_probability") or {}
    if hasattr(probability, "model_dump"):
        probability = probability.model_dump(mode="json")
    first = result.get("object_1") or {}
    second = result.get("object_2") or {}
    lines = [
        "Standalone Reference CDM Collision Assessment",
        f"Event ID: {result.get('event_id', '')}",
        f"Source: {result.get('source_label') or 'Bundled public NASA CARA reference CDM'}",
        f"Input SHA-256: {result.get('input_sha256', '')}",
        f"CDM message ID: {result.get('message_id', '')}",
        f"Frame: {result.get('reference_frame', '')}",
        f"TCA UTC: {result.get('tca_utc', '')}",
        "",
        "Objects",
        f"Primary: {first.get('name', '')} | ID {first.get('id', '')}",
        f"Secondary: {second.get('name', '')} | ID {second.get('id', '')}",
        f"Source-reported miss distance: {result.get('source_reported_miss_distance_km', '')} km",
        f"Source-reported Pc: {result.get('source_reported_pc', '')} | method {result.get('source_reported_pc_method', '')}",
        "",
        "Foster 2D result",
        f"Collision probability: {probability.get('pc', '')}",
        f"Method: {probability.get('method', '')} {probability.get('method_version', '')}",
        f"Status: {probability.get('status', '')}",
        f"Hard-body radius: {probability.get('hbr_km', '')} km | source {probability.get('hbr_source', '')}",
        f"Covariance: {probability.get('covariance_status', '')} | frame {probability.get('covariance_frame', '')} | epoch {probability.get('covariance_epoch', '')}",
        "",
        "Scope",
        "This is a standalone historical/reference CDM assessment. It uses the states and covariance supplied in the CDM at its declared TCA and is not a live catalog screening result.",
        "The source and declared originator were not independently authenticated.",
        *[f"Assumption: {item}" for item in probability.get("assumptions", [])],
    ]
    lines = [line for line in lines if not line.endswith(": ")]
    return simple_pdf([part for line in lines for part in _wrap_report_line(line, 56)], footer="Vyoma SSA | Research Prototype | Not for operational decisions")


def conjunctions_csv(events: list[dict[str, Any]], *, export_metadata: dict[str, Any] | None = None) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    headers = [
            "event_id",
            "event_identity_type",
            "result_kind",
            "object_primary_id",
            "object_secondary_id",
            "object_primary_type",
            "object_secondary_type",
            "object_primary_source_classification",
            "object_secondary_source_classification",
            "screening_horizon_start",
            "screening_horizon_end",
            "screening_threshold_km",
            "tca_status",
            "tca_utc",
            "miss_distance_km",
            "relative_position_at_tca_km",
            "relative_velocity_at_tca_km_s",
            "relative_speed_at_tca_km_s",
            "frame",
            "method",
            "method_version",
            "convergence",
            "physics_status",
            "physics_reason_codes",
            "covariance_status",
            "probability_of_collision_status",
            "pc_status",
            "pc",
            "pc_method",
            "pc_method_version",
            "pc_applicability_status",
            "hbr_km",
            "hbr_source",
            "hbr_provenance",
            "covariance_input_status",
            "covariance_sources",
            "covariance_frame",
            "covariance_epoch",
            "pc_assumptions",
            "pc_warnings",
            "pc_reason_codes",
            "pc_provenance",
            "source_type",
            "input_hash",
            "is_synthetic",
            "is_fallback",
            "ml_status",
            "ml_model_name",
            "ml_model_version",
            "ml_predicted_log10_risk",
            # Legacy headers retained for CSV-client compatibility; canonical
            # event-risk and threshold-flag headers are appended below.
            "ml_predicted_risk_probability_deprecated_alias_not_calibrated",
            "ml_high_risk_deprecated_alias_unvalidated",
            "ml_feature_availability",
            "ml_features_imputed",
            "ml_provenance",
            "comparison_status",
            "comparison_reason_code",
            "primary",
            "secondary",
            "heuristic_risk_score",
            "risk_level",
            "priority_score",
            "suggested_action",
            "tle_source_records",
            "ml_exponentiated_esa_event_risk_estimate",
            "ml_threshold_flag_at_log10_minus_6",
            "ml_reason_code",
            "anomaly_status",
            "anomaly_score",
            "anomaly_classification",
            "anomaly_score_definition",
            "anomaly_reason_code",
            "anomaly_provenance",
            "pc_independence_assumption_authorized",
            "scenario_pc_status",
            "scenario_pc",
            "scenario_pc_method",
            "scenario_pc_method_version",
            "scenario_pc_applicability_status",
            "scenario_hbr_km",
            "scenario_hbr_units",
            "scenario_hbr_source",
            "scenario_hbr_provenance",
            "scenario_covariance_status",
            "scenario_covariance_frame",
            "scenario_covariance_epoch",
            "scenario_covariance_sources",
            "scenario_pc_independence_assumption_authorized",
            "scenario_pc_assumptions",
            "scenario_assumptions",
            "scenario_pc_reason_codes",
            "scenario_pc_warnings",
            "scenario_pc_provenance",
            "scenario_is_synthetic",
            "review_priority_category",
            "review_priority_status",
            "review_priority_policy_version",
            "review_priority_criteria",
            "review_priority_explanation",
            "research_pc_status",
            "research_pc_scientific",
            "research_log10_pc_exact",
            "research_covariance_policy",
            "research_encounter_sigma_min_km",
            "research_encounter_sigma_max_km",
            "research_covariance_frame",
            "research_covariance_epoch_utc",
            "research_hbr_km",
            "research_hbr_source",
            "research_hbr_provenance",
            "research_covariance_method",
            "research_sensitivity_lower_pc",
            "research_sensitivity_upper_pc",
            "research_sensitivity_reason",
            "research_pc_reason_codes",
            "research_pc_assumptions",
        ]
    metadata_fields = [
        "record_type",
        "export_scope",
        "screening_status",
        "screening_completion_status",
        "screening_result_status",
        "catalog_source",
        "catalog_object_count",
        "candidate_pair_count",
        "candidate_minimum_count",
        "refinement_count",
        "close_approach_count",
        "screening_horizon_start_utc",
        "screening_horizon_end_utc",
        "export_screening_threshold_km",
        "screening_job_id",
        "event_record_count",
        "invalid_assessment_count",
    ]
    if export_metadata is not None:
        headers.extend(metadata_fields)
    writer.writerow(headers)
    if export_metadata is not None:
        # This is a typed metadata record, not an event row. Event columns remain blank.
        writer.writerow([""] * (len(headers) - len(metadata_fields)) + [
            "export_metadata",
            export_metadata.get("export_scope", "fresh_stage_2a_run_for_this_report; not a previously completed Collision Analysis job"),
            export_metadata.get("screening_status", "unavailable"),
            export_metadata.get("screening_completion_status", "unavailable"),
            export_metadata.get("screening_result_status", "unavailable"),
            export_metadata.get("catalog_source", "unavailable"),
            export_metadata.get("catalog_object_count"),
            export_metadata.get("candidate_pair_count"),
            export_metadata.get("candidate_minimum_count"),
            export_metadata.get("refinement_count"),
            export_metadata.get("close_approach_count"),
            export_metadata.get("screening_horizon_start_utc"),
            export_metadata.get("screening_horizon_end_utc"),
            export_metadata.get("screening_threshold_km"),
            export_metadata.get("screening_job_id"),
            export_metadata.get("event_record_count"),
            export_metadata.get("invalid_assessment_count"),
        ])
    for event in events:
        physics = event.get("physics_result", {})
        provenance = physics.get("provenance") or event.get("provenance") or {}
        tca_field = physics.get("tca") or {}
        miss_field = physics.get("miss_distance") or {}
        relative_position = physics.get("relative_position_at_tca") or {}
        relative_velocity = physics.get("relative_velocity_at_tca") or {}
        relative_speed = physics.get("relative_speed_at_tca") or {}
        is_physics = event.get("result_kind") == "physics_assessment"
        pc_result = event.get("collision_probability") or {}
        scenario_result = event.get("scenario_collision_probability") or {}
        review_priority = event.get("review_priority") or {}
        scenario_hbr_provenance = scenario_result.get("hbr_provenance") or {}
        ml_result = event.get("ml_result") or {}
        ml_prediction = ml_result.get("prediction") or {}
        ml_provenance = ml_result.get("provenance") or {}
        ml_event_matches = ml_provenance.get("source_physics_event_id") == event.get("id")
        ml_compatibility_verified = ml_provenance.get("live_feature_semantics_compatibility") == "verified"
        ml_associated = ml_event_matches and ml_compatibility_verified
        ml_prediction_available = ml_associated and ml_result.get("status") == "available"
        anomaly = event.get("anomaly_result") or {}
        anomaly_provenance = anomaly.get("provenance") or {}
        anomaly_associated = anomaly_provenance.get("source_physics_event_id") == event.get("id")
        comparison = event.get("comparison_result") or {}
        row = [
                event["id"],
                event.get("event_identity_type", "trajectory_event_deterministic" if is_physics else "internal_deterministic"),
                "physics_assessment" if is_physics else "screening_proxy",
                physics.get("object_primary_id"),
                physics.get("object_secondary_id"),
                event.get("primary", {}).get("object_type", "UNKNOWN"),
                event.get("secondary", {}).get("object_type", "UNKNOWN"),
                event.get("primary", {}).get("source_classification"),
                event.get("secondary", {}).get("source_classification"),
                physics.get("screening_horizon_start"),
                physics.get("screening_horizon_end"),
                physics.get("screening_threshold_km"),
                physics.get("tca_status", physics.get("status")) if is_physics else None,
                tca_field.get("value"),
                miss_field.get("value"),
                _csv_value(relative_position.get("value")),
                _csv_value(relative_velocity.get("value")),
                relative_speed.get("value"),
                (physics.get("state_information") or {}).get("source_frame") if is_physics else None,
                provenance.get("method"),
                provenance.get("method_version"),
                _csv_value(physics.get("convergence")),
                physics.get("status", "unavailable"),
                ";".join(physics.get("reason_codes", [])),
                (physics.get("covariance") or {}).get("status", "unavailable"),
                (physics.get("probability_of_collision") or {}).get("status", "unavailable"),
                pc_result.get("status", "unavailable" if is_physics else "proxy_only"),
                _available_pc_value(pc_result),
                pc_result.get("method"),
                pc_result.get("method_version"),
                pc_result.get("applicability_status"),
                pc_result.get("hbr_km"),
                pc_result.get("hbr_source", "proxy_only" if not is_physics else "unavailable"),
                _csv_value(pc_result.get("hbr_provenance")),
                pc_result.get("covariance_status", "proxy_only" if not is_physics else "unavailable"),
                _csv_value(pc_result.get("covariance_sources")),
                pc_result.get("covariance_frame"),
                pc_result.get("covariance_epoch"),
                _csv_value(pc_result.get("assumptions")),
                _csv_value(pc_result.get("warnings")),
                ";".join(pc_result.get("reason_codes", ["PROXY_ONLY"] if not is_physics else [])),
                _csv_value(pc_result.get("provenance")),
                provenance.get("source_type"),
                provenance.get("input_hash"),
                provenance.get("is_synthetic", False),
                provenance.get("is_fallback", False),
                ml_result.get("status", "unavailable") if is_physics and (ml_associated or (ml_event_matches and ml_result.get("status") != "available")) else "not_applicable" if not is_physics else "unavailable",
                ml_result.get("model_name"),
                ml_result.get("model_version"),
                ml_prediction.get("predicted_log_risk") if ml_prediction_available else None,
                ml_prediction.get("predicted_risk_probability") if ml_prediction_available else None,
                ml_prediction.get("high_risk") if ml_prediction_available else None,
                _csv_value(ml_result.get("feature_availability")),
                ml_result.get("features_imputed"),
                _csv_value(ml_provenance),
                comparison.get("status"),
                comparison.get("reason_code"),
                event.get("primary", {}).get("name"),
                event.get("secondary", {}).get("name"),
                event.get("risk_score"),
                event.get("risk_level"),
                event.get("priority_score"),
                event.get("suggested_action"),
                _csv_value(provenance.get("source_record") or (event.get("provenance") or {}).get("source_record")),
                (ml_prediction.get("predicted_risk_estimate", ml_prediction.get("predicted_risk_probability")) if ml_prediction_available else None),
                (ml_prediction.get("threshold_flag_at_minus_6", ml_prediction.get("high_risk")) if ml_prediction_available else None),
                (ml_result.get("reason_code", "ML_RESULT_NOT_RETURNED") if ml_associated or (ml_event_matches and ml_result.get("status") != "available") else "ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED" if ml_event_matches and is_physics else "ML_EVENT_ID_MISMATCH" if is_physics else "NOT_APPLICABLE_SCREENING_PROXY"),
                (anomaly.get("status", "unavailable") if is_physics and anomaly_associated else "not_applicable" if not is_physics else "unavailable"),
                (anomaly.get("anomaly_score") if is_physics and anomaly_associated and anomaly.get("status") == "available" else None),
                (anomaly.get("classification") if is_physics and anomaly_associated and anomaly.get("status") == "available" else None),
                anomaly.get("score_definition"),
                (anomaly.get("reason_code") if anomaly_associated else "ANOMALY_EVENT_ID_MISMATCH" if is_physics else "NOT_APPLICABLE_SCREENING_PROXY"),
                _csv_value(anomaly_provenance),
                pc_result.get("independence_assumption_authorized"),
                scenario_result.get("status", "not_run"),
                _available_pc_value(scenario_result),
                scenario_result.get("method"),
                scenario_result.get("method_version"),
                scenario_result.get("applicability_status"),
                scenario_result.get("hbr_km"),
                scenario_hbr_provenance.get("units"),
                scenario_result.get("hbr_source", "unavailable"),
                _csv_value(scenario_hbr_provenance),
                scenario_result.get("covariance_status", "unavailable"),
                scenario_result.get("covariance_frame"),
                scenario_result.get("covariance_epoch"),
                _csv_value(scenario_result.get("covariance_sources")),
                scenario_result.get("independence_assumption_authorized"),
                _csv_value(scenario_result.get("assumptions")),
                _csv_value(event.get("scenario_assumptions")),
                ";".join(scenario_result.get("reason_codes", [])),
                _csv_value(scenario_result.get("warnings")),
                _csv_value(scenario_result.get("provenance")),
                (scenario_result.get("provenance") or {}).get("is_synthetic", False),
                _geometry_review_band(review_priority.get("category")),
                review_priority.get("status", "unclassified"),
                review_priority.get("policy_version"),
                _csv_value(_geometry_review_criteria(review_priority.get("criteria"))),
                review_priority.get("explanation"),
                (event.get("automatic_research_pc_assessment") or {}).get("status"),
                (event.get("automatic_research_pc_assessment") or {}).get("estimated_pc_scientific"),
                (event.get("automatic_research_pc_assessment") or {}).get("log10_pc"),
                (event.get("automatic_research_pc_assessment") or {}).get("covariance_policy_name") or (event.get("automatic_research_pc_assessment") or {}).get("covariance_policy_id"),
                (event.get("automatic_research_pc_assessment") or {}).get("encounter_plane_sigma_min_km"),
                (event.get("automatic_research_pc_assessment") or {}).get("encounter_plane_sigma_max_km"),
                (event.get("automatic_research_pc_assessment") or {}).get("covariance_frame"),
                (event.get("automatic_research_pc_assessment") or {}).get("covariance_epoch_utc"),
                (event.get("automatic_research_pc_assessment") or {}).get("hbr_km"),
                (event.get("automatic_research_pc_assessment") or {}).get("hbr_source"),
                _csv_value((event.get("automatic_research_pc_assessment") or {}).get("hbr_provenance")),
                (event.get("automatic_research_pc_assessment") or {}).get("covariance_method"),
                (event.get("automatic_research_pc_assessment") or {}).get("lower_sensitivity_pc_scientific"),
                (event.get("automatic_research_pc_assessment") or {}).get("upper_sensitivity_pc_scientific"),
                (event.get("automatic_research_pc_assessment") or {}).get("sensitivity_reason"),
                ";".join((event.get("automatic_research_pc_assessment") or {}).get("reason_codes", [])),
                _csv_value((event.get("automatic_research_pc_assessment") or {}).get("assumptions")),
            ]
        if export_metadata is not None:
            row.extend(["event"] + [""] * (len(metadata_fields) - 1))
        writer.writerow(row)
    return buffer.getvalue()


def _trajectory_event_report_pdf(event: dict[str, Any], maneuver: dict[str, Any] | None, screening_summary: dict[str, Any] | None = None, evaluation_metadata: dict[str, Any] | None = None) -> bytes:
    physics = event.get("physics_result", {})
    tca = physics.get("tca", {})
    miss = physics.get("miss_distance", {})
    relative_position = physics.get("relative_position_at_tca", {})
    relative_velocity = physics.get("relative_velocity_at_tca", {})
    relative_speed = physics.get("relative_speed_at_tca", {})
    provenance = physics.get("provenance", {})
    pc_result = event.get("collision_probability") or {}
    research_assessment = event.get("automatic_research_pc_assessment") or {}
    review_category = (event.get("review_priority") or {}).get("category")
    review_band = {"CRITICAL": "Band 1", "HIGH": "Band 2", "MEDIUM": "Band 3", "LOW": "Band 4", "REVIEW_REQUIRED": "Review required"}.get(review_category, "Unclassified")
    research_risk = research_assessment.get("risk_assessment") or {}
    pc_event_matches = pc_result.get("event_id") == event.get("id")
    pc_status = pc_result.get("status", "unavailable") if pc_event_matches else "unavailable"
    pc_value = _available_pc_value(pc_result) if pc_event_matches else None
    pc_reason_codes = pc_result.get("reason_codes") or ([pc_result.get("reason_code")] if pc_result.get("reason_code") else [])
    if not pc_event_matches and pc_result.get("event_id") is not None:
        pc_reason_codes = ["PC_EVENT_ID_MISMATCH"]
    if not pc_reason_codes and pc_result.get("status", "unavailable") != "available":
        pc_reason_codes = ["PC_RESULT_NOT_RETURNED"] if not event.get("collision_probability") else ["PC_UNAVAILABLE_REASON_NOT_RECORDED"]
    hbr_value = pc_result.get("hbr_km")
    ml_result = event.get("ml_result") or {}
    ml_prediction = ml_result.get("prediction") or {}
    comparison = event.get("comparison_result") or {}
    ml_provenance = ml_result.get("provenance") or {}
    ml_event_matches = ml_provenance.get("source_physics_event_id") == event.get("id")
    ml_compatibility_verified = ml_provenance.get("live_feature_semantics_compatibility") == "verified"
    ml_associated = ml_event_matches and ml_compatibility_verified
    anomaly = event.get("anomaly_result") or {}
    anomaly_provenance = anomaly.get("provenance") or {}
    anomaly_associated = anomaly_provenance.get("source_physics_event_id") == event.get("id")
    convergence = physics.get("convergence") or {}
    convergence_summary = "; ".join(
        f"{label} {convergence[key]}" for key, label in (
            ("iterations", "iterations"), ("final_bracket_width_seconds", "final bracket s"),
            ("neighbor_check_passed", "neighbor check"), ("time_tolerance_seconds", "time tolerance s"),
        ) if convergence.get(key) is not None
    ) or "unavailable"
    feature_availability = ml_result.get("feature_availability") or {}
    feature_count = sum(value is True for value in feature_availability.values())
    feature_summary = f"{feature_count}/{len(feature_availability)} features present; imputed {ml_result.get('features_imputed', 'unavailable')}" if feature_availability else "unavailable"
    ml_provenance_summary = "; ".join(
        f"{label} {ml_provenance[key]}" for key, label in (
            ("source_physics_event_id", "event"), ("feature_schema_version", "schema"),
            ("artifact_sha256", "model SHA-256"), ("training_dataset_sha256", "dataset SHA-256"),
        ) if ml_provenance.get(key) is not None
    ) or "unavailable"
    anomaly_provenance_summary = "; ".join(
        f"{label} {anomaly_provenance[key]}" for key, label in (
            ("source_physics_event_id", "event"), ("feature_schema_version", "schema"),
            ("artifact_sha256", "model SHA-256"), ("training_dataset_sha256", "dataset SHA-256"),
        ) if anomaly_provenance.get(key) is not None
    ) or "unavailable"
    if not ml_event_matches:
        reason = "ML_EVENT_ID_MISMATCH"
        ml_result = {**ml_result, "status": "unavailable", "reason_code": reason}
        ml_prediction = {}
    elif ml_result.get("status") == "available" and not ml_compatibility_verified:
        reason = "ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED"
        ml_result = {**ml_result, "status": "unavailable", "reason_code": reason}
        ml_prediction = {}
    elif ml_result.get("status") != "available":
        ml_prediction = {}
    if not anomaly_associated:
        anomaly = {**anomaly, "status": "unavailable", "reason_code": "ANOMALY_EVENT_ID_MISMATCH"}
    lines = [
        "Trajectory-Derived Close Approach Report",
        f"Deterministic event key: {event.get('id', 'unavailable')}",
        f"Generated UTC: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Objects",
        f"Primary: {event.get('primary', {}).get('name')} | ID {event.get('primary', {}).get('id')}",
        f"Secondary: {event.get('secondary', {}).get('name')} | ID {event.get('secondary', {}).get('id')}",
        f"Pair type: {event.get('pair_type', 'unavailable')} | primary class {event.get('primary', {}).get('object_type', 'unavailable')} | secondary class {event.get('secondary', {}).get('object_type', 'unavailable')}",
        f"Classification sources: primary {event.get('primary', {}).get('classification_source', 'unavailable')} ({event.get('primary', {}).get('source_classification') or 'no source type reported'}) | secondary {event.get('secondary', {}).get('classification_source', 'unavailable')} ({event.get('secondary', {}).get('source_classification') or 'no source type reported'})",
        "",
        "Stage 2A trajectory result",
        f"Status: {physics.get('status', 'unavailable')}",
        f"Physical validity: {physics.get('status', 'unavailable')} | provenance validity: {(event.get('provenance') or {}).get('validity_status', 'unavailable')}",
        f"Horizon UTC: {physics.get('screening_horizon_start', 'unavailable')} to {physics.get('screening_horizon_end', 'unavailable')}",
        f"Screening threshold: {physics.get('screening_threshold_km', 'unavailable')} km",
        f"TCA UTC: {tca.get('value', 'unavailable') if tca.get('status') == 'available' else 'unavailable'}",
        f"Miss distance: {miss.get('value', 'unavailable') if miss.get('status') == 'available' else 'unavailable'} km",
        f"Relative position at TCA: {_csv_value(relative_position.get('value')) or 'unavailable'} km",
        f"Relative velocity at TCA: {_csv_value(relative_velocity.get('value')) or 'unavailable'} km/s",
        f"Relative speed at TCA: {relative_speed.get('value', 'unavailable') if relative_speed.get('status') == 'available' else 'unavailable'} km/s",
        *_wrap_report_line(f"State frame / units: {(physics.get('state_information') or {}).get('source_frame', 'unavailable')} | position {(physics.get('state_information') or {}).get('position_units', 'unavailable')} | velocity {(physics.get('state_information') or {}).get('velocity_units', 'unavailable')}"),
        *_wrap_report_line(f"TCA epoch: {tca.get('value', 'unavailable') if tca.get('status') == 'available' else 'unavailable'} | state epochs: primary {(event.get('primary_state_at_tca') or {}).get('epoch', 'unavailable')} | secondary {(event.get('secondary_state_at_tca') or {}).get('epoch', 'unavailable')}"),
        f"Method: {provenance.get('method', 'unavailable')} v{provenance.get('method_version', 'unavailable')}",
        f"Convergence metadata: {convergence_summary}",
        f"Reason codes: {', '.join(physics.get('reason_codes', [])) or 'none'}",
        f"Screening job ID: {(screening_summary or {}).get('screening_job_id', 'unavailable')}",
        f"Screening job lifecycle: {(screening_summary or {}).get('screening_job_status', 'unavailable')} | archive status: {'archived / read-only snapshot' if (screening_summary or {}).get('screening_job_archived') else 'live job'}",
        f"Screening run completion: {(screening_summary or {}).get('completion_status', (screening_summary or {}).get('status', 'unavailable'))} | reason: {(screening_summary or {}).get('reason_code', 'unavailable')} | candidate cap: {(screening_summary or {}).get('candidate_limit_reached', 'unavailable')}",
        *_wrap_report_line(f"Coverage counts: requested objects {(screening_summary or {}).get('objects_requested', 'unavailable')} | records received {(screening_summary or {}).get('catalog_records_received', 'unavailable')} | objects used {(screening_summary or {}).get('objects_used', (screening_summary or {}).get('valid_track_count', 'unavailable'))} | candidate pairs {(screening_summary or {}).get('candidate_pairs', (screening_summary or {}).get('candidate_pair_count', 'unavailable'))} | refinements {(screening_summary or {}).get('refinements', (screening_summary or {}).get('refinement_count', 'unavailable'))} | physical events {(screening_summary or {}).get('physical_events', (screening_summary or {}).get('close_approach_count', 'unavailable'))}"),
        *_wrap_report_line(f"Coverage caps hit: {_csv_value((screening_summary or {}).get('caps_hit')) or 'none recorded'} | partial reasons: {_csv_value((screening_summary or {}).get('partial_reasons')) or 'none recorded'}"),
        *_wrap_report_line(
            "Input provenance: "
            f"source {(event.get('provenance') or {}).get('source', 'unavailable')} | "
            f"type {(event.get('provenance') or {}).get('source_type', 'unavailable')} | "
            f"method {(event.get('provenance') or {}).get('method', 'unavailable')} | "
            f"version {(event.get('provenance') or {}).get('method_version', 'unavailable')} | "
            f"input hash {(event.get('provenance') or {}).get('input_hash', 'unavailable')}"
        ),
        "Vyoma geometry-only review priority (not a Pc risk class)",
        f"Geometry review band: {review_band} | policy version: {(event.get('review_priority') or {}).get('policy_version', 'unavailable')} | status: {(event.get('review_priority') or {}).get('status', 'unclassified')}",
        f"Explanation: {(event.get('review_priority') or {}).get('explanation', 'unavailable')}",
        f"Criteria: {_csv_value(_geometry_review_criteria((event.get('review_priority') or {}).get('criteria'))) or 'unavailable'} | reasons: {', '.join((event.get('review_priority') or {}).get('reason_codes', [])) or 'none'}",
        f"Limitations: {_csv_value((event.get('review_priority') or {}).get('limitations')) or 'unavailable'}",
        *_wrap_report_line("Scientific scope: research trajectory screening; not an operational warning. TLE uncertainty is not quantified here; live TLE-only inputs have no covariance or measured HBR."),
        "Maneuver scope: exploratory two-body simulation; perturbations, covariance, burn execution error, attitude, and propulsion constraints are omitted.",
        "Collision probability assessment",
        f"Pc: {pc_value if pc_value is not None else 'unavailable'} | status {pc_status}",
        f"Source-reported Pc: {pc_result.get('source_reported_pc') if pc_result.get('source_reported_event_id') == event.get('id') and pc_result.get('source_reported_pc') is not None else 'not reported'} | method {pc_result.get('source_reported_pc_method') or 'undeclared'}",
        f"Event-specific Foster Pc: {pc_value if pc_value is not None else 'unavailable'} | status {pc_status}",
        f"Research Pc: {research_assessment.get('estimated_pc_scientific') or 'unavailable'} | {research_assessment.get('percentage_scientific') or 'unavailable'}% | method {research_assessment.get('method_name', 'unavailable')} v{research_assessment.get('method_version', 'unavailable')}",
        f"Physics risk score/class: {research_risk.get('risk_score') if research_risk.get('risk_score') is not None else 'unavailable'} / 100 | {research_risk.get('final_risk_class') or research_risk.get('physics_risk_class') or 'unavailable'} | basis {research_risk.get('classification_basis') or 'unavailable'}",
        f"Method: {pc_result.get('method', 'unavailable') if pc_event_matches else 'unavailable'} v{pc_result.get('method_version', 'unavailable') if pc_event_matches else 'unavailable'}",
        f"Applicability: {pc_result.get('applicability_status', 'not_assessed')} | reason codes: {', '.join(pc_reason_codes) or 'none'}",
        f"Independence assumption authorized: {pc_result.get('independence_assumption_authorized', 'not recorded')}",
        f"HBR km: {hbr_value if hbr_value is not None else research_assessment.get('hbr_km', 'unavailable')} | source {pc_result.get('hbr_source') or research_assessment.get('hbr_source', 'unavailable')} | provenance: {_csv_value(pc_result.get('hbr_provenance') or research_assessment.get('hbr_provenance')) or 'unavailable'}",
        f"Covariance policy: {research_assessment.get('covariance_policy_name') or research_assessment.get('covariance_policy_id') or 'not provided'} | encounter-plane sigmas km: {research_assessment.get('encounter_plane_sigma_min_km', 'unavailable')} / {research_assessment.get('encounter_plane_sigma_max_km', 'unavailable')}",
        f"Covariance status: {pc_result.get('covariance_status') or ('assumed research model' if research_assessment.get('covariance_method') else 'unavailable')} | frame: {pc_result.get('covariance_frame') or research_assessment.get('covariance_frame', 'unavailable')} | epoch: {pc_result.get('covariance_epoch') or research_assessment.get('covariance_epoch_utc', 'unavailable')}",
        f"Covariance sources: {_csv_value(pc_result.get('covariance_sources') or research_assessment.get('covariance_method')) or 'unavailable'}",
        f"Assumptions: {_csv_value(pc_result.get('assumptions') or research_assessment.get('assumptions')) or 'unavailable'}",
        f"Warnings: {_csv_value(pc_result.get('warnings')) or 'none'}",
        f"Pc provenance: {_csv_value(pc_result.get('provenance')) or 'unavailable'}",
        f"Maneuver research assessment: {(maneuver or {}).get('status', 'unavailable')} | {(maneuver or {}).get('reason', 'unavailable')}",
        "Independent ML estimate (ESA final log10 event risk; not a calibrated probability or Foster Pc)",
        f"Status: {ml_result.get('status', 'unavailable')} | reason: {ml_result.get('reason_code', 'unavailable')}",
        f"Model: {ml_result.get('model_name', 'unavailable')} v{ml_result.get('model_version', 'unavailable')} | dataset: {ml_result.get('training_dataset', 'unavailable')}",
        f"Predicted log10 ESA event-risk: {ml_prediction.get('predicted_log_risk', 'unavailable')} | exponentiated ESA event-risk estimate: {ml_prediction.get('predicted_risk_estimate', ml_prediction.get('predicted_risk_probability', 'unavailable'))} | threshold flag (log10 risk >= -6): {ml_prediction.get('threshold_flag_at_minus_6', ml_prediction.get('high_risk', 'unavailable'))}",
        "The ESA-scale estimate is not a calibrated probability or Foster Pc. The threshold flag is an unvalidated research convention.",
        eligible_legacy_diagnostic_summary(
            evaluation_metadata,
            expected_artifact_sha256=ml_provenance.get("artifact_sha256") if ml_associated else None,
        ),
        f"Feature availability: {feature_summary}",
        f"ML provenance: {ml_provenance_summary}",
        f"Physics/ML comparison: {comparison.get('status', 'unavailable')} | {comparison.get('reason_code', 'unavailable')}; no numerical agreement claim is made.",
        "Orbital anomaly assessment (historical feature unusualness; not collision risk)",
        f"Status: {anomaly.get('status', 'unavailable')} | reason: {anomaly.get('reason_code', 'ANOMALY_RESULT_NOT_RETURNED')}",
        f"Score: {anomaly.get('anomaly_score', 'unavailable') if anomaly.get('status') == 'available' else 'unavailable'} | classification: {anomaly.get('classification', 'unavailable') if anomaly.get('status') == 'available' else 'unavailable'}",
        f"Definition: {anomaly.get('score_definition', 'unavailable')}",
        f"Anomaly provenance: {anomaly_provenance_summary}",
    ]
    scenario_result = event.get("scenario_collision_probability") or {}
    if scenario_result:
        scenario_hbr_provenance = scenario_result.get("hbr_provenance") or {}
        scenario_pc_value = _available_pc_value(scenario_result)
        lines.extend([
            "",
            "Separate research scenario Pc (user-assumed sensitivity result; not observed)",
            f"Status: {scenario_result.get('status', 'unavailable')}",
            f"Pc: {scenario_pc_value if scenario_pc_value is not None else 'unavailable'}",
            f"Method: {scenario_result.get('method', 'unavailable')} v{scenario_result.get('method_version', 'unavailable')}",
            f"Applicability: {scenario_result.get('applicability_status', 'not_assessed')} | reason codes: {', '.join(scenario_result.get('reason_codes', [])) or 'none'}",
            f"Warnings: {_csv_value(scenario_result.get('warnings')) or 'none'}",
            f"HBR: {scenario_result.get('hbr_km') if scenario_result.get('hbr_km') is not None else 'unavailable'} {scenario_hbr_provenance.get('units', 'km')} | source {scenario_result.get('hbr_source', 'unavailable')}",
            f"Covariance status: {scenario_result.get('covariance_status', 'unavailable')} | frame: {scenario_result.get('covariance_frame', 'unavailable')} | epoch: {scenario_result.get('covariance_epoch', 'unavailable')}",
            f"Independence assumption authorized: {scenario_result.get('independence_assumption_authorized', 'not recorded')}",
            f"Synthetic inputs: {(scenario_result.get('provenance') or {}).get('is_synthetic', False)}",
        ])
        lines.extend(_wrap_report_line(f"HBR provenance: {_csv_value(scenario_hbr_provenance) or 'unavailable'}"))
        lines.extend(_wrap_report_line(f"Covariance sources: {_csv_value(scenario_result.get('covariance_sources')) or 'unavailable'}"))
        lines.extend(_wrap_report_line(f"Foster assumptions: {_csv_value(scenario_result.get('assumptions')) or 'unavailable'}"))
        lines.extend(_wrap_report_line(f"User scenario assumptions: {_csv_value(event.get('scenario_assumptions')) or 'unavailable'}"))
        lines.extend(_wrap_report_line(f"Scenario provenance: {_csv_value(scenario_result.get('provenance')) or 'unavailable'}"))
        lines.extend(_wrap_report_line(f"Warnings: {_csv_value(scenario_result.get('warnings')) or 'none'}"))
    else:
        lines.extend(["", "Separate research scenario Pc: not run"])
    if maneuver:
        baseline = maneuver.get("baseline_reference_comparison") or {}
        stage2a_block = maneuver.get("stage2a_reference") or {}
        zero_burn_block = maneuver.get("zero_burn_baseline") or {}
        candidate_block = maneuver.get("physics_candidates") or {}
        surrogate_block = maneuver.get("surrogate_rank") or {}
        stage2a_tca = (stage2a_block.get("tca") or {}).get("value", "unavailable") if isinstance(stage2a_block.get("tca"), dict) else stage2a_block.get("tca_utc", "unavailable")
        stage2a_miss = (stage2a_block.get("miss_distance") or {}).get("value", "unavailable") if isinstance(stage2a_block.get("miss_distance"), dict) else stage2a_block.get("miss_distance_km", "unavailable")
        maneuver_ml = maneuver.get("ml_result") or {}
        maneuver_ml_evaluation = maneuver_ml.get("evaluation_summary") or {}
        probability_before = maneuver.get("probability_before") or {}
        probability_after = maneuver.get("probability_after") or {}
        probability_comparison = maneuver.get("probability_comparison") or {}
        best_candidate = maneuver.get("best_candidate") or {}
        best_fuel = best_candidate.get("fuel") or maneuver.get("fuel") or {}
        baseline_status = baseline.get("status", "unavailable")
        lines.extend([
            "", "Maneuver assessment",
            f"Maneuver event ID: {maneuver.get('event_id') or event.get('id') or 'unavailable'}",
            f"Maneuver screening job ID: {maneuver.get('screening_job_id') or (screening_summary or {}).get('screening_job_id', 'unavailable')}",
            f"Status: {maneuver.get('status', 'unavailable')} | {maneuver.get('reason_code') or 'no reason code'}",
            f"Reason: {maneuver.get('reason') or 'unavailable'}",
            f"Method: {maneuver.get('method', 'unavailable')}",
            *_wrap_report_line(f"Stage 2A reference block: status {stage2a_block.get('status', 'unavailable')} | event {stage2a_block.get('event_id', 'unavailable')} | job {stage2a_block.get('screening_job_id', 'unavailable')} | TCA {stage2a_tca} | miss km {stage2a_miss} | method {stage2a_block.get('method', stage2a_block.get('propagator', 'unavailable'))}"),
            *_wrap_report_line(f"Zero-burn block: status {zero_burn_block.get('status', 'unavailable')} | event {zero_burn_block.get('event_id', 'unavailable')} | job {zero_burn_block.get('screening_job_id', 'unavailable')} | TCA {zero_burn_block.get('tca_utc', zero_burn_block.get('closest_approach_utc', 'unavailable'))} | miss km {zero_burn_block.get('miss_distance_km', 'unavailable')} | method {zero_burn_block.get('method', 'unavailable')}"),
            *_wrap_report_line(f"Physics candidate block: status {candidate_block.get('status', 'unavailable')} | event {candidate_block.get('event_id', 'unavailable')} | job {candidate_block.get('screening_job_id', 'unavailable')} | candidates {len(candidate_block.get('candidates', [])) if isinstance(candidate_block.get('candidates', []), list) else 'unavailable'}"),
            *_wrap_report_line(f"Surrogate rank block: status {surrogate_block.get('status', 'unavailable')} | event {surrogate_block.get('event_id', 'unavailable')} | job {surrogate_block.get('screening_job_id', 'unavailable')} | synthetic training labels {surrogate_block.get('synthetic_training_labels', 'unavailable')} | ranking used {surrogate_block.get('ranking_used', 'unavailable')} | reason {surrogate_block.get('reason_code', 'unavailable')}"),
            "Baseline comparison: original Stage 2A SGP4 event is the reference; zero-burn two-body is the simulated baseline.",
            f"Baseline comparison status: {baseline_status}",
            f"Original Stage 2A SGP4 TCA: {baseline.get('reference_tca_utc') or 'unavailable'}",
            f"Zero-burn two-body simulated closest-approach TCA: {baseline.get('zero_burn_closest_approach_utc') or 'unavailable'}",
            f"Original Stage 2A SGP4 reference miss distance: {baseline.get('reference_miss_distance_km') if baseline.get('reference_miss_distance_km') is not None else 'unavailable'} km",
            f"Zero-burn two-body simulated baseline miss distance: {baseline.get('zero_burn_two_body_miss_distance_km') if baseline.get('zero_burn_two_body_miss_distance_km') is not None else 'unavailable'} km",
            f"Zero-burn closest-approach TCA offset from original TCA: {baseline.get('zero_burn_tca_offset_from_reference_seconds') if baseline.get('zero_burn_tca_offset_from_reference_seconds') is not None else 'unavailable'} s",
            f"Baseline interpretation: {baseline.get('interpretation') or 'Comparison details unavailable; candidate changes cannot be interpreted against the original event.'}",
            f"Assumptions: {_csv_value(maneuver.get('assumptions')) or 'unavailable'}",
            f"Maneuver ML status: {maneuver_ml.get('status', 'unavailable')} | reason: {maneuver_ml.get('reason_code', 'unavailable')}",
            f"Maneuver surrogate: {maneuver_ml.get('model_name', 'unavailable')} v{maneuver_ml.get('model_version', 'unavailable')} | synthetic training labels: {maneuver_ml.get('synthetic_training_labels', True)} | candidate ranking used: {maneuver_ml.get('ranking_used', False)}",
            f"Maneuver ML model: {maneuver_ml.get('model_name', 'unavailable')} v{maneuver_ml.get('model_version', 'unavailable')}",
            f"Maneuver ML score meaning: {maneuver_ml.get('score_name', 'unavailable')} ({maneuver_ml.get('score_units', 'unavailable')}); {maneuver_ml.get('score_semantics', 'unavailable')}",
            "Maneuver ML held-out evidence: " + (
                f"{maneuver_ml_evaluation.get('held_out_scenario_count', 'unavailable')} parents / {maneuver_ml_evaluation.get('held_out_candidate_count', 'unavailable')} candidates; "
                f"within-parent Spearman {maneuver_ml_evaluation.get('mean_within_scenario_spearman', 'unavailable')}; "
                f"top-1 agreement {maneuver_ml_evaluation.get('top1_agreement_with_physics_best', 'unavailable')}; "
                f"model regret {maneuver_ml_evaluation.get('model_mean_regret_log10_pc_reduction', 'unavailable')} log10 units; "
                f"deterministic baseline regret {maneuver_ml_evaluation.get('baseline_mean_regret_log10_pc_reduction', 'unavailable')} log10 units; "
                f"{maneuver_ml_evaluation.get('source', 'not supplied')}"
            ),
            f"Maneuver ML provenance: {_csv_value(maneuver_ml.get('provenance')) or 'unavailable'}",
            f"Research Pc before: {probability_before.get('pc_scientific') or 'unavailable'} | status {probability_before.get('status', 'unavailable')} | TCA {probability_before.get('tca_utc') or baseline.get('zero_burn_closest_approach_utc') or 'unavailable'}",
            f"Research Pc after: {probability_after.get('pc_scientific') or 'unavailable'} | status {probability_after.get('status', 'unavailable')} | TCA {probability_after.get('tca_utc') or best_candidate.get('closest_approach_utc') or 'unavailable'}",
            f"Pc reduction: absolute {best_candidate.get('absolute_research_pc_reduction_scientific') or 'unavailable'} | percentage {maneuver.get('risk_reduction_pct') if maneuver.get('risk_reduction_pct') is not None else 'unavailable'}% | {probability_comparison.get('interpretation') or probability_comparison.get('reason_code') or maneuver.get('probability_reason_code') or 'unavailable'}",
            f"Fuel: {best_fuel.get('propellant_consumption_kg') if best_fuel.get('propellant_consumption_kg') is not None else 'unavailable'} kg | initial mass {best_fuel.get('initial_mass_kg', 'unavailable')} kg | Isp {best_fuel.get('specific_impulse_s', 'unavailable')} s | {best_fuel.get('assumption_status') or best_fuel.get('status', 'unavailable')}",
        ])
        lines.extend(_wrap_report_line(
            "Candidate closest approaches are simulated two-body results. Change from baseline is relative to "
            "zero-burn two-body, not automatically an improvement over the original conjunction. No "
            "post-maneuver Pc, operational safety, fuel savings, or maneuver recommendation is inferred."
        ))
        maneuver_candidates = maneuver.get("candidates") if isinstance(maneuver.get("candidates"), list) else candidate_block.get("candidates", [])
        ranked_candidates = sorted(
            maneuver_candidates,
            key=lambda item: item.get("physics_research_pc_rank") if item.get("physics_research_pc_rank") is not None else float("inf"),
        )
        for candidate in ranked_candidates[:5]:
            candidate_pc = candidate.get("research_pc_after") or {}
            candidate_fuel = candidate.get("fuel") or {}
            candidate_lines = [
                f"Candidate burn: {candidate.get('delta_v_m_s')} m/s | RTN {candidate.get('delta_v_rtn_m_s')} m/s | {candidate.get('direction')} | burn UTC {candidate.get('maneuver_epoch_utc')} | lead {candidate.get('lead_time_seconds')} s",
                f"Candidate TCA {candidate.get('closest_approach_utc') or 'unavailable'} | relative velocity after {candidate.get('relative_velocity_km_s') or 'unavailable'} km/s",
                f"Miss distance after {candidate.get('predicted_miss_distance_km') if candidate.get('predicted_miss_distance_km') is not None else 'unavailable'} km | change from zero-burn {candidate.get('change_from_zero_burn_km') if candidate.get('change_from_zero_burn_km') is not None else 'unavailable'} km",
                f"Pc after {candidate_pc.get('pc_scientific') or 'unavailable'} | absolute reduction {candidate.get('absolute_research_pc_reduction_scientific') or 'unavailable'} | percentage {candidate.get('percentage_research_pc_reduction') if candidate.get('percentage_research_pc_reduction') is not None else 'unavailable'}%",
                f"Fuel {candidate_fuel.get('propellant_consumption_kg') if candidate_fuel.get('propellant_consumption_kg') is not None else 'unavailable'} kg | mass {candidate_fuel.get('initial_mass_kg', 'unavailable')} kg | Isp {candidate_fuel.get('specific_impulse_s', 'unavailable')} s | {candidate_fuel.get('assumption_status') or candidate_fuel.get('status', 'unavailable')}",
                f"AI rank {candidate.get('maneuver_ml_rank') if candidate.get('maneuver_ml_rank') is not None else 'unavailable'} | physics research-Pc rank {candidate.get('physics_research_pc_rank') if candidate.get('physics_research_pc_rank') is not None else 'unavailable'} | AI predicted log10 Pc reduction {candidate.get('maneuver_ml_predicted_log10_pc_reduction') if candidate.get('maneuver_ml_predicted_log10_pc_reduction') is not None else 'unavailable'}",
            ]
            lines.extend([part for line in candidate_lines for part in _wrap_report_line(line, 68)])
        if len(ranked_candidates) > 5:
            lines.append(f"{len(ranked_candidates) - 5} additional candidates are included in the CSV and JSON downloads.")
    return simple_pdf([wrapped for line in lines for wrapped in _wrap_report_line(line, 56)], footer="Vyoma SSA | Research Prototype | Not for operational decisions")


def _csv_value(value: Any) -> str:
    import json

    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, separators=(",", ":"), sort_keys=isinstance(value, dict))
    return str(value)


def _available_pc_value(result: dict[str, Any]) -> float | None:
    value = result.get("pc")
    if (
        result.get("status") != "available"
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 < value <= 1.0
    ):
        return None
    return value


def _wrap_report_line(value: str, max_length: int = 96) -> list[str]:
    """Split long provenance text so simple_pdf's 104-character limit loses no fields."""
    return textwrap.wrap(value, width=max_length, break_long_words=True, break_on_hyphens=False) or [""]


def simple_pdf(lines: list[str], footer: str) -> bytes:
    pages: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if len(current) >= 38 or (len(current) >= 36 and str(line).rstrip().endswith(":")):
            pages.append(current)
            current = []
        current.append(str(line))
    if current:
        pages.append(current)

    objects: list[bytes] = []
    content_refs: list[int] = []
    for page_number, page_lines in enumerate(pages, start=1):
        stream = _page_stream(page_lines, page_number, len(pages), footer)
        content_refs.append(len(objects) + 1)
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")

    font_ref = len(objects) + 1
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_ref = len(objects) + 1 + len(pages)
    page_refs: list[int] = []
    for index, content_ref in enumerate(content_refs):
        page_refs.append(len(objects) + 1)
        objects.append(
            (
                f"<< /Type /Page /Parent {pages_ref} 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_ref} 0 R >> >> /Contents {content_ref} 0 R >>"
            ).encode("latin-1")
        )
    kids = " ".join(f"{ref} 0 R" for ref in page_refs)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_refs)} >>".encode("latin-1"))
    catalog_ref = len(objects) + 1
    objects.append(f"<< /Type /Catalog /Pages {pages_ref} 0 R >>".encode("latin-1"))

    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{index} 0 obj\n".encode("latin-1"))
        output.write(obj)
        output.write(b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    output.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode("latin-1"))
    output.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_ref} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("latin-1")
    )
    return output.getvalue()


def _page_stream(lines: list[str], page_number: int, page_count: int, footer: str) -> bytes:
    commands = ["BT", "/F1 18 Tf", "72 730 Td", f"({_escape(lines[0] if lines else 'Report')}) Tj"]
    y_offset = -28
    for index, line in enumerate(lines[1:], start=1):
        font_size = 13 if line and not line.startswith("-") else 10
        if line == "":
            y_offset -= 10
            continue
        commands.append(f"/F1 {font_size} Tf")
        commands.append(f"0 {y_offset} Td")
        commands.append(f"({_escape(line[:104])}) Tj")
        y_offset = -18
    commands.extend(
        [
            "/F1 8 Tf",
            "0 -28 Td",
            f"({_escape(footer)} | Page {page_number} of {page_count}) Tj",
            "ET",
        ]
    )
    return "\n".join(commands).encode("latin-1", errors="replace")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
