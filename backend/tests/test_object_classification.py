from __future__ import annotations

import csv
import io
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.services.object_classification import classify_object, pair_type_for
from app.services.conjunction import _object_summary as proxy_object_summary
from app.services.orbit import propagate_records
from app.services.reports import conjunctions_csv, event_report_pdf
from app.services.tle_provider import FALLBACK_TLES, parse_tle_text
from app.services.trajectory_screening import _object_summary as physical_object_summary
from app import main


class ObjectClassificationTests(unittest.TestCase):
    def test_catalog_types_and_name_inference_precede_group_fallback(self):
        cases = [
            (classify_object(name="SL-3 R/B", source_group="stations"), "ROCKET_BODY", "name_pattern"),
            (classify_object(name="COSMOS 2251 DEB", source_group="stations"), "SPACE_DEBRIS", "name_pattern"),
            (classify_object(name="PAYLOAD 12345", source_group="debris"), "ACTIVE_SATELLITE", "name_pattern"),
            (classify_object(name="ISS (ZARYA)"), "SPACE_STATION", "name_pattern"),
            (classify_object(object_type="PAYLOAD", name="SL-3 R/B"), "ROCKET_BODY", "name_pattern"),
            (classify_object(source_group="stations"), "ACTIVE_SATELLITE", "group_based_fallback"),
        ]
        for result, object_type, source in cases:
            with self.subTest(result=result):
                self.assertEqual(result.object_type, object_type)
                self.assertEqual(result.classification_source, source)

    def test_authoritative_source_types_cover_supported_classes(self) -> None:
        expected = {
            "PAYLOAD": ("payload", "ACTIVE_SATELLITE"),
            "DEBRIS": ("debris", "SPACE_DEBRIS"),
            "ROCKET BODY": ("rocket_body", "ROCKET_BODY"),
            "UNKNOWN / OTHER": ("unknown", "UNKNOWN"),
        }
        for source_type, result in expected.items():
            with self.subTest(source_type=source_type):
                classified = classify_object(source_classification=source_type)
                self.assertEqual((classified.category, classified.object_type), result)

    def test_missing_metadata_stays_unknown_but_known_name_is_classified(self) -> None:
        self.assertEqual(classify_object().object_type, "UNKNOWN")
        self.assertEqual(classify_object().category, "unknown")
        self.assertEqual(classify_object(name="COSMOS 2251 DEB").object_type, "SPACE_DEBRIS")
        self.assertEqual(classify_object(source_group="unclassified").object_type, "UNKNOWN")

    def test_catalog_object_type_wins_over_conflicting_legacy_metadata(self) -> None:
        conflict = classify_object(object_type="PAYLOAD", source_classification="DEBRIS")
        unsupported = classify_object(source_classification="NONSTANDARD CLASS")
        self.assertEqual(conflict.classification_source, "catalog_object_type")
        self.assertEqual(conflict.object_type, "ACTIVE_SATELLITE")
        self.assertEqual(unsupported.object_type, "UNKNOWN")

    def test_authoritative_metadata_precedes_catalog_group_fallback(self) -> None:
        classified = classify_object(source_classification="DEBRIS", source_group="stations")
        self.assertEqual((classified.category, classified.object_type), ("debris", "SPACE_DEBRIS"))
        self.assertEqual(classified.classification_source, "source_classification")

    def test_pair_labels_preserve_each_objects_own_classification(self) -> None:
        self.assertEqual(pair_type_for("ACTIVE_SATELLITE", "SPACE_DEBRIS"), "SATELLITE vs DEBRIS")
        self.assertEqual(pair_type_for("ACTIVE_SATELLITE", "ACTIVE_SATELLITE"), "SATELLITE vs SATELLITE")
        self.assertEqual(pair_type_for("ROCKET_BODY", "ACTIVE_SATELLITE"), "SATELLITE vs ROCKET BODY")
        self.assertEqual(pair_type_for("UNKNOWN", "ACTIVE_SATELLITE"), "SATELLITE vs UNKNOWN")

    def test_live_curated_groups_and_fallback_records_are_distinguished(self) -> None:
        lines = "\n".join(FALLBACK_TLES.splitlines()[:3])
        live_record = parse_tle_text(lines, "stations")[0]
        fallback_record = parse_tle_text(lines, "fallback", source_type="fallback")[0]
        live, _, _ = propagate_records([live_record], limit=1)
        fallback, _, _ = propagate_records([fallback_record], limit=1)
        self.assertEqual((live[0].object_type, live[0].classification_source), ("ACTIVE_SATELLITE", "group_based_fallback"))
        self.assertEqual((fallback[0].object_type, fallback[0].category), ("UNKNOWN", "unknown"))
        self.assertEqual(fallback[0].provenance.source_type, "fallback")

    def test_debris_group_classifies_both_members_independently_in_api_and_report(self) -> None:
        debris_record = parse_tle_text(lines_for_id("00005"), "cosmos_debris")[0]
        payload_record = parse_tle_text(lines_for_id("25544"), "stations")[0]
        objects, _, _ = propagate_records([debris_record, payload_record], limit=2)
        for obj in objects:
            self.assertEqual(proxy_object_summary(obj).object_type, obj.object_type)
            self.assertEqual(physical_object_summary(obj).object_type, obj.object_type)
        event = {
            "id": "classification-event",
            "result_kind": "screening_proxy",
            "primary": {"id": objects[0].id, "name": objects[0].name, "category": objects[0].category,
                        "object_type": objects[0].object_type, "source_classification": objects[0].source_classification,
                        "classification_source": objects[0].classification_source, "band": "LEO", "altitude_km": 500},
            "secondary": {"id": objects[1].id, "name": objects[1].name, "category": objects[1].category,
                          "object_type": objects[1].object_type, "source_classification": objects[1].source_classification,
                          "classification_source": objects[1].classification_source, "band": "LEO", "altitude_km": 500},
            "pair_type": "SATELLITE vs DEBRIS", "risk_score": 0.1, "priority_score": 1,
            "risk_level": "Low", "provenance": {"source_type": "live", "method": "test", "method_version": "1"},
            "physics_result": {"status": "unavailable", "reason_codes": []},
            "ml_result": {"status": "unavailable", "reason_code": "not_applicable"},
            "suggested_action": "Review", "event_identity_type": "internal_deterministic",
        }
        row = next(csv.DictReader(io.StringIO(conjunctions_csv([event]))))
        self.assertEqual(row["object_primary_type"], "SPACE_DEBRIS")
        self.assertEqual(row["object_secondary_type"], "SPACE_STATION")
        pdf = event_report_pdf(event).decode("latin-1")
        self.assertIn("SPACE_DEBRIS", pdf)
        self.assertIn("SPACE_STATION", pdf)
        self.assertEqual(objects[0].provenance.source_type, "live")

    def test_catalog_api_returns_canonical_classification_fields(self) -> None:
        record = parse_tle_text(lines_for_id("00005"), "cosmos_debris")[0]
        objects, _, _ = propagate_records([record], limit=1)
        snapshot = SimpleNamespace(
            objects=objects, unavailable_objects=[], stats=SimpleNamespace(model_dump=lambda **_: {}),
            source="CelesTrak live GP/TLE", source_summary=SimpleNamespace(model_dump=lambda **_: {}),
        )
        with patch.object(main, "build_snapshot", new=AsyncMock(return_value=snapshot)):
            response = TestClient(main.app).get("/api/objects?limit=25")
        self.assertEqual(response.status_code, 200)
        obj = response.json()["data"]["objects"][0]
        self.assertEqual(obj["object_type"], "SPACE_DEBRIS")
        self.assertEqual(obj["classification_source"], "group_based_fallback")
        self.assertEqual(obj["provenance"]["source_record"]["source_group"], "cosmos_debris")


def lines_for_id(catalog_id: str) -> str:
    rows = FALLBACK_TLES.splitlines()
    for index in range(0, len(rows), 3):
        if rows[index + 1][2:7] == catalog_id:
            return "\n".join(rows[index:index + 3])
    raise AssertionError(f"No bundled fixture with catalog ID {catalog_id}")

