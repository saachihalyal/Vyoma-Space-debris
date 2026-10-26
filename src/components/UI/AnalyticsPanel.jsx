import { Download } from "lucide-react";
import { motion } from "framer-motion";
import { Crosshair, Orbit, Satellite, ShieldAlert } from "lucide-react";
import { formatIndex, formatNumber } from "../../utils/orbitalMath";
import { getObjectTypeLabel } from "../../utils/objectClassification";
import { buildCanonicalIdentity, resolveById, OBJECT_TYPE } from "../../utils/identityModel";

export function AnalyticsPanel({ object, selectedEvent, eventScreeningJobId, risk, snapshot, activeFrame, onDownloadReport }) {
  // Use canonical identity model for consistent display
  // This ensures the AnalyticsPanel shows the SAME type/classification as
  // Collision Analysis, EventList, ObjectPair, and the Globe.
  const canonicalIdentity = object ? buildCanonicalIdentity(object) : null;
  const resolvedType = canonicalIdentity ? canonicalIdentity.displayType : getObjectTypeLabel(object);
  const resolvedId = canonicalIdentity ? canonicalIdentity.id : (object?.id || "");
  const resolvedName = canonicalIdentity ? canonicalIdentity.name : (object?.name || "UNKNOWN");

  // Cross-verify the object against the catalog (if available)
  // This catches cases where the object was passed with wrong identity
  // We use the catalog identity as authoritative if it differs from locally inferred type
  let finalType = resolvedType;
  let finalId = resolvedId;
  let finalName = resolvedName;
  if (object && snapshot?.objects && canonicalIdentity) {
    const catalogIdentity = resolveById(object.id, snapshot.objects, { suppressErrors: true });
    if (!catalogIdentity.unresolved && catalogIdentity.objectType !== canonicalIdentity.objectType) {
      console.warn(
        `[AnalyticsPanel] TYPE MISMATCH for ID ${object.id}: ` +
        `displayed type "${canonicalIdentity.displayType}" differs from catalog "${catalogIdentity.displayType}". ` +
        `Using catalog type for consistency.`
      );
      finalType = catalogIdentity.displayType;
      finalId = catalogIdentity.id;
      finalName = catalogIdentity.name;
    }
  }

  if (object) {
    const objectType = finalType;
    return (
      <motion.aside className="glass-panel analytics-panel" initial={{ x: 22, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 22, opacity: 0 }}>
        <PanelTitle icon={<Satellite size={18} />} eyebrow={`${objectType} | ${finalId}`} title={finalName} />
        <div className="analytics-grid">
          <Readout label="Object Type" value={objectType} />
          <Readout label="Orbit Type" value={object.orbit_type} />
          <Readout label="Band" value={object.band} />
          <Readout label="Altitude" value={`${formatNumber(object.altitude_km, 1)} km`} />
          <Readout label="Inclination" value={`${formatNumber(object.inclination_deg, 1)} deg`} />
          <Readout label="Velocity" value={`${formatNumber(object.velocity_kms, 2)} km/s`} />
          <Readout label="Heuristic Debris Pressure Score" value={formatIndex(object.heuristic_debris_pressure_score)} />
          <Readout label="Heuristic Risk Index" value={formatIndex(object.heuristic_risk_score)} tone="risk" />
          <Readout label="Heuristic Forecast Score" value={formatIndex(object.heuristic_forecast_score)} tone="risk" />
          {selectedEvent ? <Readout label="Selected conjunction event" value={selectedEvent.id} /> : null}
          {selectedEvent ? <Readout label="Conjunction pair" value={`${selectedEvent.primary?.name || "Unknown"} (${selectedEvent.primary?.id || "ID unavailable"}) ↔ ${selectedEvent.secondary?.name || "Unknown"} (${selectedEvent.secondary?.id || "ID unavailable"})`} /> : null}
          {selectedEvent?.physics_result?.tca?.status === "available" ? <Readout label="Conjunction TCA (UTC)" value={selectedEvent.physics_result.tca.value} /> : null}
          {selectedEvent?.physics_result?.miss_distance?.status === "available" ? <Readout label="Closest approach" value={`${selectedEvent.physics_result.miss_distance.value} km`} /> : null}
          {selectedEvent?.result_kind === "physics_assessment" && eventScreeningJobId ? <Readout label="Originating screening job" value={eventScreeningJobId} /> : null}
          {selectedEvent?.result_kind === "screening_proxy" ? <Readout label="Event type" value="Heuristic proxy (not a physical conjunction)" /> : null}
        </div>
        {onDownloadReport ? (
          <button className="primary-action download-report-btn" type="button" onClick={onDownloadReport}>
            <Download size={16} /> Download Report
          </button>
        ) : null}
      </motion.aside>
    );
  }

  if (risk) {
    return (
      <motion.aside className="glass-panel analytics-panel" initial={{ x: 22, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 22, opacity: 0 }}>
        <PanelTitle icon={<ShieldAlert size={18} />} eyebrow="Risk Region" title={`${risk.band} ${risk.severity.toUpperCase()} Corridor`} />
        <div className="risk-badge-line">
          <span className={`risk-pill ${risk.severity}`}>{risk.severity}</span>
          <span>{formatNumber(risk.altitude_km)} km</span>
          <span>{formatNumber(risk.inclination_deg)} deg inc</span>
        </div>
        <div className="analytics-grid">
          <Readout label="Heuristic Risk Index" value={formatIndex(risk.heuristic_risk_score)} tone="risk" />
          <Readout label="Tracked-Object Density Score" value={formatIndex(risk.tracked_object_density_score)} />
          <Readout label="Heuristic Untracked-Pressure Score" value={formatIndex(risk.heuristic_untracked_pressure_score)} />
          <Readout label="Heuristic Forecast Score" value={formatIndex(risk.heuristic_forecast_score)} tone="risk" />
          <Readout label="Heuristic Uncertainty Score" value={formatIndex(risk.heuristic_uncertainty_score)} />
          <Readout label="RAAN" value={`${formatNumber(risk.raan_deg, 1)} deg`} />
        </div>
        <div className="contributor-list">
          <div className="section-label">
            <Crosshair size={14} />
            <span>Contributing Objects</span>
          </div>
          {risk.contributors?.slice(0, 4).map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      </motion.aside>
    );
  }

  const stats = snapshot?.stats || {};
  const globalHeuristicScore = activeFrame
    ? activeFrame.global_heuristic_risk_score
    : stats.global_heuristic_risk_score;
  return (
    <motion.aside className="glass-panel analytics-panel" initial={{ x: 22, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 22, opacity: 0 }}>
      <PanelTitle icon={<Orbit size={18} />} eyebrow="Orbital Picture" title="Global Risk Field" />
      <div className="large-risk-readout">
        <span>{formatIndex(globalHeuristicScore)}</span>
        <p>global heuristic risk index</p>
      </div>
      <div className="analytics-grid">
        <Readout label="Tracked Objects" value={formatNumber(stats.tracked_objects)} />
        <Readout label="Active Satellites" value={formatNumber(stats.active_satellites)} />
        <Readout label="Debris Objects" value={formatNumber(stats.debris_objects)} />
        <Readout label="Heuristic Forecast Trend" value={formatIndex(stats.heuristic_forecast_trend_score)} tone="risk" />
      </div>
    </motion.aside>
  );
}

function PanelTitle({ icon, eyebrow, title }) {
  return (
    <div className="panel-title">
      {icon}
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
      </div>
    </div>
  );
}

function Readout({ label, value, tone }) {
  return (
    <div className={`readout ${tone || ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

