import React, { lazy, Suspense } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bell,
  CheckCircle2,
  ChevronRight,
  Cpu,
  DatabaseZap,
  Download,
  FileText,
  Filter,
  Gauge,
  Globe2,
  Home,
  LayoutDashboard,
  Loader2,
  PanelRightOpen,
  Pause,
  Play,
  Radar,
  RefreshCw,
  Rocket,
  Satellite,
  Settings,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  downloadReport,
  downloadTrajectoryAssessmentCsv,
  getAnalytics,
  getCatalog,
  getConjunctions,
  getLatestConjunctionJob,
  getSavedEventLibrary,
  getActiveConjunctionJob,
  resumeConjunctionJob,
  importEventCdm,
  calculateScenarioPc,
  calculateResearchPcWhatIf,
  getForecast,
  getManeuver,
  restoreArchivedScreeningJob,
  selectedEventReportPath,
  selectedManeuverReportPath,
  calculateNasaCaraReferenceCase,
  getScreeningProxies,
  getSmartFilter,
  getSystemHealth,
  calculateReferenceCdmPc,
  calculateReferenceManeuver,
} from "./api/ssaClient";
const VisualizationPage = lazy(() => import("./components/UI/VisualizationPage.jsx").then((module) => ({ default: module.VisualizationPage })));
const HomePage = lazy(() => import("./components/UI/HomePage.jsx").then((module) => ({ default: module.HomePage })));
const SmartFilterWorkbench = lazy(() => import("./components/UI/SmartFilterWorkbench.jsx").then((module) => ({ default: module.SmartFilterWorkbench })));
import { CollisionPcSummary, CollisionProbabilityCard, formatCollisionProbability, formatProbabilityPercentage, formatProbabilityScientific, isUsablePc, isValidProbability, pcDisplayStatus, sourcePcLabel } from "./components/UI/CollisionPcSummary.js";
const CdmReferenceAssessment = lazy(() => import("./components/UI/CdmReferenceAssessment.jsx").then((module) => ({ default: module.CdmReferenceAssessment })));
const ReferenceManeuverAssessment = lazy(() => import("./components/UI/ReferenceManeuverAssessment.jsx").then((module) => ({ default: module.ReferenceManeuverAssessment })));
const EventAnomalyPanel = lazy(() => import("./components/UI/OrbitalAnomalySummary.js").then((module) => ({ default: module.EventAnomalyPanel })));
const RiskBadge = lazy(() => import("./components/UI/RiskBadge.js").then((module) => ({ default: module.RiskBadge })));
import { formatNumber } from "./utils/orbitalMath";
import { createRequestSequence, ignoreAbort } from "./utils/requestSequence";
import { getScreeningJobSelection } from "./utils/screeningJobSelection";
import { datasetLabel, retainCatalogSnapshot, sourceLabel } from "./utils/catalogStatus";
import { eligibleManeuverEvents, isCurrentManeuverRequest, maneuverAssessmentForSelection, maneuverPageState, resolveManeuverEvent, selectManeuverEvent } from "./utils/maneuverSelection";
const ManeuverBaselineComparison = lazy(() => import("./components/UI/ManeuverBaselineComparison.js").then((module) => ({ default: module.ManeuverBaselineComparison })));
const ManeuverEventContext = lazy(() => import("./components/UI/ManeuverEventContext.js").then((module) => ({ default: module.ManeuverEventContext })));
const CollisionPriorityTable = lazy(() => import("./components/UI/CollisionPriorityTable.js").then((module) => ({ default: module.CollisionPriorityTable })));
const CollisionWorkbench = lazy(() => import("./components/UI/CollisionWorkbench.jsx").then((module) => ({ default: module.CollisionWorkbench })));
import { operationalFosterStatus, physicsPcRiskPresentation, researchPcPresentation } from "./utils/collisionPcPresentation.js";
const ManeuverAiSummary = lazy(() => import("./components/UI/ManeuverAiSummary.js").then((module) => ({ default: module.ManeuverAiSummary })));
const ManeuverScreeningContext = lazy(() => import("./components/UI/ManeuverScreeningContext.js").then((module) => ({ default: module.ManeuverScreeningContext })));
const ManeuverUserUpload = lazy(() => import("./components/UI/ManeuverUserUpload.jsx").then((module) => ({ default: module.ManeuverUserUpload })));
const ManeuverWorkbench = lazy(() => import("./components/UI/ManeuverWorkbench.jsx").then((module) => ({ default: module.ManeuverWorkbench })));
import { BuildVersionBadge } from "./components/UI/BuildVersionBadge.jsx";
import { buildSmartFilterView } from "./utils/smartFilterView";
import { captureGlobeEventSelection, downloadGlobeEventReport, resolveGlobeEventSelection } from "./utils/globeEventReport.js";
const EventRiskEstimate = lazy(() => import("./components/UI/EventRiskEstimate.js").then((module) => ({ default: module.EventRiskEstimate })));
import { proxyPriorityClassIndex } from "./utils/analyticsPresentation.js";
import { CatalogDensityGlobe } from "./components/Scene/CatalogDensityGlobe.jsx";
import { beginScreeningAttempt, collisionScreeningState, createExplicitRefreshHandler, finishScreeningAttempt, reconcilePhysicalEventSelection, resolvePhysicalEventSelection, screeningResultMatchesRun, screeningStatusForEmptyResults, screeningSummaryDisplay, shouldStartScreeningRun, updateScreeningAttempt } from "./utils/screeningRefreshPolicy.js";
import { readWatchlist } from "./utils/watchlistStorage.js";
import { researchPcCatalogSummary } from "./utils/researchPcAnalytics.js";
import { readAcceptedScreeningCache, saveAcceptedScreeningCache } from "./utils/acceptedScreeningCache.js";
import { COLLISION_INVALID_ASSESSMENT_LABEL, COLLISION_PAIR_FILTERS, collisionEventPriority, explainPhysicsReason, filterCollisionEvents, getCollisionEventsForDisplay, rankCollisionEvents, rankOrbitalAnomalyEvents, screeningAssessmentCounts, searchAndSortCollisionEvents } from "./utils/collisionEventDisplay.js";
import { clearActiveScreeningJobId, readActiveScreeningJobId, saveActiveScreeningJobId } from "./utils/screeningJobStorage.js";
import {
  getObjectTypeLabel,
  getObjectTypeKey,
  validateAndFilterEvents,
} from "./utils/objectClassification";
import {
  buildCanonicalIdentity,
  resolveObjectType,
  getDisplayType,
  getPairType,
  formatObjectIdentity,
  isSatelliteDebrisPair,
  resolveById,
  validateEventIdentities,
  getEventCategoryLabel,
  isPrimaryOperationalRisk,
  PAIR_PRIORITY_MULTIPLIER,
  PAIR_CATEGORY_LABEL,
  OBJECT_TYPE,
  OBJECT_TYPE_DISPLAY,
  PAIR_TYPE,
} from "./utils/identityModel";
const initialFilters = {
  active: true,
  debris: true,
  LEO: true,
  MEO: true,
  GEO: true,
  low: true,
  moderate: true,
  elevated: true,
  severe: true,
};

const NAV = [
  { id: "home", label: "Home", icon: Home },
  { id: "visualization", label: "Visualization", icon: Globe2 },
  { id: "smart", label: "Smart Filter", icon: Filter },
  { id: "collision", label: "Collision Analysis", icon: Radar },
  { id: "maneuver", label: "Maneuver", icon: Rocket },
  { id: "analytics", label: "Catalog Analytics", icon: BarChart3 },
  { id: "reports", label: "Reports", icon: FileText },
  { id: "upload", label: "Upload CDM", icon: Download },
];

export default function App() {
  const [activePage, setActivePage] = useState("home");
  const [screeningHorizonHours, setScreeningHorizonHours] = useState(72);
  const [uncertaintyScale, setUncertaintyScale] = useState(1);
  const [scenarioClassCounts, setScenarioClassCounts] = useState(null);
  const scenarioClassCacheRef = useRef(new Map());
  const [sensitivityPcByEvent, setSensitivityPcByEvent] = useState({});
  const sensitivityPcCacheRef = useRef(new Map());
  const [snapshot, setSnapshot] = useState(null);
  const [eventLibrary, setEventLibrary] = useState(null);
  const lastCatalogSnapshotRef = useRef(null);
  const [forecast, setForecast] = useState(null);
  const [platform, setPlatform] = useState(() => {
    const cached = readAcceptedScreeningCache();
    return { health: null, analytics: null, conjunctions: cached?.events || [], screeningProxies: [], conjunctionStatus: cached?.status || { api_status: "idle", result_status: "not_started" }, screeningAttempt: null, smart: null };
  });
  const [archivedJobSelection, setArchivedJobSelection] = useState(null);
  const [archiveRestoreBusy, setArchiveRestoreBusy] = useState(false);
  const [filters, setFilters] = useState(initialFilters);
  const [forecastHours, setForecastHours] = useState(24);
  const [isPlaying, setIsPlaying] = useState(true);
  const [selectedObject, setSelectedObject] = useState(null);
  const [selectedRisk, setSelectedRisk] = useState(null);
  const [eventSelection, setEventSelection] = useState({ event: null, context: null, notice: null });
  const selectedEvent = eventSelection.event;
  const [pendingFocusId, setPendingFocusId] = useState(null);
  const [pendingGlobeSelection, setPendingGlobeSelection] = useState(null);
  const [maneuver, setManeuver] = useState(null);
  const [maneuverRequest, setManeuverRequest] = useState(null);
  const [referenceManeuverEvent, setReferenceManeuverEvent] = useState(null);
  const [maneuverDemoBusy, setManeuverDemoBusy] = useState(false);
  const [maneuverDemoAssessment, setManeuverDemoAssessment] = useState(null);
  const maneuverRequestGenerationRef = useRef(0);
  const [loading, setLoading] = useState(true);
  const [backendBusy, setBackendBusy] = useState(false);
  const [pulse, setPulse] = useState(0);
  const explicitScreeningRefreshRef = useRef(null);
  const screeningLaunchRef = useRef({ runId: null });
  const screeningRunRef = useRef({ startedAt: null, timer: null, catalogIdentity: null });
  const screeningRunSequenceRef = useRef(0);
  const [analyticsOpen, setAnalyticsOpen] = useState(true);
  const [globalSearch, setGlobalSearch] = useState("");
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [notices, setNotices] = useState([]);
  const [watchlist, setWatchlist] = useState(() => new Set(readWatchlist()));
  const acceptedScreeningJobIdRef = useRef(platform.conjunctionStatus?.job_id || null);
  const proxyFetchKeyRef = useRef(null);
  acceptedScreeningJobIdRef.current = platform.conjunctionStatus?.job_id || null;
  
  useEffect(() => {
    let cancelled = false;
    let activeController = null;
    let activeRequestId = null;
    let activeInvocationId = null;
    const requests = createRequestSequence();

    async function load({ explicitScreeningRefresh = true, invocationId = null, horizonHours = 72 } = {}) {
      const currentRequestId = requests.next();
      console.info("[ORION screening diagnostic] load entered", {
        invocationId,
        requestId: currentRequestId,
        explicitScreeningRefresh,
        runActive: screeningRunRef.current.startedAt != null,
        abortingPreviousCatalogRequest: Boolean(activeController),
        previousRequestId: activeRequestId,
        previousInvocationId: activeInvocationId,
      });
      if (activeController) console.info("[ORION screening diagnostic] aborting prior catalogue request", { invocationId, requestId: currentRequestId, abortedRequestId: activeRequestId, abortedInvocationId: activeInvocationId });
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      activeRequestId = currentRequestId;
      activeInvocationId = invocationId;
      setLoading((wasLoading) => wasLoading && !lastCatalogSnapshotRef.current);
      const current = () => !cancelled && requests.isCurrent(currentRequestId);
      const catalogPromise = getCatalog({ signal: controller.signal }).then((catalog) => {
        const requestIsCurrent = current();
        console.info("[ORION screening diagnostic] catalogue resolved", {
          invocationId,
          requestId: currentRequestId,
          requestIsCurrent,
          catalogueReady: Boolean(catalog),
          objectCount: Array.isArray(catalog?.objects) ? catalog.objects.length : null,
          sourceStatus: catalog?.source_state?.status || null,
          aborted: controller.signal.aborted,
        });
        if (!requestIsCurrent) {
          console.info("[ORION screening diagnostic] catalogue result ignored: request is cancelled or superseded", { invocationId, requestId: currentRequestId, cancelled, requestStillCurrent: requests.isCurrent(currentRequestId), signalAborted: controller.signal.aborted });
          return null;
        }
        const acceptedCatalog = retainCatalogSnapshot(lastCatalogSnapshotRef.current, catalog);
        lastCatalogSnapshotRef.current = acceptedCatalog;
        setSnapshot(acceptedCatalog);
        setBackendBusy(acceptedCatalog?.source_state?.status === "unavailable" && String(acceptedCatalog?.source_state?.last_error_code || "").toLowerCase().includes("backend busy"));
        setLoading(false);
        setPulse((value) => value + 1);
        return acceptedCatalog;
      }).catch((error) => {
        const launch = screeningLaunchRef.current;
        if (explicitScreeningRefresh && launch.runId && current() && error?.name !== "AbortError") {
          screeningLaunchRef.current = { runId: null };
          setLoading(false);
          setPlatform((previous) => updateScreeningAttempt(previous, launch.runId, {
            api_status: "error", result_status: "unavailable", completion_status: "failed",
            reason: error?.message || "The current catalog could not be loaded; screening did not start.",
            progress: { stage: "failed", percent: null, message: error?.message || "The current catalog could not be loaded; screening did not start." },
          }));
        }
        throw error;
      });
      ignoreAbort(getForecast({ horizonHours: 168, steps: 9, signal: controller.signal }).then((value) => {
        if (current()) setForecast(value);
      }), (error) => {
        if (current() && error?.name !== "AbortError") console.warn("Forecast refresh failed.", error);
      });
      ignoreAbort(catalogPromise.then((catalog) => {
        const requestIsCurrent = current();
        const runActive = screeningRunRef.current.startedAt != null;
        const policyAllowsScreening = shouldStartScreeningRun({ explicitRefresh: explicitScreeningRefresh, runActive });
        if (!catalog || !requestIsCurrent || !policyAllowsScreening) {
          const skippedBecause = !catalog ? "catalogue_unavailable"
            : !requestIsCurrent ? "request_cancelled_or_superseded"
              : !explicitScreeningRefresh ? "refresh_was_passive"
                : runActive ? "screening_job_already_active" : "policy_rejected";
          console.warn("[ORION screening diagnostic] screening skipped", {
            invocationId,
            requestId: currentRequestId,
            skippedBecause,
            explicitScreeningRefresh,
            requestIsCurrent,
            catalogueReady: Boolean(catalog),
            runActive,
            policyAllowsScreening,
          });
          if (!catalog && explicitScreeningRefresh && screeningLaunchRef.current.runId) {
            const launchRunId = screeningLaunchRef.current.runId;
            screeningLaunchRef.current = { runId: null };
            setPlatform((previous) => updateScreeningAttempt(previous, launchRunId, {
              api_status: "error", result_status: "unavailable", completion_status: "failed",
              reason: "The current catalog could not be loaded; screening did not start.",
              progress: { stage: "failed", percent: null, message: "The current catalog could not be loaded; screening did not start." },
            }));
          }
          return;
        }
        const catalogIdentity = catalog.generated_at || catalog.stats?.provenance?.input_hash || `${catalog.source_state?.source || "unknown"}:${catalog.objects?.length || 0}`;
        const startedAt = Date.now();
        const runId = `${startedAt}-${++screeningRunSequenceRef.current}`;
        const startUtc = new Date(startedAt).toISOString();
        screeningLaunchRef.current = { runId: null };
        screeningRunRef.current = { startedAt, runId, catalogIdentity, startUtc, timer: null };
        console.info("[ORION screening diagnostic] screening guard passed", { invocationId, requestId: currentRequestId, runId, catalogueObjectCount: catalog.objects?.length || 0 });
        console.info("[ORION lifecycle] screening started", { invocationId, requestId: currentRequestId, runId, catalogIdentity, startUtc });
        const queuedStatus = {
          run_id: runId, job_id: null,
          api_status: "available", result_status: "queued", completion_status: null,
          progress: { stage: "queued", percent: 0, message: "Screening job accepted." },
          source_summary: catalog.source_summary || null,
          screening: { horizon_hours: horizonHours, sample_step_seconds: 60, screening_threshold_km: 25, start_utc: startUtc },
        };
        setPlatform((previous) => beginScreeningAttempt(previous, queuedStatus));
        getConjunctions({ limit: 400, horizonHours, sampleStepSeconds: 60, screeningThresholdKm: 25, startUtc, catalogIdentity, diagnosticInvocationId: invocationId,
          onStatus: (job) => {
            if (screeningRunRef.current.runId !== runId) {
              console.warn("[ORION screening diagnostic] job status ignored: run identity changed", { invocationId, requestId: currentRequestId, expectedRunId: runId, receivedJobId: job?.job_id || null });
              return;
            }
            if (job.job_id) screeningRunRef.current.jobId = job.job_id;
            if (job.job_id) saveActiveScreeningJobId(job.job_id);
              setBackendBusy(job.progress?.stage === "status_retry");
            if (job.status !== screeningRunRef.current.lastLoggedStatus) {
              screeningRunRef.current.lastLoggedStatus = job.status;
              console.info("[ORION lifecycle] screening status", { invocationId, requestId: currentRequestId, runId, jobId: job.job_id || null, status: job.status || job.result_status || "unknown" });
            }
            setPlatform((previous) => updateScreeningAttempt(previous, runId, {
              api_status: job.api_status || "available",
              result_status: job.status || job.result_status || "running",
              job_id: job.job_id || previous.screeningAttempt?.job_id || null,
              started_at: job.started_at || previous.screeningAttempt?.started_at || null,
              finished_at: job.finished_at || previous.screeningAttempt?.finished_at || null,
              completion_status: job.completion_status || null,
              progress: job.progress || null,
              reason: job.progress?.message || null,
            }));
          },
        }).then((payload) => {
          if (screeningRunRef.current.runId !== runId) {
            console.warn("[ORION screening diagnostic] terminal result ignored: run identity changed", { invocationId, requestId: currentRequestId, runId });
            return;
          }
          const finishingRun = { ...screeningRunRef.current, sequence: screeningRunSequenceRef.current };
          console.info("[ORION lifecycle] screening terminal", { invocationId, requestId: currentRequestId, runId, jobId: payload?.job_id || null, status: payload?.completion_status || payload?.result_status || "unknown", eventCount: Array.isArray(payload?.data) ? payload.data.length : null });
          screeningRunRef.current = { startedAt: null, timer: null, catalogIdentity: null, startUtc: null };
          const returnedEvents = Array.isArray(payload?.data) ? payload.data : [];
          const validatedEvents = validateAndFilterEvents(returnedEvents);
          const physicalEvents = validatedEvents.filter((event) => event.result_kind === "physics_assessment");
          const resultPayload = { ...payload, structurally_invalid_excluded_count: returnedEvents.length - validatedEvents.length };
          const accepted = screeningResultMatchesRun(finishingRun, payload);
          if (accepted && ["complete", "partial"].includes(payload?.completion_status)) saveActiveScreeningJobId(payload.job_id);
          else if (finishingRun.jobId) clearActiveScreeningJobId(finishingRun.jobId);
          console.info("[ORION screening diagnostic] terminal result evaluation", {
            invocationId,
            requestId: currentRequestId,
            accepted,
            expectedJobId: finishingRun.jobId || null,
            receivedJobId: payload?.job_id || null,
            completionStatus: payload?.completion_status || null,
            resultStatus: payload?.result_status || null,
            recordCount: returnedEvents.length,
            validPhysicalEventCount: physicalEvents.length,
          });
          setPlatform((previous) => finishScreeningAttempt(previous, runId, resultPayload, physicalEvents));
          if (accepted) saveAcceptedScreeningCache({ ...payload, api_status: payload.api_status || "available" }, physicalEvents);
          if (accepted) {
            setEventSelection((previous) => screeningRunSequenceRef.current === finishingRun.sequence
              ? reconcilePhysicalEventSelection(previous, physicalEvents)
              : previous);
          }
        }).catch((error) => {
          if (screeningRunRef.current.runId !== runId) {
            console.warn("[ORION screening diagnostic] request error ignored: run identity changed", { invocationId, requestId: currentRequestId, runId, name: error?.name || "Error" });
            return;
          }
          console.error("[ORION lifecycle] screening request failed", { invocationId, requestId: currentRequestId, runId, name: error?.name || "Error", message: error?.message || "Screening request failed." });
          screeningRunRef.current = { startedAt: null, timer: null, catalogIdentity: null, startUtc: null };
          setPlatform((previous) => finishScreeningAttempt(previous, runId, { api_status: "error", result_status: "unavailable", completion_status: "failed", reason: error.message || "Screening request failed." }, []));
        });
      }), (error) => {
        console.warn("[ORION screening diagnostic] catalogue follow-up rejected", {
          invocationId,
          requestId: currentRequestId,
          requestIsCurrent: current(),
          errorName: error?.name || "Error",
          message: error?.message || "Catalogue request failed.",
        });
      });
      Promise.all([catalogPromise, getSystemHealth({ signal: controller.signal }), getAnalytics({ signal: controller.signal }), getSmartFilter({ signal: controller.signal })])
        .then(([catalog, healthPayload, analyticsPayload, smartPayload]) => {
          if (!catalog || !current()) {
            console.info("[ORION screening diagnostic] secondary catalogue results ignored", {
              invocationId,
              requestId: currentRequestId,
              catalogueReady: Boolean(catalog),
              requestIsCurrent: current(),
            });
            return;
          }
          setBackendBusy([healthPayload, analyticsPayload, smartPayload].some((payload) => payload?.backend_busy));
          setPlatform((previous) => ({ ...previous, health: healthPayload?.data || healthPayload,
            analytics: analyticsPayload?.data || buildLocalAnalytics(catalog, []),
            smart: smartPayload?.data || buildLocalSmart([], catalog?.stats?.tracked_objects || 0),
          }));
        }).catch((error) => {
          console.warn("[ORION screening diagnostic] secondary refresh requests rejected", {
            invocationId,
            requestId: currentRequestId,
            requestIsCurrent: current(),
            errorName: error?.name || "Error",
            message: error?.message || "Refresh request failed.",
          });
          if (current() && error.name !== "AbortError") pushNotice(setNotices, "Data refresh failed; showing the last accepted mission state.", "warning");
        });
    }

    const explicitRefresh = (invocationId, options = {}) => {
      console.info("[ORION screening diagnostic] explicit callback invoked", { invocationId });
      return load({ explicitScreeningRefresh: true, invocationId, ...options });
    };
    explicitScreeningRefreshRef.current = explicitRefresh;
    console.info("[ORION screening diagnostic] explicit refresh callback installed");
    const savedJobId = readActiveScreeningJobId();
    const restoreAcceptedJob = async () => {
      try {
        let latestJob;
        for (let attempt = 0; attempt < 5; attempt += 1) {
          try { latestJob = await getLatestConjunctionJob(); break; }
          catch (error) {
            if (attempt === 4 || cancelled) throw error;
            await new Promise((resolve) => window.setTimeout(resolve, 8_000));
          }
        }
        if (cancelled) return;
        if (latestJob) {
          const records = latestJob.result.data;
          const validated = validateAndFilterEvents(records);
          const physicalEvents = validated.filter((event) => event.result_kind === "physics_assessment");
          const result = { ...latestJob.result, api_status: "available", job_id: latestJob.job_id, completion_status: latestJob.status, run_date: latestJob.finished_at || latestJob.created_at };
          saveActiveScreeningJobId(latestJob.job_id);
          saveAcceptedScreeningCache(result, physicalEvents);
          const counts = physicalEvents.reduce((out, event) => { const level = event.automatic_research_pc_assessment?.risk_assessment?.final_risk_class; if (level in out) out[level] += 1; return out; }, { Low: 0, Medium: 0, High: 0 });
          setEventLibrary({ events: physicalEvents, references: [], counts, total: physicalEvents.length, current_job_id: latestJob.job_id, label: "accepted screening" });
          setPlatform((previous) => ({
            ...previous, conjunctions: physicalEvents, screeningAttempt: null,
            conjunctionStatus: { api_status: "available", result_status: result.result_status || "valid_non_empty",
              completion_status: latestJob.status, job_id: latestJob.job_id, reason: null,
              physics_assessment_status: result.physics_assessment_status || "available", ml_status: result.ml_status || "unavailable" },
          }));
          setEventSelection((previous) => reconcilePhysicalEventSelection(previous, physicalEvents));
          return;
        }
        const activeJob = await getActiveConjunctionJob();
        if (activeJob?.job_id) {
          resumeSavedJob(activeJob.job_id);
          return;
        }
        if (savedJobId) clearActiveScreeningJobId(savedJobId);
      } catch (error) {
        if (cancelled) return;
        console.warn("[Vyoma startup] accepted screening recovery failed; keeping the current view without starting a screening run.", error);
        if (savedJobId) clearActiveScreeningJobId(savedJobId);
      }
    };
    function resumeSavedJob(savedJobId) {
      const startedAt = Date.now();
      const runId = `resume-${startedAt}-${++screeningRunSequenceRef.current}`;
      screeningRunRef.current = { startedAt, runId, jobId: savedJobId, timer: null };
      setPlatform((previous) => beginScreeningAttempt(previous, {
        run_id: runId, job_id: savedJobId, api_status: "available", result_status: "running", completion_status: null,
        reason: "Restoring the saved screening job.", progress: { stage: "restoring", percent: null, message: "Checking the saved screening job." },
      }));
      const isCurrentResume = () => !cancelled && screeningRunRef.current.runId === runId && screeningRunRef.current.jobId === savedJobId;
      resumeConjunctionJob(savedJobId, {
        onStatus: (job) => {
          if (!isCurrentResume() || job.job_id && job.job_id !== savedJobId) return;
          if (job.job_id) saveActiveScreeningJobId(job.job_id);
          setBackendBusy(job.progress?.stage === "status_retry");
          setPlatform((previous) => updateScreeningAttempt(previous, runId, {
            api_status: job.api_status || "available",
            result_status: job.status || job.result_status || "running",
            job_id: job.job_id || savedJobId,
            started_at: job.started_at || previous.screeningAttempt?.started_at || null,
            finished_at: job.finished_at || previous.screeningAttempt?.finished_at || null,
            completion_status: job.completion_status || null,
            progress: job.progress || null,
            reason: job.reason || job.progress?.message || null,
          }));
        },
      }).then((payload) => {
        if (!isCurrentResume()) return;
        const finishingRun = { ...screeningRunRef.current, sequence: screeningRunSequenceRef.current };
        screeningRunRef.current = { startedAt: null, timer: null, catalogIdentity: null, startUtc: null };
        const returnedEvents = Array.isArray(payload?.data) ? payload.data : [];
        const validatedEvents = validateAndFilterEvents(returnedEvents);
        const physicalEvents = validatedEvents.filter((event) => event.result_kind === "physics_assessment");
        const resultPayload = { ...payload, structurally_invalid_excluded_count: returnedEvents.length - validatedEvents.length };
        const accepted = screeningResultMatchesRun(finishingRun, payload);
        if (accepted && ["complete", "partial"].includes(payload?.completion_status)) saveActiveScreeningJobId(savedJobId);
        else clearActiveScreeningJobId(savedJobId);
        setPlatform((previous) => finishScreeningAttempt(previous, runId, resultPayload, physicalEvents));
        if (accepted) saveAcceptedScreeningCache({ ...payload, api_status: payload.api_status || "available" }, physicalEvents);
        if (accepted) {
          setEventSelection((previous) => screeningRunSequenceRef.current === finishingRun.sequence
            ? reconcilePhysicalEventSelection(previous, physicalEvents)
            : previous);
        }
      }).catch((error) => {
        if (!isCurrentResume()) return;
        screeningRunRef.current = { startedAt: null, timer: null, catalogIdentity: null, startUtc: null };
        clearActiveScreeningJobId(savedJobId);
        setPlatform((previous) => finishScreeningAttempt(previous, runId, {
          api_status: "error", result_status: "unavailable", completion_status: "failed", job_id: savedJobId,
          reason: error?.message || "The saved screening job could not be restored.", data: [],
        }, []));
      });
    }
    void restoreAcceptedJob();
    load({ explicitScreeningRefresh: false });
    const refresh = window.setInterval(() => load({ explicitScreeningRefresh: false }), 90_000);
    return () => {
      cancelled = true;
      console.info("[ORION screening diagnostic] catalogue effect cleanup", { activeRequestId, activeInvocationId, controllerReferencePresent: Boolean(activeController) });
      if (activeController) console.info("[ORION screening diagnostic] aborting catalogue request during effect cleanup", { requestId: activeRequestId, invocationId: activeInvocationId });
      if (explicitScreeningRefreshRef.current === explicitRefresh) explicitScreeningRefreshRef.current = null;
      activeController?.abort();
      window.clearInterval(refresh);
    };
  }, []);

  useEffect(() => {
    const currentJobId = platform.conjunctionStatus?.job_id;
    if (!currentJobId) return undefined;
    const controller = new AbortController();
    getSavedEventLibrary({ currentJobId, signal: controller.signal })
      .then((library) => { if (!controller.signal.aborted) setEventLibrary(library); })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        console.warn("[Vyoma event library] using the accepted job data while the library is unavailable.", error);
        setEventLibrary({ events: platform.conjunctions || [], references: [], counts: {}, total: platform.conjunctions?.length || 0, current_job_id: currentJobId, label: "accepted screening" });
      });
    return () => controller.abort();
  }, [platform.conjunctionStatus?.job_id]);

  useEffect(() => {
    if (!["smart", "analytics"].includes(activePage) || !snapshot) return undefined;
    const snapshotKey = snapshot.generated_at || `${snapshot.source_state?.source || "unknown"}:${snapshot.objects?.length || 0}`;
    if (proxyFetchKeyRef.current === snapshotKey) return undefined;
    proxyFetchKeyRef.current = snapshotKey;
    const controller = new AbortController();
    getScreeningProxies({ limit: 120, signal: controller.signal }).then((payload) => {
      if (controller.signal.aborted) return;
      const proxies = applyOperationalPrioritization(validateAndFilterEvents(payload?.data || []));
      logPairTypeDistribution(proxies);
      setPlatform((previous) => ({ ...previous, screeningProxies: proxies }));
    }).catch((error) => {
      if (error?.name !== "AbortError") proxyFetchKeyRef.current = null;
    });
    return () => controller.abort();
  }, [activePage, snapshot]);

  useEffect(() => {
    if (!isPlaying) return undefined;
    const timer = window.setInterval(() => {
      setForecastHours((value) => (value >= 168 ? 0 : value + 3));
    }, 1400);
    return () => window.clearInterval(timer);
  }, [isPlaying]);

  const savedEvents = eventLibrary ? eventLibrary.events : platform.conjunctions;
  useEffect(() => {
    if (activePage !== "collision" || !Array.isArray(savedEvents) || !savedEvents.length) return undefined;
    const controller = new AbortController();
    let active = true;
    const selectedCandidate = savedEvents.find((item) => item?.id === selectedEvent?.id);
    const candidates = selectedCandidate?.result_kind === "physics_assessment"
      && selectedCandidate?.physics_result?.status === "valid" && selectedCandidate?.screening_job_id
      ? [selectedCandidate] : [];
    const cache = sensitivityPcCacheRef.current;
    const publishCache = () => setSensitivityPcByEvent(Object.fromEntries(cache));
    publishCache();
    (async () => {
      for (const item of candidates) {
        const key = `${item.screening_job_id}|${item.id}|2`;
        if (cache.has(key)) continue;
        try {
          const result = await calculateResearchPcWhatIf({
            screeningJobId: item.screening_job_id,
            eventId: item.id,
            covarianceScale: 2,
            signal: controller.signal,
          });
          if (result?.success === true && result?.data) cache.set(key, { status: "available", assessment: result.data });
          else cache.set(key, { status: "not_available" });
        } catch (error) {
          if (error?.name === "AbortError" || controller.signal.aborted) return;
          cache.set(key, { status: "not_available" });
        }
        if (active) publishCache();
      }
    })();
    return () => { active = false; controller.abort(); };
  }, [activePage, savedEvents, selectedEvent?.id]);
  const resolvedManeuverEvent = referenceManeuverEvent ? null : resolveManeuverEvent(selectedEvent, savedEvents);
  const acceptedManeuverEvent = resolvedManeuverEvent && Array.isArray(platform.conjunctions)
    ? platform.conjunctions.find((event) => event?.id === resolvedManeuverEvent.id && event?.result_kind === "physics_assessment") || null
    : null;
  const maneuverAssessmentEvent = acceptedManeuverEvent || resolvedManeuverEvent;
  const maneuverScreeningJobId = acceptedManeuverEvent
    ? platform.conjunctionStatus?.job_id || acceptedManeuverEvent.screening_job_id || null
    : maneuverAssessmentEvent?.screening_job_id || platform.conjunctionStatus?.job_id || null;
  const validManeuverEvents = useMemo(() => eligibleManeuverEvents(savedEvents), [savedEvents]);
  const everyManeuverEventBelowFloor = validManeuverEvents.length > 0 && validManeuverEvents.every((item) => (
    Number.isFinite(item.automatic_research_pc_assessment?.log10_pc)
    && item.automatic_research_pc_assessment.log10_pc < -30
  ));
  const maneuverSampleAutoRequestedRef = useRef(false);

  async function loadManeuverDemo() {
    setManeuverDemoBusy(true);
    try {
      const response = await fetch("/sample_conjunction_data.cdm", { cache: "no-cache" });
      if (!response.ok) throw new Error(`Sample CDM could not be loaded (HTTP ${response.status}).`);
      const cdmText = await response.text();
      const assessment = await calculateReferenceCdmPc({ cdmText, sourceLabel: "public/sample_conjunction_data.cdm", assumeIndependentCovariances: true });
      const parameters = { eventId: assessment.data.event_id, maneuveringObjectId: assessment.data.object_1.id, burnLeadSeconds: 1800, direction: "along_track+", deltaVMs: 0.05 };
      const maneuverAssessment = await calculateReferenceManeuver(parameters);
      setManeuverRequest(null);
      setManeuver(null);
      setManeuverDemoAssessment({ data: maneuverAssessment.data, parameters });
      setReferenceManeuverEvent(assessment.data);
      setActivePage("maneuver");
    } catch (error) {
      setManeuverDemoAssessment({ error: error?.message || "The demo conjunction could not be assessed." });
    } finally {
      setManeuverDemoBusy(false);
    }
  }

  useEffect(() => {
    if (activePage !== "maneuver" || !everyManeuverEventBelowFloor || referenceManeuverEvent
      || maneuverDemoBusy || maneuverDemoAssessment?.error || maneuverSampleAutoRequestedRef.current) return;
    maneuverSampleAutoRequestedRef.current = true;
    loadManeuverDemo();
  }, [activePage, everyManeuverEventBelowFloor, referenceManeuverEvent, maneuverDemoBusy, maneuverDemoAssessment]);

  useEffect(() => {
    if (activePage !== "maneuver") return undefined;
    const requestGeneration = ++maneuverRequestGenerationRef.current;
    if (!maneuverAssessmentEvent?.id) {
      setManeuver(null);
      return undefined;
    }
    if (maneuverRequest?.eventId !== maneuverAssessmentEvent.id || maneuverRequest?.screeningJobId !== maneuverScreeningJobId) {
      if (!maneuverScreeningJobId) {
        setManeuver({ status: "unavailable", event_id: maneuverAssessmentEvent.id, screening_job_id: null, reason: "No accepted screening job is attached to this event." });
        return undefined;
      }
      setManeuverRequest({ eventId: maneuverAssessmentEvent.id, screeningJobId: maneuverScreeningJobId, leadSeconds: 1800, maxDeltaVMs: 0.05, rtnDirection: "all", initialMassKg: 500, specificImpulseS: 220, covarianceScale: 1 });
      return undefined;
    }
    const controller = new AbortController();
    setManeuver({ status: "running", event_id: maneuverAssessmentEvent.id, screening_job_id: maneuverScreeningJobId, reason: "Repropagating the selected event through the bounded numerical maneuver search." });
    
    async function fetchManeuver() {
      try {
        const result = await getManeuver(maneuverAssessmentEvent, {
          signal: controller.signal,
          screeningJobId: maneuverScreeningJobId,
          leadSeconds: maneuverRequest.leadSeconds,
          maxDeltaVMs: maneuverRequest.maxDeltaVMs,
          rtnDirection: maneuverRequest.rtnDirection,
          initialMassKg: maneuverRequest.initialMassKg,
          specificImpulseS: maneuverRequest.specificImpulseS,
          covarianceScale: maneuverRequest.covarianceScale,
        });
        if (!isCurrentManeuverRequest(requestGeneration, maneuverRequestGenerationRef.current, controller.signal.aborted)) return;
        const matchingResult = result?.event_id === maneuverAssessmentEvent.id ? result : {
          status: "unavailable",
          reason_code: "maneuver_event_identity_mismatch",
          reason: "The maneuver response did not identify the selected event.",
        };
        setManeuver({ screening_job_id: maneuverScreeningJobId, event_id: maneuverAssessmentEvent.id, result: matchingResult });
      } catch (error) {
        if (!isCurrentManeuverRequest(requestGeneration, maneuverRequestGenerationRef.current, controller.signal.aborted)
            || error?.name === "AbortError") return;
        setManeuver({ screening_job_id: maneuverScreeningJobId, event_id: maneuverAssessmentEvent.id, result: {
          status: "unavailable",
          reason_code: "maneuver_api_unavailable",
          reason: error?.message || "Maneuver assessment service is unavailable.",
        } });
      }
    }
    
    fetchManeuver();
    return () => controller.abort();
  }, [activePage, maneuverAssessmentEvent, maneuverScreeningJobId, maneuverRequest]);

  const activeFrame = useMemo(() => {
    if (!forecast?.frames?.length) return null;
    return forecast.frames.reduce((closest, frame) => {
      return Math.abs(frame.hour - forecastHours) < Math.abs(closest.hour - forecastHours) ? frame : closest;
    }, forecast.frames[0]);
  }, [forecast, forecastHours]);

  const searchedSnapshot = snapshot;
  const searchSuggestions = [];
  const smartSnapshot = useMemo(() => buildSmartFilterView(snapshot, platform.screeningProxies), [snapshot, platform.screeningProxies]);
  const topEvent = eventSelection.notice ? null : selectedEvent || platform.conjunctions[0] || null;
  const maneuverEvent = referenceManeuverEvent ? null : resolveManeuverEvent(selectedEvent, savedEvents);
  const highPriority = platform.screeningProxies.filter((event) => ["Critical", "High"].includes(event.risk_level));
  const screeningJobSelection = useMemo(
    () => getScreeningJobSelection(platform, archivedJobSelection),
    [platform, archivedJobSelection],
  );
  const startScreening = createExplicitRefreshHandler((invocationId) => {
    if (screeningLaunchRef.current.runId || screeningRunRef.current.startedAt) return;
    const launchRunId = `launch-${Date.now()}-${++screeningRunSequenceRef.current}`;
    screeningLaunchRef.current = { runId: launchRunId };
    setPlatform((previous) => beginScreeningAttempt(previous, {
      run_id: launchRunId, job_id: null, api_status: "pending", result_status: "starting", completion_status: null,
      reason: "Refreshing the current catalog before screening starts.",
      progress: { stage: "catalog", percent: null, message: "Refreshing the current catalog before screening starts." },
    }));
    const explicitRefresh = explicitScreeningRefreshRef.current;
    if (!explicitRefresh) {
      screeningLaunchRef.current = { runId: null };
      setPlatform((previous) => updateScreeningAttempt(previous, launchRunId, {
        api_status: "error", result_status: "unavailable", completion_status: "failed",
        reason: "The screening workflow is not ready yet. Retry in a moment.",
        progress: { stage: "failed", percent: null, message: "The screening workflow is not ready yet. Retry in a moment." },
      }));
      pushNotice(setNotices, "Screening is still initializing. Try again in a moment.", "warning");
      return;
    }
    return explicitRefresh(invocationId, { horizonHours: screeningHorizonHours });
  });

  function navigate(page) {
    setActivePage(page);
    setNotificationsOpen(false);
  }

  function selectEvent(event, page = "collision") {
    setEventSelection(resolvePhysicalEventSelection(event, savedEvents));
    setActivePage(page);
  }

  function acceptUpdatedEvent(updatedEvent, responseJobId) {
    if (!updatedEvent?.id || updatedEvent.result_kind !== "physics_assessment") return;
    setEventLibrary((previous) => previous ? ({
      ...previous,
      events: previous.events.map((item) => item.id === updatedEvent.id && item.screening_job_id === responseJobId ? updatedEvent : item),
    }) : previous);
    if (acceptedScreeningJobIdRef.current !== responseJobId) return;
    setPlatform((previous) => {
      if (previous.conjunctionStatus?.job_id !== responseJobId) return previous;
      return {
        ...previous,
        conjunctions: previous.conjunctions.map((event) => event.id === updatedEvent.id ? updatedEvent : event),
      };
    });
    setEventSelection((previous) => previous.event?.id === updatedEvent.id
      ? { ...previous, event: updatedEvent, context: updatedEvent }
      : previous);
  }

  async function handleImportEventCdm({ eventId, cdmXml, sourceLabel, assumeIndependentCovariances }) {
    const jobId = savedEvents.find((item) => item.id === eventId)?.screening_job_id || platform.conjunctionStatus?.job_id;
    const payload = await importEventCdm({ screeningJobId: jobId, eventId, cdmXml, sourceLabel, assumeIndependentCovariances });
    acceptUpdatedEvent(payload.data, payload.job_id);
    return payload;
  }

  async function handleScenarioPc(input) {
    const jobId = savedEvents.find((item) => item.id === input.eventId)?.screening_job_id || platform.conjunctionStatus?.job_id;
    const payload = await calculateScenarioPc({ screeningJobId: jobId, ...input });
    acceptUpdatedEvent(payload.data, payload.job_id);
    return payload;
  }

  function handleShowInGlobe(objectId, event, screeningJobId) {
    setPendingFocusId(objectId);
    setPendingGlobeSelection(captureGlobeEventSelection(event, screeningJobId));
    setActivePage("visualization");
  }

  function handleUseReferenceEvent(referenceEvent) {
    if (!referenceEvent?.reference_case || referenceEvent?.collision_probability?.status !== "available") return;
    setReferenceManeuverEvent(referenceEvent);
    setManeuver(null);
    setActivePage("maneuver");
  }

  function handleGlobeReportDownload(selection) {
    return downloadGlobeEventReport(selection, handleDownload, (error) => {
      pushNotice(setNotices, `Download failed: ${error?.message || "the report identity is unavailable."}`, "warning");
    });
  }

  function toggleWatchlist(objectId) {
    setWatchlist((current) => {
      const next = new Set(current);
      if (next.has(objectId)) next.delete(objectId);
      else next.add(objectId);
      localStorage.setItem("ssa-watchlist", JSON.stringify([...next]));
      return next;
    });
  }

  async function handleDownload(path, filename) {
    try {
      await downloadReport(path, filename);
      pushNotice(setNotices, `Download started: ${filename}.`, "success");
    } catch (error) {
      pushNotice(setNotices, `Download failed: ${error?.message || "the report could not be retrieved."}`, "warning");
    }
  }

  async function handleTrajectoryCsvDownload(screeningJobId) {
    try {
      const filename = await downloadTrajectoryAssessmentCsv(screeningJobId);
      pushNotice(setNotices, `Download started: ${filename}.`, "success");
    } catch (error) {
      pushNotice(setNotices, `Trajectory CSV download failed: ${error?.message || "the assessment file could not be retrieved."}`, "warning");
    }
  }

  async function handleRestoreArchivedJob(jobId) {
    setArchiveRestoreBusy(true);
    try {
      const archivedJob = await restoreArchivedScreeningJob(jobId);
      setArchivedJobSelection(archivedJob);
      const recordCount = archivedJob.result.data.length;
      const demoEvents = validateAndFilterEvents(archivedJob.result.data).filter((item) => item.result_kind === "physics_assessment");
      const demoStatus = { ...archivedJob.result, api_status: "available", job_id: archivedJob.job_id, completion_status: archivedJob.status };
      setPlatform((previous) => ({ ...previous, conjunctions: demoEvents, conjunctionStatus: demoStatus, screeningAttempt: null }));
      saveActiveScreeningJobId(archivedJob.job_id);
      saveAcceptedScreeningCache(demoStatus, demoEvents);
      setEventSelection((previous) => reconcilePhysicalEventSelection(previous, demoEvents));
      pushNotice(setNotices, `DEMO snapshot loaded from archived job ${archivedJob.job_id} (${archivedJob.status}; ${recordCount} stored assessments). The current live catalog was not changed.`, "success");
    } catch (error) {
      pushNotice(setNotices, `Archive restore failed: ${error?.message || "the archived screening job could not be restored."}`, "warning");
    } finally {
      setArchiveRestoreBusy(false);
    }
  }

  useEffect(() => {
    const events = (platform.conjunctions || []).filter((event) => event?.result_kind === "physics_assessment"
      && event?.physics_result?.status === "valid" && event?.physics_result?.tca_status === "valid" && event?.id);
    const jobId = platform.conjunctionStatus?.job_id;
    if (!jobId || events.length === 0) { setScenarioClassCounts({ status: "empty", counts: null, evaluated: 0, total: events.length, highestPcLog10: null, assessments: {} }); return undefined; }
    const controller = new AbortController();
    const scenarioKey = `${jobId}|${uncertaintyScale}`;
    if (Number(uncertaintyScale) === 1) {
      const counts = { High: 0, Medium: 0, Low: 0, Unclassified: 0 };
      const assessments = {};
      let highestPcLog10 = null;
      for (const event of events) {
        const assessment = event.automatic_research_pc_assessment;
        const riskClass = assessment?.risk_assessment?.final_risk_class;
        counts[Object.hasOwn(counts, riskClass) ? riskClass : "Unclassified"] += 1;
        assessments[event.id] = { ...assessment, success: Boolean(assessment), data: assessment };
        if (Number.isFinite(assessment?.log10_pc)) highestPcLog10 = highestPcLog10 == null ? assessment.log10_pc : Math.max(highestPcLog10, assessment.log10_pc);
      }
      setScenarioClassCounts({ status: "complete", counts, evaluated: events.length, total: events.length, highestPcLog10, assessments });
      return () => controller.abort();
    }
    const cached = scenarioClassCacheRef.current.get(scenarioKey);
    if (cached) { setScenarioClassCounts(cached); return () => controller.abort(); }
    setScenarioClassCounts({ status: "loading", counts: { High: 0, Medium: 0, Low: 0, Unclassified: 0 }, evaluated: 0, total: events.length, highestPcLog10: null, assessments: {} });
    (async () => {
      const counts = { High: 0, Medium: 0, Low: 0, Unclassified: 0 };
      const assessments = {};
      let evaluated = 0;
      let highestPcLog10 = null;
      for (const event of events) {
        if (controller.signal.aborted) return;
        try {
          const result = await calculateResearchPcWhatIf({ screeningJobId: jobId, eventId: event.id, covarianceScale: Number(uncertaintyScale), signal: controller.signal });
          if (result?.success === true) {
            const assessment = result.data;
            assessments[event.id] = { ...assessment, success: true, data: assessment };
            const riskClass = assessment?.risk_assessment?.final_risk_class;
            counts[Object.hasOwn(counts, riskClass) ? riskClass : "Unclassified"] += 1;
            if (Number.isFinite(assessment?.log10_pc)) highestPcLog10 = highestPcLog10 == null ? assessment.log10_pc : Math.max(highestPcLog10, assessment.log10_pc);
            evaluated += 1;
          }
        } catch (error) {
          if (error?.name === "AbortError" || controller.signal.aborted) return;
        }
        setScenarioClassCounts({ status: "loading", counts: { ...counts }, evaluated, total: events.length, highestPcLog10, assessments: { ...assessments } });
      }
      if (!controller.signal.aborted) {
        const result = { status: "complete", counts, evaluated, total: events.length, highestPcLog10, assessments };
        scenarioClassCacheRef.current.set(scenarioKey, result);
        setScenarioClassCounts(result);
      }
    })();
    return () => controller.abort();
  }, [platform.conjunctionStatus?.job_id, platform.conjunctions, uncertaintyScale]);

  return (
    <div className="platform-shell">
      <Sidebar activePage={activePage} navigate={navigate} health={platform.health} />
      <div className="platform-main">
        <TopBar
          refresh={startScreening}
          loading={loading}
          backendBusy={backendBusy}
          notificationsOpen={notificationsOpen}
          setNotificationsOpen={setNotificationsOpen}
          notices={notices}
          health={platform.health}
          snapshot={snapshot}
          suggestions={searchSuggestions}
        />
        <main className="content-main"><Suspense fallback={<div className="og-card loading-skeleton" role="status" aria-label="Loading page"><span /><span /><span /></div>}><PageErrorBoundary key={activePage}>
          {activePage === "home" ? (
            <HomePage snapshot={snapshot} platform={platform} eventLibrary={eventLibrary} maneuver={maneuver} navigate={navigate} loading={loading} uncertaintyScale={uncertaintyScale} scenarioClassCounts={scenarioClassCounts} />
          ) : null}
          {activePage === "visualization" ? (
            <VisualizationPage
              snapshot={searchedSnapshot}
              filters={filters}
              setFilters={setFilters}
              forecastHours={forecastHours}
              setForecastHours={setForecastHours}
              isPlaying={isPlaying}
              setIsPlaying={setIsPlaying}
              activeFrame={activeFrame}
              selectedObject={selectedObject}
              setSelectedObject={setSelectedObject}
              selectedRisk={selectedRisk}
              setSelectedRisk={setSelectedRisk}
              analyticsOpen={analyticsOpen}
              setAnalyticsOpen={setAnalyticsOpen}
              pulse={pulse}
              loading={loading}
              pendingFocusId={pendingFocusId}
              pendingGlobeSelection={pendingGlobeSelection}
              onClearPendingFocus={() => { setPendingFocusId(null); setPendingGlobeSelection(null); }}
              onGlobeReportDownload={handleGlobeReportDownload}
            />
          ) : null}
          {activePage === "smart" ? (
            <SmartFilterWorkbench acceptedJob={platform.conjunctionStatus?.job_id ? { job_id: platform.conjunctionStatus.job_id, result: { data: platform.conjunctions } } : null} snapshot={snapshot} smartSnapshot={smartSnapshot} platform={platform} download={handleDownload} />
          ) : null}
          {activePage === "collision" ? (
            <CollisionPage
              eventLibrary={eventLibrary}
              event={eventSelection.notice ? null : savedEvents.find((item) => item.id === selectedEvent?.id) || null}
              selectionNotice={eventSelection.notice}
              events={savedEvents}
              eventStatus={platform.conjunctionStatus}
              attemptStatus={platform.screeningAttempt}
              screeningStatus={platform.conjunctionStatus?.screening}
              sourceSummary={platform.conjunctionStatus?.source_summary || snapshot?.source_summary}
              sourceState={platform.conjunctionStatus?.source_state || snapshot?.source_state}
              screeningJobId={platform.conjunctionStatus?.job_id}
              csvScreeningJobId={screeningJobSelection.jobId}
              csvJobArchived={screeningJobSelection.isArchived}
              onImportCdm={handleImportEventCdm}
              onScenarioPc={handleScenarioPc}
              onUseReferenceEvent={handleUseReferenceEvent}
              onStartScreening={startScreening}
              screeningHorizonHours={screeningHorizonHours}
              setScreeningHorizonHours={setScreeningHorizonHours}
              currentEvents={platform.conjunctions}
              sensitivityPcByEvent={sensitivityPcByEvent}
              uncertaintyScale={uncertaintyScale}
              setUncertaintyScale={setUncertaintyScale}
              uncertaintyWhatIf={scenarioClassCounts?.assessments?.[selectedEvent?.id] || null}
              uncertaintyWhatIfStatus={scenarioClassCounts?.status || "idle"}
              scenarioClassCounts={scenarioClassCounts}
              onLoadDemo={() => handleRestoreArchivedJob("fcec3945251c45f38f215485ecbb5605")}
              demoBusy={archiveRestoreBusy}
              selectEvent={selectEvent}
              toggleWatchlist={toggleWatchlist}
              watchlist={watchlist}
              download={handleDownload}
              downloadTrajectoryCsv={handleTrajectoryCsvDownload}
              onShowInGlobe={handleShowInGlobe}
            />
          ) : null}
          {activePage === "maneuver" ? <ManeuverWorkbench event={maneuverEvent} events={savedEvents} screeningJobId={maneuverScreeningJobId} screeningStatus={platform.conjunctionStatus} screeningAttempt={platform.screeningAttempt} onSelectEvent={(eventId) => { setReferenceManeuverEvent(null); setManeuverDemoAssessment(null); selectEvent(selectManeuverEvent(savedEvents, eventId), "maneuver"); }} onRunManeuver={(configuration) => setManeuverRequest({ ...configuration, eventId: maneuverEvent?.id, screeningJobId: maneuverScreeningJobId })} onLoadDemo={loadManeuverDemo} demoBusy={maneuverDemoBusy} maneuver={maneuver} download={handleDownload} referenceEvent={referenceManeuverEvent} demoAssessment={maneuverDemoAssessment} onClearReferenceEvent={() => { setReferenceManeuverEvent(null); setManeuverDemoAssessment(null); }} /> : null}
          {activePage === "analytics" ? <AnalyticsPage analytics={platform.analytics || buildLocalAnalytics(snapshot, platform.screeningProxies || [])} events={platform.screeningProxies} snapshot={snapshot} objects={snapshot?.objects || []} catalogEvents={eventLibrary?.events || []} /> : null}
          {activePage === "reports" ? <ReportsPage
            event={topEvent}
            events={eventLibrary?.events || platform.conjunctions}
            eventLibrary={eventLibrary}
            maneuverEvent={maneuverEvent}
            maneuver={maneuver}
            screeningJobId={platform.conjunctionStatus?.job_id}
            csvScreeningJobId={screeningJobSelection.jobId}
            download={handleDownload}
            downloadTrajectoryCsv={handleTrajectoryCsvDownload}
          /> : null}
          {activePage === "upload" ? <CdmReferenceAssessment standalone /> : null}
        </PageErrorBoundary></Suspense></main>
      </div>
    </div>
  );
}

class PageErrorBoundary extends React.Component {
  state = { hasError: false, error: null, componentStack: "" };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    this.setState({ error, componentStack: info?.componentStack || "" });
    console.error("Page render failed", error, info?.componentStack || "");
  }

  render() {
    if (this.state.hasError) {
      return <section className="og-card" role="alert"><h1>This page hit an error</h1><button type="button" className="og-btn primary" onClick={() => window.location.reload()}>Reload</button><details><summary>Details</summary><p>{this.state.error?.message || String(this.state.error || "Unknown render error")}</p><pre>{this.state.componentStack}</pre></details></section>;
    }
    return this.props.children;
  }
}

function Sidebar({ activePage, navigate, health }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
      <button type="button" className="sidebar-collapse" aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} onClick={() => setCollapsed((value) => !value)}>{collapsed ? "›" : "‹"}</button>
      <button className="brand-lockup" type="button" onClick={() => navigate("home")}>
        <span className="brand-mark"><Radar size={22} /></span>
        <span>
          <strong>Vyoma SSA</strong>
          <small>Risk Intelligence</small>
        </span>
      </button>
      <nav className="sidebar-nav">
        {NAV.map((item) => (
          <button key={item.id} className={`nav-item ${activePage === item.id ? "active" : ""}`} type="button" onClick={() => navigate(item.id)}>
            <item.icon size={17} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}

function TopBar({ refresh, loading, notificationsOpen, setNotificationsOpen, notices, health, snapshot }) {
  const [utc, setUtc] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setUtc(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <header className="topbar">
      <div className="topbar-meta">
        <span className="mono">{utc.toISOString().replace("T", " ").slice(0, 19)}Z</span>
        <span
          className={`system-chip source-chip source-chip-${snapshot?.source_state?.status || "unavailable"}`}
          title={sourceDetail(snapshot?.source_state)}
        >
          <DatabaseZap size={14} /> {sourceLabel(snapshot?.source_state?.status, snapshot?.source_state?.cache_age_seconds)}
        </span>
        <span className="system-chip"><CheckCircle2 size={14} /> {datasetLabel(loading, snapshot?.source_state?.status)}</span>
        <BuildVersionBadge />
        <button className="icon-button" type="button" aria-label="Refresh orbital data" onClick={refresh}>
          {loading ? <Loader2 className="spin" size={17} /> : <RefreshCw size={17} />}
        </button>
      </div>
      {notices.length ? <div className="notification-center" role={notices.at(-1)?.type === "warning" ? "alert" : "status"} aria-live={notices.at(-1)?.type === "warning" ? "assertive" : "polite"}>
        <strong>Recent activity</strong>
        {notices.slice(-3).map((notice) => <p className={notice.type} key={notice.at}>{notice.message}</p>)}
      </div> : null}
    </header>
  );
}



function ScreeningRunSummary({ eventStatus = {}, attemptStatus = null, screeningStatus = {}, sourceSummary = {}, sourceState = {}, eventCount = 0, returnedInvalidCount = 0, assessmentEvents = [] }) {
  const statusLine = screeningSummaryDisplay(eventStatus, attemptStatus);
  const summary = screeningStatus || {};
  const performance = eventStatus.performance || {};
  const recordCounts = screeningAssessmentCounts(summary, eventCount, returnedInvalidCount);
  const totalObjects = summary.valid_track_count == null
    ? sourceSummary.object_count ?? "Unavailable"
    : summary.valid_track_count + (summary.rejected_object_count || 0);
  const invalidCount = summary.invalid_assessment_count ?? "Unavailable";
  const reviewPriorityCounts = Object.fromEntries([["CRITICAL", "Band 1"], ["HIGH", "Band 2"], ["MEDIUM", "Band 3"], ["LOW", "Band 4"], ["REVIEW_REQUIRED", "Review required"], ["UNCLASSIFIED", "Unclassified"]].map(([category, label]) => [
    label,
    assessmentEvents.filter((item) => item?.result_kind === "physics_assessment" && (item.review_priority?.category || "UNCLASSIFIED") === category).length,
  ]));
  const pcUnavailableCount = assessmentEvents.filter((item) => item?.result_kind === "physics_assessment" && item.collision_probability?.status !== "available").length;
  const duplicateTrajectoryCount = assessmentEvents.filter((item) => item?.physics_result?.reason_codes?.some((reason) => ["duplicate_tle_state_for_distinct_catalog_ids", "identical_propagation_parameters_for_distinct_catalog_ids"].includes(reason))).length;
  const capReached = summary.candidate_limit_reached == null ? "Not recorded" : summary.candidate_limit_reached ? "Yes · coverage limited" : "No";
  return <Panel title="Screening Run" icon={Radar}>
    <div className="readout-list">
      <span>{statusLine.label} <strong>{statusLine.text}</strong></span>
      {attemptStatus ? <>
        <span>Attempt progress <strong>{attemptStatus.progress?.stage || attemptStatus.result_status || "starting"} · {attemptStatus.completion_status || "not complete"} · job {attemptStatus.job_id || "pending"}</strong></span>
        {attemptStatus.progress?.message || attemptStatus.reason ? <span>Attempt detail <strong>{attemptStatus.progress?.message || attemptStatus.reason}</strong></span> : null}
      </> : null}
      <span>Accepted result catalog source <strong>{sourceSummary.status || "Unavailable"} · {Object.entries(sourceSummary.counts_by_source_type || {}).map(([key, count]) => `${key}: ${count}`).join(", ") || "source counts unavailable"}</strong></span>
      <span>Catalog acquisition <strong>{sourceState.source || "Source unavailable"} · {sourceState.status || "unavailable"}{sourceState.last_error_code ? ` · acquisition failed: ${sourceState.last_error_code}` : ""}{sourceState.last_attempt_at ? ` · attempted ${sourceState.last_attempt_at}` : ""}</strong></span>
      <span>Last successful source retrieval <strong>{sourceState.last_success_at || "Unavailable"}{sourceState.status === "stale_live" ? " · cached data is stale" : ""}</strong></span>
      <span>Accepted result objects screened / catalog objects <strong>{summary.valid_track_count == null ? "Unavailable" : `${summary.valid_track_count} usable / ${totalObjects} total`}</strong></span>
      <span>Accepted result horizon UTC <strong>{summary.screening_horizon_start || summary.start_utc || "Unavailable"} → {summary.screening_horizon_end || "pending / unavailable"}</strong></span>
      <span>Accepted result sampling / threshold <strong>{summary.sample_step_seconds == null ? "Unavailable" : `${summary.sample_step_seconds} s · ${summary.screening_threshold_km} km threshold · ${summary.sample_epoch_count ?? "?"} epochs`}</strong></span>
      <span>Accepted result close approaches <strong>{summary.close_approach_count ?? (eventStatus.result_status === "valid_empty" ? 0 : "Unavailable")}</strong></span>
      <span>Accepted result assessment records <strong>{recordCounts.total} total · {recordCounts.returned} returned</strong></span>
      {recordCounts.truncated ? <span>Assessment response limit <strong>Only {recordCounts.returned} of {recordCounts.total} records were returned; full-run counts follow.</strong></span> : null}
      <span>{COLLISION_INVALID_ASSESSMENT_LABEL} <strong>{recordCounts.invalidTotal ?? invalidCount}</strong></span>
      {assessmentEvents.some((item) => item?.physics_result?.status === "invalid") ? <details className="invalid-reason-list"><summary>Invalid events and reasons ({assessmentEvents.filter((item) => item?.physics_result?.status === "invalid").length} returned)</summary><ul>{assessmentEvents.filter((item) => item?.physics_result?.status === "invalid").map((item) => <li key={item.id}><strong>{item.primary?.name || item.primary?.id} ({item.primary?.id}) vs {item.secondary?.name || item.secondary?.id} ({item.secondary?.id})</strong><span>{(item.physics_result?.reason_codes || ["ASSESSMENT_REASON_UNAVAILABLE"]).map((code) => <span key={code}><code>{code}</code> — {explainPhysicsReason(code)}</span>)}</span></li>)}</ul></details> : null}
      <span>Indistinguishable duplicate trajectories excluded from rank <strong>{duplicateTrajectoryCount}</strong></span>
      <span>Returned physical Pc unavailable <strong>{pcUnavailableCount}</strong></span>
      <span>Returned rule-based geometry review bands <strong>{Object.entries(reviewPriorityCounts).map(([category, count]) => `${category}: ${count}`).join(" · ")}</strong></span>
      <span>ML model / event inference <strong>{eventStatus.ml_model?.status || eventStatus.ml_status || "Unavailable"} · {eventStatus.ml_available_event_count ?? "?"} available predictions returned</strong></span>
      {recordCounts.truncated ? <span>Invalid assessments in returned records <strong>{recordCounts.returnedInvalid}</strong></span> : null}
      <span>Accepted result malformed records excluded <strong>{eventStatus.structurally_invalid_excluded_count ?? 0}</strong></span>
      <span>Accepted result candidate pairs / minima / refinements <strong>{summary.candidate_pair_count ?? "Unavailable"} / {summary.candidate_local_minimum_count ?? "Unavailable"} / {summary.refinement_count ?? "Unavailable"}</strong></span>
      <span>Accepted result candidate/refinement cap reached <strong>{capReached}</strong></span>
      {performance.total_stage_2a_seconds != null ? <span>Stage 2A / API elapsed <strong>{Number(performance.total_stage_2a_seconds).toFixed(3)} s / {performance.api_request_total_seconds == null ? "Unavailable" : `${Number(performance.api_request_total_seconds).toFixed(3)} s`}</strong></span> : null}
      {summary.reason_code || eventStatus.reason ? <span>Run note <strong>{summary.reason_code || eventStatus.reason}</strong></span> : null}
    </div>
  </Panel>;
}

function CollisionScreeningControls({ eventStatus = {}, attemptStatus = null, screeningStatus = {}, sourceSummary = {}, sourceState = {}, eventCount = 0, onStartScreening = () => {} }) {
  const state = collisionScreeningState(eventStatus, attemptStatus);
  const progress = attemptStatus?.progress;
  const progressPercent = Number.isFinite(progress?.percent) ? progress.percent : null;
  const stateLabel = { ready: "Ready", starting: "Starting", running: "Running", completed: "Completed", failed: "Failed" }[state];
  const source = sourceState?.source || sourceSummary?.primary_source || null;
  const lastRun = eventStatus?.timestamp || eventStatus?.finished_at || attemptStatus?.finished_at || screeningStatus?.finished_at || null;
  const pairCount = screeningStatus?.candidate_pair_count ?? eventStatus?.screening?.candidate_pair_count ?? "Unavailable";
  return <section className="panel collision-screening-controls" aria-label="Screening controls">
    <div className="collision-screening-heading">
      <div><span className={`screening-state-badge screening-state-${state}`}>Screening: {stateLabel}</span>
        <p className="muted">{source ? `Source: ${source} · ` : ""}{pairCount !== "Unavailable" ? `${pairCount} pairs screened · ` : ""}{eventCount} candidate event{eventCount === 1 ? "" : "s"}{lastRun ? ` · Last accepted run: ${lastRun}` : " · No prior screening run"}</p>
      </div>
      <button className="primary-action" type="button" onClick={onStartScreening} disabled={state === "starting" || state === "running"}>
        {state === "starting" || state === "running" ? "Screening…" : state === "failed" ? "Retry Screening" : "Start Screening"}
      </button>
    </div>
    {progress?.message || attemptStatus?.reason ? <p className="screening-progress-message" role={state === "failed" ? "alert" : "status"}>{progress?.message || attemptStatus?.reason}</p> : null}
    {["starting", "running"].includes(state) && eventCount > 0
      ? <p className="screening-progress-message">Showing the last accepted results until this screening run completes.</p>
      : null}
    {progressPercent != null && ["starting", "running", "completed"].includes(state)
      ? <progress aria-label="Backend-reported screening progress" max="100" value={progressPercent} />
      : null}
  </section>;
}

export function CollisionPage({ event, events, eventLibrary, eventStatus, attemptStatus, screeningStatus, sourceSummary, sourceState, screeningJobId, csvScreeningJobId, csvJobArchived = false, selectionNotice, onStartScreening = () => {}, onLoadDemo = () => {}, demoBusy = false, onImportCdm = async () => {}, onScenarioPc = async () => {}, onUseReferenceEvent = () => {}, selectEvent, toggleWatchlist, watchlist, download, downloadTrajectoryCsv, onShowInGlobe, uncertaintyScale = 1, setUncertaintyScale = () => {}, uncertaintyWhatIf = null, uncertaintyWhatIfStatus = "idle", scenarioClassCounts = null, currentEvents = [], sensitivityPcByEvent = {}, screeningHorizonHours = 72, setScreeningHorizonHours = () => {} }) {
  const [pairFilter, setPairFilter] = useState("all");
  const [eventSearch, setEventSearch] = useState("");
  const [eventSort, setEventSort] = useState("research_pc");
  const [statusFilter, setStatusFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [physicalOnly, setPhysicalOnly] = useState(true);
  const [quantityFilter, setQuantityFilter] = useState("all");
  const [minimumMiss, setMinimumMiss] = useState("");
  const [maximumMiss, setMaximumMiss] = useState("");
  const [fromTca, setFromTca] = useState("");
  const [toTca, setToTca] = useState("");
  const [cdmXml, setCdmXml] = useState("");
  const [cdmSourceLabel, setCdmSourceLabel] = useState("");
  const [cdmAssumeIndependent, setCdmAssumeIndependent] = useState(false);
  const [scenarioPrimary, setScenarioPrimary] = useState("");
  const [scenarioSecondary, setScenarioSecondary] = useState("");
  const [scenarioHbr, setScenarioHbr] = useState("");
  const [scenarioAssumptionsText, setScenarioAssumptionsText] = useState("");
  const [scenarioAssumeIndependent, setScenarioAssumeIndependent] = useState(false);
  const [pcInputBusy, setPcInputBusy] = useState(false);
  const [pcInputMessage, setPcInputMessage] = useState("");
  useEffect(() => {
    setCdmXml("");
    setCdmSourceLabel("");
    setScenarioPrimary("");
    setScenarioSecondary("");
    setScenarioHbr("");
    setScenarioAssumptionsText("");
    setPcInputMessage("");
  }, [event?.id]);
  const filteredEvents = filterCollisionEvents(events, {
    physicalOnly, pairFilter, statusFilter, priorityFilter, quantityFilter,
    minimumMiss, maximumMiss, fromTca, toTca,
  });
  const availableEvents = searchAndSortCollisionEvents(filteredEvents, eventSearch, eventSort);
  const anomalyRankById = rankOrbitalAnomalyEvents(events || []);
  const chosenPhysical = event?.result_kind === "physics_assessment";
  const eventScreeningJobId = event?.screening_job_id || screeningJobId;
  const reportBase = chosenPhysical && eventScreeningJobId ? selectedEventReportPath(eventScreeningJobId, event.id) : null;
  return <CollisionWorkbench
    events={events || []} event={event} eventStatus={eventStatus} screeningStatus={screeningStatus}
    currentEvents={currentEvents} references={eventLibrary?.references || []} sensitivityPcByEvent={sensitivityPcByEvent}
    screeningAttempt={attemptStatus} screeningHorizonHours={screeningHorizonHours}
    setScreeningHorizonHours={setScreeningHorizonHours}
    screeningJobId={eventScreeningJobId} selectEvent={selectEvent}
    onShowInGlobe={onShowInGlobe} onAssessManeuver={(item) => selectEvent(item, "maneuver")}
    download={download} eventReportPath={reportBase}
    eventReportCsvPath={chosenPhysical && screeningJobId ? selectedEventReportPath(screeningJobId, event.id, "csv") : null}
    eventReportJsonPath={chosenPhysical && screeningJobId ? selectedEventReportPath(screeningJobId, event.id, "json") : null}
    onImportCdm={onImportCdm}
    onStartScreening={onStartScreening}
  />;
}

export function ManeuverPage(props) {
  return <ManeuverWorkbench {...props} />;

}

function AnalyticsPage({ analytics, events, snapshot, objects = [], catalogEvents = [] }) {
  return (
    <div className="page-stack">
      <PageHeader eyebrow="Catalog Analytics" title="Catalog Heuristic Analysis" text="Current catalog distribution, screening proxy matrix, and common-epoch catalog density with saved close approach locations." />
      <section className="split-grid">
        <Panel title="Current Catalog by Orbit Band" icon={BarChart3}>
          <BarList data={analytics?.band_distribution || {}} total={snapshot?.stats?.tracked_objects || 1} />
        </Panel>
        <Panel title="Catalog Density and Saved Close Approaches" icon={Globe2}>
          <CatalogDensityGlobe objects={objects} events={catalogEvents} />
        </Panel>
      </section>
      <section className="analytics-matrix">
        <Panel title="Current Screening Proxy Matrix" icon={Gauge}>
          <RiskMatrix events={events} />
        </Panel>
      </section>
    </div>
  );
}

function ReportsPage({ events = [], eventLibrary, maneuverEvent, maneuver, screeningJobId, csvScreeningJobId, download, downloadTrajectoryCsv }) {
  const [calculationCheck, setCalculationCheck] = useState({ status: "idle", message: "" });
  const runCalculationCheck = async () => {
    setCalculationCheck({ status: "loading", message: "Running NASA CARA reference assessment..." });
    try {
      const response = await calculateNasaCaraReferenceCase();
      const result = response?.data || {};
      const pc = result.collision_probability || {};
      setCalculationCheck({ status: "complete", message: pc.status === "available"
        ? `NASA CARA reference Pc ${Number(pc.pc).toExponential(3)}; comparison ${result.reference_case?.within_tolerance ? "within" : "outside"} published rounding tolerance.`
        : `NASA CARA calculation returned ${pc.status || "no Pc result"}.` });
    } catch (error) {
      setCalculationCheck({ status: "error", message: error?.message || "NASA CARA reference assessment failed." });
    }
  };
  const eventRows = events.filter((item) => item?.result_kind === "physics_assessment");
  const [selectedEventId, setSelectedEventId] = useState("");
  const currentJobId = screeningJobId || eventLibrary?.current_job_id || null;
  const csvJobId = csvScreeningJobId || currentJobId;
  const missionEvent = maneuverEvent || eventRows[0] || null;
  const eventDisplayName = (item) => `${item?.primary?.name || item?.primary?.id || "Object"} vs ${item?.secondary?.name || item?.secondary?.id || "Object"}`;
  const selectedEvent = eventRows.find((item) => item.id === selectedEventId) || eventRows[0] || null;
  const selectedJobId = selectedEvent?.screening_job_id || currentJobId;
  const maneuverAvailable = Boolean(selectedJobId && maneuverEvent?.id === selectedEvent?.id && maneuver?.result);
  return <div className="page-stack reports-page">
    <PageHeader eyebrow="Reports" title="Export Center" text="Download reports and data for events from saved screenings." />
    <section className="og-card report-download-list" aria-label="Event reports">
      <h2>Event reports</h2>
      {selectedEvent ? <><label className="report-event-selector">Select event<select value={selectedEvent.id} onChange={(event) => setSelectedEventId(event.target.value)}>{eventRows.map((item) => <option key={item.id} value={item.id}>{eventDisplayName(item)}</option>)}</select></label><article className="report-download-row"><strong>{eventDisplayName(selectedEvent)}</strong><small>Event ID: {selectedEvent.id}</small><div className="report-download-actions"><span>Collision report</span>{["pdf", "csv", "json"].map((format) => <button key={`collision-${format}`} className="og-btn" type="button" disabled={!selectedJobId} onClick={() => selectedJobId && download(selectedEventReportPath(selectedJobId, selectedEvent.id, format), `${selectedEvent.id}-collision-report.${format}`)}>Download {format.toUpperCase()}</button>)}</div><div className="report-download-actions"><span>Maneuver report</span>{maneuverAvailable ? ["pdf", "csv", "json"].map((format) => <button key={`maneuver-${format}`} className="og-btn" type="button" onClick={() => download(selectedManeuverReportPath(selectedJobId, selectedEvent.id, format), `${selectedEvent.id}-maneuver-report.${format}`)}>Download {format.toUpperCase()}</button>) : <small>Maneuver assessment is unavailable for this event.</small>}</div></article></> : <p>No saved screening events are available.</p>}
    </section>
    <section className="og-card report-download-list" aria-label="Mission downloads">
      <h2>Mission downloads</h2>
      <article className="report-download-row mission-download-row">
        <strong>{missionEvent ? eventDisplayName(missionEvent) : "Mission screening data"}</strong>
        <div className="report-download-actions"><button className="og-btn" type="button" onClick={() => download("/api/reports/mission.pdf", "orbital-mission-report.pdf")}>Mission Report</button><button className="og-btn" type="button" disabled={!csvJobId} onClick={() => csvJobId && downloadTrajectoryCsv(csvJobId)}>Trajectory CSV</button><button className="og-btn" type="button" onClick={() => download("/api/reports/mission.json", "orbital-mission-report.json")}>Mission JSON</button></div>
      </article>
      <section className="report-calculation-check" aria-label="NASA CARA calculation check"><button className="og-btn" type="button" disabled={calculationCheck.status === "loading"} onClick={runCalculationCheck}>{calculationCheck.status === "loading" ? "Checking..." : "Calculation check"}</button>{calculationCheck.message ? <p role="status">{calculationCheck.message}</p> : null}</section>
    </section>
  </div>;
}
function SceneComparison({ title, label, count, snapshot, accent, lightweight = false }) {
  return (
    <div className={`scene-comparison ${accent ? "accent" : ""}`}>
      <div className="scene-comparison-head">
        <span>{title}</span>
        <strong>{formatNumber(count)}</strong>
      </div>
      <div className={`mini-scene ${lightweight ? "mini-scene-summary" : ""}`}>
        {lightweight ? <span>{formatNumber(count)} catalog objects</span> : <SSAScene
            snapshot={snapshot}
            filters={initialFilters}
            forecastHours={24}
            activeFrame={null}
            selectedObject={null}
            selectedRisk={null}
            onSelectObject={() => {}}
            onSelectRisk={() => {}}
          />}
      </div>
      <small>{label}</small>
    </div>
  );
}

function KpiGrid({ stats, analytics, smart }) {
  const cards = [
    ["Objects Tracked", stats.tracked_objects, Satellite],
    ["Debris Count", stats.debris_objects, AlertTriangle],
    ["Screening Proxy Pairs", analytics?.total_screening_proxy_pairs, ShieldAlert],
    ["Mean Heuristic Score", Number.isFinite(analytics?.mean_heuristic_risk_score) ? analytics.mean_heuristic_risk_score.toFixed(3) : "Unavailable", Gauge],
    ["ESA ML Model", smart?.ml_model_status?.status || "Loading", Cpu],
    ["Heuristic Proxy Review List", smart?.after_filter ?? "Unavailable", Filter],
  ];
  return (
    <section className="kpi-grid">
      {cards.map(([label, value, Icon]) => (
        <div className="kpi-card" key={label}>
          <Icon size={18} />
          <span>{label}</span>
          <strong>{value ?? "..."}</strong>
          <small>Updated UTC</small>
        </div>
      ))}
    </section>
  );
}

function PageHeader({ eyebrow, title, text, action }) {
  return (
    <section className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {text ? <p>{text}</p> : null}
      </div>
      {action ? <div className="page-action">{action}</div> : null}
    </section>
  );
}

function Panel({ title, icon: Icon, children }) {
  return (
    <section className="panel">
      <div className="panel-heading"><Icon size={17} /><h2>{title}</h2></div>
      {children}
    </section>
  );
}

function EventList({ events, onSelect, detailed, compact }) {
  if (!events?.length) return <p className="muted">No screening events are available.</p>;
  const priorityRanks = new Map(rankCollisionEvents(events).map((event, index) => [event.id, index + 1]));
  return (
    <div className={`event-list ${compact ? "compact" : ""}`}>
      {events.map((event) => {
        const physical = event.result_kind === "physics_assessment";
        const physics = event.physics_result || {};
        // Resolve identities for display
        const pName = event.primary.canonicalName || event.primary.name;
        const pType = event.primary.canonicalType || getDisplayType(resolveObjectType(event.primary));
        const pId = event.primary.canonicalId || event.primary.id;

        const sName = event.secondary.canonicalName || event.secondary.name;
        const sType = event.secondary.canonicalType || getDisplayType(resolveObjectType(event.secondary));
        const sId = event.secondary.canonicalId || event.secondary.id;

        const pairType = event.pair_type || getPairType(event.primary, event.secondary);
        const pcResult = event.collision_probability || {};
        const priority = collisionEventPriority(event);
        const mlResult = event.ml_result || {};
        const mlProvenance = mlResult.provenance || {};
        const mlPrediction = mlResult.prediction || {};
        const mlSupported = mlResult.status === "available"
          && mlProvenance.source_physics_event_id === event.id
          && mlProvenance.live_feature_semantics_compatibility === "verified";
        const tcaSpeed = physics.relative_speed_at_tca;
        const epochs = physical
          ? `Element epochs ${event.primary.provenance?.element_epoch || "unavailable"} / ${event.secondary.provenance?.element_epoch || "unavailable"}`
          : null;
        const summary = physical
          ? `TCA ${physics.tca?.status === "available" ? physics.tca.value : "unavailable"} | Miss ${physics.miss_distance?.status === "available" ? `${Number(physics.miss_distance.value).toFixed(3)} km` : "unavailable"} | Relative speed ${tcaSpeed?.status === "available" ? `${Number(tcaSpeed.value).toFixed(4)} km/s` : "unavailable"}`
          : `Heuristic score ${Number(event.risk_score).toFixed(3)}`;
        return (
          <button key={event.id} type="button" onClick={() => onSelect(event)} className="event-row">
            <RiskBadge risk={physical ? physics.status : event.risk_level} label={physical ? undefined : `Rank ${event.risk_level}`} />
            <span>
              <strong>{pName} · ID: {pId}</strong>
              <small>{sName} · ID: {sId} | {summary}</small>
              <em>{pType} vs {sType}</em>
              {physical ? <em>{epochs}</em> : null}
              {physical ? <em>{isUsablePc(pcResult)
                ? `Physical Pc ${formatCollisionProbability(pcResult.pc)}`
                : `Physical Pc ${pcDisplayStatus(pcResult)} · ${(pcResult.reason_codes || []).join(", ") || (pcResult.status === "available" ? "INVALID_PC_VALUE" : pcResult.status || "not assessed")}`}</em> : null}
              {physical && isValidProbability(pcResult.source_reported_pc) && pcResult.source_reported_event_id === event.id ? <em>Source-reported CDM Pc {formatProbabilityScientific(pcResult.source_reported_pc)} - kept separate from computed Pc</em> : null}
              {physical ? <em>{mlSupported
                ? `ESA log10 event-risk target: ${Number(mlPrediction.predicted_log_risk).toFixed(4)} (not Pc)`
                : `AI classification unavailable · ${mlResult.model_name ? `${mlResult.model_name} v${mlResult.model_version || "unknown"}; ` : ""}${mlResult.reason_code || "ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED"}; bundled model is a regression estimator, not a classifier`}</em> : null}
              {physical ? <em>Vyoma geometry review band: {{ CRITICAL: "Band 1", HIGH: "Band 2", MEDIUM: "Band 3", LOW: "Band 4", REVIEW_REQUIRED: "Review required" }[event.review_priority?.category] || "Unclassified"}</em> : null}
              <em>Evidence priority #{priorityRanks.get(event.id) || "?"}: {priority.label}. {priority.basis}</em>
              {detailed ? <em>{physical ? `SGP4 trajectory result · ${physics.provenance?.method || "method unavailable"}` : event.suggested_action}</em> : null}
            </span>
            <b title={physical ? "Trajectory assessment status" : "Deterministic heuristic priority score (0–100)"}>
              {physical ? physics.status : `H ${event.priority_score}`}
            </b>
          </button>
        );
      })}
    </div>
  );
}

function MetricRow({ metrics }) {
  return (
    <section className="metric-row">
      {metrics.map(([label, value]) => (
        <div key={label}><span>{label}</span><strong>{value}</strong></div>
      ))}
    </section>
  );
}

function Pipeline({ stages }) {
  const safeStages = Array.isArray(stages) ? stages : [];
  return (
    <div className="pipeline">
      {(safeStages.length ? safeStages : [{ name: "Catalog", count: 0 }, { name: "Heuristic Features", count: 0 }, { name: "Screening Proxy", count: 0 }, { name: "Heuristic Triage", count: 0 }, { name: "Review Watchlist", count: 0 }]).map((stage, index) => (
        <div key={`${stage.name}-${index}`}>
          <span>{index + 1}</span>
          <strong>{stage.name}</strong>
          <small>{stage.count ?? 0} records | {stage.kept_pct == null ? "retained % unavailable" : `${stage.kept_pct}% retained`}</small>
        </div>
      ))}
    </div>
  );
}

function BarList({ data, total }) {
  const entries = Object.entries(data || {});
  if (!entries.length) return <p className="muted">No catalog objects are available for this breakdown.</p>;
  return (
    <div className="bar-list">
      {entries.map(([label, value]) => (
        <div key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
          <i style={{ width: `${Math.max(4, (Number(value) / Math.max(1, total)) * 100)}%` }} />
        </div>
      ))}
    </div>
  );
}

function ObjectPair({ event, screeningJobId, toggleWatchlist, watched, onShowInGlobe }) {
  // Use canonical identities for display
  const pIdentity = buildCanonicalIdentity(event.primary);
  const sIdentity = buildCanonicalIdentity(event.secondary);
  const pairType = event.pair_type || getPairType(event.primary, event.secondary);

  return (
    <div className="object-pair">
      <div>
        <strong>{pIdentity.name} · ID: {pIdentity.id}</strong>
        <span className="object-type-badge" data-type={pIdentity.objectType}>{pIdentity.displayType}</span>
        <small className="classification-provenance">Object type: {event.primary.object_type || "UNKNOWN"} · source: {event.primary.classification_source || "classification unavailable"}{event.primary.source_classification ? ` · raw catalog class: ${event.primary.source_classification}` : ""}</small>
        <span>{event.primary.band} | {event.primary.orbit_type}</span>
        <small>{event.primary.altitude_km} km | {event.primary.inclination_deg} deg | {event.primary.velocity_kms} km/s</small>
        <div className="object-actions">
          <button className="secondary-action" type="button" onClick={() => toggleWatchlist(pIdentity.id)}>{watched ? "Unpin Watchlist" : "Pin Watchlist"}</button>
          <button className="primary-action" type="button" onClick={() => onShowInGlobe(pIdentity.id, event, screeningJobId)}>Show in Globe</button>
        </div>
      </div>
      <div>
        <strong>{sIdentity.name} · ID: {sIdentity.id}</strong>
        <span className="object-type-badge" data-type={sIdentity.objectType}>{sIdentity.displayType}</span>
        <small className="classification-provenance">Object type: {event.secondary.object_type || "UNKNOWN"} · source: {event.secondary.classification_source || "classification unavailable"}{event.secondary.source_classification ? ` · raw catalog class: ${event.secondary.source_classification}` : ""}</small>
        <span>{event.secondary.band} | {event.secondary.orbit_type}</span>
        <small>{event.secondary.altitude_km} km | {event.secondary.inclination_deg} deg | {event.secondary.velocity_kms} km/s</small>
        <div className="object-actions">
          <button className="secondary-action" type="button" onClick={() => toggleWatchlist(sIdentity.id)}>{watched ? "Unpin Watchlist" : "Pin Watchlist"}</button>
          <button className="primary-action" type="button" onClick={() => onShowInGlobe(sIdentity.id, event, screeningJobId)}>Show in Globe</button>
        </div>
      </div>
    </div>
  );
}

function RiskMatrix({ events }) {
  // Display the heuristic proxy classes over object altitude and speed magnitude.

  const [hover, setHover] = useState(null);

  const width = 1600;
  const height = 780;
  const pad = { l: 104, r: 32, t: 32, b: 84 };

  const safeEvents = (events || []).filter(Boolean);
  if (!safeEvents.length) return <p className="muted">No screening proxy pairs are available to plot.</p>;

  // Extract numeric fields gracefully.
  const points = safeEvents
    .map((e) => {
      const alt = Number(e?.primary?.altitude_km ?? e?.obj_a?.altitude_km ?? e?.secondary?.altitude_km);
      const rv = Number(e?.primary?.velocity_kms ?? e?.obj_a?.velocity_kms);
      const score = Number(e?.risk_score);
      const risk = String(e?.risk_level || "low").toLowerCase();
      if (!Number.isFinite(alt) || !Number.isFinite(rv)) return null;
      return { e, alt, rv, score: Number.isFinite(score) ? score : null, risk };
    })
    .filter(Boolean);

  // If object features are absent, do not manufacture a display matrix.
  if (!points.length) {
    return <p className="muted">Object altitude or speed magnitude is unavailable.</p>;
  }

  const altMin = Math.min(...points.map((p) => p.alt));
  const altMax = Math.max(...points.map((p) => p.alt));
  const rvMin = Math.min(...points.map((p) => p.rv));
  const rvMax = Math.max(...points.map((p) => p.rv));

  // Use a fixed binning resolution for stable UI.
  const binsX = 32;
  const binsY = 18;

  const cellW = (width - pad.l - pad.r) / binsX;
  const cellH = (height - pad.t - pad.b) / binsY;

  const colorStops = [
    { at: 0.0, c: "#22c55e" }, // low
    { at: 0.25, c: "#38bdf8" }, // moderate
    { at: 0.45, c: "#ffd166" }, // elevated
    { at: 0.7, c: "#ff8a3d" }, // high
    { at: 0.9, c: "#ff2f55" }, // critical
    { at: 1.0, c: "#b91cff" }, // extreme
  ];

  const lerp = (a, b, t) => a + (b - a) * t;

  const hexToRgb = (hex) => {
    const h = hex.replace("#", "");
    const n = parseInt(h, 16);
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
  };

  const rgbToCss = (r, g, b, a = 1) => `rgba(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)}, ${a})`;

  const colorScale = (t) => {
    const x = Math.max(0, Math.min(1, t));
    for (let i = 0; i < colorStops.length - 1; i += 1) {
      const a = colorStops[i];
      const b = colorStops[i + 1];
      if (x >= a.at && x <= b.at) {
        const u = (x - a.at) / Math.max(1e-9, b.at - a.at);
        const ra = hexToRgb(a.c);
        const rb = hexToRgb(b.c);
        return rgbToCss(lerp(ra.r, rb.r, u), lerp(ra.g, rb.g, u), lerp(ra.b, rb.b, u), 0.92);
      }
    }
    const last = colorStops[colorStops.length - 1];
    const rl = hexToRgb(last.c);
    return rgbToCss(rl.r, rl.g, rl.b, 0.92);
  };

  // Bin aggregation: store sum of risk scores and count.
  const grid = Array.from({ length: binsY }, () => Array.from({ length: binsX }, () => ({ sum: 0, count: 0 })));

  for (const p of points) {
    const nx = (p.alt - altMin) / Math.max(1e-9, altMax - altMin);
    const ny = (p.rv - rvMin) / Math.max(1e-9, rvMax - rvMin);

    const ix = Math.max(0, Math.min(binsX - 1, Math.floor(nx * binsX)));
    const iy = Math.max(0, Math.min(binsY - 1, Math.floor(ny * binsY)));

    const score = proxyPriorityClassIndex(p.risk);
    grid[iy][ix].sum += score;
    grid[iy][ix].count += 1;
  }

  const cells = [];
  for (let iy = 0; iy < binsY; iy += 1) {
    for (let ix = 0; ix < binsX; ix += 1) {
      const cell = grid[iy][ix];
      const has = cell.count > 0;
      const score = has ? cell.sum / cell.count : 0;

      // Determine representative values for hover (exact fields averaged only if available).
      // For mission dashboard: keep simple; we show exact-ish aggregated approximations.
      const xAlt = altMin + ((ix + 0.5) / binsX) * (altMax - altMin);
      const yRv = rvMin + ((iy + 0.5) / binsY) * (rvMax - rvMin);

      cells.push({ ix, iy, score, has, xAlt, yRv, count: cell.count });
    }
  }

  const riskBand = (score) => {
    if (score < 0.15) return "Low";
    if (score < 0.4) return "Moderate";
    if (score < 0.62) return "High";
    if (score < 0.82) return "Critical";
    return "Extreme";
  };

  const showHover = (evt, cell) => {
    if (!cell.has) {
      setHover(null);
      return;
    }
    const rect = evt.currentTarget.getBoundingClientRect();
    const x = evt.clientX - rect.left;
    const y = evt.clientY - rect.top;
    setHover({ cell, x, y });
  };

  const hideHover = () => setHover(null);

  return (
    <div className="heatmap-graph">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 8 }}>
        <div style={{ color: "#38bdf8", fontWeight: 800, fontSize: 12, textTransform: "uppercase" }}>Proxy Priority Class Matrix</div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ color: "#94a3b8", fontSize: 11, fontWeight: 750, textTransform: "uppercase" }}>Legend</span>
          <div className="proxy-matrix-legend" aria-label="Priority legend">{[["Low", "#22c55e"], ["Moderate", "#38bdf8"], ["High", "#ffd166"], ["Critical", "#ff8a3d"], ["Extreme", "#b91cff"]].map(([label, color]) => <span key={label}><i style={{ background: color }} />{label}</span>)}</div>
        </div>
      </div>
      <p className="muted">Each proxy-pair record is placed by its primary object's altitude and speed. Cell color uses a fixed ordinal mapping of relative priority labels; it is not a measured event-risk score. Catalog objects can appear in multiple pairs.</p>

      <div style={{ position: "relative", width: "100%", height: "clamp(560px, 56vw, 780px)", border: "1px solid rgba(255,255,255,0.08)", background: "#02030a", borderRadius: 10, overflow: "hidden" }}>
        <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" onMouseLeave={hideHover}>
          {/* grid lines */}
          {Array.from({ length: binsX + 1 }, (_, i) => (
            <line
              key={`gx-${i}`}
              x1={pad.l + i * cellW}
              y1={pad.t}
              x2={pad.l + i * cellW}
              y2={height - pad.b}
              stroke="rgba(255,255,255,0.06)"
              strokeWidth={1}
            />
          ))}
          {Array.from({ length: binsY + 1 }, (_, i) => (
            <line
              key={`gy-${i}`}
              x1={pad.l}
              y1={pad.t + i * cellH}
              x2={width - pad.r}
              y2={pad.t + i * cellH}
              stroke="rgba(255,255,255,0.06)"
              strokeWidth={1}
            />
          ))}

          {/* cells */}
          {cells.map((cell) => {
            const x = pad.l + cell.ix * cellW;
            const y = pad.t + (binsY - 1 - cell.iy) * cellH; // invert so higher RV is top
            const fill = cell.has ? colorScale(cell.score) : "rgba(255,255,255,0.03)";
            const stroke = cell.has ? "rgba(255,255,255,0.10)" : "rgba(255,255,255,0.04)";
            const opacity = cell.has ? 0.95 : 1;

            return (
              <g key={`c-${cell.ix}-${cell.iy}`}>
              <rect
                x={x}
                y={y}
                width={cellW}
                height={cellH}
                fill={fill}
                stroke={stroke}
                strokeWidth={1}
                opacity={opacity}
                onMouseMove={(e) => showHover(e, cell)}
              />
              {cell.has && cellW >= 22 && <text x={x + cellW / 2} y={y + cellH / 2 + 5} fill="white" fontSize="13" fontWeight="700" textAnchor="middle" pointerEvents="none">{cell.count}</text>}
              </g>
            );
          })}

          {/* axes ticks */}
          {Array.from({ length: 5 }, (_, i) => {
            const t = i / 4;
            const x = pad.l + t * (width - pad.l - pad.r);
            const alt = altMin + t * (altMax - altMin);
            return (
              <g key={`xt-${i}`}>
                <line x1={x} y1={height - pad.b} x2={x} y2={height - pad.b + 6} stroke="rgba(255,255,255,0.12)" />
                <text x={x} y={height - pad.b + 22} fill="#9fb7d9" fontSize="10" textAnchor="middle">{Math.round(alt)} km</text>
              </g>
            );
          })}

          {Array.from({ length: 5 }, (_, i) => {
            const t = i / 4;
            const y = pad.t + (binsY - 1 - t * (binsY - 1)) * cellH;
            const rv = rvMin + t * (rvMax - rvMin);
            return (
              <g key={`yt-${i}`}>
                <line x1={pad.l - 6} y1={y} x2={pad.l} y2={y} stroke="rgba(255,255,255,0.12)" />
                <text x={pad.l - 10} y={y + 3} fill="#9fb7d9" fontSize="10" textAnchor="end">{rv.toFixed(1)} km/s</text>
              </g>
            );
          })}

          <text x={(pad.l + width - pad.r) / 2} y={height - 8} fill="#94a3b8" fontSize="11" textAnchor="middle" fontWeight="700">Orbital altitude (km)</text>
          <text transform={`rotate(-90 ${18} ${(pad.t + height - pad.b) / 2})`} x={18} y={(pad.t + height - pad.b) / 2} fill="#94a3b8" fontSize="11" textAnchor="middle" fontWeight="700">Primary-object speed magnitude (km/s)</text>
        </svg>

        {hover?.cell ? (
          <div
            className="heatmap-tooltip"
            style={{
              position: "absolute",
              left: Math.min(1000 - 240, Math.max(6, hover.x)),
              top: Math.min(500 - 160, Math.max(6, hover.y)),
              width: 220,
              pointerEvents: "none",
              border: "1px solid rgba(129,225,255,0.22)",
              background: "linear-gradient(180deg, rgba(14,28,46,0.88), rgba(5,9,18,0.72))",
              borderRadius: 12,
              padding: 12,
              boxShadow: "0 18px 50px rgba(0,0,0,0.4)",
              backdropFilter: "blur(12px)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <div style={{ width: 12, height: 12, borderRadius: 999, background: colorScale(hover.cell.score), boxShadow: `0 0 18px ${colorScale(hover.cell.score)}` }} />
              <div style={{ fontWeight: 900, color: "#fff", fontSize: 13 }}>{riskBand(hover.cell.score)} risk region</div>
            </div>

            <div style={{ display: "grid", gap: 6, color: "#dbeafe", fontSize: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}><span style={{ color: "#94a3b8", textTransform: "uppercase", fontWeight: 800, fontSize: 10 }}>Ordinal class index</span><strong style={{ color: "#fff" }}>{hover.cell.score.toFixed(3)}</strong></div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}><span style={{ color: "#94a3b8", textTransform: "uppercase", fontWeight: 800, fontSize: 10 }}>Proxy-pair records</span><strong style={{ color: "#fff" }}>{hover.cell.count}</strong></div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}><span style={{ color: "#94a3b8", textTransform: "uppercase", fontWeight: 800, fontSize: 10 }}>Altitude</span><strong style={{ color: "#fff" }}>{hover.cell.xAlt.toFixed(0)} km</strong></div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}><span style={{ color: "#94a3b8", textTransform: "uppercase", fontWeight: 800, fontSize: 10 }}>Primary-object speed magnitude</span><strong style={{ color: "#fff" }}>{hover.cell.yRv.toFixed(2)} km/s</strong></div>

              {/* The rest of the requested fields are omitted gracefully if not available in the event bins. */}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
      <span style={{ color: "#94a3b8", fontWeight: 800, fontSize: 10, textTransform: "uppercase" }}>{label}</span>
      <strong style={{ color: "#fff", fontWeight: 900, fontSize: 12, textAlign: "right" }}>{String(value ?? "...")}</strong>
    </div>
  );
}


function SliderSetting({ label, value, onChange }) {
  return (
    <label className="slider-setting">
      <span>{label}</span>
      <input type="range" min="0" max="100" value={value} onChange={(event) => onChange(Number(event.target.value))} />
      <strong>{value}</strong>
    </label>
  );
}

function EmptyState({ title, text }) {
  return (
    <div className="empty-state">
      <AlertTriangle size={22} />
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

function filterSnapshot(snapshot, query) {
  if (!snapshot || !query.trim()) return snapshot;
  const q = query.trim().toLowerCase();
  const objects = snapshot.objects.filter((object) => {
    const searchable = [
      object.name,
      object.id,
      object.band,
      object.category,
      object.orbit_type,
      `${object.altitude_km}`,
      `${object.inclination_deg}`,
      `${object.velocity_kms}`,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return searchable.includes(q);
  });
  return { ...snapshot, objects, stats: { ...snapshot.stats, tracked_objects: objects.length } };
}

function buildSearchSuggestions(snapshot) {
  if (!snapshot?.objects?.length) return [];
  const values = new Set();
  for (const object of snapshot.objects.slice(0, 500)) {
    values.add(object.name);
    values.add(object.id);
    values.add(object.band);
    values.add(object.category);
    values.add(object.orbit_type);
  }
  return [...values].filter(Boolean).slice(0, 120);
}

function applyOperationalPrioritization(events) {
  if (!events || !Array.isArray(events)) return [];

  const prioritized = events.map((event) => {
    return {
      ...event,
      pair_type: event.pair_type || getPairType(event.primary, event.secondary),
    };
  });

  prioritized.sort((a, b) => (b.priority_score || 0) - (a.priority_score || 0));

  prioritized.forEach((event, index) => {
    event.display_order = index + 1;
  });

  return prioritized;
}

/**
 * Log pair type distribution for verification.
 */
function logPairTypeDistribution(events) {
  if (!events || !Array.isArray(events)) {
    console.warn("[HeuristicScreening] No screening proxies to analyze");
    return;
  }

  const counts = {
    "SATELLITE vs DEBRIS": 0,
    "SATELLITE vs ROCKET BODY": 0,
    "SATELLITE vs SATELLITE": 0,
    "DEBRIS vs ROCKET BODY": 0,
    "DEBRIS vs DEBRIS": 0,
    "ROCKET BODY vs ROCKET BODY": 0,
    UNKNOWN: 0,
  };

  let activeDebrisCount = 0;
  let topSatelliteDebris = null;

  for (const event of events) {
    const pairType = event.pair_type || getPairType(event.primary, event.secondary);
    if (counts[pairType] !== undefined) {
      counts[pairType]++;
    } else {
      counts.UNKNOWN++;
    }

    if (pairType === "SATELLITE vs DEBRIS") {
      activeDebrisCount++;
      if (!topSatelliteDebris) {
        topSatelliteDebris = event;
      }
    }
  }

  console.info(
    `[HeuristicScreening] Pair type distribution (${events.length} screening proxies):\n` +
    `  SATELLITE vs DEBRIS:       ${counts["SATELLITE vs DEBRIS"]}\n` +
    `  SATELLITE vs ROCKET BODY:  ${counts["SATELLITE vs ROCKET BODY"]}\n` +
    `  SATELLITE vs SATELLITE:    ${counts["SATELLITE vs SATELLITE"]}\n` +
    `  DEBRIS vs ROCKET BODY:     ${counts["DEBRIS vs ROCKET BODY"]}\n` +
    `  DEBRIS vs DEBRIS:          ${counts["DEBRIS vs DEBRIS"]}\n` +
    `  ROCKET BODY vs ROCKET BODY: ${counts["ROCKET BODY vs ROCKET BODY"]}\n` +
    `  UNKNOWN:                   ${counts.UNKNOWN}`
  );

  if (activeDebrisCount === 0) {
    console.warn(
      `[HeuristicScreening] No satellite-debris proxy pairs were created by the current selection rules.`
    );
  } else {
    console.info(
      `[HeuristicScreening] Top satellite-debris screening proxy: ` +
      `"${topSatelliteDebris?.primary?.name || "?"} · ID: ${topSatelliteDebris?.primary?.id || "?"}" ` +
      `vs "${topSatelliteDebris?.secondary?.name || "?"} · ID: ${topSatelliteDebris?.secondary?.id || "?"}"`
    );
  }
}

function buildLocalAnalytics(snapshot, events) {
  const risk_distribution = {};
  for (const event of events) risk_distribution[event.risk_level] = (risk_distribution[event.risk_level] || 0) + 1;
  const scores = events.map((event) => Number(event.risk_score)).filter(Number.isFinite);
  return {
    total_objects: snapshot?.stats?.tracked_objects || 0,
    unavailable_objects: snapshot?.stats?.unavailable_objects || 0,
    active_satellites: snapshot?.stats?.active_satellites || 0,
    debris_objects: snapshot?.stats?.debris_objects || 0,
    total_screening_proxy_pairs: events.length,
    high_priority_screening_proxies: events.filter((event) => ["High", "Critical"].includes(event.risk_level)).length,
    mean_heuristic_risk_score: scores.length ? scores.reduce((sum, value) => sum + value, 0) / scores.length : null,
    global_heuristic_risk_score: snapshot?.stats?.global_heuristic_risk_score ?? null,
    heuristic_forecast_trend_score: snapshot?.stats?.heuristic_forecast_trend_score ?? null,
    risk_distribution,
    band_distribution: { LEO: snapshot?.stats?.leo || 0, MEO: snapshot?.stats?.meo || 0, GEO: snapshot?.stats?.geo || 0 },
    risk_timeline: [],
    provenance: snapshot?.stats?.provenance || null,
  };
}

function buildLocalSmart(events, totalObjects) {
  const retained = events.filter((event) => ["High", "Medium", "Critical"].includes(event.risk_level));
  const total = events.length;
  return {
    result_type: "heuristic_filter",
    status: "available",
    model_status: "not_applicable_to_proxy_events",
    model_reason: "ESA inference requires complete event-level Stage 2A physics features; proxy pairs do not contain them.",
    ml_supported_event_count: 0,
    physics_only_event_count: 0,
    heuristic_only_proxy_count: total,
    unavailable_ml_prediction_count: 0,
    raw_events: total,
    objects_analyzed: totalObjects,
    after_filter: retained.length,
    reduction_pct: null,
    reduction_status: "not_measured",
    reduction_reason: "No validated workload-reduction benchmark exists; these counts describe heuristic proxy pairs only.",
    mean_heuristic_risk_score: total ? events.reduce((sum, event) => sum + event.risk_score, 0) / total : null,
    by_class: events.reduce((counts, event) => ({ ...counts, [event.risk_level]: (counts[event.risk_level] || 0) + 1 }), {}),
    briefing: `${totalObjects.toLocaleString()} catalog objects analyzed. ${retained.length} heuristic screening proxies are on the review list; physical conjunction assessment and ML are unavailable.`,
    pipeline_stages: [],
  };
}

function sourceDetail(sourceState) {
  if (!sourceState) return "Catalog source status unavailable";
  const details = [];
  if (sourceState.last_success_at) details.push(`Last successful live refresh: ${sourceState.last_success_at}`);
  if (sourceState.last_error_code) details.push(`Refresh diagnostic: ${sourceState.last_error_code}`);
  return details.join("; ") || sourceState.source || sourceState.status;
}

function PhysicsAvailability({ physics, pcResult, proxyOnly = false }) {
  if (physics?.applicability === "candidate_pair_only") {
    return (
      <div className="readout-list">
        <span>Physics status <strong>Not assessed — heuristic proxy only</strong></span>
        <span>TCA <strong>Unavailable — no trajectory assessment attached.</strong></span>
        <span>Miss distance <strong>Unavailable — no trajectory assessment attached.</strong></span>
        <span>Covariance <strong>Unavailable — no covariance is attached to a heuristic proxy.</strong></span>
        <span>Collision probability <strong>Unavailable — proxy only.</strong></span>
        <span>Proxy method <strong>{physics.provenance?.method || "Unavailable"}</strong></span>
        <span>Reason codes <strong>{physics.reason_codes?.join(", ") || "proxy_only"}</strong></span>
      </div>
    );
  }
  const reasons = physics?.reason_codes?.length ? physics.reason_codes.join(", ") : "none";
  const provenance = physics?.provenance || {};
  const pcReasons = pcResult?.reason_codes || [];
  const covarianceSources = pcResult?.covariance_sources || [];
  const covarianceSourceText = covarianceSources.length
    ? covarianceSources.map((item) => `${item.object_id}: ${item.source} (${item.source_type}${item.is_synthetic ? ", SYNTHETIC" : ""}, ${item.frame}, ${item.epoch})`).join("; ")
    : "Unavailable";
  return (
    <div className="readout-list">
      <span>Assessment status <strong>{physics?.status || "unavailable"}</strong></span>
      <span>TCA status <strong>{physics?.tca_status || "unavailable"}</strong></span>
      {physics?.status === "boundary" ? <span>Boundary meaning <strong>The minimum lies at a screening horizon edge; this is not a threshold or collision-risk class.</strong></span> : null}
      <span>Screening horizon UTC <strong>{physics?.screening_horizon_start ? `${physics.screening_horizon_start} to ${physics.screening_horizon_end}` : "Unavailable"}</strong></span>
      <span>Screening threshold <strong>{physics?.screening_threshold_km == null ? "Unavailable" : `${physics.screening_threshold_km} km`}</strong></span>
      <span>TCA <strong>{formatScientificField(physics?.tca, 3)}</strong></span>
      <span>Miss distance <strong>{formatScientificField(physics?.miss_distance, 6)}</strong></span>
      <span>Relative position <strong>{formatScientificField(physics?.relative_position_at_tca, 3)}</strong></span>
      <span>Relative velocity <strong>{formatScientificField(physics?.relative_velocity_at_tca, 6)}</strong></span>
      <span>Relative speed <strong>{formatScientificField(physics?.relative_speed_at_tca, 6)}</strong></span>
      <span>Frame <strong>{physics?.state_information?.source_frame || "Unavailable"}</strong></span>
      <span>Method <strong>{provenance.method ? `${provenance.method} v${provenance.method_version || "?"}` : "Unavailable"}</strong></span>
      <span>Input provenance <strong>{provenance.source || provenance.source_type || "Unavailable"} · {provenance.source_type || "unknown source type"}</strong></span>
      <span>Catalog input hash <strong>{provenance.input_hash || "Unavailable"}</strong></span>
      {pcResult ? <>
        <span>Collision probability <strong>{isUsablePc(pcResult) ? formatCollisionProbability(pcResult.pc) : "Collision probability unavailable"}</strong></span>
        <span>Pc status / reason <strong>{pcDisplayStatus(pcResult)} · {pcReasons.length ? pcReasons.map(describePcReason).join(" ") : pcResult.status === "available" && !isUsablePc(pcResult) ? "INVALID_PC_VALUE" : "No failure reason."}</strong></span>
        <span>Pc method <strong>{pcResult.method || "Unavailable"} {pcResult.method_version ? `v${pcResult.method_version}` : ""}</strong></span>
        <span>Applicability <strong>{pcResult.applicability_status || "not_assessed"}</strong></span>
        <span>Covariance status / frame / epoch <strong>{pcResult.covariance_status || "unavailable"} · {pcResult.covariance_frame || "Unavailable"} · {pcResult.covariance_epoch || "Unavailable"}</strong></span>
        <span>Covariance provenance <strong>{covarianceSourceText}</strong></span>
        <span>Hard-body radius <strong>{pcResult.hbr_km == null ? "Unavailable" : `${pcResult.hbr_km} km`} · source {pcResult.hbr_source || "unavailable"}</strong></span>
        <span>HBR provenance <strong>{pcResult.hbr_provenance?.description ? `${pcResult.hbr_provenance.description}${pcResult.hbr_provenance.is_synthetic ? " (SYNTHETIC)" : ""}` : "Unavailable"}</strong></span>
        <span>Pc assumptions <strong>{pcResult.assumptions?.join(" ") || "Unavailable"}</strong></span>
        <span>Pc warnings <strong>{pcResult.warnings?.join(" ") || "None"}</strong></span>
        <span>Pc provenance <strong>{pcResult.provenance?.source || "Unavailable"} · {pcResult.provenance?.method || "method unavailable"}</strong></span>
      </> : !proxyOnly ? <>
        <span>Covariance <strong>Unavailable</strong></span>
        <span>Collision probability <strong>Unavailable — no Pc result attached.</strong></span>
        <span>Hard-body radius <strong>Unavailable — not estimated from object category.</strong></span>
      </> : null}
      <span>Reason codes <strong>{reasons}</strong></span>
    </div>
  );
}

function explainMlReason(code) {
  const reasons = {
    ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED: "Model output withheld: equivalence between historical ESA CDM features and live TLE-derived features has not been established.",
    PHYSICS_ENCOUNTER_UNAVAILABLE: "The event does not have a valid or boundary trajectory assessment.",
    PHYSICS_FRAME_UNAVAILABLE: "The physics event is not expressed in the required TEME frame.",
    PHYSICS_TIME_UNAVAILABLE_OR_INCONSISTENT: "The event time or time-to-TCA could not be validated.",
    ESA_INPUT_TIME_TO_TCA_UNAVAILABLE_OR_INVALID: "The ESA estimate is unavailable because time-to-TCA could not be validated.",
    ESA_INPUT_TIME_TO_TCA_BELOW_MINIMUM: "The ESA estimate is inapplicable because this event is less than 2 days from TCA; physical results remain available.",
    PRIMARY_TCA_STATE_UNAVAILABLE: "A valid primary-object state at TCA is missing.",
    DEGENERATE_RTN_BASIS: "The relative state cannot be represented in a stable RTN frame.",
    INCONSISTENT_PHYSICS_STATE: "The state vectors do not agree with reported miss distance or relative speed.",
    REQUIRED_PHYSICS_FEATURE_UNAVAILABLE: "One or more of the nine required event-level model features are unavailable.",
    MODEL_ARTIFACT_UNAVAILABLE: "The trained ESA model artifact is unavailable.",
    MODEL_RUNTIME_UNAVAILABLE: "The optional machine-learning runtime is unavailable.",
    MODEL_RUNTIME_VERSION_MISMATCH: "The installed model runtime does not match the artifact version.",
    INVALID_PREDICTION_PAYLOAD: "The service marked a prediction available, but its output fields failed validation.",
  };
  return reasons[code] || code || "Required event-level physics features are unavailable.";
}

function describePcReason(code) {
  const descriptions = {
    NO_COVARIANCE: "Live covariance is not available for this data source.",
    HBR_UNAVAILABLE: "Object dimensions / hard-body radius are unavailable.",
    INSUFFICIENT_ENCOUNTER_STATE: "A valid TCA encounter state is unavailable.",
    INVALID_COVARIANCE: "The supplied covariance failed validation.",
    INVALID_HBR: "The supplied hard-body radius failed validation.",
    PC_METHOD_NOT_APPLICABLE: "Foster 2D is not applicable to this encounter state.",
    COVARIANCE_OBJECT_ID_MISMATCH: "Covariance object ID does not match this conjunction object.",
    COVARIANCE_EPOCH_MISMATCH: "Covariance is not at the TCA epoch; epoch transforms are unsupported.",
    COVARIANCE_FRAME_MISMATCH: "Covariance is not in the trajectory frame; frame transforms are unsupported.",
    RELATIVE_COVARIANCE_CORRELATION_UNKNOWN: "Cross-object correlation is unknown; independence was not authorized.",
    DEGENERATE_ENCOUNTER_GEOMETRY: "Relative velocity does not define a stable encounter plane.",
    NUMERICAL_FAILURE: "The probability integral did not converge within the configured tolerance.",
  };
  return descriptions[code] || code;
}

function formatScientificField(field, digits = 3) {
  if (!field || field.status !== "available" || field.value == null) return "Unavailable";
  const value = field.value;
  const units = field.units ? ` ${field.units}` : "";
  if (typeof value === "number" && Number.isFinite(value)) return `${value.toFixed(digits)}${units}`;
  if (Array.isArray(value) && value.every((item) => Number.isFinite(Number(item)))) {
    return `${value.map((item) => Number(item).toFixed(digits)).join(", ")}${units}`;
  }
  return `${value}${units}`;
}

function pushNotice(setNotices, message, type) {
  setNotices((current) => [...current.slice(-5), { message, type, at: Date.now() }]);
}

function scientific(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return "...";
  return Number(value).toExponential(3);
}

