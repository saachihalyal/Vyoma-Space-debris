from __future__ import annotations

import math
import unittest

import numpy as np

from app.services.collision_probability import (
    CovarianceInput,
    HardBodyRadiusInput,
    calculate_foster_2d,
    small_hbr_pc_approximation,
)
from app.services.probability_classification import classify_probability_pc


TCA = "2025-01-01T00:00:00+00:00"
UNITS_3D = {"position": "km^2"}
UNITS_6D = {
    "position": "km^2",
    "velocity": "km^2/s^2",
    "position_velocity_cross": "km^2/s",
}


class Foster2DReferenceTests(unittest.TestCase):
    def test_small_hbr_approximation_matches_full_integral_in_its_local_regime(self) -> None:
        sigma = 1.2
        radius = 1e-3
        args = assessment_args(miss_km=0.4, sigma_km=sigma, hbr_km=radius)
        full = calculate_foster_2d(**args)
        approximate = small_hbr_pc_approximation(
            np.asarray([0.4, 0.0]), np.diag([sigma**2, sigma**2]), radius,
        )
        self.assertEqual(full.status, "available")
        self.assertAlmostEqual(approximate, full.pc, delta=full.pc * 1e-6)

    def test_seeded_monte_carlo_cross_checks_centered_isotropic_foster_case(self) -> None:
        sigma = 2.0
        hbr = 1.0
        result = calculate_foster_2d(**assessment_args(miss_km=0.0, sigma_km=sigma, hbr_km=hbr))
        samples = np.random.default_rng(4107).normal(0.0, sigma, size=(300_000, 2))
        observed = float(np.mean(np.sum(samples * samples, axis=1) <= hbr * hbr))
        standard_error = math.sqrt(result.pc * (1.0 - result.pc) / len(samples))
        self.assertEqual(result.status, "available")
        self.assertLessEqual(abs(observed - result.pc), 5.0 * standard_error + 1.0 / len(samples))

    def test_seeded_monte_carlo_cross_checks_offcenter_foster_case(self) -> None:
        sigma = 0.75
        hbr = 0.4
        result = calculate_foster_2d(**assessment_args(miss_km=1.2, sigma_km=sigma, hbr_km=hbr))
        samples = np.random.default_rng(4113).multivariate_normal(
            [1.2, 0.0], np.eye(2) * sigma**2, size=300_000,
        )
        observed = float(np.mean(np.sum(samples * samples, axis=1) <= hbr * hbr))
        standard_error = math.sqrt(result.pc * (1.0 - result.pc) / len(samples))
        self.assertEqual(result.status, "available")
        self.assertLessEqual(abs(observed - result.pc), 5.0 * standard_error + 1.0 / len(samples))

    def test_research_pc_is_monotonic_as_mean_moves_toward_collision_center(self) -> None:
        probabilities = [
            calculate_foster_2d(**assessment_args(miss_km=miss, sigma_km=1.0, hbr_km=0.25)).pc
            for miss in (0.0, 0.25, 0.5, 1.0, 2.0)
        ]
        self.assertTrue(all(value is not None for value in probabilities))
        self.assertTrue(all(near >= far for near, far in zip(probabilities, probabilities[1:])))

    def test_nasa_reference_classification_threshold_boundaries_are_strict(self) -> None:
        self.assertEqual(classify_probability_pc(1e-7)["category"], "AT_OR_BELOW_NASA_ATTENTION_REFERENCE")
        self.assertEqual(classify_probability_pc(1.0000001e-7)["category"], "ABOVE_NASA_ATTENTION_BELOW_MITIGATION_REFERENCE")
        self.assertEqual(classify_probability_pc(1e-4)["category"], "ABOVE_NASA_ATTENTION_BELOW_MITIGATION_REFERENCE")
        self.assertEqual(classify_probability_pc(1.0000001e-4)["category"], "ABOVE_NASA_MITIGATION_REFERENCE")
        self.assertEqual(classify_probability_pc(None)["status"], "unavailable")
        self.assertIsNone(classify_probability_pc(0.0)["category"])

    def test_isotropic_zero_miss_matches_independent_rayleigh_reference(self) -> None:
        sigma = 2.0
        hbr_km = 1.0
        result = calculate_foster_2d(
            **assessment_args(
                miss_km=0.0,
                sigma_km=sigma,
                hbr_km=hbr_km,
                covariance_dimension=3,
            )
        )

        # For a centered isotropic 2D Gaussian, radial distance is Rayleigh;
        # integrating its density from zero to R gives 1-exp(-R^2/(2*sigma^2)).
        expected = -math.expm1(-(hbr_km**2) / (2.0 * sigma**2))
        self.assertEqual(result.status, "available")
        self.assertAlmostEqual(result.pc or 0.0, expected, delta=1e-10)
        self.assertEqual(result.covariance_status, "available")
        self.assertEqual(result.applicability_status, "applicable")
        self.assertGreater(result.evaluations or 0, 0)
        self.assertEqual(result.risk_assessment.risk_score_pc_channel, "event_specific_foster_pc")
        self.assertEqual(result.risk_assessment.physics_risk_class, "High")
        self.assertEqual(result.risk_assessment.final_risk_class, result.risk_assessment.physics_risk_class)

    def test_anisotropic_centered_case_matches_independent_cartesian_reference(self) -> None:
        # Reference: 1D adaptive integration of x's marginal density times
        # the conditional y probability over each vertical disk slice. Inputs
        # are mean=(0, 0) km, Sigma=diag(0.25, 4.0) km^2, R=0.7 km.
        args = assessment_args(miss_km=0.0, sigma_km=1.0, hbr_km=0.7)
        half_covariance = np.diag([0.125, 0.5, 2.0])
        args["covariance_1"] = covariance("A", half_covariance)
        args["covariance_2"] = covariance("B", half_covariance)
        result = calculate_foster_2d(**args)
        self.assertEqual(result.status, "available")
        self.assertAlmostEqual(result.pc or 0.0, 0.19394188550444136, delta=2e-10)

    def test_isotropic_offcenter_case_matches_independent_cartesian_reference(self) -> None:
        # mean=(1.2, 0) km, Sigma=diag(0.5625, 0.5625) km^2, R=0.4 km.
        result = calculate_foster_2d(**assessment_args(
            miss_km=1.2, sigma_km=0.75, hbr_km=0.4,
        ))
        self.assertEqual(result.status, "available")
        self.assertAlmostEqual(result.pc or 0.0, 0.040235078885898626, delta=2e-10)

    def test_anisotropic_offcenter_case_matches_independent_cartesian_reference(self) -> None:
        # The encounter-plane covariance is [[0.25, 0.25], [0.25, 2.89]] km^2;
        # mean=(1, 0) km and R=0.45 km. Each object supplies half this matrix.
        args = assessment_args(miss_km=1.0, sigma_km=1.0, hbr_km=0.45)
        half_covariance = np.asarray([
            [0.125, 0.0, -0.125],
            [0.0, 0.5, 0.0],
            [-0.125, 0.0, 1.445],
        ])
        args["covariance_1"] = covariance("A", half_covariance)
        args["covariance_2"] = covariance("B", half_covariance)
        result = calculate_foster_2d(**args)
        self.assertEqual(result.status, "available")
        self.assertAlmostEqual(result.pc or 0.0, 0.01881386057219643, delta=2e-10)

    def test_numerical_stress_ranges_are_bounded_and_explicit(self) -> None:
        # Small and large HBR/sigma ratios are numerical stress inputs, not
        # operational encounter statistics. The centered small-disk limit is
        # approximately R^2/(2 sigma^2), which is representable and nonzero.
        tiny_but_representable = calculate_foster_2d(**assessment_args(
            miss_km=0.0, sigma_km=1.0, hbr_km=1e-8,
        ))
        self.assertEqual(tiny_but_representable.status, "available")
        self.assertAlmostEqual(tiny_but_representable.pc or 0.0, 5e-17, delta=2e-25)

        large_disk = calculate_foster_2d(**assessment_args(
            miss_km=0.0, sigma_km=1.0, hbr_km=5.0,
        ))
        self.assertEqual(large_disk.status, "available")
        self.assertGreater(large_disk.pc or 0.0, 0.99999)
        self.assertLessEqual(large_disk.pc or 2.0, 1.0)

        # A positive-definite but extremely ill-conditioned encounter-plane
        # covariance is accepted by covariance validation; the bounded
        # production quadrature does not converge for this stress case and
        # must expose that as NUMERICAL_FAILURE, never as an available Pc.
        near_singular = np.asarray([
            [0.5, 0.0, 0.4999995],
            [0.0, 0.5, 0.0],
            [0.4999995, 0.0, 0.5],
        ])
        args = assessment_args(miss_km=0.2, sigma_km=1.0, hbr_km=0.6)
        args["covariance_1"] = covariance("A", near_singular)
        args["covariance_2"] = covariance("B", near_singular)
        ill_conditioned = calculate_foster_2d(**args)
        self.assertEqual(ill_conditioned.covariance_status, "available")
        self.assertEqual(ill_conditioned.status, "invalid")
        self.assertIn("NUMERICAL_FAILURE", ill_conditioned.reason_codes)
        self.assertIsNone(ill_conditioned.pc)

        # A probability below binary64's representable range is correctly
        # unavailable as a numeric result rather than fabricated as zero.
        underflow = calculate_foster_2d(**assessment_args(
            miss_km=0.0, sigma_km=1.0, hbr_km=1e-170,
        ))
        self.assertEqual(underflow.status, "invalid")
        self.assertIn("NUMERICAL_FAILURE", underflow.reason_codes)
        self.assertIsNone(underflow.pc)

    def test_strongly_anisotropic_case_matches_independent_reference(self) -> None:
        # mean=(0.3, 0) km, Sigma=diag(0.0064, 6.25) km^2, R=0.5 km.
        args = assessment_args(miss_km=0.3, sigma_km=1.0, hbr_km=0.5)
        half_covariance = np.diag([0.0032, 0.25, 3.125])
        args["covariance_1"] = covariance("A", half_covariance)
        args["covariance_2"] = covariance("B", half_covariance)
        result = calculate_foster_2d(**args)
        self.assertEqual(result.status, "available")
        self.assertAlmostEqual(result.pc or 0.0, 0.12241465361254343, delta=2e-10)

    def test_pc_is_bounded_and_large_miss_is_small_but_not_fabricated_zero(self) -> None:
        result = calculate_foster_2d(**assessment_args(miss_km=15.0, sigma_km=1.0, hbr_km=0.1))
        self.assertEqual(result.status, "available")
        self.assertIsNotNone(result.pc)
        self.assertGreaterEqual(result.pc or -1.0, 0.0)
        self.assertLessEqual(result.pc or 2.0, 1.0)
        self.assertGreater(result.pc or 0.0, 0.0)
        self.assertLess(result.pc or 1.0, 1e-40)

    def test_near_zero_miss_and_larger_hbr_increase_probability(self) -> None:
        small_hbr = calculate_foster_2d(**assessment_args(miss_km=1e-10, sigma_km=1.0, hbr_km=0.5))
        large_hbr = calculate_foster_2d(**assessment_args(miss_km=1e-10, sigma_km=1.0, hbr_km=1.0))
        self.assertEqual(small_hbr.status, "available")
        self.assertEqual(large_hbr.status, "available")
        self.assertGreater(large_hbr.pc or 0.0, small_hbr.pc or 0.0)
        self.assertTrue(any("Zero miss" in warning for warning in small_hbr.warnings))

    def test_increasing_uncertainty_reduces_centered_probability(self) -> None:
        tighter = calculate_foster_2d(**assessment_args(miss_km=0.0, sigma_km=1.0, hbr_km=1.0))
        wider = calculate_foster_2d(**assessment_args(miss_km=0.0, sigma_km=2.0, hbr_km=1.0))
        self.assertEqual(tighter.status, "available")
        self.assertEqual(wider.status, "available")
        self.assertGreater(tighter.pc or 0.0, wider.pc or 0.0)

    def test_swapping_objects_preserves_probability_for_independent_covariances(self) -> None:
        covariance_1 = covariance("A", np.diag([0.2, 0.8, 0.5]))
        covariance_2 = covariance("B", np.diag([0.6, 0.3, 0.4]))
        forward = calculate_foster_2d(**assessment_args(
            miss_km=2.5, sigma_km=1.0, hbr_km=0.7,
            covariance_1=covariance_1, covariance_2=covariance_2,
        ))
        reverse = calculate_foster_2d(
            **assessment_args(
                miss_km=2.5,
                sigma_km=1.0,
                hbr_km=0.7,
                covariance_1=covariance("B", np.diag([0.6, 0.3, 0.4])),
                covariance_2=covariance("A", np.diag([0.2, 0.8, 0.5])),
                object_1_id="B",
                object_2_id="A",
                swap=True,
            )
        )
        self.assertEqual(forward.status, "available")
        self.assertEqual(reverse.status, "available")
        self.assertAlmostEqual(forward.pc or 0.0, reverse.pc or 0.0, delta=1e-12)

    def test_common_frame_rotation_preserves_anisotropic_probability(self) -> None:
        args = assessment_args(
            miss_km=0.0,
            sigma_km=1.0,
            hbr_km=0.3,
            covariance_1=covariance("A", [
                [0.3, 0.02, 0.05],
                [0.02, 0.5, 0.04],
                [0.05, 0.04, 0.8],
            ]),
            covariance_2=covariance("B", [
                [0.2, 0.01, -0.03],
                [0.01, 0.4, 0.02],
                [-0.03, 0.02, 0.6],
            ]),
        )
        args.update({
            "position_1_km": (0.0, 0.0, 0.0),
            "position_2_km": (0.4, 0.0, 0.3),
            "velocity_1_km_s": (0.0, 0.0, 0.0),
            "velocity_2_km_s": (0.0, 7.0, 0.0),
        })
        baseline = calculate_foster_2d(**args)

        angle = 1.13
        rotation = np.asarray([
            [math.cos(angle), 0.0, math.sin(angle)],
            [0.0, 1.0, 0.0],
            [-math.sin(angle), 0.0, math.cos(angle)],
        ])
        rotated = dict(args)
        for key in ("position_1_km", "position_2_km", "velocity_1_km_s", "velocity_2_km_s"):
            rotated[key] = rotation @ np.asarray(args[key], dtype=float)
        for key in ("covariance_1", "covariance_2"):
            item = args[key]
            rotated[key] = CovarianceInput(
                object_id=item.object_id,
                frame=item.frame,
                epoch=item.epoch,
                matrix=rotation @ np.asarray(item.matrix) @ rotation.T,
                units=item.units,
                source=item.source,
                source_type=item.source_type,
                source_timestamp=item.source_timestamp,
                input_hash=item.input_hash,
                is_synthetic=item.is_synthetic,
                validity_status=item.validity_status,
            )

        transformed = calculate_foster_2d(**rotated)
        self.assertEqual(baseline.status, "available")
        self.assertEqual(transformed.status, "available")
        self.assertAlmostEqual(baseline.pc, transformed.pc, delta=1e-12)

    def test_six_state_covariance_contract_preserves_mixed_units(self) -> None:
        matrix = np.diag([0.5, 0.5, 0.5, 1e-6, 1e-6, 1e-6])
        result = calculate_foster_2d(**assessment_args(
            miss_km=0.2,
            sigma_km=1.0,
            hbr_km=0.3,
            covariance_1=covariance("A", matrix, units=UNITS_6D),
            covariance_2=covariance("B", matrix, units=UNITS_6D),
            covariance_dimension=6,
        ))
        self.assertEqual(result.status, "available")
        self.assertEqual(result.covariance_sources[0].matrix_dimension, 6)
        self.assertEqual(result.covariance_sources[0].units["position_velocity_cross"], "km^2/s")
        self.assertTrue(any("only the 3x3 position-position block" in item for item in result.assumptions))
        self.assertTrue(any("no state-covariance propagation" in item for item in result.warnings))

    def test_roundoff_symmetrization_is_recorded_in_provenance(self) -> None:
        nearly_symmetric = [[1.0, 1e-13, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        result = calculate_foster_2d(**assessment_args(
            miss_km=0.2,
            sigma_km=1.0,
            hbr_km=0.3,
            covariance_1=covariance("A", nearly_symmetric),
            covariance_2=covariance("B", np.eye(3)),
        ))
        self.assertEqual(result.status, "available")
        self.assertIn("symmetrized_within_tolerance", result.covariance_sources[0].normalization_operations)


class Foster2DFailureStateTests(unittest.TestCase):
    def test_missing_covariance_and_hbr_are_machine_readable(self) -> None:
        no_covariance = calculate_foster_2d(**assessment_args(
            miss_km=1.0,
            sigma_km=1.0,
            hbr_km=1.0,
            covariance_1=None,
            covariance_2=None,
            covariance_dimension=0,
        ))
        no_hbr = calculate_foster_2d(**assessment_args(miss_km=1.0, sigma_km=1.0, hbr_km=None))
        self.assertEqual(no_covariance.status, "unavailable")
        self.assertIn("NO_COVARIANCE", no_covariance.reason_codes)
        self.assertIsNone(no_covariance.pc)
        self.assertEqual(no_hbr.status, "unavailable")
        self.assertIn("HBR_UNAVAILABLE", no_hbr.reason_codes)
        self.assertIsNone(no_hbr.hbr_km)
        self.assertIsNone(no_hbr.pc)

    def test_malformed_hbr_is_invalid_without_raising_or_emitting_pc(self) -> None:
        args = assessment_args(miss_km=1.0, sigma_km=1.0, hbr_km=1.0)
        args["hbr"] = HardBodyRadiusInput(
            value_km="not-a-number",  # type: ignore[arg-type]
            source="supplied",
            source_type="live",
            description="Malformed test input",
        )
        result = calculate_foster_2d(**args)
        self.assertEqual(result.status, "invalid")
        self.assertIn("INVALID_HBR", result.reason_codes)
        self.assertIsNone(result.hbr_km)
        self.assertIsNone(result.pc)

    def test_invalid_covariance_is_rejected_without_repair(self) -> None:
        bad = covariance("A", [[1.0, 2.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        result = calculate_foster_2d(**assessment_args(
            miss_km=1.0,
            sigma_km=1.0,
            hbr_km=1.0,
            covariance_1=bad,
        ))
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.covariance_status, "invalid")
        self.assertIn("INVALID_COVARIANCE", result.reason_codes)
        self.assertIsNone(result.pc)

    def test_nonfinite_asymmetric_singular_and_non_positive_covariances_fail_closed(self) -> None:
        matrices = {
            "nonfinite": [[1.0, 0.0, 0.0], [0.0, math.nan, 0.0], [0.0, 0.0, 1.0]],
            "asymmetric": [[1.0, 0.1, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "singular": [[1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
            "non_positive_definite": [[1.0, 2.0, 0.0], [2.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        }
        for label, matrix in matrices.items():
            with self.subTest(covariance=label):
                result = calculate_foster_2d(**assessment_args(
                    miss_km=1.0,
                    sigma_km=1.0,
                    hbr_km=1.0,
                    covariance_1=covariance("A", matrix),
                ))
                self.assertEqual(result.status, "invalid")
                self.assertEqual(result.covariance_status, "invalid")
                self.assertIn("INVALID_COVARIANCE", result.reason_codes)
                self.assertIsNone(result.pc)

    def test_missing_geometry_and_invalid_tca_remain_unavailable_with_reasons(self) -> None:
        missing_geometry_args = assessment_args(miss_km=1.0, sigma_km=1.0, hbr_km=1.0)
        missing_geometry_args["position_2_km"] = None
        missing_geometry = calculate_foster_2d(**missing_geometry_args)

        invalid_tca_args = assessment_args(miss_km=1.0, sigma_km=1.0, hbr_km=1.0)
        invalid_tca_args["tca_utc"] = "not-a-timestamp"
        invalid_tca = calculate_foster_2d(**invalid_tca_args)

        self.assertEqual(missing_geometry.status, "unavailable")
        self.assertIn("INSUFFICIENT_ENCOUNTER_STATE", missing_geometry.reason_codes)
        self.assertIsNone(missing_geometry.pc)
        # Invalid TCA currently also triggers the covariance epoch mismatch
        # because the supplied covariance epoch cannot match an invalid TCA.
        self.assertNotEqual(invalid_tca.status, "available")
        self.assertIn("INSUFFICIENT_ENCOUNTER_STATE", invalid_tca.reason_codes)
        self.assertIsNone(invalid_tca.pc)

    def test_unknown_cross_correlation_requires_explicit_independence_assumption(self) -> None:
        result = calculate_foster_2d(**assessment_args(
            miss_km=1.0,
            sigma_km=1.0,
            hbr_km=1.0,
            assume_independent_covariances=False,
        ))
        self.assertEqual(result.status, "unsupported")
        self.assertIn("RELATIVE_COVARIANCE_CORRELATION_UNKNOWN", result.reason_codes)
        self.assertIsNone(result.pc)
        self.assertFalse(result.independence_assumption_authorized)
        self.assertTrue(any("No covariance-independence assumption was authorized" in item for item in result.assumptions))
        self.assertFalse(any("caller authorized treating" in item for item in result.assumptions))

    def test_epoch_and_frame_mismatches_are_not_transformed_silently(self) -> None:
        stale = covariance("A", np.eye(3), epoch="2024-12-31T23:59:59+00:00")
        stale_result = calculate_foster_2d(**assessment_args(
            miss_km=1.0, sigma_km=1.0, hbr_km=1.0, covariance_1=stale,
        ))
        wrong_frame = covariance("A", np.eye(3), frame="GCRF")
        frame_result = calculate_foster_2d(**assessment_args(
            miss_km=1.0, sigma_km=1.0, hbr_km=1.0, covariance_1=wrong_frame,
        ))
        self.assertIn("COVARIANCE_EPOCH_MISMATCH", stale_result.reason_codes)
        self.assertIn("COVARIANCE_FRAME_MISMATCH", frame_result.reason_codes)
        self.assertIsNone(stale_result.pc)
        self.assertIsNone(frame_result.pc)

    def test_covariance_object_id_mismatch_is_unavailable_without_numeric_pc(self) -> None:
        wrong_object = covariance("NOT-A", np.eye(3))
        result = calculate_foster_2d(**assessment_args(
            miss_km=1.0, sigma_km=1.0, hbr_km=1.0, covariance_1=wrong_object,
        ))
        self.assertEqual(result.status, "invalid")
        self.assertIn("COVARIANCE_OBJECT_ID_MISMATCH", result.reason_codes)
        self.assertIsNone(result.pc)

    def test_degenerate_and_boundary_encounters_are_unsupported(self) -> None:
        zero_speed = calculate_foster_2d(**assessment_args(
            miss_km=1.0, sigma_km=1.0, hbr_km=1.0, relative_velocity=(0.0, 0.0, 0.0),
        ))
        boundary = calculate_foster_2d(**assessment_args(
            miss_km=1.0, sigma_km=1.0, hbr_km=1.0, tca_status="boundary",
        ))
        self.assertEqual(zero_speed.status, "unsupported")
        self.assertIn("DEGENERATE_ENCOUNTER_GEOMETRY", zero_speed.reason_codes)
        self.assertEqual(boundary.status, "unsupported")
        self.assertIn("PC_METHOD_NOT_APPLICABLE", boundary.reason_codes)
        self.assertIsNone(zero_speed.pc)
        self.assertIsNone(boundary.pc)

    def test_small_tca_residual_is_accepted_with_explicit_warning(self) -> None:
        args = assessment_args(miss_km=1.0, sigma_km=1.0, hbr_km=0.01)
        args["position_2_km"] = (1.0, 0.0, 0.0)
        args["velocity_2_km_s"] = (0.05, 7.0, 0.0)
        result = calculate_foster_2d(**args)
        self.assertEqual(result.status, "available")
        self.assertTrue(any("TCA transversality residual" in warning for warning in result.warnings))
        too_radial = dict(args)
        too_radial["velocity_2_km_s"] = (0.2, 7.0, 0.0)
        self.assertIn("PC_METHOD_NOT_APPLICABLE", calculate_foster_2d(**too_radial).reason_codes)

    def test_synthetic_inputs_remain_explicit_and_results_repeat(self) -> None:
        args = assessment_args(miss_km=0.4, sigma_km=0.8, hbr_km=0.25)
        first = calculate_foster_2d(**args)
        second = calculate_foster_2d(**args)
        self.assertEqual(first.status, "available")
        self.assertTrue(first.provenance.is_synthetic)
        self.assertTrue(all(item.is_synthetic for item in first.covariance_sources))
        self.assertEqual(first.hbr_source, "synthetic")
        self.assertTrue(first.hbr_provenance["is_synthetic"])
        self.assertTrue(first.independence_assumption_authorized)
        self.assertTrue(any("caller authorized treating the object covariances as independent" in item.lower() for item in first.assumptions))
        self.assertEqual(first.pc, second.pc)

    def test_derived_inputs_preserve_explicit_synthetic_lineage(self) -> None:
        args = assessment_args(miss_km=0.4, sigma_km=0.8, hbr_km=0.25)
        args["covariance_1"] = covariance("A", np.eye(3), source_type="derived", is_synthetic=True)
        args["covariance_2"] = covariance("B", np.eye(3), source_type="derived", is_synthetic=True)
        args["hbr"] = HardBodyRadiusInput(
            value_km=0.25,
            source="configured",
            source_type="derived",
            description="Synthetic lineage fixture",
            is_synthetic=True,
        )
        result = calculate_foster_2d(**args)
        self.assertEqual(result.status, "available")
        self.assertTrue(result.provenance.is_synthetic)
        self.assertTrue(all(item.is_synthetic for item in result.covariance_sources))
        self.assertTrue(result.hbr_provenance["is_synthetic"])


def assessment_args(
    *,
    miss_km: float,
    sigma_km: float,
    hbr_km: float | None = 1.0,
    covariance_1: CovarianceInput | None = None,
    covariance_2: CovarianceInput | None = None,
    covariance_dimension: int = 3,
    object_1_id: str = "A",
    object_2_id: str = "B",
    relative_velocity: tuple[float, float, float] = (0.0, 7.0, 0.0),
    tca_status: str = "valid",
    assume_independent_covariances: bool = True,
    swap: bool = False,
):
    if covariance_1 is None and covariance_2 is None and covariance_dimension:
        variance_per_object = sigma_km**2 / 2.0
        matrix = np.diag([variance_per_object] * 3)
        if covariance_dimension == 6:
            matrix = np.diag([variance_per_object] * 3 + [1e-6] * 3)
        covariance_1 = covariance(object_1_id, matrix, units=UNITS_6D if covariance_dimension == 6 else UNITS_3D)
        covariance_2 = covariance(object_2_id, matrix, units=UNITS_6D if covariance_dimension == 6 else UNITS_3D)
    hbr_input = None if hbr_km is None else HardBodyRadiusInput(
        value_km=hbr_km,
        source="synthetic",
        source_type="synthetic",
        description="Explicit unit-test combined HBR fixture; never used by production API.",
        is_synthetic=True,
    )
    position_1 = (0.0, 0.0, 0.0)
    position_2 = (miss_km, 0.0, 0.0)
    velocity_1 = (0.0, 0.0, 0.0)
    velocity_2 = relative_velocity
    if swap:
        position_1, position_2 = position_2, position_1
        velocity_1, velocity_2 = velocity_2, velocity_1
    return {
        "event_id": "TEST-EVENT",
        "object_1_id": object_1_id,
        "object_2_id": object_2_id,
        "tca_utc": TCA,
        "position_1_km": position_1,
        "velocity_1_km_s": velocity_1,
        "position_2_km": position_2,
        "velocity_2_km_s": velocity_2,
        "state_frame": "TEME",
        "tca_status": tca_status,
        "covariance_1": covariance_1,
        "covariance_2": covariance_2,
        "hbr": hbr_input,
        "assume_independent_covariances": assume_independent_covariances,
    }


def covariance(
    object_id: str,
    matrix,
    *,
    frame: str = "TEME",
    epoch: str = TCA,
    units=UNITS_3D,
    source_type="synthetic",
    is_synthetic=True,
):
    return CovarianceInput(
        object_id=object_id,
        frame=frame,
        epoch=epoch,
        matrix=matrix,
        units=units,
        source="synthetic unit-test covariance",
        source_type=source_type,
        source_timestamp=TCA,
        is_synthetic=is_synthetic,
    )


if __name__ == "__main__":
    unittest.main()
