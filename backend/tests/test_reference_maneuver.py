from __future__ import annotations

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.services.cdm_ingestion import parse_cdm_input


FIXTURE = Path(__file__).parent / "fixtures" / "nasa_cara_pc_reference.cdm"
CDM = parse_cdm_input(FIXTURE.read_text(encoding="utf-8"), source_label="test reference CDM")
EVENT_ID = f"CDM-{CDM.input_sha256[:24]}"


class ReferenceManeuverWorkflowTests(unittest.TestCase):
    def test_reference_event_maneuver_recalculates_geometry_and_shared_covariance_pc(self) -> None:
        with TestClient(main.app) as client:
            response = client.post("/api/collision-probability/reference-cases/nasa-cara-foster-2d/maneuver", json={
                "event_id": EVENT_ID,
                "maneuvering_object_id": "000020580",
                "burn_lead_seconds": 300,
                "direction": "along_track+",
                "delta_v_m_s": 0.05,
            })
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        result = payload["data"]
        self.assertEqual(payload["result_kind"], "standalone_reference_cdm_maneuver_assessment")
        self.assertEqual(result["event_id"], EVENT_ID)
        self.assertEqual(result["maneuver"]["object_id"], "000020580")
        self.assertEqual(result["maneuver"]["direction"], "along_track+")
        self.assertNotEqual(
            result["candidate_two_body_geometry"]["miss_distance_km"],
            result["zero_burn_two_body_baseline"]["miss_distance_km"],
        )
        baseline = result["zero_burn_two_body_baseline"]
        candidate = result["candidate_two_body_geometry"]
        self.assertGreaterEqual(baseline["relative_velocity_km_s"], 0)
        self.assertGreaterEqual(candidate["relative_velocity_km_s"], 0)
        expected_change = candidate["miss_distance_km"] - baseline["miss_distance_km"]
        self.assertAlmostEqual(candidate["change_from_zero_burn_baseline_km"], expected_change)
        self.assertAlmostEqual(
            candidate["change_from_zero_burn_baseline_percent"],
            100 * expected_change / baseline["miss_distance_km"],
        )
        self.assertEqual(candidate["percentage_change_status"], "available")
        self.assertEqual(result["probability_before"]["status"], "available")
        self.assertIsNotNone(result["probability_before"]["pc"])
        self.assertIsNotNone(result["probability_after"]["pc"])
        self.assertEqual(result["probability_change"]["status"], "available")
        self.assertAlmostEqual(result["probability_change"]["value"], result["probability_before"]["pc"] - result["probability_after"]["pc"])
        self.assertTrue(any("held fixed" in item for item in result["assumptions"]))
        self.assertEqual(result["fuel"]["status"], "unavailable")
        self.assertEqual(payload["input_provenance"]["live_screening_binding"], "none")

    def test_reference_maneuver_rejects_wrong_event_and_object(self) -> None:
        body = {
            "event_id": EVENT_ID,
            "maneuvering_object_id": "000020580",
            "burn_lead_seconds": 300,
            "direction": "radial+",
            "delta_v_m_s": 0.01,
        }
        with TestClient(main.app) as client:
            wrong_event = client.post("/api/collision-probability/reference-cases/nasa-cara-foster-2d/maneuver", json={**body, "event_id": "CDM-wrong"})
            wrong_object = client.post("/api/collision-probability/reference-cases/nasa-cara-foster-2d/maneuver", json={**body, "maneuvering_object_id": "999999"})
        self.assertEqual(wrong_event.status_code, 404)
        self.assertEqual(wrong_object.status_code, 422)

    def test_reference_maneuver_rejects_out_of_range_inputs(self) -> None:
        body = {
            "event_id": EVENT_ID,
            "maneuvering_object_id": "000020580",
            "burn_lead_seconds": 20,
            "direction": "radial+",
            "delta_v_m_s": 0.01,
        }
        with TestClient(main.app) as client:
            response = client.post("/api/collision-probability/reference-cases/nasa-cara-foster-2d/maneuver", json=body)
        self.assertEqual(response.status_code, 422)

    def test_reference_maneuver_report_repeats_parameterized_result(self) -> None:
        with TestClient(main.app) as client:
            response = client.get("/api/collision-probability/reference-cases/nasa-cara-foster-2d/maneuver-report.pdf", params={
                "event_id": EVENT_ID,
                "maneuvering_object_id": "000020580",
                "burn_lead_seconds": 300,
                "direction": "along_track+",
                "delta_v_m_s": 0.05,
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn(b"Before Pc", response.content)
        self.assertIn(b"Pc reduction:", response.content)
        self.assertIn(b"Geometric miss-distance percentage change", response.content)
        self.assertIn(EVENT_ID.encode(), response.content)

    def test_reference_maneuver_accepts_one_orbit_lead_time(self) -> None:
        result = main._reference_maneuver_result(main.ReferenceManeuverRequest(
            event_id=EVENT_ID,
            maneuvering_object_id="000020580",
            burn_lead_seconds=5400,
            direction="along_track+",
            delta_v_m_s=0.05,
        ))
        self.assertEqual(result["maneuver"]["lead_before_reference_tca_seconds"], 5400)
        self.assertEqual(result["probability_before"]["status"], "available")


if __name__ == "__main__":
    unittest.main()
