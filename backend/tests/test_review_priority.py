from __future__ import annotations

import unittest
import csv
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main
from app.models import PhysicsResult, Provenance, ScientificField, SourceSummary
from app.services.reports import conjunctions_csv, event_report_pdf
from app.services.review_priority import ReviewPriorityPolicy, classify_review_priority, configured_policy


def _physics(miss_km: float = 2.5) -> PhysicsResult:
    return PhysicsResult(
        event_id="EV-1", status="valid", tca_status="valid",
        provenance=Provenance(source="fixture", source_type="synthetic"),
        screening_horizon_start="2026-01-01T00:00:00Z",
        screening_horizon_end="2026-01-02T00:00:00Z",
        screening_threshold_km=25.0,
        tca=ScientificField(status="available", value="2026-01-01T01:00:00Z", units="UTC"),
        miss_distance=ScientificField(status="available", value=miss_km, units="km"),
    )


class ReviewPriorityTests(unittest.TestCase):
    def test_all_four_bands_use_documented_fraction_boundaries(self):
        cases = ((1.25, "CRITICAL"), (1.25001, "HIGH"), (5.0, "HIGH"),
                 (5.00001, "MEDIUM"), (15.0, "MEDIUM"), (15.00001, "LOW"))
        for miss_km, category in cases:
            with self.subTest(miss_km=miss_km):
                result = classify_review_priority(_physics(miss_km))
                self.assertEqual(result.category, category)
                self.assertEqual(result.status, "classified")
                self.assertIn("orion-geometry-review-v1", result.explanation)
                self.assertFalse(result.input_signals["ml_signal_used"])
                self.assertFalse(result.input_signals["pc_signal_used"])

    def test_invalid_or_boundary_events_require_review_without_category(self):
        invalid = _physics()
        invalid.status = "invalid"
        invalid.reason_codes = ["identical_propagation_parameters_for_distinct_catalog_ids"]
        result = classify_review_priority(invalid)
        self.assertEqual(result.category, "REVIEW_REQUIRED")
        self.assertEqual(result.reason_codes, invalid.reason_codes)
        self.assertIn(invalid.reason_codes[0], result.explanation)

        boundary = _physics()
        boundary.status = "boundary"
        boundary.tca_status = "boundary"
        self.assertEqual(classify_review_priority(boundary).category, "REVIEW_REQUIRED")

    def test_missing_geometry_is_unclassified_and_never_treated_as_zero(self):
        event = _physics()
        event.miss_distance = ScientificField(status="unavailable", value=None, units="km")
        result = classify_review_priority(event)
        self.assertEqual(result.category, "UNCLASSIFIED")
        self.assertIn("VALID_MISS_DISTANCE_REQUIRED", result.reason_codes)

    def test_ml_or_pc_disagreement_does_not_change_geometry_category(self):
        physics = _physics(2.0)
        without_ml = classify_review_priority(physics, ml_status="unavailable", pc_status="unavailable")
        with_ml = classify_review_priority(physics, ml_status="available", pc_status="available")
        self.assertEqual(without_ml.category, with_ml.category)
        self.assertFalse(with_ml.input_signals["ml_signal_used"])
        self.assertFalse(with_ml.input_signals["pc_signal_used"])

    def test_policy_is_configurable_versioned_and_rejects_overlapping_ranges(self):
        policy = configured_policy({
            "ORION_REVIEW_POLICY_VERSION": "orion-test-v2",
            "ORION_REVIEW_CRITICAL_MAX_FRACTION": "0.1",
            "ORION_REVIEW_HIGH_MAX_FRACTION": "0.3",
            "ORION_REVIEW_MEDIUM_MAX_FRACTION": "0.8",
        })
        self.assertEqual(classify_review_priority(_physics(3), policy=policy).category, "HIGH")
        self.assertEqual(classify_review_priority(_physics(3), policy=policy).policy_version, "orion-test-v2")
        bad = ReviewPriorityPolicy(critical_max_fraction=.4, high_max_fraction=.3, medium_max_fraction=.8)
        self.assertEqual(classify_review_priority(_physics(), policy=bad).category, "UNCLASSIFIED")

    def test_csv_export_keeps_category_policy_and_event_explanation(self):
        priority = classify_review_priority(_physics(3)).model_dump(mode="json")
        event = {"id": "EV-1", "result_kind": "physics_assessment", "physics_result": {}, "review_priority": priority}
        row = next(csv.DictReader(io.StringIO(conjunctions_csv([event]))))
        expected_band = {"CRITICAL": "Band 1", "HIGH": "Band 2", "MEDIUM": "Band 3", "LOW": "Band 4"}[priority["category"]]
        self.assertEqual(row["review_priority_category"], expected_band)
        self.assertEqual(row["review_priority_policy_version"], priority["policy_version"])
        self.assertEqual(row["review_priority_explanation"], priority["explanation"])
        pdf = event_report_pdf(event).decode("latin-1")
        self.assertIn(f"Geometry review band: {expected_band}", pdf)
        self.assertNotIn(priority["category"], pdf)
        self.assertIn(priority["policy_version"], pdf)
        self.assertIn("Vyoma geometry-only review priority", pdf)

    def test_health_and_openapi_report_review_policy_and_capabilities(self):
        source_summary = SourceSummary(status="all_live", counts_by_source_type={"live": 1}, object_count=1)
        snapshot = SimpleNamespace(
            source_summary=source_summary,
            source_state={"status": "live", "last_success_at": "2026-10-20T00:00:00Z"},
            source="CelesTrak", objects=[object()], risk_cells=[],
            stats=SimpleNamespace(
                tracked_objects=1, unavailable_objects=0, active_satellites=1, debris_objects=0,
            ),
        )
        with patch.object(main, "build_snapshot", new=AsyncMock(return_value=snapshot)), \
                patch.object(main, "build_event_context", new=AsyncMock(return_value=(snapshot, []))), \
                TestClient(main.app) as client:
            openapi = client.get("/openapi.json")
            health = client.get("/api/health")
            system_health = client.get("/api/system-health")
        self.assertEqual(openapi.status_code, 200)
        self.assertIn("ReviewPriority", openapi.json()["components"]["schemas"])
        self.assertEqual(health.json()["screening_readiness"], "configured; screening runs require an explicit request")
        self.assertEqual(health.json()["review_priority_policy"]["status"], "available")
        self.assertEqual(system_health.json()["data"]["physical_pc_availability"], "input_dependent; live catalog covariance and hard-body radius are not provided")


if __name__ == "__main__":
    unittest.main()
