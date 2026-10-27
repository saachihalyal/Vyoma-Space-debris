import React, { useEffect, useMemo, useState, lazy } from "react";
import { motion } from "framer-motion";
import { DatabaseZap, PanelRightOpen, Pause, Play, Radar, Satellite, ShieldAlert, SlidersHorizontal } from "lucide-react";
import { sourceLabel } from "../../utils/catalogStatus.js";
import { resolveGlobeEventSelection } from "../../utils/globeEventReport.js";
import { TelemetryStrip } from "./TelemetryStrip.jsx";
const SSAScene = lazy(() => import("../Scene/SSAScene.jsx").then((module) => ({ default: module.SSAScene })));
const AnalyticsPanel = lazy(() => import("./AnalyticsPanel.jsx").then((module) => ({ default: module.AnalyticsPanel })));
const ControlPanel = lazy(() => import("./ControlPanel.jsx").then((module) => ({ default: module.ControlPanel })));
const TimelinePanel = lazy(() => import("./TimelinePanel.jsx").then((module) => ({ default: module.TimelinePanel })));
class SceneErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("[Vyoma visualization] scene render failed", {
      message: error?.message || "Unknown scene rendering error",
      componentStack: info?.componentStack || "",
    });
  }

  render() {
    if (this.state.error) {
      return <div className="scene-render-error" role="alert">
        <strong>Globe rendering failed</strong>
        <span>{this.state.error.message || "Unknown rendering error"}</span>
        <button type="button" onClick={() => this.setState({ error: null })}>Retry globe</button>
      </div>;
    }
    return this.props.children;
  }
}

export function VisualizationPage(props) {
  const {
    snapshot,
    filters,
    setFilters,
    forecastHours,
    setForecastHours,
    isPlaying,
    setIsPlaying,
    activeFrame,
    selectedObject,
    setSelectedObject,
    selectedRisk,
    setSelectedRisk,
    analyticsOpen,
    setAnalyticsOpen,
    pulse,
    loading,
    pendingFocusId,
    pendingGlobeSelection,
    onClearPendingFocus,
    download,
    onGlobeReportDownload,
  } = props;
  const stats = snapshot?.stats || {};

  // Track auto-focus triggers for Show in Globe navigation
  const [focusKey, setFocusKey] = useState(0);
  const [hoveredObject, setHoveredObject] = useState(null);

  // Keep the selected event and its originating job after pending navigation state is cleared.
  const [localGlobeSelection, setLocalGlobeSelection] = useState(null);

  // Consume pendingFocusId: auto-select the object and focus on it
  useEffect(() => {
    if (!pendingFocusId || !snapshot?.objects) return;
    const match = snapshot.objects.find((obj) => obj.id === pendingFocusId);
    setLocalGlobeSelection(pendingGlobeSelection || {
      event: null,
      screeningJobId: null,
      resultKind: null,
      error: "The selected close approach is no longer in the accepted screening result.",
    });
    if (match) {
      setSelectedObject(match);
      setSelectedRisk(null);
      setAnalyticsOpen(true);
      // Trigger camera focus
      setFocusKey((k) => k + 1);
    } else {
      setSelectedObject(null);
      setSelectedRisk(null);
      setAnalyticsOpen(true);
    }
    onClearPendingFocus();
  }, [pendingFocusId, snapshot]);

  const resolvedGlobeSelection = useMemo(() => {
    if (!localGlobeSelection) return { event: null, error: null };
    try {
      return { ...resolveGlobeEventSelection(localGlobeSelection), error: null };
    } catch (error) {
      return { event: null, error: error?.message || "The selected close approach could not be opened." };
    }
  }, [localGlobeSelection]);

  return (
    <div className="mission-scene-shell">
      <SceneErrorBoundary>
      <SSAScene
        snapshot={snapshot}
        filters={filters}
        forecastHours={forecastHours}
        activeFrame={activeFrame}
        selectedObject={selectedObject}
        highlightedObjectIds={resolvedGlobeSelection.event ? [resolvedGlobeSelection.event.primary?.id, resolvedGlobeSelection.event.secondary?.id].filter(Boolean) : []}
        selectedRisk={selectedRisk}
        focusKey={focusKey}
        onHoverObject={setHoveredObject}
        onSelectObject={(object) => {
          setSelectedObject(object);
          setSelectedRisk(null);
          setAnalyticsOpen(true);
        }}
        onSelectRisk={(risk) => {
          setSelectedRisk(risk);
          setSelectedObject(null);
          setAnalyticsOpen(true);
        }}
      />
      </SceneErrorBoundary>
      <div className="hud-layer">
        {hoveredObject?.object && <div className="globe-hover-tooltip" style={{ left: Math.min(window.innerWidth - 300, Math.max(8, hoveredObject.x + 14)), top: Math.min(window.innerHeight - 150, Math.max(8, hoveredObject.y + 14)) }}><strong>{hoveredObject.object.name || hoveredObject.object.id || "Unknown object"}</strong><span>{hoveredObject.object.category || "Other / unknown"}</span>{Number.isFinite(Number(hoveredObject.object.orbit?.altitude_km ?? hoveredObject.object.altitude_km)) ? <span>Altitude: {Number(hoveredObject.object.orbit?.altitude_km ?? hoveredObject.object.altitude_km).toFixed(1)} km</span> : null}{Number.isFinite(Number(hoveredObject.object.velocity_kms ?? hoveredObject.object.speed_kms)) ? <span>Speed: {Number(hoveredObject.object.velocity_kms ?? hoveredObject.object.speed_kms).toFixed(3)} km/s</span> : null}</div>}
        {loading && !snapshot ? <div className="scene-data-notice" role="status">Loading catalog objects…</div> : null}
        {!loading && snapshot && !snapshot.objects?.length && snapshot.source_state?.status !== "unavailable" ? <div className="scene-data-notice" role="status">No catalog objects were returned.</div> : null}
        {snapshot?.source_state?.status === "unavailable" && !snapshot?.objects?.length ? <div className="scene-data-notice" role="status">Catalog data could not be loaded.</div> : null}
        {resolvedGlobeSelection.error ? <div className="scene-data-notice" role="status">{resolvedGlobeSelection.error}</div> : null}
        <motion.header className="top-command-bar" initial={{ y: -16, opacity: 0 }} animate={{ y: 0, opacity: 1 }}>
          <div className="brand-block">
            <div className="brand-mark"><Radar size={22} /></div>
            <div><p className="eyebrow">Orbital Environment</p><h1>Visualization</h1></div>
          </div>
          <div className="status-cluster">
            <StatusMetric icon={<Satellite size={16} />} label="Tracked" value={stats.tracked_objects || 0} />
            {Number.isFinite(stats.global_heuristic_risk_score) ? <StatusMetric icon={<ShieldAlert size={16} />} label="Heuristic Index" value={stats.global_heuristic_risk_score.toFixed(3)} accent="risk" /> : null}
            <StatusMetric icon={<DatabaseZap size={16} />} label="Feed" value={sourceLabel(snapshot?.source_summary?.status)} />
            <button className="icon-button" type="button" aria-label="Open analytics panel" onClick={() => setAnalyticsOpen(true)}><PanelRightOpen size={17} /></button>
          </div>
        </motion.header>
        <section className="left-rail"><ControlPanel filters={filters} setFilters={setFilters} stats={stats} /></section>
        <section className={`right-rail ${analyticsOpen ? "" : "rail-closed"}`}>
          {analyticsOpen ? (
            <AnalyticsPanel
              object={selectedObject}
              selectedEvent={resolvedGlobeSelection.event}
              eventScreeningJobId={resolvedGlobeSelection.screeningJobId}
              risk={selectedRisk}
              snapshot={snapshot}
              activeFrame={activeFrame}
              onClose={() => {
                if (selectedObject || selectedRisk) {
                  setSelectedObject(null);
                  setSelectedRisk(null);
                } else {
                  setAnalyticsOpen(false);
                }
              }}
              onDownloadReport={resolvedGlobeSelection.event && onGlobeReportDownload ? () => onGlobeReportDownload(localGlobeSelection) : null}
            />
          ) : null}
        </section>
        <section className="bottom-rail">
          <TimelinePanel
            forecastHours={forecastHours}
            setForecastHours={setForecastHours}
            isPlaying={isPlaying}
            setIsPlaying={setIsPlaying}
            activeFrame={activeFrame}
          />
          <TelemetryStrip pulse={pulse} snapshot={snapshot} loading={loading} />
        </section>
        <div className="floating-actions">
          <button className="round-action" type="button" onClick={() => setIsPlaying((value) => !value)}>{isPlaying ? <Pause size={18} /> : <Play size={18} />}</button>
          <button className="round-action" type="button" onClick={() => document.querySelector(".left-rail")?.classList.toggle("rail-open")}><SlidersHorizontal size={18} /></button>
        </div>
      </div>
    </div>
  );
}


function StatusMetric({ icon, label, value, accent }) {
  return (
    <div className={`status-metric ${accent || ""}`}>
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

