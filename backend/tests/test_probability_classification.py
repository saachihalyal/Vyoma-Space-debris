from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from app.services.probability_classification import classify_orion_physics_pc


class OrionPhysicsPcRiskPolicyTests(unittest.TestCase):
    def test_score_and_classes_follow_inclusive_project_thresholds(self):
        high = classify_orion_physics_pc(1e-4, "research_pc")
        medium = classify_orion_physics_pc(1e-7, "research_pc")
        low = classify_orion_physics_pc(1e-8, "research_pc")
        self.assertEqual((high["risk_score"], high["physics_risk_class"]), (80.0, "High"))
        self.assertEqual((medium["risk_score"], medium["physics_risk_class"]), (50.0, "Medium"))
        self.assertEqual((low["risk_score"], low["physics_risk_class"]), (40.0, "Low"))
        self.assertEqual(high["risk_score_pc_channel"], "research_pc")
        self.assertEqual(high["final_risk_class"], high["physics_risk_class"])

    def test_score_uses_documented_logarithmic_mapping(self):
        result = classify_orion_physics_pc(1e-6, "event_specific_foster_pc")
        expected = min(100.0, max(0.0, ((math.log10(1e-6) + 12.0) / 10.0) * 100.0))
        self.assertAlmostEqual(result["risk_score"], expected)
        self.assertEqual(result["risk_score_pc_channel"], "event_specific_foster_pc")

    def test_zero_probability_uses_limiting_policy_without_positive_substitution(self):
        result = classify_orion_physics_pc(0.0, "research_pc")
        self.assertEqual(result["risk_score"], 0.0)
        self.assertEqual(result["physics_risk_class"], "Low")
        self.assertIn("Pc=0 is classified by the Pc->0 limit", result["boundary_policy"])
        self.assertIsNone(result["log10_pc"])

    def test_underflowed_positive_pc_keeps_its_log_domain_classification(self):
        result = classify_orion_physics_pc(None, "research_pc", log10_pc=-340.0)
        self.assertEqual(result["status"], "classified")
        self.assertEqual(result["risk_score"], 0.0)
        self.assertEqual(result["physics_risk_class"], "Low")
        self.assertEqual(result["log10_pc"], -340.0)

    def test_negative_infinity_log_is_only_valid_for_the_numeric_zero_boundary(self):
        self.assertEqual(
            classify_orion_physics_pc(None, "research_pc", log10_pc=float("-inf"))["status"],
            "unavailable",
        )
        self.assertEqual(
            classify_orion_physics_pc(0.0, "research_pc", log10_pc=float("-inf"))["status"],
            "classified",
        )
        self.assertEqual(
            classify_orion_physics_pc(0.0, "research_pc", log10_pc=-12.0)["reason_code"],
            "PC_LOG10_PC_MISMATCH",
        )

    def test_thresholds_are_configurable_and_invalid_configuration_is_explicit(self):
        with patch.dict("os.environ", {"ORION_RISK_HIGH_PC": "1e-3", "ORION_RISK_MEDIUM_PC": "1e-5"}):
            configured = classify_orion_physics_pc(1e-4, "research_pc")
        self.assertEqual(configured["physics_risk_class"], "Medium")
        self.assertEqual(configured["thresholds"], {"high_pc_inclusive": 1e-3, "medium_pc_inclusive": 1e-5})
        with patch.dict("os.environ", {"ORION_RISK_HIGH_PC": "1e-6", "ORION_RISK_MEDIUM_PC": "1e-5"}):
            invalid = classify_orion_physics_pc(1e-4, "research_pc")
        self.assertEqual(invalid["status"], "unavailable")
        self.assertEqual(invalid["reason_code"], "RISK_THRESHOLD_CONFIGURATION_INVALID")


if __name__ == "__main__":
    unittest.main()
