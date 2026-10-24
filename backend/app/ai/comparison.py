"""Comparison result builder; ML risk and physics Pc are never numerically mixed."""

from app.models import CollisionProbabilityResult, ComparisonResult, MLResult


NOT_EQUIVALENT_REASON = "ml_esa_log10_risk_is_not_equivalent_to_foster_collision_probability"


def compare_ml_and_physics(
    ml_result: MLResult,
    collision_probability: CollisionProbabilityResult | None,
) -> ComparisonResult:
    pc_available = collision_probability is not None and collision_probability.status == "available"
    ml_available = ml_result.status == "available"
    if ml_available:
        return ComparisonResult(
            status="not_comparable",
            ml_available=True,
            physics_pc_available=pc_available,
            reason_code=NOT_EQUIVALENT_REASON if pc_available else "ESA_EVENT_LOG_RISK_IS_NOT_PHYSICAL_GEOMETRY_OR_PC",
        )
    return ComparisonResult(
        status="unavailable",
        ml_available=False,
        physics_pc_available=pc_available,
        reason_code=ml_result.reason_code or "ML_RESULT_UNAVAILABLE",
    )
