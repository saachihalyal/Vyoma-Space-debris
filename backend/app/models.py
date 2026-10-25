from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.services.object_classification import classify_object


Band = Literal["LEO", "MEO", "GEO", "HEO"]
Category = Literal["active", "debris", "payload", "rocket_body", "station", "unknown"]
RiskLevel = Literal["low", "moderate", "elevated", "severe"]
SourceType = Literal["live", "fallback", "synthetic", "derived", "user_supplied", "unavailable"]
ValidityStatus = Literal["valid", "boundary", "invalid", "unavailable", "not_assessed"]


class ManeuverAssessmentData(BaseModel):
    """Maneuver result with a required event identity and extensible science fields."""

    model_config = ConfigDict(extra="allow")

    event_id: str


class ManeuverAssessmentResponse(BaseModel):
    """Identity-bearing envelope returned by the selected-event maneuver API."""

    success: bool
    timestamp: str
    screening_job_id: str
    data: ManeuverAssessmentData
    message: str


class Provenance(BaseModel):
    """Source and method metadata for catalog observations and derived values."""

    source: str
    source_type: SourceType
    source_timestamp: str | None = None
    element_epoch: str | None = None
    propagation_epoch: str | None = None
    reference_frame: str | None = None
    units: dict[str, str] = Field(default_factory=dict)
    catalog_id: str | None = None
    object_id: str | None = None
    input_hash: str | None = None
    source_record: dict[str, Any] | None = None
    propagator: str | None = None
    propagator_version: str | None = None
    propagator_configuration: dict[str, Any] = Field(default_factory=dict)
    method: str | None = None
    method_version: str | None = None
    validity_status: ValidityStatus = "not_assessed"
    reason_code: str | None = None
    is_synthetic: bool = False
    is_fallback: bool = False


class SourceSummary(BaseModel):
    status: Literal[
        "all_live",
        "mixed_live_fallback",
        "mixed_live_synthetic",
        "fallback",
        "synthetic_demo",
        "unavailable",
    ]
    counts_by_source_type: dict[str, int] = Field(default_factory=dict)
    object_count: int = 0
    unavailable_count: int = 0


class OrbitVisual(BaseModel):
    """Simplified visualization parameters; these are not propagated orbital states."""

    visual_radius: float
    inclination_deg: float
    raan_deg: float
    phase_rad: float
    angular_rate: float
    eccentricity: float


class SpaceObject(BaseModel):
    id: str
    name: str
    category: Category
    object_type: str | None = None
    source_classification: str | None = None
    classification_source: str | None = None
    band: Band
    orbit_type: str
    altitude_km: float
    inclination_deg: float
    velocity_kms: float
    heuristic_risk_score: float = Field(ge=0, le=1)
    heuristic_debris_pressure_score: float = Field(ge=0, le=1)
    heuristic_forecast_score: float = Field(ge=0, le=1)
    position: list[float]
    velocity: list[float]
    orbit: OrbitVisual
    provenance: Provenance
    heuristic_score_provenance: Provenance

    @model_validator(mode="after")
    def fill_classification_from_category(self) -> "SpaceObject":
        inferred = classify_object(
            object_type=self.object_type,
            category=self.category,
            source_classification=self.source_classification,
            name=self.name,
        )
        self.category = inferred.category
        self.object_type = inferred.object_type
        if inferred.classification_source == "conflicting_or_unsupported_metadata":
            self.classification_source = inferred.classification_source
        elif self.classification_source is None:
            self.classification_source = inferred.classification_source
        return self


class UnavailableCatalogObject(BaseModel):
    id: str
    name: str
    category: Category
    object_type: str | None = None
    source_classification: str | None = None
    classification_source: str | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def fill_classification_from_category(self) -> "UnavailableCatalogObject":
        inferred = classify_object(
            object_type=self.object_type,
            category=self.category,
            source_classification=self.source_classification,
            name=self.name,
        )
        self.category = inferred.category
        self.object_type = inferred.object_type
        if inferred.classification_source == "conflicting_or_unsupported_metadata":
            self.classification_source = inferred.classification_source
        elif self.classification_source is None:
            self.classification_source = inferred.classification_source
        return self


class RiskCell(BaseModel):
    id: str
    band: Band
    altitude_km: float
    inclination_deg: float
    raan_deg: float
    severity: RiskLevel
    heuristic_risk_score: float = Field(ge=0, le=1)
    tracked_object_density_score: float = Field(ge=0, le=1)
    heuristic_untracked_pressure_score: float = Field(ge=0, le=1)
    heuristic_forecast_score: float = Field(ge=0, le=1)
    heuristic_uncertainty_score: float = Field(ge=0, le=1)
    contributors: list[str]
    explanation: str
    provenance: Provenance


class SnapshotStats(BaseModel):
    tracked_objects: int
    active_satellites: int
    debris_objects: int
    unknown_objects: int = 0
    leo: int
    meo: int
    geo: int
    global_heuristic_risk_score: float | None = Field(default=None, ge=0, le=1)
    heuristic_forecast_trend_score: float | None = None
    data_latency_seconds: float
    unavailable_objects: int = 0
    provenance: Provenance


class CatalogSnapshot(BaseModel):
    generated_at: str
    source: str
    source_state: dict[str, Any] = Field(default_factory=dict)
    source_summary: SourceSummary
    tle_epoch: str | None
    stats: SnapshotStats
    objects: list[SpaceObject]
    unavailable_objects: list[UnavailableCatalogObject] = Field(default_factory=list)
    risk_cells: list[RiskCell]


class ForecastFrame(BaseModel):
    hour: int
    global_heuristic_risk_score: float | None = None
    tracked_object_density_score: float
    cells: list[RiskCell]
    provenance: Provenance


class ForecastResponse(BaseModel):
    generated_at: str
    horizon_hours: int
    frames: list[ForecastFrame]
    provenance: Provenance


class ScientificField(BaseModel):
    status: Literal["available", "unavailable", "invalid", "not_applicable"] = "unavailable"
    value: Any = None
    units: str | None = None
    method: str | None = None
    method_version: str | None = None
    reason_code: str | None = None


class PhysicsResult(BaseModel):
    result_type: Literal["physics"] = "physics"
    event_id: str
    status: Literal["valid", "boundary", "invalid", "available", "partial", "unavailable", "not_assessed"] = "unavailable"
    applicability: str = "not_assessed"
    provenance: Provenance
    object_primary_id: str | None = None
    object_secondary_id: str | None = None
    screening_horizon_start: str | None = None
    screening_horizon_end: str | None = None
    screening_threshold_km: float | None = None
    tca_status: Literal["valid", "boundary", "invalid", "unavailable"] = "unavailable"
    state_information: dict[str, Any] | None = None
    tca: ScientificField = Field(default_factory=lambda: ScientificField(reason_code="trajectory_assessment_not_attached"))
    miss_distance: ScientificField = Field(default_factory=lambda: ScientificField(reason_code="relative_trajectory_not_assessed"))
    relative_position_at_tca: ScientificField = Field(default_factory=lambda: ScientificField(reason_code="relative_trajectory_not_assessed"))
    relative_velocity_at_tca: ScientificField = Field(default_factory=lambda: ScientificField(reason_code="relative_trajectory_not_assessed"))
    relative_speed_at_tca: ScientificField = Field(default_factory=lambda: ScientificField(reason_code="relative_trajectory_not_assessed"))
    primary_state_at_tca: dict[str, Any] | None = None
    secondary_state_at_tca: dict[str, Any] | None = None
    encounter_geometry: dict[str, Any] | None = None
    convergence: dict[str, Any] | None = None
    covariance: ScientificField = Field(default_factory=lambda: ScientificField(reason_code="covariance_not_provided"))
    hard_body_radius: ScientificField = Field(default_factory=lambda: ScientificField(reason_code="hard_body_radius_not_provided"))
    probability_of_collision: ScientificField = Field(default_factory=lambda: ScientificField(reason_code="see_separate_collision_probability_result"))
    reason_codes: list[str] = Field(default_factory=list)


class CovarianceSourceProvenance(BaseModel):
    object_id: str
    source: str
    source_type: SourceType
    source_timestamp: str | None = None
    frame: str
    epoch: str
    matrix_dimension: int
    units: dict[str, str]
    input_hash: str | None = None
    is_synthetic: bool = False
    normalization_operations: list[str] = Field(default_factory=list)


class PhysicsPcRiskAssessment(BaseModel):
    status: Literal["classified", "unavailable"]
    risk_score: float | None = Field(default=None, ge=0, le=100)
    risk_score_policy_name: str
    risk_score_policy_version: str
    risk_score_pc_channel: Literal["event_specific_foster_pc", "research_pc"]
    physics_risk_class: Literal["Low", "Medium", "High"] | None = None
    final_risk_class: Literal["Low", "Medium", "High"] | None = None
    classification_basis: str | None = None
    log10_pc: float | None = None
    thresholds: dict[str, float] | None = None
    boundary_policy: str | None = None
    reason_code: str | None = None
    limitations: list[str] = Field(default_factory=list)


class CollisionProbabilityResult(BaseModel):
    """Foster 2D Pc result, kept independent from trajectory and proxy scores."""

    result_type: Literal["collision_probability"] = "collision_probability"
    status: Literal["available", "unavailable", "invalid", "unsupported"]
    event_id: str
    object_1_id: str | None = None
    object_2_id: str | None = None
    tca_utc: str | None = None
    miss_distance_km: float | None = None
    hbr_km: float | None = None
    hbr_source: str = "unavailable"
    hbr_provenance: dict[str, Any] | None = None
    pc: float | None = None
    source_reported_pc: float | None = None
    source_reported_pc_method: str | None = None
    source_reported_event_id: str | None = None
    source_reported_pc_provenance: dict[str, Any] | None = None
    probability_classification: dict[str, Any] | None = None
    risk_assessment: PhysicsPcRiskAssessment | None = None
    method: str = "Foster 2D encounter-plane Gaussian integral"
    method_version: str = "1.0"
    covariance_status: Literal["available", "unavailable", "invalid"] = "unavailable"
    covariance_sources: list[CovarianceSourceProvenance] = Field(default_factory=list)
    covariance_frame: str | None = None
    covariance_epoch: str | None = None
    encounter_plane_definition: str = ""
    numerical_tolerance: dict[str, float] | None = None
    evaluations: int | None = None
    applicability_status: Literal["applicable", "not_applicable", "not_assessed"] = "not_assessed"
    assumptions: list[str] = Field(default_factory=list)
    independence_assumption_authorized: bool = False
    provenance: Provenance
    reason_codes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MLRiskPrediction(BaseModel):
    quantity_label: Literal["ESA log10 event-risk estimate; not a calibrated probability or Foster Pc"] = (
        "ESA log10 event-risk estimate; not a calibrated probability or Foster Pc"
    )
    predicted_log_risk: float
    target_units: Literal["log10 risk"] = "log10 risk"
    predicted_risk_estimate: float = Field(
        description="10 ** predicted_log_risk on the ESA event-risk scale; not a calibrated probability or Foster Pc."
    )
    predicted_risk_probability: float = Field(
        deprecated=True,
        description="Deprecated compatibility alias for predicted_risk_estimate; not a calibrated probability or Foster Pc.",
    )
    threshold_flag_at_minus_6: bool = Field(
        description="True iff predicted_log_risk is at least -6; this threshold flag is not a validated detector."
    )
    high_risk: bool = Field(
        deprecated=True,
        description="Deprecated compatibility alias for threshold_flag_at_minus_6; not a validated detector.",
    )
    high_risk_threshold_log10: float = -6.0


class MLResult(BaseModel):
    result_type: Literal["ml"] = "ml"
    status: Literal["available", "unavailable", "not_implemented", "error"] = "not_implemented"
    model_name: str | None = None
    model_version: str | None = None
    training_dataset: str | None = None
    feature_schema: dict[str, Any] | None = None
    input_features: dict[str, float] | None = None
    feature_units: dict[str, str] | None = None
    feature_frame: str | None = None
    prediction: MLRiskPrediction | None = None
    feature_availability: dict[str, bool] | None = None
    features_imputed: bool | None = None
    provenance: dict[str, Any] | None = None
    uncertainty: dict[str, Any] | None = None
    validation_metrics: dict[str, Any] | None = None
    reason_code: str = "no_trained_model_configured"


class OrbitalAnomalyResult(BaseModel):
    """Unsupervised unusualness relative to historical ESA feature records; not risk."""

    result_type: Literal["orbital_anomaly"] = "orbital_anomaly"
    status: Literal["available", "unavailable", "error"] = "unavailable"
    model_name: str | None = None
    model_version: str | None = None
    training_dataset: str | None = None
    classification: Literal["unusual", "not_flagged"] | None = None
    decision_score: float | None = None
    anomaly_score: float | None = Field(default=None, ge=0.0, le=1.0)
    score_definition: str = "empirical lower-tail rank within training decision scores; not a probability or danger estimate"
    input_features: dict[str, float] | None = None
    feature_units: dict[str, str] | None = None
    feature_frame: str | None = None
    training_reference_event_count: int | None = None
    reason_code: str = "ANOMALY_MODEL_UNAVAILABLE"
    provenance: dict[str, Any] | None = None


class ComparisonResult(BaseModel):
    result_type: Literal["comparison"] = "comparison"
    status: Literal["available", "unavailable", "not_applicable", "not_comparable"] = "unavailable"
    consistency: str | None = None
    ml_available: bool | None = None
    physics_pc_available: bool | None = None
    validation_claim: Literal["none"] = "none"
    reason_code: str = "no_independent_ml_result_or_physics_assessment"


class ReviewPriority(BaseModel):
    """ORION internal geometry-only review triage, never a collision probability."""

    category: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "REVIEW_REQUIRED", "UNCLASSIFIED"] = "UNCLASSIFIED"
    policy_name: str = "ORION Geometry-only Review Priority"
    policy_version: str = "orion-geometry-review-v1"
    status: Literal["classified", "review_required", "unclassified"] = "unclassified"
    criteria: dict[str, Any] = Field(default_factory=dict)
    input_signals: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    explanation: str = "Review priority is unclassified because required geometry inputs are unavailable."
    reason_codes: list[str] = Field(default_factory=list)


class AutomaticResearchPcAssessment(BaseModel):
    """Assumption-based research estimate, separated from event-specific Pc."""

    result_type: Literal["automatic_research_pc_assessment"] = "automatic_research_pc_assessment"
    status: Literal["event_specific_foster_available", "prior_based_research_estimate", "not_estimable", "not_applicable"]
    quality_status: Literal["validated_event_inputs", "prior_based_unvalidated", "insufficient_inputs", "not_assessed"]
    estimated_pc: float | None = None
    estimated_pc_scientific: str | None = None
    log10_pc: float | None = None
    negligible: bool = False
    percentage: float | None = None
    percentage_scientific: str | None = None
    risk_assessment: PhysicsPcRiskAssessment | None = None
    lower_sensitivity_pc: float | None = None
    upper_sensitivity_pc: float | None = None
    lower_sensitivity_pc_scientific: str | None = None
    upper_sensitivity_pc_scientific: str | None = None
    method_name: str = "ORION prior-based research Pc"
    method_version: str = "1.0.0"
    covariance_policy_id: str | None = None
    covariance_policy_name: str | None = None
    encounter_plane_sigma_min_km: float | None = None
    encounter_plane_sigma_max_km: float | None = None
    miss_sigma_ratio: float | None = None
    covariance_method: str | None = None
    hbr_method: str | None = None
    hbr_km: float | None = None
    hbr_source: str | None = None
    hbr_provenance: dict[str, Any] = Field(default_factory=dict)
    covariance_frame: str | None = None
    covariance_epoch_utc: str | None = None
    hbr_sensitivity_km: list[float] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)
    reason_message: str | None = None
    geometry_review_category: str | None = None
    geometry_review_policy_version: str | None = None
    ranking_basis: str = "Geometry review priority; not collision probability"
    sensitivity_status: Literal["available", "not_available", "not_applicable"] = "not_available"
    sensitivity_reason: str = "No numerical sensitivity assessment was available."
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ResearchPcScenarioRequest(BaseModel):
    covariance_policy: Literal["esa_population_prior", "tle_age_baseline", "tle_age_baseline_2x"] = "tle_age_baseline"
    covariance_scale: float = Field(default=1.0, gt=0, le=10)
    hbr_scale: float = Field(default=1.0, gt=0, le=10)


class AiRiskAssessment(BaseModel):
    """Live-compatible deterministic queue score; not ML probability or Pc."""

    score: float = Field(ge=0.0, le=1.0)
    category: Literal["Critical", "High", "Medium", "Low"]
    model_name: str = "ORION deterministic live-geometry risk prioritizer"
    model_version: str = "1.0.0"
    target_definition: str = "Normalized screening-priority index in [0,1]; not collision probability, Pc, or ESA log10 event risk."
    prediction_method: Literal["deterministic_geometry_speed_fallback"] = "deterministic_geometry_speed_fallback"
    feature_provenance: dict[str, Any] = Field(default_factory=dict)
    model_quality: dict[str, Any] = Field(default_factory=dict)
    explanation: str
    geometry_rank: int | None = None
    foster_pc_rank: int | None = None
    research_pc_rank: int | None = None
    final_priority_rank: int | None = None
    final_priority_score: float | None = Field(default=None, ge=0.0, le=1.0)
    ranking_explanation: str | None = None


class CollisionPcSurrogateResult(BaseModel):
    status: Literal["available", "fallback", "unavailable", "error"]
    model_name: str | None = None
    model_version: str | None = None
    ai_predicted_log10_pc: float | None = None
    deterministic_reference_log10_pc: float | None = None
    fallback_method: str | None = None
    reason_code: str | None = None
    target_definition: str = "log10(research_pc) generated by ORION physics"
    feature_schema_version: str | None = None
    artifact_sha256: str | None = None


class CollisionRiskClassifierResult(BaseModel):
    status: Literal["available", "fallback", "unavailable", "error"]
    model_name: str | None = None
    model_version: str | None = None
    ai_risk_class: Literal["Low", "Medium", "High"] | None = None
    class_probabilities: dict[str, float] | None = None
    deterministic_reference_risk_class: Literal["Low", "Medium", "High"] | None = None
    fallback_method: str | None = None
    reason_code: str | None = None
    target_definition: str = "Risk class derived from the same ORION physics research Pc policy"
    feature_schema_version: str | None = None
    artifact_sha256: str | None = None


class CollisionAiAssessment(BaseModel):
    result_type: Literal["collision_ai_assessment"] = "collision_ai_assessment"
    status: Literal["available", "partial", "fallback", "unavailable"]
    inference_provenance: dict[str, Any] = Field(default_factory=dict)
    pc_surrogate: CollisionPcSurrogateResult
    risk_classifier: CollisionRiskClassifierResult


class ObjectSummary(BaseModel):
    id: str
    name: str
    category: Category
    object_type: str
    source_classification: str | None = None
    classification_source: str | None = None
    band: Band
    orbit_type: str
    altitude_km: float
    inclination_deg: float
    velocity_kms: float
    heuristic_risk_score: float
    heuristic_forecast_score: float
    provenance: Provenance
    heuristic_score_provenance: Provenance

    @model_validator(mode="after")
    def validate_classification_consistency(self) -> "ObjectSummary":
        inferred = classify_object(
            object_type=self.object_type,
            category=self.category,
            source_classification=self.source_classification,
            name=self.name,
        )
        self.category = inferred.category
        self.object_type = inferred.object_type
        if inferred.classification_source == "conflicting_or_unsupported_metadata":
            self.classification_source = inferred.classification_source
        return self


class ScreeningProxyEvent(BaseModel):
    id: str
    event_identity_type: Literal["internal_deterministic"] = "internal_deterministic"
    primary: ObjectSummary
    secondary: ObjectSummary
    obj_a: ObjectSummary
    obj_b: ObjectSummary
    pair_type: str
    risk_level: str
    risk_score: float = Field(ge=0, le=1)
    priority_score: float = Field(ge=0, le=100)
    suggested_action: str
    features: dict[str, Any]
    provenance: Provenance
    physics_result: PhysicsResult
    ml_result: MLResult = Field(default_factory=MLResult)
    comparison_result: ComparisonResult = Field(default_factory=ComparisonResult)


class ConjunctionAssessmentEvent(BaseModel):
    """Trajectory-derived close approach with separate physics and queue-assessment fields."""

    id: str
    screening_job_id: str | None = None
    event_identity_type: Literal["trajectory_event_deterministic"] = "trajectory_event_deterministic"
    result_kind: Literal["physics_assessment"] = "physics_assessment"
    primary: ObjectSummary
    secondary: ObjectSummary
    obj_a: ObjectSummary
    obj_b: ObjectSummary
    pair_type: str
    provenance: Provenance
    physics_result: PhysicsResult
    collision_probability: CollisionProbabilityResult | None = None
    automatic_research_pc_assessment: AutomaticResearchPcAssessment | None = None
    scenario_collision_probability: CollisionProbabilityResult | None = None
    scenario_inputs: dict[str, Any] | None = None
    scenario_assumptions: list[str] = Field(default_factory=list)
    ml_result: MLResult = Field(default_factory=MLResult)
    anomaly_result: OrbitalAnomalyResult = Field(default_factory=OrbitalAnomalyResult)
    comparison_result: ComparisonResult = Field(default_factory=ComparisonResult)
    review_priority: ReviewPriority = Field(default_factory=ReviewPriority)
    ai_risk_assessment: AiRiskAssessment | None = None
    collision_ai_assessment: CollisionAiAssessment | None = None


class CdmImportRequest(BaseModel):
    cdm_xml: str = Field(min_length=1, max_length=1_000_000)
    source_label: str = Field(min_length=1, max_length=200)
    assume_independent_covariances: bool = False


class SpaceTrackCdmRequest(BaseModel):
    assume_independent_covariances: bool = False


class ReferenceManeuverRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=100)
    maneuvering_object_id: str = Field(min_length=1, max_length=32)
    burn_lead_seconds: float = Field(ge=60, le=10800)
    direction: Literal["radial+", "radial-", "along_track+", "along_track-", "cross_track+", "cross_track-"]
    delta_v_m_s: float = Field(gt=0, le=0.1)


class ReferenceManeuverReportRequest(ReferenceManeuverRequest):
    pass


class ScenarioPcRequest(BaseModel):
    covariance_primary_km2: list[list[float]]
    covariance_secondary_km2: list[list[float]]
    hbr_km: float = Field(gt=0)
    assume_independent_covariances: bool
    assumptions: str = Field(min_length=10, max_length=1000)
