"""Foster 2D conjunction probability with explicit input/provenance contracts.

The live ORION TLE provider has no orbit covariance or object dimensions. This
module therefore returns an unavailable result for the production path unless
two same-epoch covariances and an explicitly sourced combined HBR are supplied.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np

from app.models import CollisionProbabilityResult, CovarianceSourceProvenance, Provenance
from app.services.probability_classification import classify_orion_physics_pc, classify_probability_pc


METHOD = "Foster 2D encounter-plane Gaussian integral"
METHOD_VERSION = "1.0"
RELATIVE_TOLERANCE = 1e-8
MAX_QUADRATURE_ORDER = 1024
MIN_RELATIVE_SPEED_KM_S = 1e-8
TCA_RADIAL_RATIO_TOLERANCE = 1e-2
TCA_RADIAL_RATIO_WARNING_THRESHOLD = 1e-3
MATRIX_SYMMETRY_REL_TOLERANCE = 1e-12
MATRIX_SYMMETRY_ABS_TOLERANCE = 1e-30
ENCOUNTER_PLANE_DEFINITION = (
    "e_v = normalized relative velocity; e_1 is the normalized TCA miss vector "
    "projected perpendicular to e_v (or a deterministic least-aligned Cartesian "
    "axis at zero miss); e_2 = cross(e_v, e_1); project the common-frame relative "
    "position covariance onto [e_1, e_2]."
)
FOSTER_ASSUMPTIONS = [
    "TCA relative-position uncertainty is represented by a bivariate Gaussian.",
    "Relative motion is locally linear over the encounter interval.",
    "Relative position covariance is treated as constant over the encounter interval.",
]


@dataclass(frozen=True)
class CovarianceInput:
    """A 3x3 position covariance or 6x6 [r,v] state covariance contract.

    A 6x6 matrix is ordered [x, y, z, vx, vy, vz] and uses mixed SI-derived
    units by block. The 2D Foster method uses only its top-left position block.
    """

    object_id: str
    frame: str
    epoch: str
    matrix: Any
    units: dict[str, str]
    source: str
    source_type: Literal["live", "fallback", "synthetic", "derived", "user_supplied"]
    source_timestamp: str | None = None
    input_hash: str | None = None
    is_synthetic: bool = False
    validity_status: Literal["valid", "invalid", "unavailable"] = "valid"


@dataclass(frozen=True)
class HardBodyRadiusInput:
    """Explicit combined hard-body radius; never inferred from object class."""

    value_km: float
    source: Literal["supplied", "configured", "synthetic"]
    source_type: Literal["live", "fallback", "synthetic", "derived", "user_supplied"]
    description: str
    source_timestamp: str | None = None
    input_hash: str | None = None
    is_synthetic: bool = False


def small_hbr_pc_approximation(mean_km: Any, covariance_km2: Any, hbr_km: float) -> float:
    """Return the local-density small-disc approximation to Foster Pc.

    This independent approximation evaluates ``pi * HBR^2`` times the
    bivariate Gaussian density at the encounter-plane origin. It is useful
    only when the density changes little across the collision disc; it is not
    a substitute for the full integral outside that small-HBR regime.
    """
    mean = np.asarray(mean_km, dtype=float)
    covariance = np.asarray(covariance_km2, dtype=float)
    radius = float(hbr_km)
    if mean.shape != (2,) or covariance.shape != (2, 2):
        raise ValueError("mean must be length 2 and covariance must be 2x2")
    if not np.isfinite(mean).all() or not np.isfinite(covariance).all() or not math.isfinite(radius) or radius <= 0:
        raise ValueError("mean, covariance, and positive HBR must be finite")
    if not np.allclose(covariance, covariance.T, rtol=MATRIX_SYMMETRY_REL_TOLERANCE, atol=MATRIX_SYMMETRY_ABS_TOLERANCE):
        raise ValueError("encounter-plane covariance must be symmetric")
    covariance = (covariance + covariance.T) * 0.5
    sign, log_determinant = np.linalg.slogdet(covariance)
    if sign <= 0 or not math.isfinite(float(log_determinant)):
        raise ValueError("encounter-plane covariance must be positive definite")
    try:
        mahalanobis = float(mean @ np.linalg.solve(covariance, mean))
    except np.linalg.LinAlgError as exc:
        raise ValueError("encounter-plane covariance must be positive definite") from exc
    log_probability = math.log(math.pi) + 2.0 * math.log(radius) - math.log(2.0 * math.pi) \
        - 0.5 * float(log_determinant) - 0.5 * mahalanobis
    return math.exp(log_probability) if log_probability > math.log(float.fromhex("0x0.0000000000001p-1022")) else 0.0


def calculate_foster_2d(
    *,
    event_id: str,
    object_1_id: str,
    object_2_id: str,
    tca_utc: str | None,
    position_1_km: Any = None,
    velocity_1_km_s: Any = None,
    position_2_km: Any = None,
    velocity_2_km_s: Any = None,
    state_frame: str | None = None,
    tca_status: str = "valid",
    covariance_1: CovarianceInput | None = None,
    covariance_2: CovarianceInput | None = None,
    hbr: HardBodyRadiusInput | None = None,
    assume_independent_covariances: bool = False,
    relative_tolerance: float = RELATIVE_TOLERANCE,
    max_quadrature_order: int = MAX_QUADRATURE_ORDER,
) -> CollisionProbabilityResult:
    """Calculate circular-region 2D Pc or return an explicit non-available state."""
    result_fields: dict[str, Any] = {
        "event_id": event_id,
        "object_1_id": object_1_id,
        "object_2_id": object_2_id,
        "tca_utc": tca_utc,
        "method": METHOD,
        "method_version": METHOD_VERSION,
        "encounter_plane_definition": ENCOUNTER_PLANE_DEFINITION,
        "numerical_tolerance": {"relative_tolerance": relative_tolerance},
        "assumptions": [
            *FOSTER_ASSUMPTIONS,
            (
                "The caller authorized treating the object covariances as independent; no cross-correlation term is included."
                if assume_independent_covariances
                else "No covariance-independence assumption was authorized; cross-object correlation remains unknown."
            ),
        ],
        "independence_assumption_authorized": bool(assume_independent_covariances),
    }
    warnings: list[str] = [
        "Applicability assumptions are not independently verified by TLE-only propagation.",
        "This is a research implementation and is not NASA operational conjunction software.",
    ]
    has_6d_covariance = False
    for covariance in (covariance_1, covariance_2):
        if covariance is None:
            continue
        try:
            has_6d_covariance = has_6d_covariance or np.asarray(covariance.matrix).shape == (6, 6)
        except (TypeError, ValueError):
            pass  # malformed input is reported by the normal covariance validator below
    if has_6d_covariance:
        result_fields["assumptions"].append(
            "For each supplied 6x6 [position, velocity] covariance, only the 3x3 position-position block at the declared TCA is used; velocity and position-velocity terms are ignored, and covariance is not propagated."
        )
        warnings.append(
            "6x6 covariance is reduced to its TCA position block; no state-covariance propagation is performed."
        )

    covariances = [covariance_1, covariance_2]
    covariance_sources: list[CovarianceSourceProvenance] = []
    normalized_matrices: list[np.ndarray] = []
    reasons: list[str] = []
    covariance_status: Literal["available", "unavailable", "invalid"] = "unavailable"
    covariance_invalid = False
    for covariance, expected_id in zip(covariances, (object_1_id, object_2_id)):
        if covariance is None:
            continue
        matrix, matrix_reason, symmetrized = _validate_covariance(covariance)
        if matrix_reason:
            reasons.append(matrix_reason)
            covariance_invalid = True
            continue
        assert matrix is not None
        normalized_matrices.append(matrix)
        covariance_sources.append(_covariance_source(covariance, matrix, symmetrized))
        if covariance.object_id != expected_id:
            reasons.append("COVARIANCE_OBJECT_ID_MISMATCH")
            covariance_invalid = True
        if covariance.validity_status != "valid":
            reasons.append("INVALID_COVARIANCE")
            covariance_invalid = True
        if covariance.source_type == "synthetic" and not covariance.is_synthetic:
            reasons.append("INVALID_COVARIANCE")
            covariance_invalid = True
        if covariance.is_synthetic and covariance.source_type not in {"synthetic", "derived"}:
            reasons.append("INVALID_COVARIANCE")
            covariance_invalid = True
        if tca_utc and _parse_epoch(covariance.epoch) != _parse_epoch(tca_utc):
            reasons.append("COVARIANCE_EPOCH_MISMATCH")
        if state_frame and covariance.frame != state_frame:
            reasons.append("COVARIANCE_FRAME_MISMATCH")

    if covariance_invalid:
        covariance_status = "invalid"
    elif any(item is None for item in covariances):
        reasons.append("NO_COVARIANCE")
    else:
        covariance_status = "available"

    result_fields["covariance_status"] = covariance_status
    result_fields["covariance_sources"] = covariance_sources
    if covariance_sources and len({source.frame for source in covariance_sources}) == 1:
        result_fields["covariance_frame"] = covariance_sources[0].frame
    if covariance_sources and len({source.epoch for source in covariance_sources}) == 1:
        result_fields["covariance_epoch"] = covariance_sources[0].epoch

    hbr_source: Literal["supplied", "configured", "synthetic", "unavailable"] = "unavailable"
    hbr_provenance = None
    if hbr is None:
        reasons.append("HBR_UNAVAILABLE")
    else:
        hbr_source = hbr.source if hbr.source in {"supplied", "configured", "synthetic"} else "unavailable"
        hbr_value = _positive_finite_scalar(hbr.value_km)
        result_fields["hbr_km"] = hbr_value
        hbr_provenance = {
            "source": hbr.source,
            "source_type": hbr.source_type,
            "description": hbr.description,
            "source_timestamp": hbr.source_timestamp,
            "input_hash": hbr.input_hash,
            "units": "km",
            "is_synthetic": hbr.is_synthetic,
        }
        if hbr_value is None:
            reasons.append("INVALID_HBR")
        if hbr.source not in {"supplied", "configured", "synthetic"}:
            reasons.append("INVALID_HBR")
        if hbr.source_type not in {"live", "fallback", "synthetic", "derived", "user_supplied"}:
            reasons.append("INVALID_HBR")
        if hbr.source == "synthetic" and (hbr.source_type != "synthetic" or not hbr.is_synthetic):
            reasons.append("INVALID_HBR")
        if hbr.is_synthetic and hbr.source_type not in {"synthetic", "derived"}:
            reasons.append("INVALID_HBR")
        if hbr.source_type == "synthetic" and hbr.source != "synthetic":
            reasons.append("INVALID_HBR")

    result_fields["hbr_source"] = hbr_source
    result_fields["hbr_provenance"] = hbr_provenance

    state = _relative_state(
        position_1_km,
        velocity_1_km_s,
        position_2_km,
        velocity_2_km_s,
        state_frame,
    )
    if state is None:
        reasons.append("INSUFFICIENT_ENCOUNTER_STATE")
    else:
        relative_position, _ = state
        result_fields["miss_distance_km"] = float(np.linalg.norm(relative_position))
    if tca_status != "valid":
        reasons.append("PC_METHOD_NOT_APPLICABLE")
    if not _valid_epoch(tca_utc):
        reasons.append("INSUFFICIENT_ENCOUNTER_STATE")

    if covariance_status == "invalid":
        reasons.append("INVALID_COVARIANCE")

    if reasons:
        unique_reasons = list(dict.fromkeys(reasons))
        applicability_reasons = {
            "PC_METHOD_NOT_APPLICABLE",
            "COVARIANCE_EPOCH_MISMATCH",
            "COVARIANCE_FRAME_MISMATCH",
        }
        status = "invalid" if covariance_status == "invalid" or "INVALID_HBR" in unique_reasons else (
            "unsupported" if applicability_reasons.intersection(unique_reasons) else "unavailable"
        )
        if status == "unsupported":
            result_fields["applicability_status"] = "not_applicable"
        return _result(
            result_fields,
            status=status,
            covariance_status=covariance_status,
            hbr_provenance=hbr_provenance,
            reason_codes=unique_reasons,
            warnings=warnings,
            covariance_sources=covariance_sources,
        )

    assert state is not None and covariance_1 is not None and covariance_2 is not None and hbr is not None
    if not assume_independent_covariances:
        return _result(
            result_fields,
            status="unsupported",
            covariance_status="available",
            hbr_provenance=hbr_provenance,
            reason_codes=["RELATIVE_COVARIANCE_CORRELATION_UNKNOWN"],
            warnings=warnings,
            covariance_sources=covariance_sources,
            applicability_status="not_assessed",
        )

    tca = _parse_epoch(tca_utc)
    if not math.isfinite(relative_tolerance) or not (0 < relative_tolerance < 1):
        return _result(
            result_fields,
            status="invalid",
            covariance_status="available",
            hbr_provenance=hbr_provenance,
            reason_codes=["INVALID_NUMERICAL_TOLERANCE"],
            warnings=warnings,
            covariance_sources=covariance_sources,
            applicability_status="not_assessed",
        )
    if not isinstance(max_quadrature_order, int) or max_quadrature_order < 32:
        return _result(
            result_fields,
            status="invalid",
            covariance_status="available",
            hbr_provenance=hbr_provenance,
            reason_codes=["INVALID_NUMERICAL_CONFIGURATION"],
            warnings=warnings,
            covariance_sources=covariance_sources,
            applicability_status="not_assessed",
        )

    relative_position, relative_velocity = state
    speed = float(np.linalg.norm(relative_velocity))
    miss_distance = float(np.linalg.norm(relative_position))
    if speed <= MIN_RELATIVE_SPEED_KM_S:
        return _result(
            result_fields,
            status="unsupported",
            covariance_status="available",
            hbr_provenance=hbr_provenance,
            reason_codes=["DEGENERATE_ENCOUNTER_GEOMETRY"],
            warnings=warnings + ["Relative velocity is too small to define a 2D encounter plane."],
            covariance_sources=covariance_sources,
            applicability_status="not_applicable",
        )

    radial_ratio = abs(float(np.dot(relative_position, relative_velocity))) / max(miss_distance * speed, 1e-30)
    if miss_distance > 1e-9 and radial_ratio > TCA_RADIAL_RATIO_TOLERANCE:
        return _result(
            result_fields,
            status="unsupported",
            covariance_status="available",
            hbr_provenance=hbr_provenance,
            reason_codes=["PC_METHOD_NOT_APPLICABLE"],
            warnings=warnings + ["The supplied state is not sufficiently transverse for the declared TCA."],
            covariance_sources=covariance_sources,
            applicability_status="not_applicable",
        )
    if miss_distance > 1e-9 and radial_ratio > TCA_RADIAL_RATIO_WARNING_THRESHOLD:
        warnings.append(
            f"TCA transversality residual is {radial_ratio:.4g}; ORION permits at most {TCA_RADIAL_RATIO_TOLERANCE:g} and flags residuals above {TCA_RADIAL_RATIO_WARNING_THRESHOLD:g}."
        )

    e_v = relative_velocity / speed
    miss_perpendicular = relative_position - float(np.dot(relative_position, e_v)) * e_v
    if float(np.linalg.norm(miss_perpendicular)) > 1e-9:
        e_1 = miss_perpendicular / np.linalg.norm(miss_perpendicular)
    else:
        reference = np.eye(3)[int(np.argmin(np.abs(e_v)))]
        e_1 = reference - float(np.dot(reference, e_v)) * e_v
        e_1 = e_1 / np.linalg.norm(e_1)
        warnings.append("Zero miss used a deterministic in-plane axis; Pc is invariant to in-plane rotation when covariance is transformed consistently.")
    e_2 = np.cross(e_v, e_1)
    e_2_norm = float(np.linalg.norm(e_2))
    if not math.isfinite(e_2_norm) or e_2_norm <= 1e-12:
        return _result(
            result_fields,
            status="unsupported",
            covariance_status="available",
            hbr_provenance=hbr_provenance,
            reason_codes=["DEGENERATE_ENCOUNTER_GEOMETRY"],
            warnings=warnings,
            covariance_sources=covariance_sources,
            applicability_status="not_applicable",
        )
    e_2 = e_2 / e_2_norm
    plane_basis = np.vstack((e_1, e_2))
    relative_covariance_position = normalized_matrices[0][:3, :3] + normalized_matrices[1][:3, :3]
    encounter_covariance = plane_basis @ relative_covariance_position @ plane_basis.T
    encounter_covariance = (encounter_covariance + encounter_covariance.T) * 0.5
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(encounter_covariance)
    except np.linalg.LinAlgError:
        return _result(
            result_fields,
            status="invalid",
            covariance_status="invalid",
            hbr_provenance=hbr_provenance,
            reason_codes=["INVALID_COVARIANCE"],
            warnings=warnings,
            covariance_sources=covariance_sources,
        )
    if not np.isfinite(eigenvalues).all() or float(np.min(eigenvalues)) <= 0:
        return _result(
            result_fields,
            status="invalid",
            covariance_status="invalid",
            hbr_provenance=hbr_provenance,
            reason_codes=["INVALID_COVARIANCE"],
            warnings=warnings,
            covariance_sources=covariance_sources,
        )

    miss_vector = plane_basis @ relative_position
    principal_miss = eigenvectors.T @ miss_vector
    sigma_x, sigma_y = (math.sqrt(float(value)) for value in eigenvalues)
    try:
        pc, evaluations, roundoff_bounded = _integrate_circular_region(
            principal_miss,
            sigma_x,
            sigma_y,
            hbr.value_km,
            relative_tolerance,
            max_quadrature_order,
        )
    except (ArithmeticError, FloatingPointError, ValueError, np.linalg.LinAlgError):
        pc, evaluations, roundoff_bounded = None, None, False
    if pc is None or not math.isfinite(pc) or not (0.0 < pc <= 1.0):
        return _result(
            result_fields,
            status="invalid",
            covariance_status="available",
            hbr_provenance=hbr_provenance,
            reason_codes=["NUMERICAL_FAILURE"],
            warnings=warnings + ["The deterministic quadrature did not produce a finite, converged probability in (0, 1]."],
            covariance_sources=covariance_sources,
            evaluations=evaluations,
            applicability_status="applicable",
        )

    if any(source.normalization_operations for source in covariance_sources):
        warnings.append("A covariance was symmetrized only within the declared roundoff tolerance; operation is recorded in covariance provenance.")
    if roundoff_bounded:
        warnings.append("The converged probability exceeded 1 only within 1e-12 roundoff and was bounded to 1; this numerical correction is disclosed here.")
    result_fields["pc"] = pc
    result_fields["evaluations"] = evaluations
    result_fields["applicability_status"] = "applicable"
    result_fields["covariance_frame"] = state_frame
    result_fields["covariance_epoch"] = tca.isoformat()
    return _result(
        result_fields,
        status="available",
        covariance_status="available",
        hbr_provenance=hbr_provenance,
        reason_codes=[],
        warnings=warnings,
        covariance_sources=covariance_sources,
        evaluations=evaluations,
        applicability_status="applicable",
    )


def _integrate_circular_region(
    mean: np.ndarray,
    sigma_x: float,
    sigma_y: float,
    radius: float,
    relative_tolerance: float,
    max_order: int,
) -> tuple[float | None, int, bool]:
    """Evaluate the Foster disk integral with deterministic Gauss-Legendre rules.

    Diagonalizing the 2x2 covariance makes the coordinates independent. The
    inner normal integral is evaluated with stable erfc differences; the outer
    integral is transformed to theta in [0, pi] to remove the circle's square
    root boundary. Successive quadrature orders must agree relatively.
    """
    if not np.isfinite(mean).all() or sigma_x <= 0 or sigma_y <= 0 or radius <= 0:
        raise ValueError("invalid integral inputs")
    if max_order > 4096:
        max_order = 4096
    evaluations = 0
    previous: float | None = None
    order = 32
    while order <= max_order:
        nodes, weights = np.polynomial.legendre.leggauss(order)
        theta = (nodes + 1.0) * (math.pi / 2.0)
        theta_weights = weights * (math.pi / 2.0)
        cosine = np.cos(theta)
        sine = np.sin(theta)
        x = float(mean[0]) + radius * cosine
        half_y = radius * sine
        x_density = np.exp(-0.5 * np.square(x / sigma_x)) / (math.sqrt(2.0 * math.pi) * sigma_x)
        lower = (float(mean[1]) - half_y) / sigma_y
        upper = (float(mean[1]) + half_y) / sigma_y
        y_probability = np.fromiter(
            (_normal_interval_probability(float(a), float(b)) for a, b in zip(lower, upper)),
            dtype=float,
            count=order,
        )
        estimate = float(np.dot(theta_weights, x_density * y_probability * radius * sine))
        evaluations += order
        if not math.isfinite(estimate):
            raise FloatingPointError("non-finite quadrature estimate")
        if estimate <= 0:
            return None, evaluations, False
        if previous is not None and abs(estimate - previous) <= relative_tolerance * abs(estimate):
            roundoff_bounded = False
            if estimate > 1.0 and estimate <= 1.0 + 1e-12:
                estimate = 1.0
                roundoff_bounded = True
            if estimate > 1.0:
                raise ArithmeticError("probability exceeded one beyond roundoff")
            return estimate, evaluations, roundoff_bounded
        previous = estimate
        order *= 2
    return None, evaluations, False


def _normal_interval_probability(lower: float, upper: float) -> float:
    if upper <= lower:
        return 0.0
    root_two = math.sqrt(2.0)
    if lower >= 0.0:
        value = 0.5 * (math.erfc(lower / root_two) - math.erfc(upper / root_two))
    elif upper <= 0.0:
        value = 0.5 * (math.erfc(-upper / root_two) - math.erfc(-lower / root_two))
    else:
        value = 1.0 - 0.5 * math.erfc(upper / root_two) - 0.5 * math.erfc(-lower / root_two)
    return max(0.0, value)


def _validate_covariance(covariance: CovarianceInput) -> tuple[np.ndarray | None, str | None, bool]:
    try:
        matrix = np.asarray(covariance.matrix, dtype=float)
    except (TypeError, ValueError):
        return None, "INVALID_COVARIANCE", False
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or matrix.shape[0] not in {3, 6}:
        return None, "INVALID_COVARIANCE", False
    if (
        not np.isfinite(matrix).all()
        or not covariance.object_id
        or not covariance.frame
        or not covariance.source
        or not covariance.units
        or covariance.source_type not in {"live", "fallback", "synthetic", "derived", "user_supplied"}
    ):
        return None, "INVALID_COVARIANCE", False
    if _parse_epoch(covariance.epoch) is None:
        return None, "INVALID_COVARIANCE", False
    expected_units = (
        {"position": "km^2"}
        if matrix.shape[0] == 3
        else {"position": "km^2", "velocity": "km^2/s^2", "position_velocity_cross": "km^2/s"}
    )
    if covariance.units != expected_units:
        return None, "INVALID_COVARIANCE", False

    scale = max(float(np.max(np.abs(matrix))), np.finfo(float).tiny)
    asymmetry = float(np.max(np.abs(matrix - matrix.T)))
    allowed_asymmetry = MATRIX_SYMMETRY_ABS_TOLERANCE + MATRIX_SYMMETRY_REL_TOLERANCE * scale
    if asymmetry > allowed_asymmetry:
        return None, "INVALID_COVARIANCE", False
    symmetrized = asymmetry > 0.0
    symmetric = (matrix + matrix.T) * 0.5 if symmetrized else matrix.copy()

    diagonal = np.diag(symmetric)
    if np.any(diagonal <= 0.0):
        return None, "INVALID_COVARIANCE", symmetrized
    standard_deviations = np.sqrt(diagonal)
    correlation_scaled = symmetric / np.outer(standard_deviations, standard_deviations)
    try:
        eigenvalues = np.linalg.eigvalsh((correlation_scaled + correlation_scaled.T) * 0.5)
    except np.linalg.LinAlgError:
        return None, "INVALID_COVARIANCE", symmetrized
    if not np.isfinite(eigenvalues).all() or float(np.min(eigenvalues)) <= 0.0:
        return None, "INVALID_COVARIANCE", symmetrized
    return symmetric, None, symmetrized


def _covariance_source(
    covariance: CovarianceInput,
    normalized_matrix: np.ndarray,
    symmetrized: bool,
) -> CovarianceSourceProvenance:
    dimension = int(normalized_matrix.shape[0])
    input_hash = covariance.input_hash or hashlib.sha256(
        json.dumps(normalized_matrix.tolist(), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    units = (
        {"position": "km^2"}
        if dimension == 3
        else {"position": "km^2", "velocity": "km^2/s^2", "position_velocity_cross": "km^2/s"}
    )
    return CovarianceSourceProvenance(
        object_id=covariance.object_id,
        source=covariance.source,
        source_type=covariance.source_type,
        source_timestamp=covariance.source_timestamp,
        frame=covariance.frame,
        epoch=_parse_epoch(covariance.epoch).isoformat(),  # type: ignore[union-attr]
        matrix_dimension=dimension,
        units=units,
        input_hash=input_hash,
        is_synthetic=covariance.is_synthetic,
        normalization_operations=["symmetrized_within_tolerance"] if symmetrized else [],
    )


def _relative_state(position_1: Any, velocity_1: Any, position_2: Any, velocity_2: Any, frame: str | None):
    if not frame:
        return None
    try:
        r1 = np.asarray(position_1, dtype=float)
        v1 = np.asarray(velocity_1, dtype=float)
        r2 = np.asarray(position_2, dtype=float)
        v2 = np.asarray(velocity_2, dtype=float)
    except (TypeError, ValueError):
        return None
    if any(vector.shape != (3,) or not np.isfinite(vector).all() for vector in (r1, v1, r2, v2)):
        return None
    return r2 - r1, v2 - v1


def _parse_epoch(epoch: str | None) -> datetime | None:
    if not epoch:
        return None
    try:
        parsed = datetime.fromisoformat(epoch.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _positive_finite_scalar(value: Any) -> float | None:
    if isinstance(value, (bool, np.bool_)):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) and numeric > 0.0 else None


def _valid_epoch(epoch: str | None) -> bool:
    return _parse_epoch(epoch) is not None


def _result(
    fields: dict[str, Any],
    *,
    status: Literal["available", "unavailable", "invalid", "unsupported"],
    covariance_status: Literal["available", "unavailable", "invalid"],
    hbr_provenance: dict[str, Any] | None,
    reason_codes: list[str],
    warnings: list[str],
    covariance_sources: list[CovarianceSourceProvenance],
    evaluations: int | None = None,
    applicability_status: Literal["applicable", "not_applicable", "not_assessed"] | None = None,
) -> CollisionProbabilityResult:
    if status == "available" and fields.get("pc") is not None:
        fields["probability_classification"] = classify_probability_pc(fields["pc"])
        fields["risk_assessment"] = classify_orion_physics_pc(
            fields["pc"], "event_specific_foster_pc",
        )
    fields["status"] = status
    fields["covariance_status"] = covariance_status
    fields["hbr_provenance"] = hbr_provenance
    fields["reason_codes"] = reason_codes
    fields["warnings"] = warnings
    fields["covariance_sources"] = covariance_sources
    fields["provenance"] = Provenance(
        source="ORION Foster 2D research calculation",
        source_type="derived",
        method=METHOD,
        method_version=METHOD_VERSION,
        reference_frame=fields.get("covariance_frame"),
        units={"miss_distance": "km", "hbr": "km", "probability": "dimensionless"},
        validity_status=(
            "valid" if status == "available"
            else "unavailable" if status == "unavailable"
            else "not_assessed" if status == "unsupported"
            else "invalid"
        ),
        reason_code=reason_codes[0] if reason_codes else None,
        is_synthetic=any(source.is_synthetic for source in covariance_sources) or bool(hbr_provenance and hbr_provenance.get("is_synthetic")),
    )
    if evaluations is not None:
        fields["evaluations"] = evaluations
    if applicability_status is not None:
        fields["applicability_status"] = applicability_status
    return CollisionProbabilityResult(**fields)
