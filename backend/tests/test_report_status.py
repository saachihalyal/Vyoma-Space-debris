from __future__ import annotations

import asyncio
import csv
import copy
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main
from app.models import ConjunctionAssessmentEvent, ObjectSummary, PhysicsResult, Provenance, ScientificField
from app.services.reports import conjunctions_csv, event_report_csv, event_report_payload, event_report_pdf, mission_report_pdf


def pdf_text(pdf: bytes) -> str:
    fragments = re.findall(rb"\(((?:\\.|[^\\)])*)\) Tj", pdf)
    decoded = [part.decode("latin-1").replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\") for part in fragments]
    return " ".join(decoded)


class MissionReportStatusTests(unittest.TestCase):
    def test_report_uses_research_uncertainty_for_negligible_pc_without_replacing_foster_channel(self) -> None:
        event = stored_physical_event("CA-NEGLIGIBLE-RESEARCH")
        event["automatic_research_pc_assessment"] = {
            "status": "prior_based_research_estimate", "estimated_pc_scientific": "< 1e-30", "log10_pc": -55,
            "covariance_method": "TLE-age model assigned at TCA", "covariance_policy_id": "tle_age_baseline",
            "covariance_policy_name": "TLE-age position-sigma baseline", "encounter_plane_sigma_min_km": 0.24,
            "encounter_plane_sigma_max_km": 1.37, "covariance_frame": "TEME", "covariance_epoch_utc": "2026-10-20T00:00:00+00:00",
            "hbr_km": 0.012, "hbr_source": "assumed_object_size_override", "hbr_provenance": {"assumption": "project size proxy"},
            "assumptions": ["Assumed covariance and HBR"],
        }
        payload = event_report_payload(event)
        self.assertEqual(payload["covariance"]["policy"], "TLE-age position-sigma baseline")
        self.assertEqual(payload["covariance"]["sigmas_encounter_plane_km"], {"minimum_km": 0.24, "maximum_km": 1.37})
        self.assertEqual(payload["covariance"]["frame"], "TEME")
        self.assertEqual(payload["covariance"]["epoch_utc"], "2026-10-20T00:00:00+00:00")
        self.assertEqual(payload["hard_body_radius"]["value_km"], 0.012)
        self.assertEqual(payload["hard_body_radius"]["source"], "assumed_object_size_override")
        self.assertIsNone(payload["pc_channels"]["event_specific_foster_pc"])
        row = next(csv.DictReader(io.StringIO(event_report_csv(payload))))
        self.assertEqual(row["covariance_policy"], "TLE-age position-sigma baseline")
        self.assertEqual(row["encounter_sigma_max_km"], "1.37")
        pdf = pdf_text(event_report_pdf(event))
        for term in ("TLE-age position-sigma baseline", "0.24 / 1.37", "frame: TEME", "2026-10-20T00:00:00+00:00", "HBR km: 0.012", "assumed_object_size_override"):
            self.assertIn(term, pdf)

    def test_full_screening_csv_carries_research_uncertainty_for_each_event(self) -> None:
        event = stored_physical_event("CA-FULL-CSV-RESEARCH")
        event["primary"].update(name="SL-3 R/B", object_type="ROCKET_BODY")
        event["secondary"].update(name="ISS (Zarya)", object_type="SPACE_STATION")
        event["automatic_research_pc_assessment"] = {
            "status": "prior_based_research_estimate", "estimated_pc_scientific": "< 1e-30", "log10_pc": -45.2,
            "covariance_policy_id": "tle_age_baseline", "encounter_plane_sigma_min_km": 0.2,
            "encounter_plane_sigma_max_km": 1.1, "covariance_frame": "TEME", "covariance_epoch_utc": "2026-10-20T00:00:00+00:00",
            "hbr_km": 0.019, "hbr_source": "assumed_object_size_override", "hbr_provenance": {"assumption": "documented proxy"},
            "sensitivity_reason": "HBR-only range; covariance scale what-if is separate.",
        }
        row = next(csv.DictReader(io.StringIO(conjunctions_csv([event]))))
        self.assertEqual(row["object_primary_type"], "ROCKET_BODY")
        self.assertEqual(row["object_secondary_type"], "SPACE_STATION")
        self.assertEqual(row["research_log10_pc_exact"], "-45.2")
        self.assertEqual(row["research_covariance_policy"], "tle_age_baseline")
        self.assertEqual(row["research_encounter_sigma_max_km"], "1.1")
        self.assertEqual(row["research_covariance_frame"], "TEME")
        self.assertEqual(row["research_covariance_epoch_utc"], "2026-10-20T00:00:00+00:00")
        self.assertEqual(row["research_hbr_km"], "0.019")
        self.assertEqual(row["research_hbr_source"], "assumed_object_size_override")

    def test_selected_report_payload_keeps_probability_channels_and_maneuver_rows_separate(self) -> None:
        event = stored_physical_event("CA-REPORT-CHANNELS")
        event["collision_probability"] = {"status": "available", "event_id": event["id"], "source_reported_event_id": event["id"], "pc": 2e-7, "source_reported_pc": 1e-6, "source_reported_pc_method": "source", "covariance_status": "available", "covariance_frame": "TEME", "covariance_epoch": "2026-10-20T00:00:00+00:00", "hbr_km": 0.001, "hbr_source": "measured"}
        event["automatic_research_pc_assessment"] = {"status": "prior_based_research_estimate", "estimated_pc": 3e-7, "estimated_pc_scientific": "3.0e-7", "percentage": 3e-5, "percentage_scientific": "3.0e-5", "risk_assessment": {"risk_score": 38.0, "physics_risk_class": "Medium", "final_risk_class": "Medium", "classification_basis": "research_pc"}, "assumptions": ["independent"], "sensitivity_status": "available"}
        event["collision_ai_assessment"] = {"status": "partial", "pc_surrogate": {"status": "available", "ai_predicted_log10_pc": -6.5}, "risk_classifier": {"status": "fallback", "ai_risk_class": "Low"}}
        maneuver = {"event_id": event["id"], "status": "available", "probability_before": {"status": "available", "pc_scientific": "3.0e-7"}, "probability_after": {"status": "available", "pc_scientific": "2.0e-7"}, "zero_burn_baseline": {"miss_distance_km": 1.0, "candidate": {"closest_approach_utc": "2026-10-20T00:00:00+00:00", "relative_velocity_km_s": [1, 2, 3]}}, "physics_candidates": {"candidates": [{"direction": "along-track +", "research_pc_after": {"pc_scientific": "2.0e-7"}, "absolute_research_pc_reduction_scientific": "1.0e-7", "percentage_research_pc_reduction": 33.3, "fuel": {"status": "estimated", "initial_mass_kg": 500, "specific_impulse_s": 220, "propellant_consumption_kg": 0.002, "assumption_status": "estimated_from_default_assumptions"}}]}}
        payload = event_report_payload(event, maneuver, screening_job_id="JOB-REPORT")
        self.assertEqual(payload["screening_job_id"], "JOB-REPORT")
        self.assertEqual(payload["pc_channels"]["source_reported_pc"], 1e-6)
        self.assertEqual(payload["pc_channels"]["event_specific_foster_pc"], 2e-7)
        self.assertEqual(payload["pc_channels"]["research_pc_scientific"], "3.0e-7")
        rows = list(csv.DictReader(io.StringIO(event_report_csv(payload))))
        self.assertEqual([row["record_type"] for row in rows], ["collision_event", "maneuver_candidate"])
        self.assertEqual(rows[1]["pc_before_scientific"], "3.0e-7")
        self.assertEqual(rows[1]["pc_after_scientific"], "2.0e-7")
        self.assertEqual(rows[1]["fuel_assumption_status"], "estimated_from_default_assumptions")
        pdf = pdf_text(event_report_pdf(event, maneuver))
        for text in ("Source-reported Pc:", "Event-specific Foster Pc:", "Research Pc:", "Physics risk score/class:", "Pc reduction: absolute", "Fuel:", "physics research-Pc rank"):
            self.assertIn(text, pdf)

        stale_event = copy.deepcopy(event)
        stale_event["collision_probability"].update(event_id="CA-OTHER", source_reported_event_id="CA-OTHER")
        stale_pdf = pdf_text(event_report_pdf(stale_event))
        self.assertIn("Event-specific Foster Pc: unavailable | status unavailable", stale_pdf)
        self.assertIn("Source-reported Pc: not reported", stale_pdf)

    def render(self, completion_status: str, screening_status: str) -> str:
        pdf = mission_report_pdf(
            {"source": "Bundled fallback TLE sample"},
            [],
            {"total_objects": 7},
            physics_events=[],
            screening_summary={
                "completion_status": completion_status,
                "status": screening_status,
                "candidate_pair_count": 7,
                "candidate_local_minimum_count": 36,
                "refinement_count": 36,
            },
        )
        return pdf_text(pdf)

    def test_valid_empty_screening_is_reported_as_completed_empty(self) -> None:
        report = self.render("complete", "valid")
        self.assertIn("Screening completed successfully; 0 qualifying physical close approaches returned.", report)
        self.assertIn("7 / 36 / 36", report)
        self.assertIn("fresh run for this report", report)

    def test_event_report_prints_screening_job_identity(self) -> None:
        event = {"id": "CA-REPORT-JOB", "result_kind": "physics_assessment", "physics_result": {}}
        report = event_report_pdf(
            event,
            screening_summary={"screening_job_id": "accepted-screen-job", "completion_status": "partial"},
        )
        report = pdf_text(report)
        self.assertIn("Deterministic event key: CA-REPORT-JOB", report)
        self.assertIn("Screening job ID: accepted-screen-job", report)
        self.assertIn("Screening run completion: partial", report)

    def test_physical_event_report_contains_identity_coverage_pc_and_maneuver_blocks(self) -> None:
        event = stored_physical_event("CA-REPORT-COMPLETE")
        event["collision_probability"] = {
            "status": "unavailable", "pc": None,
            "reason_codes": ["NO_COVARIANCE", "HBR_UNAVAILABLE"],
            "method": "Foster 2D", "method_version": "1.0",
        }
        event["provenance"]["source_type"] = "live"
        job_id = "a" * 32
        maneuver = {
            "event_id": event["id"], "screening_job_id": job_id, "status": "available_with_warning",
            "stage2a_reference": {"event_id": event["id"], "screening_job_id": job_id, "status": "valid", "tca": {"value": "2026-10-20T00:00:00+00:00"}, "miss_distance": {"value": 1.0}, "propagator": "SGP4"},
            "zero_burn_baseline": {"event_id": event["id"], "screening_job_id": job_id, "status": "available_with_warning", "tca_utc": "2026-10-20T00:00:01+00:00", "miss_distance_km": 2.0, "method": "two-body RK4"},
            "physics_candidates": {"event_id": event["id"], "screening_job_id": job_id, "status": "available", "candidates": [{"event_id": event["id"], "screening_job_id": job_id, "delta_v_m_s": 0.01, "direction": "along_track", "maneuver_epoch_utc": "2026-10-19T23:55:00+00:00", "closest_approach_utc": "2026-10-20T00:00:02+00:00", "predicted_miss_distance_km": 2.1, "change_from_zero_burn_km": 0.1}]},
            "surrogate_rank": {"event_id": event["id"], "screening_job_id": job_id, "status": "unavailable", "synthetic_training_labels": True, "ranking_used": False, "reason_code": "MODEL_UNAVAILABLE"},
        }
        report = event_report_pdf(event, maneuver, {
            "screening_job_id": job_id, "screening_job_status": "complete", "completion_status": "complete",
            "objects_requested": 20, "catalog_records_received": 19, "objects_used": 18,
            "candidate_pairs": 4, "refinements": 3, "physical_events": 1,
            "caps_hit": ["candidate_minimum_limit"], "partial_reasons": ["catalog_objects_rejected"],
        })
        report = pdf_text(report)
        for value in (
            "CA-REPORT-COMPLETE", job_id, "Primary | ID 25544", "Secondary | ID 36086",
            "PAYLOAD", "SPACE_DEBRIS", "TCA UTC:", "TCA epoch:", "Relative velocity at TCA:",
            "TEME", "fixture source", "Coverage counts:", "requested objects 20", "candidate_minimum_limit",
            "catalog_objects_rejected", "Pc: unavailable | status unavailable", "NO_COVARIANCE", "HBR_UNAVAILABLE",
            "Stage 2A reference block:", "Zero-burn block:", "Physics candidate block:", "Surrogate rank block:",
            "TCA 2026-10-20T00:00:00+00:00 | miss km 1.0", "TCA 2026-10-20T00:00:01+00:00 | miss km 2.0",
            "synthetic training labels True", "two-body simulation", "not an operational warning",
        ):
            self.assertIn(value, report)
        self.assertNotIn("Pc: 0 |", report)


    def test_unavailable_screening_is_not_reported_as_valid_empty(self) -> None:
        report = self.render("failed", "unavailable")
        self.assertIn("Physical screening failed or was unavailable; no conclusion about close approaches can be drawn.", report)
        self.assertNotIn("Screening completed successfully; 0 qualifying physical close approaches returned.", report)

    def test_mission_report_keeps_esa_risk_and_anomaly_separate(self) -> None:
        event = {"id": "CA-REPORT", "physics_result": {},
            "ml_result": {"status": "available", "reason_code": "prediction_available",
                "prediction": {"predicted_risk_estimate": 1e-8},
                "provenance": {"source_physics_event_id": "CA-REPORT", "live_feature_semantics_compatibility": "verified"}},
            "anomaly_result": {"status": "available", "reason_code": "prediction_available",
                "anomaly_score": .9, "provenance": {"source_physics_event_id": "CA-REPORT"}}}
        report = mission_report_pdf({"source": "test"}, [], {}, physics_events=[event],
            screening_summary={"completion_status": "complete", "status": "valid"}).decode("latin-1")
        self.assertIn("ESA event-risk estimate", report)
        self.assertIn("Exponentiated ESA-scale estimate: 1e-08", report)
        self.assertIn("Orbital anomaly assessment", report)
        self.assertIn("Anomaly score: 0.9", report)

    def test_trajectory_csv_metadata_is_a_distinct_non_event_row(self) -> None:
        content = conjunctions_csv([], export_metadata={
            "screening_status": "valid",
            "screening_completion_status": "complete",
            "screening_result_status": "valid_empty",
            "catalog_source": "Bundled fallback TLE sample",
            "catalog_object_count": 7,
            "screening_threshold_km": 25.0,
            "candidate_pair_count": 7,
            "candidate_minimum_count": 36,
            "refinement_count": 36,
            "close_approach_count": 0,
        })
        rows = list(csv.DictReader(io.StringIO(content)))
        headers = next(csv.reader(io.StringIO(content)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(headers), len(set(headers)))
        self.assertEqual(rows[0]["record_type"], "export_metadata")
        self.assertEqual(rows[0]["screening_result_status"], "valid_empty")
        self.assertEqual(rows[0]["screening_completion_status"], "complete")
        self.assertEqual(rows[0]["catalog_source"], "Bundled fallback TLE sample")
        self.assertEqual(rows[0]["export_screening_threshold_km"], "25.0")
        self.assertEqual(rows[0]["event_id"], "")

    def test_ml_event_risk_export_labels_deprecated_aliases_and_separates_pc(self) -> None:
        event = {
            "id": "CA-ML-TERMS",
            "result_kind": "physics_assessment",
            "physics_result": {},
            "ml_result": {"status": "available", "reason_code": "prediction_available", "prediction": {
                "predicted_log_risk": -6.0,
                "predicted_risk_estimate": 1e-6,
                "predicted_risk_probability": 1e-6,
                "threshold_flag_at_minus_6": True,
                "high_risk": True,
            }, "provenance": {"source_physics_event_id": "CA-ML-TERMS", "live_feature_semantics_compatibility": "verified"}},
            "anomaly_result": {"status": "available", "reason_code": "prediction_available",
                "anomaly_score": 0.97, "classification": "unusual",
                "score_definition": "empirical rank; not a probability or danger estimate",
                "provenance": {"source_physics_event_id": "CA-ML-TERMS"}},
        }
        row = next(csv.DictReader(io.StringIO(conjunctions_csv([event]))))

        self.assertEqual(row["ml_predicted_risk_probability_deprecated_alias_not_calibrated"], "1e-06")
        self.assertEqual(row["ml_exponentiated_esa_event_risk_estimate"], "1e-06")
        self.assertEqual(row["ml_high_risk_deprecated_alias_unvalidated"], "True")
        self.assertEqual(row["ml_threshold_flag_at_log10_minus_6"], "True")
        self.assertEqual(row["pc"], "")
        self.assertEqual(row["ml_reason_code"], "prediction_available")
        self.assertEqual(row["anomaly_status"], "available")
        self.assertEqual(row["anomaly_score"], "0.97")
        self.assertEqual(row["anomaly_classification"], "unusual")
        self.assertEqual(row["anomaly_reason_code"], "prediction_available")
        self.assertIn("not a probability or danger estimate", row["anomaly_score_definition"])
        pdf = pdf_text(event_report_pdf(event))
        self.assertIn("not a calibrated probability or Foster Pc", pdf)
        self.assertIn("exponentiated ESA event-risk estimate", pdf)
        self.assertIn("Orbital anomaly assessment", pdf)
        self.assertIn("0.97", pdf)
        self.assertNotIn("ML-estimated risk probability", pdf)
        self.assertNotIn("0 of 51 high-risk labels", pdf)
        self.assertIn("diagnostic: unavailable; not recomputed", pdf)

    def test_event_report_does_not_present_fixture_metrics_as_observed_diagnostics(self) -> None:
        event = {"id": "CA-META", "result_kind": "physics_assessment", "physics_result": {},
            "ml_result": {"status": "unavailable", "provenance": {
                "source_physics_event_id": "CA-META", "artifact_sha256": "artifact-hash",
            }}}
        metadata = {
            "input_eligibility": {"boundary": "Inclusive at exactly 2.0 days; ESA documentation excludes CDMs within two days."},
            "split": {"test": {"eligible_events": 60, "high_risk_events": 51, "low_risk_events": 9}},
            "legacy_or_corrected_artifact_diagnostic": {
                "status": "legacy_unfiltered_artifact_scored_on_eligible_inputs",
                "training_population": "legacy unfiltered pre-final rows, including inputs under 2.0 days",
                "evaluation_population": "one closest-to-TCA eligible pre-final input per held-out event",
                "evidence_source": "fixture_only",
                "artifact_sha256": "artifact-hash",
                "metrics": {"high_risk_test_events": 51, "true_positive_high_risk_events": 0, "test_event_count": 60},
            },
        }
        report = event_report_pdf(event, evaluation_metadata=metadata).decode("latin-1")
        self.assertIn("Eligible-input artifact diagnostic: unavailable", report)
        self.assertNotIn("0/51 high-risk detected", report)
        for unavailable_metadata in (None, {}, {
            **metadata,
            "legacy_or_corrected_artifact_diagnostic": {
                **metadata["legacy_or_corrected_artifact_diagnostic"], "status": "unavailable",
            },
        }):
            report = event_report_pdf(event, evaluation_metadata=unavailable_metadata).decode("latin-1")
            self.assertIn("Eligible-input artifact diagnostic: unavailable", report)
            self.assertNotIn("0/51 high-risk detected", report)

    def test_reports_suppress_ai_scores_with_mismatched_event_provenance(self) -> None:
        event = {
            "id": "CA-SELECTED", "result_kind": "physics_assessment", "physics_result": {},
            "ml_result": {"status": "available", "prediction": {"predicted_log_risk": -8,
                "predicted_risk_estimate": 1e-8}, "provenance": {"source_physics_event_id": "CA-OTHER"}},
            "anomaly_result": {"status": "available", "anomaly_score": .99,
                "provenance": {"source_physics_event_id": "CA-OTHER"}},
        }
        row = next(csv.DictReader(io.StringIO(conjunctions_csv([event]))))
        self.assertEqual(row["ml_status"], "unavailable")
        self.assertEqual(row["ml_reason_code"], "ML_EVENT_ID_MISMATCH")
        self.assertEqual(row["ml_exponentiated_esa_event_risk_estimate"], "")
        self.assertEqual(row["anomaly_status"], "unavailable")
        self.assertEqual(row["anomaly_reason_code"], "ANOMALY_EVENT_ID_MISMATCH")
        self.assertEqual(row["anomaly_score"], "")
        pdf = event_report_pdf(event).decode("latin-1")
        self.assertIn("ML_EVENT_ID_MISMATCH", pdf)
        self.assertIn("ANOMALY_EVENT_ID_MISMATCH", pdf)
        self.assertNotIn("0.99", pdf)
        self.assertNotIn("1e-08", pdf)

    def test_unavailable_esa_result_keeps_reason_and_suppresses_stale_prediction(self) -> None:
        event = pc_report_event()
        event.update({
            "ml_result": {
                "status": "unavailable",
                "reason_code": "ESA_INPUT_TIME_TO_TCA_BELOW_MINIMUM",
                "prediction": {"predicted_log_risk": -8.0, "predicted_risk_estimate": 1e-8},
                "provenance": {"source_physics_event_id": event["id"]},
            },
            "anomaly_result": {
                "status": "available", "anomaly_score": 0.91, "classification": "unusual",
                "score_definition": "empirical rank; not a probability or danger estimate",
                "provenance": {"source_physics_event_id": event["id"]},
            },
        })

        row = next(csv.DictReader(io.StringIO(conjunctions_csv([event]))))
        self.assertEqual(row["ml_status"], "unavailable")
        self.assertEqual(row["ml_reason_code"], "ESA_INPUT_TIME_TO_TCA_BELOW_MINIMUM")
        self.assertEqual(row["ml_predicted_risk_probability_deprecated_alias_not_calibrated"], "")
        self.assertEqual(row["ml_exponentiated_esa_event_risk_estimate"], "")
        self.assertEqual(row["anomaly_status"], "available")
        self.assertEqual(row["anomaly_score"], "0.91")
        self.assertEqual(row["pc"], "1e-07")

        pdf = event_report_pdf(event).decode("latin-1")
        self.assertIn("ESA_INPUT_TIME_TO_TCA_BELOW_MINIMUM", pdf)
        self.assertIn("Pc: 1e-07 | status available", pdf)
        self.assertIn("0.91", pdf)
        self.assertNotIn("1e-08", pdf)

    def test_reports_withhold_legacy_prediction_without_feature_semantics_compatibility_evidence(self) -> None:
        event = {
            "id": "CA-UNVERIFIED-FEATURES", "result_kind": "physics_assessment", "physics_result": {},
            "ml_result": {"status": "available", "reason_code": "prediction_available",
                "prediction": {"predicted_log_risk": -8.0, "predicted_risk_estimate": 1e-8},
                "provenance": {"source_physics_event_id": "CA-UNVERIFIED-FEATURES"}},
        }
        row = next(csv.DictReader(io.StringIO(conjunctions_csv([event]))))
        self.assertEqual(row["ml_status"], "unavailable")
        self.assertEqual(row["ml_reason_code"], "ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED")
        self.assertEqual(row["ml_predicted_log10_risk"], "")
        self.assertEqual(row["ml_exponentiated_esa_event_risk_estimate"], "")

        pdf = pdf_text(event_report_pdf(event))
        self.assertIn("Status: unavailable | reason: ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED", pdf)
        self.assertIn("Predicted log10 ESA event-risk: unavailable", pdf)
        self.assertNotIn("-8.0", pdf)
        self.assertNotIn("1e-08", pdf)

    def test_report_preserves_anomaly_unavailability_reason(self) -> None:
        event = {"id": "CA-UNAVAILABLE", "result_kind": "physics_assessment", "physics_result": {},
            "anomaly_result": {"status": "unavailable", "reason_code": "PHYSICS_FEATURES_UNAVAILABLE",
                "score_definition": "empirical rank; not a probability or danger estimate",
                "provenance": {"source_physics_event_id": "CA-UNAVAILABLE"}}}
        row = next(csv.DictReader(io.StringIO(conjunctions_csv([event]))))
        self.assertEqual(row["anomaly_status"], "unavailable")
        self.assertEqual(row["anomaly_reason_code"], "PHYSICS_FEATURES_UNAVAILABLE")
        self.assertEqual(row["anomaly_score"], "")
        pdf = event_report_pdf(event).decode("latin-1")
        self.assertIn("PHYSICS_FEATURES_UNAVAILABLE", pdf)
        self.assertIn("Score: unavailable", pdf)

    def test_csv_and_pdf_keep_available_scenario_pc_separate_from_source_pc(self) -> None:
        event = pc_report_event()
        original_source = copy.deepcopy(event["collision_probability"])
        row = next(csv.DictReader(io.StringIO(conjunctions_csv([event]))))

        self.assertEqual(row["pc"], "1e-07")
        self.assertEqual(row["scenario_pc"], "2e-07")
        self.assertEqual(row["pc_status"], "available")
        self.assertEqual(row["scenario_pc_status"], "available")
        self.assertEqual(row["scenario_pc_method"], "Foster 2D scenario")
        self.assertEqual(row["scenario_hbr_km"], "0.004")
        self.assertEqual(row["scenario_hbr_units"], "km")
        self.assertIn("synthetic", row["scenario_covariance_sources"])
        self.assertIn("user-entered covariance and HBR assumptions", row["scenario_assumptions"])
        self.assertEqual(row["scenario_is_synthetic"], "True")

        pdf = pdf_text(event_report_pdf(event))
        self.assertIn("Separate research scenario Pc (user-assumed sensitivity result; not observed)", pdf)
        self.assertIn("Status: available", pdf)
        self.assertIn("Pc: 2e-07", pdf)
        self.assertIn("user-entered covariance and HBR", pdf)
        self.assertIn("User scenario assumptions:", pdf)
        self.assertIn("Synthetic inputs: True", pdf)
        self.assertIn("Pc: 1e-07 | status available", pdf)
        self.assertEqual(event["collision_probability"], original_source)

    def test_csv_and_pdf_suppress_nonavailable_source_and_scenario_values(self) -> None:
        for status, reason in (
            ("unavailable", "NO_COVARIANCE"),
            ("unsupported", "RELATIVE_COVARIANCE_CORRELATION_UNKNOWN"),
            ("invalid", "INVALID_COVARIANCE"),
            ("invalid", "NUMERICAL_FAILURE"),
        ):
            with self.subTest(result="source", status=status, reason=reason):
                event = pc_report_event()
                event["collision_probability"].update(status=status, pc=0.25, reason_codes=[reason])
                event.pop("scenario_collision_probability")
                row = next(csv.DictReader(io.StringIO(conjunctions_csv([event]))))
                pdf = pdf_text(event_report_pdf(event))
                self.assertEqual(row["pc_status"], status)
                self.assertEqual(row["pc"], "")
                self.assertEqual(row["pc_reason_codes"], reason)
                self.assertIn(reason, pdf)
                self.assertNotIn("Pc: 0.25", pdf)

        for status, reason in (
            ("unavailable", "NO_COVARIANCE"),
            ("unsupported", "RELATIVE_COVARIANCE_CORRELATION_UNKNOWN"),
            ("invalid", "NUMERICAL_FAILURE"),
        ):
            with self.subTest(result="scenario", status=status, reason=reason):
                event = pc_report_event()
                event["scenario_collision_probability"].update(status=status, pc=0.25, reason_codes=[reason])
                row = next(csv.DictReader(io.StringIO(conjunctions_csv([event]))))
                pdf = pdf_text(event_report_pdf(event))
                self.assertEqual(row["scenario_pc_status"], status)
                self.assertEqual(row["scenario_pc"], "")
                self.assertEqual(row["scenario_pc_reason_codes"], reason)
                self.assertIn(f"Status: {status}", pdf)
                self.assertIn(reason, pdf)
                self.assertNotIn("Pc: 0.25", pdf)

    def test_csv_and_pdf_reject_invalid_numeric_pc_even_if_status_says_available(self) -> None:
        for value in (0.0, -0.1, 1.01, float("nan"), float("inf"), True):
            with self.subTest(value=value):
                event = pc_report_event()
                event["collision_probability"]["pc"] = value
                event["scenario_collision_probability"]["pc"] = value
                row = next(csv.DictReader(io.StringIO(conjunctions_csv([event]))))
                pdf = event_report_pdf(event).decode("latin-1")
                self.assertEqual(row["pc"], "")
                self.assertEqual(row["scenario_pc"], "")
                self.assertNotIn(f"Pc: {value}", pdf)

    def test_trajectory_csv_endpoint_marks_fresh_valid_empty_run(self) -> None:
        snapshot = SimpleNamespace(
            source="Bundled fallback TLE sample",
            source_summary=SimpleNamespace(object_count=7),
        )
        run = SimpleNamespace(events=[], summary={
            "status": "valid",
            "completion_status": "complete",
            "candidate_pair_count": 7,
            "candidate_local_minimum_count": 36,
            "refinement_count": 36,
            "close_approach_count": 0,
            "screening_horizon_start": "2026-10-11T00:00:00+00:00",
            "screening_horizon_end": "2026-10-12T00:00:00+00:00",
            "screening_threshold_km": 25.0,
        })
        with patch.object(main, "build_trajectory_context", new=AsyncMock(return_value=(snapshot, run))):
            with TestClient(main.app) as client:
                response = client.get("/api/reports/conjunctions.csv")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.text.startswith("event_id,event_identity_type"))
        rows = list(csv.DictReader(io.StringIO(response.text)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["record_type"], "export_metadata")
        self.assertEqual(rows[0]["screening_result_status"], "valid_empty")
        self.assertIn("not a previously completed Collision Analysis job", rows[0]["export_scope"])

    def test_trajectory_csv_endpoint_distinguishes_partial_and_failed_runs(self) -> None:
        snapshot = SimpleNamespace(
            source="Bundled fallback TLE sample",
            source_summary=SimpleNamespace(object_count=7),
        )
        outcomes = [
            ("partial", "partial", "partial"),
            ("unavailable", "failed", "failed"),
        ]
        for screening_status, completion_status, expected in outcomes:
            run = SimpleNamespace(events=[], summary={
                "status": screening_status,
                "completion_status": completion_status,
            })
            with self.subTest(expected=expected):
                with patch.object(main, "build_trajectory_context", new=AsyncMock(return_value=(snapshot, run))):
                    with TestClient(main.app) as client:
                        response = client.get("/api/reports/conjunctions.csv")
                rows = list(csv.DictReader(io.StringIO(response.text)))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(rows[0]["record_type"], "export_metadata")
                self.assertEqual(rows[0]["screening_result_status"], expected)

    def test_completed_job_csv_exports_exact_stored_partial_job_and_provenance(self) -> None:
        job_id = "0123456789abcdef0123456789abcdef"
        valid = {
            "id": "CA-valid", "event_identity_type": "trajectory_event_deterministic",
            "result_kind": "physics_assessment", "primary": {"id": "10114", "name": "A"},
            "secondary": {"id": "25544", "name": "B"},
            "physics_result": {
                "object_primary_id": "10114", "object_secondary_id": "25544",
                "tca": {"value": "2026-10-13T12:56:17.152617+00:00"},
                "miss_distance": {"value": 1.765},
                "relative_velocity_at_tca": {"value": [1, 2, 3]},
                "relative_speed_at_tca": {"value": 3.742}, "status": "valid", "reason_codes": [],
                "provenance": {"method": "SGP4", "input_hash": "hash", "source_record": {
                    "primary": {"raw_line1": "tle-1a"}, "secondary": {"raw_line1": "tle-1b"},
                }},
            },
        }
        invalid = {
            **valid, "id": "CA-invalid", "physics_result": {
                **valid["physics_result"], "status": "invalid",
                "reason_codes": ["identical_propagation_parameters_for_distinct_catalog_ids"],
            },
        }
        job = {"job_id": job_id, "status": "partial", "result": {
            "result_status": "partial", "physics_assessment_status": "partial",
            "source_summary": {"object_count": 120, "status": "fallback"},
            "screening": {"candidate_pair_count": 1894, "candidate_local_minimum_count": 6878, "refinement_count": 6878, "screening_threshold_km": 25.0},
            "data": [valid, invalid],
        }}
        async def completed_runtime_task() -> asyncio.Task:
            task = asyncio.create_task(asyncio.sleep(0))
            await task
            return task

        runtime_task = asyncio.run(completed_runtime_task())
        job["task"] = runtime_task
        job["created_monotonic"] = 123.0
        with tempfile.TemporaryDirectory() as archive_dir:
            with (
                patch.object(main, "SCREENING_EXPORT_ARCHIVE_DIR", Path(archive_dir)),
                patch.dict(main._screening_jobs, {job_id: job}),
                patch.object(main, "build_trajectory_context", new=AsyncMock(side_effect=AssertionError("must not start a new screening"))),
                TestClient(main.app) as client,
            ):
                response = client.get(f"/api/conjunction-jobs/{job_id}/reports/conjunctions.csv")
                active_task_after_export = main._screening_jobs[job_id]["task"]

            archived_job = json.loads((Path(archive_dir) / f"screening-job-{job_id}.json").read_text(encoding="utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-screening-job-id"], job_id)
        self.assertIn(job_id, response.headers["content-disposition"])
        headers = next(csv.reader(io.StringIO(response.text)))
        self.assertEqual(len(headers), len(set(headers)))
        rows = list(csv.DictReader(io.StringIO(response.text)))
        self.assertEqual([row["event_id"] for row in rows if row["record_type"] == "event"], ["CA-valid", "CA-invalid"])
        metadata = next(row for row in rows if row["record_type"] == "export_metadata")
        self.assertEqual(metadata["screening_job_id"], job_id)
        self.assertEqual(metadata["catalog_source"], "Bundled fallback TLE sample")
        self.assertEqual(metadata["export_screening_threshold_km"], "25.0")
        self.assertEqual(metadata["event_record_count"], "2")
        self.assertEqual(metadata["invalid_assessment_count"], "1")
        self.assertIn("identical_propagation_parameters_for_distinct_catalog_ids", rows[2]["physics_reason_codes"])
        self.assertIn("tle-1a", rows[1]["tle_source_records"])
        self.assertEqual(archived_job["status"], "partial")
        self.assertEqual([event["id"] for event in archived_job["result"]["data"]], ["CA-valid", "CA-invalid"])
        self.assertNotIn("task", archived_job)
        self.assertNotIn("created_monotonic", archived_job)
        self.assertIs(active_task_after_export, runtime_task)

    def test_archived_historical_job_exports_all_52_actual_records(self) -> None:
        job_id = "8fa7230ce99e4182afc2c1a8506130bf"
        with TestClient(main.app) as client:
            response = client.get(f"/api/conjunction-jobs/{job_id}/reports/conjunctions.csv")
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.text)))
        metadata = next(row for row in rows if row["record_type"] == "export_metadata")
        records = [row for row in rows if row["record_type"] == "event"]
        invalid = [row for row in records if row["physics_status"] == "invalid"]
        self.assertEqual(metadata["screening_job_id"], job_id)
        self.assertEqual(len(records), 52)
        self.assertEqual(len(invalid), 12)
        self.assertTrue(all(row["physics_reason_codes"] for row in invalid))

    def test_proxy_event_pdf_does_not_require_a_physics_result_kind_field(self) -> None:
        event = SimpleNamespace(
            id="SP-test",
            model_dump=lambda mode="json": {"id": "SP-test", "primary": {}, "secondary": {}},
        )
        with (
            patch.object(main, "build_event_context", new=AsyncMock(return_value=(None, [event]))),
            patch.object(main, "optimize_maneuver", return_value={}),
            patch.object(main, "event_report_pdf", return_value=b"%PDF-1.4 test"),
            TestClient(main.app) as client,
        ):
            response = client.get("/api/reports/SP-test.pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"%PDF-1.4 test")
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("SP-test-screening-proxy-report.pdf", response.headers["content-disposition"])

    def test_standalone_physical_event_pdf_requires_the_selected_job(self) -> None:
        with (
            patch.object(main, "build_trajectory_context", new=AsyncMock(side_effect=AssertionError("must use the selected stored job"))) as screen,
            patch.object(main, "event_report_pdf", return_value=b"%PDF-1.4") as render,
            TestClient(main.app) as client,
        ):
            response = client.get("/api/reports/CA-invalid-standalone.pdf")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["reason_code"], "SCREENING_JOB_REQUIRED")
        render.assert_not_called()
        screen.assert_not_awaited()


def stored_physical_event(event_id: str) -> dict:
    provenance = Provenance(source="fixture source", source_type="live", method="fixture", validity_status="valid")
    primary = ObjectSummary(id="25544", name="Primary", category="active", object_type="PAYLOAD", band="LEO", orbit_type="LEO", altitude_km=400, inclination_deg=51, velocity_kms=7.6, heuristic_risk_score=0.1, heuristic_forecast_score=0.1, provenance=provenance, heuristic_score_provenance=provenance)
    secondary = ObjectSummary(id="36086", name="Secondary", category="debris", object_type="SPACE_DEBRIS", band="LEO", orbit_type="LEO", altitude_km=410, inclination_deg=52, velocity_kms=7.5, heuristic_risk_score=0.1, heuristic_forecast_score=0.1, provenance=provenance, heuristic_score_provenance=provenance)
    physics = PhysicsResult(event_id=event_id, status="valid", applicability="fixture", provenance=provenance, object_primary_id=primary.id, object_secondary_id=secondary.id, tca_status="valid", state_information={"source_frame": "TEME", "position_units": "km", "velocity_units": "km/s"}, tca=ScientificField(status="available", value="2026-10-20T00:00:00+00:00", units="UTC"), miss_distance=ScientificField(status="available", value=1.0, units="km"), primary_state_at_tca={"object_id": primary.id, "epoch": "2026-10-20T00:00:00+00:00", "position_km": [7000, 0, 0], "velocity_km_s": [0, 7.5, 0], "frame": "TEME"}, secondary_state_at_tca={"object_id": secondary.id, "epoch": "2026-10-20T00:00:00+00:00", "position_km": [7001, 0, 0], "velocity_km_s": [0, 7.4, 0], "frame": "TEME"})
    return ConjunctionAssessmentEvent(id=event_id, primary=primary, secondary=secondary, obj_a=primary, obj_b=secondary, pair_type="PAYLOAD vs DEBRIS", provenance=provenance, physics_result=physics).model_dump(mode="json")


class SelectedJobEventReportTests(unittest.TestCase):
    def test_selected_event_csv_and_json_downloads_use_stored_job_data(self) -> None:
        job_id = "0123456789abcdef0123456789abcdef"
        event_id = "CA-selected-formats"
        stored_event = stored_physical_event(event_id)
        candidate = {"event_id": event_id, "screening_job_id": job_id, "direction": "along-track +", "delta_v_m_s": 0.01, "predicted_miss_distance_km": 1.3, "closest_approach_utc": "2026-10-20T00:00:01+00:00", "relative_velocity_km_s": [1, 2, 3], "research_pc_after": {"status": "unavailable"}}
        job = {"status": "complete", "result": {"data": [stored_event], "screening": {}}, "maneuver_results": {event_id: {"event_id": event_id, "screening_job_id": job_id, "status": "available", "zero_burn_baseline": {"event_id": event_id, "screening_job_id": job_id, "miss_distance_km": 1.2, "candidate": {"relative_velocity_km_s": [1, 2, 3], "closest_approach_utc": "2026-10-20T00:00:00+00:00"}}, "probability_before": {"status": "unavailable"}, "probability_after": {"status": "unavailable"}, "physics_candidates": {"event_id": event_id, "screening_job_id": job_id, "candidates": [candidate]}}}}
        with patch.dict(main._screening_jobs, {job_id: job}), patch.object(main, "build_trajectory_context", new=AsyncMock(side_effect=AssertionError("reports must not screen again"))), TestClient(main.app) as client:
            json_response = client.get(f"/api/conjunction-jobs/{job_id}/events/{event_id}/report.json")
            csv_response = client.get(f"/api/conjunction-jobs/{job_id}/events/{event_id}/assessment.csv")
        self.assertEqual(json_response.status_code, 200)
        payload = json_response.json()
        self.assertEqual(payload["screening_job_id"], job_id)
        self.assertEqual(payload["event_identity"]["event_id"], event_id)
        self.assertEqual(payload["maneuver"]["candidates"][0]["direction"], "along-track +")
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("event_specific_foster_pc", csv_response.text)
        self.assertIn("maneuver_candidate", csv_response.text)
        self.assertIn(job_id, json_response.headers["x-screening-job-id"])

    def test_selected_event_pdf_uses_stored_job_event_without_rescreening(self) -> None:
        job_id = "0123456789abcdef0123456789abcdef"
        event_id = "CA-selected"
        stored_event = stored_physical_event(event_id)
        stored_maneuver = {"event_id": event_id, "screening_job_id": job_id, "status": "available", "source": "same job"}
        screening_summary = {"screening_marker": "same job"}
        job = {
            "status": "complete",
            "result": {"data": [stored_event], "screening": screening_summary},
            "maneuver_results": {event_id: stored_maneuver},
        }
        with (
            patch.dict(main._screening_jobs, {job_id: job}),
            patch.object(main, "build_trajectory_context", new=AsyncMock(side_effect=AssertionError("event report must not start a new screen"))) as screening,
            patch.object(main, "event_report_pdf", return_value=b"%PDF-1.4 selected job") as render,
            TestClient(main.app) as client,
        ):
            response = client.get(f"/api/conjunction-jobs/{job_id}/events/{event_id}/report.pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"%PDF-1.4 selected job")
        self.assertEqual(render.call_args.args, (stored_event, stored_maneuver, {**screening_summary, "screening_job_id": job_id, "screening_job_status": "complete", "screening_job_archived": False}))
        self.assertEqual(render.call_args.args[0]["id"], event_id)
        self.assertEqual(render.call_args.args[0]["primary"]["id"], "25544")
        self.assertEqual(render.call_args.args[0]["secondary"]["id"], "36086")
        self.assertEqual(render.call_args.args[0]["provenance"]["source"], "fixture source")
        screening.assert_not_awaited()

    def test_selected_event_pdf_rejects_event_outside_requested_job(self) -> None:
        job_id = "1123456789abcdef0123456789abcdef"
        job = {"status": "complete", "result": {"data": [stored_physical_event("CA-other")]}}
        with (
            patch.dict(main._screening_jobs, {job_id: job}),
            patch.object(main, "event_report_pdf", return_value=b"%PDF-1.4") as render,
            TestClient(main.app) as client,
        ):
            response = client.get(f"/api/conjunction-jobs/{job_id}/events/CA-selected/report.pdf")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["reason_code"], "EVENT_NOT_FOUND")
        self.assertIn("not part of this screening job", response.json()["detail"]["message"])
        render.assert_not_called()

    def test_selected_event_pdf_preserves_archived_job_identity_and_labels_archive(self) -> None:
        job_id = "4123456789abcdef0123456789abcdef"
        event_id = "CA-archived-selected"
        job = {"status": "complete", "restored_from_archive": True,
               "result": {"data": [stored_physical_event(event_id)], "screening": {"completion_status": "complete"}}}
        with patch.dict(main._screening_jobs, {job_id: job}), patch.object(main, "event_report_pdf", return_value=b"%PDF-1.4") as render, TestClient(main.app) as client:
            response = client.get(f"/api/conjunction-jobs/{job_id}/events/{event_id}/report.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(render.call_args.args[0]["id"], event_id)
        self.assertEqual(render.call_args.args[2]["screening_job_id"], job_id)
        self.assertTrue(render.call_args.args[2]["screening_job_archived"])

    def test_selected_event_pdf_rejects_invalid_physical_validity(self) -> None:
        job_id = "5123456789abcdef0123456789abcdef"
        event = stored_physical_event("CA-invalid-report")
        event["physics_result"]["status"] = "invalid"
        job = {"status": "complete", "result": {"data": [event]}}
        with patch.dict(main._screening_jobs, {job_id: job}), patch.object(main, "event_report_pdf", return_value=b"%PDF-1.4") as render, TestClient(main.app) as client:
            response = client.get(f"/api/conjunction-jobs/{job_id}/events/CA-invalid-report/report.pdf")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["reason_code"], "EVENT_NOT_PHYSICALLY_VALID")
        render.assert_not_called()

    def test_selected_event_pdf_rejects_event_with_mismatched_job_identity(self) -> None:
        job_id = "6123456789abcdef0123456789abcdef"
        event = stored_physical_event("CA-cross-job")
        event["screening_job_id"] = "7123456789abcdef0123456789abcdef"
        job = {"status": "complete", "result": {"data": [event]}}
        with patch.dict(main._screening_jobs, {job_id: job}), patch.object(main, "event_report_pdf", return_value=b"%PDF-1.4") as render, TestClient(main.app) as client:
            response = client.get(f"/api/conjunction-jobs/{job_id}/events/CA-cross-job/report.pdf")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["reason_code"], "EVENT_JOB_MISMATCH")
        render.assert_not_called()

    def test_selected_event_pdf_rejects_proxy_as_physical_event(self) -> None:
        job_id = "8123456789abcdef0123456789abcdef"
        proxy = {"id": "SP-physical-report", "result_kind": "screening_proxy"}
        job = {"status": "complete", "result": {"data": [proxy]}}
        with patch.dict(main._screening_jobs, {job_id: job}), patch.object(main, "event_report_pdf", return_value=b"%PDF-1.4") as render, TestClient(main.app) as client:
            response = client.get(f"/api/conjunction-jobs/{job_id}/events/SP-physical-report/report.pdf")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["reason_code"], "DEMO_OR_PROXY_EVENT")
        render.assert_not_called()

    def test_selected_event_pdf_suppresses_maneuver_result_from_another_identity(self) -> None:
        job_id = "9123456789abcdef0123456789abcdef"
        event_id = "CA-maneuver-mismatch"
        job = {
            "status": "complete", "result": {"data": [stored_physical_event(event_id)]},
            "maneuver_results": {event_id: {"event_id": "CA-other", "screening_job_id": job_id, "status": "available", "probability_after": 0.0}},
        }
        with patch.dict(main._screening_jobs, {job_id: job}), patch.object(main, "event_report_pdf", return_value=b"%PDF-1.4") as render, TestClient(main.app) as client:
            response = client.get(f"/api/conjunction-jobs/{job_id}/events/{event_id}/report.pdf")
        self.assertEqual(response.status_code, 200)
        reported_maneuver = render.call_args.args[1]
        self.assertEqual(reported_maneuver["status"], "unavailable")
        self.assertEqual(reported_maneuver["reason_code"], "MANEUVER_RESULT_IDENTITY_MISMATCH")
        self.assertNotIn("probability_after", reported_maneuver)

    def test_selected_event_pdf_distinguishes_missing_and_incomplete_jobs(self) -> None:
        missing_id = "2123456789abcdef0123456789abcdef"
        incomplete_id = "3123456789abcdef0123456789abcdef"
        incomplete_job = {"status": "running", "result": None}
        with (
            patch.dict(main._screening_jobs, {incomplete_id: incomplete_job}),
            TestClient(main.app) as client,
        ):
            missing = client.get(f"/api/conjunction-jobs/{missing_id}/events/CA-selected/report.pdf")
            incomplete = client.get(f"/api/conjunction-jobs/{incomplete_id}/events/CA-selected/report.pdf")

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"]["reason_code"], "JOB_NOT_FOUND")
        self.assertIn("job was not found or has expired", missing.json()["detail"]["message"])
        self.assertEqual(incomplete.status_code, 409)
        self.assertEqual(incomplete.json()["detail"]["reason_code"], "JOB_NOT_TERMINAL")


def pc_report_event() -> dict:
    source = {
        "status": "available", "pc": 1e-7, "event_id": "CA-PC-EXPORT",
        "method": "Foster source", "method_version": "1.0", "applicability_status": "applicable",
        "hbr_km": 0.002, "hbr_source": "supplied",
        "hbr_provenance": {"source_type": "user_supplied", "units": "km", "description": "Source CDM HBR"},
        "covariance_status": "available", "covariance_frame": "TEME", "covariance_epoch": "2025-01-01T00:00:00+00:00",
        "covariance_sources": [{"object_id": "A", "source_type": "user_supplied", "frame": "TEME"}],
        "assumptions": ["source assumptions"], "warnings": [], "reason_codes": [],
        "independence_assumption_authorized": True,
        "provenance": {"source": "source CDM Foster assessment", "is_synthetic": False},
    }
    scenario = {
        "status": "available", "pc": 2e-7, "event_id": "CA-PC-EXPORT",
        "method": "Foster 2D scenario", "method_version": "1.0", "applicability_status": "applicable",
        "hbr_km": 0.004, "hbr_source": "synthetic",
        "hbr_provenance": {"source_type": "synthetic", "units": "km", "description": "User-assumed combined HBR"},
        "covariance_status": "available", "covariance_frame": "TEME", "covariance_epoch": "2025-01-01T00:00:00+00:00",
        "covariance_sources": [{"object_id": "A", "source_type": "synthetic", "frame": "TEME"}],
        "assumptions": ["independent covariance assumption authorized"], "warnings": [], "reason_codes": [],
        "independence_assumption_authorized": True,
        "provenance": {"source": "user-entered scenario", "is_synthetic": True},
    }
    return {
        "id": "CA-PC-EXPORT", "result_kind": "physics_assessment", "physics_result": {},
        "collision_probability": source, "scenario_collision_probability": scenario,
        "scenario_assumptions": ["RESEARCH SCENARIO ONLY", "user-entered covariance and HBR assumptions"],
    }


if __name__ == "__main__":
    unittest.main()
