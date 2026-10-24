import React from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bell,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Cpu,
  DatabaseZap,
  Download,
  FileText,
  Filter,
  Gauge,
  Globe2,
  Home,
  LayoutDashboard,
  LineChart,
  Loader2,
  PanelRightOpen,
  Pause,
  Play,
  Radar,
  RefreshCw,
  Rocket,
  Satellite,
  Search,
  Settings,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Target,
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
  resumeConjunctionJob,
  importEventCdm,
  retrieveEventCdmFromSpaceTrack,
  calculateScenarioPc,
  getForecast,
  getManeuver,
  restoreArchivedScreeningJob,
  selectedEventReportPath,
  getScreeningProxies,
  getSmartFilter,
  getSystemHealth,
} from "./api/ssaClient";
import { SSAScene } from "./components/Scene/SSAScene";
import { AnalyticsPanel } from "./components/UI/AnalyticsPanel";
import { ControlPanel } from "./components/UI/ControlPanel";
import { TelemetryStrip } from "./components/UI/TelemetryStrip";
import { TimelinePanel } from "./components/UI/TimelinePanel";
import { SmartFilterPage } from "./components/UI/SmartFilterPage";
import { CollisionPcSummary, CollisionProbabilityCard, formatCollisionProbability, formatProbabilityPercentage, formatProbabilityScientific, isUsablePc, isValidProbability, pcDisplayStatus, sourcePcLabel } from "./components/UI/CollisionPcSummary.js";
import { CdmReferenceAssessment } from "./components/UI/CdmReferenceAssessment.jsx";
import { ReferenceManeuverAssessment } from "./components/UI/ReferenceManeuverAssessment.jsx";
import { EventAnomalyPanel } from "./components/UI/OrbitalAnomalySummary.js";
import { RiskBadge } from "./components/UI/RiskBadge.js";
import { formatNumber } from "./utils/orbitalMath";
import { createRequestSequence, ignoreAbort } from "./utils/requestSequence";
import { getScreeningJobSelection } from "./utils/screeningJobSelection";
import { datasetLabel, retainCatalogSnapshot, sourceLabel } from "./utils/catalogStatus";
import { isCurrentManeuverRequest, maneuverAssessmentForSelection, maneuverPageState, resolveManeuverEvent, selectManeuverEvent } from "./utils/maneuverSelection";
import { ManeuverBaselineComparison } from "./components/UI/ManeuverBaselineComparison.js";
import { ManeuverEventContext } from "./components/UI/ManeuverEventContext.js";
import { CollisionPriorityTable } from "./components/UI/CollisionPriorityTable.js";
import { CollisionAnalysisSummary } from "./components/UI/CollisionAnalysisSummary.js";
import { operationalFosterStatus, researchPcPresentation } from "./utils/collisionPcPresentation.js";
import { ManeuverAiSummary } from "./components/UI/ManeuverAiSummary.js";
import { ManeuverScreeningContext } from "./components/UI/ManeuverScreeningContext.js";
import { buildSmartFilterView } from "./utils/smartFilterView";
import { catalogHoverDetails } from "./utils/catalogHover.js";
import { captureGlobeEventSelection, downloadGlobeEventReport, resolveGlobeEventSelection } from "./utils/globeEventReport.js";
import { EventRiskEstimate } from "./components/UI/EventRiskEstimate.js";
import { forecastHourLabel, proxyPriorityClassIndex } from "./utils/analyticsPresentation.js";
import { beginScreeningAttempt, collisionScreeningState, createExplicitRefreshHandler, finishScreeningAttempt, reconcilePhysicalEventSelection, resolvePhysicalEventSelection, screeningResultMatchesRun, screeningStatusForEmptyResults, screeningSummaryDisplay, shouldStartScreeningRun, updateScreeningAttempt } from "./utils/screeningRefreshPolicy.js";
import { readWatchlist } from "./utils/watchlistStorage.js";
import { COLLISION_INVALID_ASSESSMENT_LABEL, COLLISION_PAIR_FILTERS, collisionEventPriority, filterCollisionEvents, getCollisionEventsForDisplay, rankCollisionEvents, rankOrbitalAnomalyEvents, screeningAssessmentCounts, searchAndSortCollisionEvents } from "./utils/collisionEventDisplay.js";
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
import {
  LineChart as RechartsLineChart,
  Line,
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";

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
];

export default function App() {
  const [activePage, setActivePage] = useState("home");
  const [snapshot, setSnapshot] = useState(null);
  const lastCatalogSnapshotRef = useRef(null);
  const [forecast, setForecast] = useState(null);
  const [platform, setPlatform] = useState({ health: null, analytics: null, conjunctions: [], screeningProxies: [], conjunctionStatus: { api_status: "idle", result_status: "not_started" }, screeningAttempt: null, smart: null });
  const [archivedJobSelection, setArchivedJobSelection] = useState(null);
  const [archiveRestoreBusy, setArchiveRestoreBusy] = useState(false);
  const [filters, setFilters] = useState(initialFilters);
  const [forecastHours, setForecastHours] = useState(24);
  const [isPlaying, setIsPlaying] = useState(true);
  const [selectedObject, setSelectedObject] = useState(null);
  const [hoverObject, setHoverObject] = useState(null);
  const [selectedRisk, setSelectedRisk] = useState(null);
  const [eventSelection, setEventSelection] = useState({ event: null, context: null, notice: null });
  const selectedEvent = eventSelection.event;
  const [pendingFocusId, setPendingFocusId] = useState(null);
  const [pendingGlobeSelection, setPendingGlobeSelection] = useState(null);
  const [maneuver, setManeuver] = useState(null);
  const [maneuverRequest, setManeuverRequest] = useState(null);
  const [referenceManeuverEvent, setReferenceManeuverEvent] = useState(null);
  const maneuverRequestGenerationRef = useRef(0);
  const [loading, setLoading] = useState(true);
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
  acceptedScreeningJobIdRef.current = platform.conjunctionStatus?.job_id || null;
  
  useEffect(() => {
    let cancelled = false;
    let activeController = null;
    let activeRequestId = null;
    let activeInvocationId = null;
    const requests = createRequestSequence();

    async function load({ explicitScreeningRefresh = true, invocationId = null } = {}) {
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
      setLoading(true);
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
          screening: { horizon_hours: 24, sample_step_seconds: 60, screening_threshold_km: 25, start_utc: startUtc },
        };
        setPlatform((previous) => beginScreeningAttempt(previous, queuedStatus));
        getConjunctions({ limit: 120, horizonHours: 24, sampleStepSeconds: 60, screeningThresholdKm: 25, startUtc, catalogIdentity, diagnosticInvocationId: invocationId,
          onStatus: (job) => {
            if (screeningRunRef.current.runId !== runId) {
              console.warn("[ORION screening diagnostic] job status ignored: run identity changed", { invocationId, requestId: currentRequestId, expectedRunId: runId, receivedJobId: job?.job_id || null });
              return;
            }
            if (job.job_id) screeningRunRef.current.jobId = job.job_id;
            if (job.job_id) saveActiveScreeningJobId(job.job_id);
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
      Promise.all([catalogPromise, getSystemHealth({ signal: controller.signal }), getAnalytics({ signal: controller.signal }), getScreeningProxies({ limit: 120, signal: controller.signal }), getSmartFilter({ signal: controller.signal })])
        .then(([catalog, healthPayload, analyticsPayload, proxyPayload, smartPayload]) => {
          if (!catalog || !current()) {
            console.info("[ORION screening diagnostic] secondary catalogue results ignored", {
              invocationId,
              requestId: currentRequestId,
              catalogueReady: Boolean(catalog),
              requestIsCurrent: current(),
            });
            return;
          }
          const localProxies = applyOperationalPrioritization(validateAndFilterEvents(proxyPayload?.data || []));
          logPairTypeDistribution(localProxies);
          setPlatform((previous) => ({ ...previous, health: healthPayload?.data || healthPayload,
            analytics: analyticsPayload?.data || buildLocalAnalytics(catalog, localProxies), screeningProxies: localProxies,
            smart: smartPayload?.data || buildLocalSmart(localProxies, catalog?.stats?.tracked_objects || 0),
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

    const explicitRefresh = (invocationId) => {
      console.info("[ORION screening diagnostic] explicit callback invoked", { invocationId });
      return load({ explicitScreeningRefresh: true, invocationId });
    };
    explicitScreeningRefreshRef.current = explicitRefresh;
    console.info("[ORION screening diagnostic] explicit refresh callback installed");
    const savedJobId = readActiveScreeningJobId();
    if (savedJobId) {
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
    if (!isPlaying) return undefined;
    const timer = window.setInterval(() => {
      setForecastHours((value) => (value >= 168 ? 0 : value + 3));
    }, 1400);
    return () => window.clearInterval(timer);
  }, [isPlaying]);

  const maneuverAssessmentEvent = referenceManeuverEvent ? null : resolveManeuverEvent(selectedEvent, platform.conjunctions);
  const maneuverScreeningJobId = platform.conjunctionStatus?.job_id || null;

  useEffect(() => {
    const requestGeneration = ++maneuverRequestGenerationRef.current;
    if (!maneuverAssessmentEvent?.id) {
      setManeuver(null);
      return undefined;
    }
    if (maneuverRequest?.eventId !== maneuverAssessmentEvent.id || maneuverRequest?.screeningJobId !== maneuverScreeningJobId) {
      setManeuver({ status: "not_run", event_id: maneuverAssessmentEvent.id, screening_job_id: maneuverScreeningJobId, reason: "Configure a bounded search and select Run Maneuver Search." });
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
          initialMassKg: maneuverRequest.initialMassKg,
          specificImpulseS: maneuverRequest.specificImpulseS,
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
  }, [maneuverAssessmentEvent, maneuverScreeningJobId, maneuverRequest]);

  const activeFrame = useMemo(() => {
    if (!forecast?.frames?.length) return null;
    return forecast.frames.reduce((closest, frame) => {
      return Math.abs(frame.hour - forecastHours) < Math.abs(closest.hour - forecastHours) ? frame : closest;
    }, forecast.frames[0]);
  }, [forecast, forecastHours]);

  const searchedSnapshot = useMemo(() => filterSnapshot(snapshot, globalSearch), [snapshot, globalSearch]);
  const searchSuggestions = useMemo(() => buildSearchSuggestions(snapshot), [snapshot]);
  const smartSnapshot = useMemo(() => buildSmartFilterView(snapshot, platform.screeningProxies), [snapshot, platform.screeningProxies]);
  const topEvent = eventSelection.notice ? null : selectedEvent || platform.conjunctions[0] || null;
  const maneuverEvent = referenceManeuverEvent ? null : resolveManeuverEvent(selectedEvent, platform.conjunctions);
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
    return explicitRefresh(invocationId);
  });

  function navigate(page) {
    setActivePage(page);
    setNotificationsOpen(false);
  }

  function selectEvent(event, page = "collision") {
    setEventSelection(resolvePhysicalEventSelection(event, platform.conjunctions));
    setActivePage(page);
  }

  function acceptUpdatedEvent(updatedEvent, responseJobId) {
    if (!updatedEvent?.id || updatedEvent.result_kind !== "physics_assessment") return;
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
    const jobId = platform.conjunctionStatus?.job_id;
    const payload = await importEventCdm({ screeningJobId: jobId, eventId, cdmXml, sourceLabel, assumeIndependentCovariances });
    acceptUpdatedEvent(payload.data, payload.job_id);
    return payload;
  }

  async function handleRetrieveEventCdmFromSpaceTrack({ eventId, assumeIndependentCovariances }) {
    const jobId = platform.conjunctionStatus?.job_id;
    const payload = await retrieveEventCdmFromSpaceTrack({ screeningJobId: jobId, eventId, assumeIndependentCovariances });
    acceptUpdatedEvent(payload.data, payload.job_id);
    return payload;
  }

  async function handleScenarioPc(input) {
    const jobId = platform.conjunctionStatus?.job_id;
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
      pushNotice(setNotices, `Restored archived job ${archivedJob.job_id} (${archivedJob.status}; ${recordCount} stored assessments). Current live results were preserved.`, "success");
    } catch (error) {
      pushNotice(setNotices, `Archive restore failed: ${error?.message || "the archived screening job could not be restored."}`, "warning");
    } finally {
      setArchiveRestoreBusy(false);
    }
  }

  return (
    <div className="platform-shell">
      <Sidebar activePage={activePage} navigate={navigate} health={platform.health} />
      <div className="platform-main">
        <TopBar
          search={globalSearch}
          setSearch={setGlobalSearch}
          refresh={startScreening}
          loading={loading}
          notificationsOpen={notificationsOpen}
          setNotificationsOpen={setNotificationsOpen}
          notices={notices}
          health={platform.health}
          snapshot={snapshot}
          suggestions={searchSuggestions}
        />
        <main className="content-main">
          {activePage === "home" ? (
            <HomePage snapshot={snapshot} platform={platform} highPriority={highPriority} navigate={navigate} selectEvent={selectEvent} />
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
              hoverObject={hoverObject}
              setHoverObject={setHoverObject}
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
            <SmartFilterPage snapshot={snapshot} smartSnapshot={smartSnapshot} platform={platform} selectEvent={selectEvent} navigate={navigate} />
          ) : null}
          {activePage === "collision" ? (
            <CollisionPage
              event={eventSelection.notice ? null : platform.conjunctions.find((item) => item.id === selectedEvent?.id) || null}
              selectionNotice={eventSelection.notice}
              events={platform.conjunctions}
              eventStatus={platform.conjunctionStatus}
              attemptStatus={platform.screeningAttempt}
              screeningStatus={platform.conjunctionStatus?.screening}
              sourceSummary={platform.conjunctionStatus?.source_summary || snapshot?.source_summary}
              sourceState={platform.conjunctionStatus?.source_state || snapshot?.source_state}
              screeningJobId={platform.conjunctionStatus?.job_id}
              csvScreeningJobId={screeningJobSelection.jobId}
              csvJobArchived={screeningJobSelection.isArchived}
              onImportCdm={handleImportEventCdm}
              onRetrieveSpaceTrackCdm={handleRetrieveEventCdmFromSpaceTrack}
              onScenarioPc={handleScenarioPc}
              onUseReferenceEvent={handleUseReferenceEvent}
              onStartScreening={startScreening}
              selectEvent={selectEvent}
              toggleWatchlist={toggleWatchlist}
              watchlist={watchlist}
              download={handleDownload}
              downloadTrajectoryCsv={handleTrajectoryCsvDownload}
              onShowInGlobe={handleShowInGlobe}
            />
          ) : null}
          {activePage === "maneuver" ? <ManeuverPage event={maneuverEvent} events={platform.conjunctions} screeningJobId={platform.conjunctionStatus?.job_id} screeningStatus={platform.conjunctionStatus} screeningAttempt={platform.screeningAttempt} onSelectEvent={(eventId) => { setReferenceManeuverEvent(null); selectEvent(selectManeuverEvent(platform.conjunctions, eventId), "maneuver"); }} onRunManeuver={(configuration) => setManeuverRequest({ ...configuration, eventId: maneuverEvent?.id, screeningJobId: platform.conjunctionStatus?.job_id || null })} maneuver={maneuver} download={handleDownload} referenceEvent={referenceManeuverEvent} onClearReferenceEvent={() => setReferenceManeuverEvent(null)} /> : null}
          {activePage === "analytics" ? <AnalyticsPage analytics={platform.analytics} events={platform.screeningProxies} snapshot={snapshot} /> : null}
          {activePage === "reports" ? <ReportsPage
            event={topEvent}
            screeningJobId={platform.conjunctionStatus?.job_id}
            csvScreeningJobId={screeningJobSelection.jobId}
            csvJobArchived={screeningJobSelection.isArchived}
            archivedJob={screeningJobSelection.archivedJob}
            restoreBusy={archiveRestoreBusy}
            onRestoreArchive={handleRestoreArchivedJob}
            onClearArchivedJob={() => setArchivedJobSelection(null)}
            download={handleDownload}
            downloadTrajectoryCsv={handleTrajectoryCsvDownload}
            smart={platform.smart}
          /> : null}
        </main>
      </div>
    </div>
  );
}

class SceneErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("[ORION visualization] scene render failed", {
      message: error?.message || "Unknown scene rendering error",
      componentStack: info?.componentStack || "unavailable",
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

function Sidebar({ activePage, navigate, health }) {
  return (
    <aside className="sidebar">
      <button className="brand-lockup" type="button" onClick={() => navigate("home")}>
        <span className="brand-mark"><Radar size={22} /></span>
        <span>
          <strong>ORION SSA</strong>
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
      <div className="sidebar-status">
        <div><Activity size={14} /><span>ML Model</span><strong>{health?.ai_status || "unavailable"}</strong></div>
        <div><DatabaseZap size={14} /><span>Dataset</span><strong>{health?.dataset_source || "unavailable"}</strong></div>
      </div>
    </aside>
  );
}

function TopBar({ search, setSearch, refresh, loading, notificationsOpen, setNotificationsOpen, notices, health, snapshot, suggestions }) {
  const [utc, setUtc] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setUtc(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <header className="topbar">
      <div className="global-search">
        <Search size={15} />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search satellite, debris, orbit shell, event..."
          list="global-search-suggestions"
        />
        <datalist id="global-search-suggestions">
          {(suggestions || []).map((item) => (
            <option key={item} value={item} />
          ))}
        </datalist>
      </div>
      <div className="topbar-meta">
        <span className="mono">{utc.toISOString().replace("T", " ").slice(0, 19)}Z</span>
        <span
          className={`system-chip source-chip source-chip-${snapshot?.source_state?.status || "unavailable"}`}
          title={sourceDetail(snapshot?.source_state)}
        >
          <DatabaseZap size={14} /> Source: {sourceLabel(snapshot?.source_state?.status)}
        </span>
        <span className="system-chip"><CheckCircle2 size={14} /> {datasetLabel(loading, snapshot?.source_state?.status)}</span>
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



function HomePage({ snapshot, platform, highPriority, navigate, selectEvent }) {
  const stats = snapshot?.stats || {};
  const briefing = platform?.smart?.briefing || "Analyzing orbital environment and preparing mission briefing.";
  const analytics = platform?.analytics || {};

  return (
    <div className="page-stack">    
      <section className="home-hero">
        <div>
          <p className="eyebrow">ORION SSA Research Prototype</p>
            <h1>Screening propagated trajectories for close approaches.</h1>
          <p>
            ORION preserves WGS-72 SGP4 propagation and keeps heuristic proxies separate from trajectory assessments. Foster 2D Pc is implemented for sourced covariance/HBR inputs; the current TLE feed does not provide those inputs.
          </p>
          <div className="hero-actions">
            <button className="secondary-action" type="button" onClick={() => navigate("visualization")}>Open Visualization</button>
            <button className="secondary-action" type="button" onClick={() => navigate("smart")}>Explore Filter</button>
          </div>
        </div>
        <div className="hero-briefing">
          <span><ShieldCheck size={18} /> Research Prototype Briefing</span>
          <p>{briefing}</p>
        </div>
      </section>

     
        <KpiGrid stats={stats} analytics={analytics} smart={platform?.smart} />
        <section className="split-grid">
          <Panel title="Heuristic-Only Proxy Review · Relative Bands" icon={AlertTriangle}>
            <EventList events={highPriority?.slice(0, 8) || []} onSelect={selectEvent} />
          </Panel>
          <Panel title="Heuristic Proxy Class Distribution" icon={Gauge}>
             <BarList data={analytics.risk_distribution || {}} total={analytics.total_screening_proxy_pairs || 1} />
              </Panel>
        </section>
      
    </div>
  );
}


function VisualizationPage(props) {
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
    hoverObject,
    setHoverObject,
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
      error: "The original Globe event handoff is unavailable.",
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
      return { event: null, error: error?.message || "The original Globe event selection is unavailable." };
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
        onHoverObject={setHoverObject}
      />
      </SceneErrorBoundary>
      <div className="hud-layer">
        {loading && !snapshot ? <div className="scene-data-notice" role="status">Loading catalog objects…</div> : null}
        {!loading && snapshot && !snapshot.objects?.length && snapshot.source_state?.status !== "unavailable" ? <div className="scene-data-notice" role="status">Catalog loaded with no objects to plot.</div> : null}
        {snapshot?.source_state?.status === "unavailable" && !snapshot?.objects?.length ? <div className="scene-data-notice" role="status">Catalog unavailable. The globe and controls are active, but no catalog objects are available to plot.</div> : null}
        {resolvedGlobeSelection.error ? <div className="scene-data-notice" role="status">Event report unavailable: {resolvedGlobeSelection.error}</div> : null}
        {hoverObject?.object ? <div className="globe-object-tooltip" role="status" style={{ left: Math.min(Math.max(12, hoverObject.x ?? 12), window.innerWidth - 300), top: Math.min(Math.max(12, hoverObject.y ?? 12), window.innerHeight - 180) }}>
          <strong>{catalogHoverDetails(hoverObject.object).name}</strong>
          <span>Catalog ID: {catalogHoverDetails(hoverObject.object).catalogId}</span>
          <span>Classification: {catalogHoverDetails(hoverObject.object).classification}</span>
          <span>Altitude: {catalogHoverDetails(hoverObject.object).altitude}</span>
          <span>Inclination: {catalogHoverDetails(hoverObject.object).inclination}</span>
          <span>Speed: {catalogHoverDetails(hoverObject.object).speed}</span>
        </div> : null}
        <motion.header className="top-command-bar" initial={{ y: -16, opacity: 0 }} animate={{ y: 0, opacity: 1 }}>
          <div className="brand-block">
            <div className="brand-mark"><Radar size={22} /></div>
            <div><p className="eyebrow">Orbital Environment</p><h1>Visualization</h1></div>
          </div>
          <div className="status-cluster">
            <StatusMetric icon={<Satellite size={16} />} label="Tracked" value={stats.tracked_objects || 0} />
            <StatusMetric icon={<ShieldAlert size={16} />} label="Heuristic Index" value={Number.isFinite(stats.global_heuristic_risk_score) ? stats.global_heuristic_risk_score.toFixed(3) : "Unavailable"} accent="risk" />
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

function ScreeningRunSummary({ eventStatus = {}, attemptStatus = null, screeningStatus = {}, sourceSummary = {}, sourceState = {}, eventCount = 0, returnedInvalidCount = 0, assessmentEvents = [] }) {
  const statusLine = screeningSummaryDisplay(eventStatus, attemptStatus);
  const summary = screeningStatus || {};
  const performance = eventStatus.performance || {};
  const recordCounts = screeningAssessmentCounts(summary, eventCount, returnedInvalidCount);
  const totalObjects = summary.valid_track_count == null
    ? sourceSummary.object_count ?? "Unavailable"
    : summary.valid_track_count + (summary.rejected_object_count || 0);
  const invalidCount = summary.invalid_assessment_count ?? "Unavailable";
  const reviewPriorityCounts = Object.fromEntries(["CRITICAL", "HIGH", "MEDIUM", "LOW", "REVIEW_REQUIRED", "UNCLASSIFIED"].map((category) => [
    category,
    assessmentEvents.filter((item) => item?.result_kind === "physics_assessment" && (item.review_priority?.category || "UNCLASSIFIED") === category).length,
  ]));
  const pcUnavailableCount = assessmentEvents.filter((item) => item?.result_kind === "physics_assessment" && item.collision_probability?.status !== "available").length;
  const duplicateTrajectoryCount = assessmentEvents.filter((item) => item?.physics_result?.reason_codes?.some((reason) => ["duplicate_tle_state_for_distinct_catalog_ids", "identical_propagation_parameters_for_distinct_catalog_ids"].includes(reason))).length;
  const capReached = summary.candidate_limit_reached == null ? "Unavailable" : summary.candidate_limit_reached ? "Yes · result is partial" : "No";
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
      <span>Indistinguishable duplicate trajectories excluded from rank <strong>{duplicateTrajectoryCount}</strong></span>
      <span>Returned physical Pc unavailable <strong>{pcUnavailableCount}</strong></span>
      <span>Returned ORION review-priority categories <strong>{Object.entries(reviewPriorityCounts).map(([category, count]) => `${category}: ${count}`).join(" · ")}</strong></span>
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
  const source = sourceState?.source || sourceSummary?.primary_source || "Source unavailable";
  const lastRun = eventStatus?.timestamp || eventStatus?.finished_at || attemptStatus?.finished_at || screeningStatus?.finished_at || "Not recorded";
  const pairCount = screeningStatus?.candidate_pair_count ?? eventStatus?.screening?.candidate_pair_count ?? "Unavailable";
  return <section className="panel collision-screening-controls" aria-label="Screening controls">
    <div className="collision-screening-heading">
      <div><span className={`screening-state-badge screening-state-${state}`}>Screening: {stateLabel}</span>
        <p className="muted">Source: {source} · {pairCount} pairs screened · {eventCount} candidate event{eventCount === 1 ? "" : "s"} · Last accepted run: {lastRun}</p>
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

export function CollisionPage({ event, events, eventStatus, attemptStatus, screeningStatus, sourceSummary, sourceState, screeningJobId, csvScreeningJobId, csvJobArchived = false, selectionNotice, onStartScreening = () => {}, onImportCdm = async () => {}, onRetrieveSpaceTrackCdm = async () => {}, onScenarioPc = async () => {}, onUseReferenceEvent = () => {}, selectEvent, toggleWatchlist, watchlist, download, downloadTrajectoryCsv, onShowInGlobe }) {
  const [pairFilter, setPairFilter] = useState("all");
  const [eventSearch, setEventSearch] = useState("");
  const [eventSort, setEventSort] = useState("tca_soonest");
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
  const [spaceTrackBusy, setSpaceTrackBusy] = useState(false);
  const [spaceTrackMessage, setSpaceTrackMessage] = useState("");
  useEffect(() => {
    setCdmXml("");
    setCdmSourceLabel("");
    setScenarioPrimary("");
    setScenarioSecondary("");
    setScenarioHbr("");
    setScenarioAssumptionsText("");
    setPcInputMessage("");
    setSpaceTrackMessage("");
  }, [event?.id]);
  const filteredEvents = filterCollisionEvents(events, {
    physicalOnly, pairFilter, statusFilter, priorityFilter, quantityFilter,
    minimumMiss, maximumMiss, fromTca, toTca,
  });
  const availableEvents = searchAndSortCollisionEvents(filteredEvents, eventSearch, eventSort);
  const anomalyRankById = rankOrbitalAnomalyEvents(events || []);
  async function retrieveSpaceTrackCdm() {
    if (!screeningJobId) {
      setSpaceTrackMessage("A completed screening job ID is required.");
      return;
    }
    if (event?.result_kind !== "physics_assessment" || event?.physics_result?.status !== "valid") {
      setSpaceTrackMessage("Space-Track lookup is available only for a valid selected physical event.");
      return;
    }
    setSpaceTrackBusy(true);
    setSpaceTrackMessage(`Searching Space-Track for ${event.primary.id} and ${event.secondary.id} at TCA ${event.physics_result.tca?.value || "unavailable"}...`);
    try {
      const result = await onRetrieveSpaceTrackCdm({
        eventId: event.id,
        assumeIndependentCovariances: cdmAssumeIndependent,
      });
      const pc = result.data?.collision_probability;
      const pcDetails = pc?.status === "available"
        ? ` Foster Pc calculated: ${pc.pc}.`
        : ` Foster Pc remains unavailable${pc?.reason_codes?.length ? ` (${pc.reason_codes.join(", ")})` : ""}.`;
      setSpaceTrackMessage(`CDM ${result.retrieval?.cdm_id || "retrieved"} validated against both selected catalog IDs and the event TCA.${pcDetails}`);
    } catch (error) {
      setSpaceTrackMessage(error?.message || "Space-Track CDM retrieval failed.");
    } finally {
      setSpaceTrackBusy(false);
    }
  }
  if (!event) {
    const emptyStateStatus = screeningStatusForEmptyResults(eventStatus, attemptStatus);
    const unavailable = emptyStateStatus?.api_status === "unavailable" || emptyStateStatus?.api_status === "error";
    const screeningNotStarted = emptyStateStatus?.result_status === "not_started";
    const completedEmpty = emptyStateStatus?.result_status === "valid_empty";
    const partial = emptyStateStatus?.result_status === "partial";
    const noUsableTracks = emptyStateStatus?.result_status === "unavailable";
    const screeningPending = ["pending", "queued", "running"].includes(emptyStateStatus?.result_status) || emptyStateStatus?.api_status === "pending";
    const screeningTimedOut = emptyStateStatus?.result_status === "timeout";
    const screeningCancelled = emptyStateStatus?.result_status === "cancelled";
    const noValidEventAvailable = (events || []).length > 0 && !(events || []).some((item) => item?.physics_result?.status === "valid");
    const emptyTitle = selectionNotice ? "No physical event selected"
      : noValidEventAvailable ? "No valid close approach is available"
        : screeningPending ? "Screening in progress"
          : screeningTimedOut ? "Screening is taking longer than expected"
            : screeningCancelled ? "Screening cancelled"
              : screeningNotStarted ? "Screening not started"
                : unavailable || noUsableTracks ? "Trajectory screening unavailable"
                  : partial ? "Trajectory screening incomplete"
                    : completedEmpty ? "No close approaches in screened horizon" : "No trajectory assessments";
    const selectionNoticeText = selectionNotice
      ? `${selectionNotice}${completedEmpty ? " The accepted run found no qualifying close approaches, and the previous event has been cleared." : noValidEventAvailable ? " The accepted run has no valid event; invalid assessments remain in diagnostics and are excluded from the risk-ranked list." : (events || []).length ? " Choose a returned event below." : ""}`
      : null;
    const emptyText = selectionNoticeText
      || (noValidEventAvailable ? "The accepted run has no valid interior-TCA event to select automatically. Invalid duplicate or unassessable trajectories are kept in screening diagnostics and receive no risk rank."
        : screeningPending ? "Stage 2A trajectory screening is running. Its status will update here when the backend reports progress or completion."
          : screeningTimedOut ? (emptyStateStatus?.reason || "Screening is still running; catalog data remains available and results will update when complete.")
            : screeningCancelled ? (emptyStateStatus?.reason || "The screening job was cancelled. Select Start Screening to try again.")
              : screeningNotStarted ? "Select Start Screening to run a physical close-approach screen on the current catalog."
                : unavailable || noUsableTracks ? (emptyStateStatus?.reason || "The latest screening attempt did not produce an available physical assessment.")
                  : partial ? "Some catalog objects or candidate calculations were incomplete. Review screening metadata before interpreting the result."
                    : completedEmpty ? "The completed run found no qualifying close approaches for this source, horizon, sampling interval and distance threshold. No event was synthesized."
                      : "No physical close-approach result is available.");

    return <div className="page-stack">
      <PageHeader eyebrow="Collision Analysis" title="Trajectory Screening" text="Run a physical close-approach screen using the current orbital catalog and configured screening horizon." />
      <CollisionAnalysisSummary events={events || []} displayedEvents={availableEvents} screeningStatus={screeningStatus} />
      <CollisionScreeningControls eventStatus={eventStatus} attemptStatus={attemptStatus} screeningStatus={screeningStatus} sourceSummary={sourceSummary} sourceState={sourceState} eventCount={(events || []).length} onStartScreening={onStartScreening} />
      <details className="collision-tools-details"><summary>Collision probability tools · Upload Conjunction Data</summary><CdmReferenceAssessment onUseReferenceEvent={onUseReferenceEvent} /></details>
      <details className="advanced-screening-details"><summary>Advanced screening diagnostics</summary><ScreeningRunSummary eventStatus={eventStatus} attemptStatus={attemptStatus} screeningStatus={screeningStatus} sourceSummary={sourceSummary} sourceState={sourceState} eventCount={(events || []).length} returnedInvalidCount={(events || []).filter((item) => item.physics_result?.status === "invalid").length} assessmentEvents={events || []} /></details>
      <EmptyState
        title={emptyTitle}
        text={emptyText}
      />
      {availableEvents.length ? <Panel title="Screened Events" icon={Radar}>
        <p className="muted">Showing {availableEvents.length} event rows from {(events || []).length} returned screening assessments. Invalid assessments remain visible for diagnosis and receive no priority rank.</p>
        <CollisionPriorityTable events={getCollisionEventsForDisplay(availableEvents)} anomalyRanks={anomalyRankById} screeningJobId={screeningJobId} onSelect={(item) => selectEvent(item, "collision")} onShowInGlobe={onShowInGlobe} onAssessManeuver={(item) => selectEvent(item, "maneuver")} />
      </Panel> : null}
    </div>;
  }

  // Resolve canonical identities for display
  const pIdentity = buildCanonicalIdentity(event.primary);
  const sIdentity = buildCanonicalIdentity(event.secondary);
  const pairType = event.pair_type || getPairType(event.primary, event.secondary);

  // Build display strings
  const pDisplay = `${pIdentity.name} · ID: ${pIdentity.id}`;
  const sDisplay = `${sIdentity.name} · ID: ${sIdentity.id}`;
  const pTypeDisplay = pIdentity.displayType;
  const sTypeDisplay = sIdentity.displayType;
  const physical = event.result_kind === "physics_assessment";
  const physics = event.physics_result || {};
  const tcaValue = formatScientificField(physics.tca, 3);
  const missValue = formatScientificField(physics.miss_distance, 3);
  const relativeSpeed = formatScientificField(physics.relative_speed_at_tca, 4);
  const pcResult = event.collision_probability || null;
  const pcClassification = pcResult?.probability_classification;
  const evidencePriority = collisionEventPriority(event);
  const evidenceRank = rankCollisionEvents(events).findIndex((item) => item.id === event.id) + 1;
  const mlResult = event.ml_result || {};
  const comparisonResult = event.comparison_result || {};
  const provenance = event.provenance || {};
  const computedPcMatches = physical && isUsablePc(pcResult) && pcResult.event_id === event.id;
  const sourcePc = pcResult?.source_reported_event_id === event.id && isValidProbability(pcResult?.source_reported_pc) ? pcResult.source_reported_pc : null;
  const researchPcDisplay = researchPcPresentation(event.automatic_research_pc_assessment);
  const aiPriority = event.ai_risk_assessment;
  const aiScoreDisplay = Number.isFinite(aiPriority?.score) ? `${(aiPriority.score * 100).toFixed(1)} / 100` : "Unavailable";

  const watched = watchlist.has(event.primary.id) || watchlist.has(event.secondary.id);
  const eventReportPath = physical
    ? screeningJobId ? selectedEventReportPath(screeningJobId, event.id) : null
    : `/api/reports/${encodeURIComponent(event.id)}.pdf`;
  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Collision Analysis"
        title={`${pDisplay} vs ${sDisplay}`}
        text={physical
          ? `${pTypeDisplay} vs ${sTypeDisplay} — ${pairType}. Selected conjunction details and assessment evidence.`
          : `${pTypeDisplay} vs ${sTypeDisplay} — ${pairType}. This record is a heuristic screening proxy only; it is not a trajectory-derived conjunction assessment.`}
        action={<button className="primary-action" type="button" disabled={!eventReportPath} title={physical && !screeningJobId ? "The selected event's completed screening job is unavailable." : undefined} onClick={() => eventReportPath && download(eventReportPath, `${event.id}-report.pdf`)}>Download Event PDF</button>}
      />
      <CollisionAnalysisSummary events={events || []} displayedEvents={availableEvents} screeningStatus={screeningStatus} />
      <CollisionScreeningControls eventStatus={eventStatus} attemptStatus={attemptStatus} screeningStatus={screeningStatus} sourceSummary={sourceSummary} sourceState={sourceState} eventCount={(events || []).length} onStartScreening={onStartScreening} />
      <details className="collision-tools-details"><summary>Collision probability tools · Upload Conjunction Data</summary><CdmReferenceAssessment onUseReferenceEvent={onUseReferenceEvent} /></details>
      <div className="collision-maneuver-entry"><span>Continue to maneuver assessment using this selected event's identity and states.</span><button className="secondary-action" type="button" onClick={() => selectEvent(event, "maneuver")}>Open Maneuver Assessment</button></div>
      <details className="advanced-screening-details"><summary>Advanced screening diagnostics</summary><ScreeningRunSummary eventStatus={eventStatus} attemptStatus={attemptStatus} screeningStatus={screeningStatus} sourceSummary={sourceSummary} sourceState={sourceState} eventCount={(events || []).length} returnedInvalidCount={(events || []).filter((item) => item.physics_result?.status === "invalid").length} assessmentEvents={events || []} /></details>
      <section className="selected-event-summary" aria-label="Selected event summary">
         <div className="selected-event-heading"><div><span className="reference-eyebrow">Selected conjunction</span><h2>{pDisplay} vs {sDisplay}</h2><p>{physical ? `Priority #${aiPriority?.final_priority_rank || evidenceRank || "?"} · score ${aiScoreDisplay} · ${aiPriority?.category || "classification unavailable"} · ${aiPriority?.ranking_explanation || evidencePriority.basis}` : `Heuristic review only · rank ${event.risk_level || "unavailable"}`}</p></div><button className="secondary-action" type="button" onClick={() => selectEvent(event, "maneuver")}>Open Maneuver Assessment</button></div>
        <div className="selected-event-metrics">
          <span>TCA<strong>{physical ? tcaValue : "Unavailable · proxy only"}</strong></span>
          <span>Miss distance<strong>{physical ? missValue : "Unavailable · proxy only"}</strong></span>
           <span>Relative speed<strong>{physical ? `${relativeSpeed} km/s` : "Unavailable · proxy only"}</strong></span>
          <span>Event-specific Foster Pc<strong>{computedPcMatches ? `${formatProbabilityScientific(pcResult.pc)} · ${formatProbabilityPercentage(pcResult.pc)}` : operationalFosterStatus(event, false)}</strong></span>
          {event.automatic_research_pc_assessment?.status === "prior_based_research_estimate" ? <span>ESA-prior Pc · assumption-based research estimate<strong>{`${researchPcDisplay.value} · ${researchPcDisplay.percentage} (unvalidated research prior)`}</strong></span> : null}
           {event.automatic_research_pc_assessment?.status === "prior_based_research_estimate" ? <span>Research Pc sensitivity scenarios<strong>{researchPcDisplay.sensitivity}</strong></span> : null}
           <span>Source-reported Pc<strong>{sourcePc != null ? `${formatProbabilityScientific(sourcePc)} · ${formatProbabilityPercentage(sourcePc)} · ${pcResult.source_reported_pc_method || "method undeclared"}` : "Not provided by this event's source"}</strong></span>
           <span>AI queue index and category<strong>{physical ? `${aiScoreDisplay} · ${aiPriority?.category || "Unavailable"} · ${aiPriority?.prediction_method || "method unavailable"}; not Pc` : "Unavailable · proxy-only record"}</strong></span>
           <span>Final ranking basis<strong>{physical ? aiPriority?.ranking_explanation || evidencePriority.basis : "Catalog heuristic only; not a probability"}</strong></span>
        </div>
         {event.automatic_research_pc_assessment?.status === "prior_based_research_estimate" ? <details className="selected-research-assumptions"><summary>Research estimate assumptions and provenance</summary><p>{(event.automatic_research_pc_assessment.assumptions || []).join(" ")}</p><p>{event.automatic_research_pc_assessment.provenance?.source || "ESA population prior"} · model {event.automatic_research_pc_assessment.provenance?.prior_model_version || "unknown"}.</p></details> : null}
      </section>
      {physical && physics.status === "valid" ? <Panel title="Event-specific Space-Track CDM" icon={DatabaseZap}>
        <div className="readout-list">
          <span>Selected event<strong>{event.primary.id} ↔ {event.secondary.id} · TCA {physics.tca?.value || "unavailable"}</strong></span>
          <span>Lookup rule<strong>Both catalog IDs and event TCA must validate before the CDM is attached to this event.</strong></span>
          <label className="filter-checkbox"><input type="checkbox" checked={cdmAssumeIndependent} onChange={(e) => setCdmAssumeIndependent(e.target.checked)} /> Explicitly assume independent object covariance for Foster Pc</label>
          <button className="secondary-action" type="button" onClick={retrieveSpaceTrackCdm} disabled={spaceTrackBusy || !screeningJobId}>
            {spaceTrackBusy ? "Retrieving Space-Track CDM..." : "Retrieve Space-Track CDM"}
          </button>
          {spaceTrackMessage ? <p className="muted" role="status" aria-live="polite">{spaceTrackMessage}</p> : null}
        </div>
      </Panel> : null}
      <section className="collision-layout">
        <Panel title="Screened Events" icon={Radar}>
          <details className="collision-filter-details"><summary>Search and filter events</summary><div className="collision-filters">
            <label>Search events<input type="search" value={eventSearch} onChange={(e) => setEventSearch(e.target.value)} placeholder="Object name, catalog ID, or event ID" /></label>
            <label>Pair type<select value={pairFilter} onChange={(e) => setPairFilter(e.target.value)}>{COLLISION_PAIR_FILTERS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
            <label>Sort events<select value={eventSort} onChange={(e) => setEventSort(e.target.value)}><option value="evidence_priority">Evidence priority, highest first</option><option value="tca_soonest">TCA, soonest first</option><option value="miss_nearest">Miss distance, nearest first</option></select></label>
            <label>Screening status<select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}><option value="all">All statuses</option><option value="valid">Valid interior TCA</option><option value="boundary">Horizon-edge minimum</option><option value="invalid">Invalid</option><option value="unavailable">Unavailable</option></select></label>
            <label>ORION review priority<select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}><option value="all">All review states</option><option value="CRITICAL">CRITICAL</option><option value="HIGH">HIGH</option><option value="MEDIUM">MEDIUM</option><option value="LOW">LOW</option><option value="REVIEW_REQUIRED">REVIEW_REQUIRED</option><option value="UNCLASSIFIED">UNCLASSIFIED</option></select></label>
            <label>Available quantities<select value={quantityFilter} onChange={(e) => setQuantityFilter(e.target.value)}><option value="all">All available / unavailable</option><option value="geometry">TCA and miss distance available</option><option value="relative_velocity">Relative velocity available</option><option value="pc">Pc available (covariance and HBR required)</option></select></label>
            <label>Min miss distance (km)<input type="number" min="0" value={minimumMiss} onChange={(e) => setMinimumMiss(e.target.value)} /></label>
            <label>Max miss distance (km)<input type="number" min="0" value={maximumMiss} onChange={(e) => setMaximumMiss(e.target.value)} /></label>
            <label>From TCA date (UTC)<input type="date" value={fromTca} onChange={(e) => setFromTca(e.target.value)} /></label>
            <label>To TCA date (UTC)<input type="date" value={toTca} onChange={(e) => setToTca(e.target.value)} /></label>
            <label className="filter-checkbox"><input type="checkbox" checked={physicalOnly} onChange={(e) => setPhysicalOnly(e.target.checked)} /> Physical assessments only</label>
          </div></details>
          <p className="muted">Showing {availableEvents.length} event rows from {(events || []).length} returned screening assessments. “All statuses” includes invalid assessments for review; invalid physics assessments receive no priority rank. Search covers event and catalog identities, names, object types, and pair type.</p>
          {availableEvents.length ? <CollisionPriorityTable events={getCollisionEventsForDisplay(availableEvents)} anomalyRanks={anomalyRankById} screeningJobId={screeningJobId} onSelect={(item) => selectEvent(item, "collision")} onShowInGlobe={onShowInGlobe} onAssessManeuver={(item) => selectEvent(item, "maneuver")} /> : <p className="muted">No events match these filters.</p>}
        </Panel>
        <details className="advanced-selected-details"><summary>Advanced selected-event details and diagnostics</summary><div className="detail-stack">
          <div className="event-hero">
            {physical ? <RiskBadge risk={physics.status || "unavailable"} label={physics.status === "boundary" ? "Horizon-edge minimum" : physics.status || "unavailable"} /> : <RiskBadge risk={event.risk_level} label={`Relative rank: ${event.risk_level}`} />}
            <strong>{physical ? `Physics status: ${physics.status || "unavailable"}` : `Heuristic priority ${event.priority_score}/100`}</strong>
            <span>{physical
              ? `Threshold ${physics.screening_threshold_km ?? "unavailable"} km · ${physics.screening_horizon_start || "unavailable"} to ${physics.screening_horizon_end || "unavailable"}`
              : event.suggested_action}</span>
          </div>
          <Panel title={physical ? "Selected Conjunction: Key Results" : "Screening Proxy Details"} icon={Radar}>
            {physical ? <CollisionProbabilityCard result={pcResult} sourceReportedPc={pcResult?.source_reported_pc} sourceReportedMethod={pcResult?.source_reported_pc_method} /> : <CollisionProbabilityCard result={null} />}
            <MetricRow
              metrics={[
              [physical ? "Assessment Status" : "Heuristic Risk Index", physical ? (physics.status || "Unavailable") : Number(event.risk_score).toFixed(3)],
              ["TCA", physical ? tcaValue : "Unavailable — proxy only"],
              ["Miss Distance", physical ? missValue : "Unavailable — proxy only"],
              ["Relative Speed", physical ? relativeSpeed : "Unavailable — proxy only"],
              ["Relative Velocity (TEME)", physical ? formatScientificField(physics.relative_velocity_at_tca, 6) : "Unavailable — proxy only"],
              ["Evidence Priority", physical ? `#${evidenceRank || "?"} - ${evidencePriority.label}` : `Heuristic - ${event.risk_level || "unavailable"}`],
              ["Foster Pc reference category", physical ? (pcClassification?.category || "Unavailable · no event-specific Pc") : "Unavailable · proxy only"],
              ["Geometry review category", physical ? (event.review_priority?.category || "UNCLASSIFIED") : `Proxy heuristic · ${event.risk_level || "unavailable"}`],
              ["AI prioritization (not Pc)", physical && event.ai_risk_assessment ? `${(event.ai_risk_assessment.score * 100).toFixed(1)} / 100 · ${event.ai_risk_assessment.category} · ${event.ai_risk_assessment.prediction_method}` : "Unavailable · valid geometry inputs required"],
              ["Final priority rank", physical ? `#${event.ai_risk_assessment?.final_priority_rank || "?"}` : "Proxy heuristic only"],
              ]}
            />
          </Panel>
          <Panel title="Why this result?" icon={Target}>
            <div className="readout-list collision-why-result">
              <span>Pc status<strong>{physical && isUsablePc(pcResult) ? `${pcResult.method || "Foster 2D"} · ${pcResult.status}` : physical && pcResult?.status === "available" ? `${pcDisplayStatus(pcResult)} · no valid numeric probability was returned` : physical ? `Unavailable · ${(pcResult?.reason_codes || []).join(", ") || (pcResult?.reason || "Event-matched covariance and HBR are unavailable.")}` : "Unavailable · heuristic proxy has no encounter covariance or HBR"}</strong></span>
              <span>Priority and basis<strong>{physical ? `Rank #${evidenceRank || "?"} - ${evidencePriority.label}. ${evidencePriority.basis} ${pcClassification?.status === "classified" ? `${pcClassification.policy_name || "Pc reference bands"}: ${pcClassification.explanation}` : event.review_priority?.explanation || "Geometry-based review priority only; no calibrated risk classification is available."}` : "Catalog heuristic ranking only; not a probability or physical conjunction classification."}</strong></span>
              <span>AI classification<strong>{physical && event.ai_risk_assessment ? `${event.ai_risk_assessment.category} · deterministic live-geometry queue index ${(event.ai_risk_assessment.score * 100).toFixed(1)} / 100; not a trained prediction or Pc. ${event.ai_risk_assessment.explanation}` : physical ? "Unavailable: required valid geometry features are missing." : "Unavailable: a screening proxy has no event-level physical inference."}</strong></span>
            </div>
          </Panel>
          <details className="advanced-result-details"><summary>Advanced details: Pc inputs, covariance, HBR, AI and screening diagnostics</summary>
          {physical ? <Panel title="ORION Review Priority" icon={Cpu}>
            <div className="readout-list">
              <span>Category <strong>{event.review_priority?.category || "UNCLASSIFIED"}</strong></span>
              <span>Policy version <strong>{event.review_priority?.policy_version || "unavailable"}</strong></span>
              <span>Explanation <strong>{event.review_priority?.explanation || "Review priority is unclassified because required evidence is unavailable."}</strong></span>
              {event.review_priority?.reason_codes?.map((code) => <span key={code}>Reason <strong>{code}</strong></span>)}
              {event.review_priority?.limitations?.map((limitation, index) => <span key={index}>Limitation <strong>{limitation}</strong></span>)}
            </div>
          </Panel> : null}
          {physical && event.ai_risk_assessment ? <Panel title="AI Risk Prioritization · Deterministic Fallback" icon={Cpu}>
            <div className="readout-list">
              <span>Score and category<strong>{(event.ai_risk_assessment.score * 100).toFixed(1)} / 100 · {event.ai_risk_assessment.category} (queue index; not Pc)</strong></span>
              <span>Model identity<strong>{event.ai_risk_assessment.model_name} v{event.ai_risk_assessment.model_version}; {event.ai_risk_assessment.prediction_method}</strong></span>
              <span>Final priority<strong>#{event.ai_risk_assessment.final_priority_rank || "unranked"} · {event.ai_risk_assessment.ranking_explanation || "Ranking awaits screening-set aggregation."}</strong></span>
              <span>Ranking evidence<strong>Geometry #{event.ai_risk_assessment.geometry_rank || "—"}; Foster Pc #{event.ai_risk_assessment.foster_pc_rank || "—"}; ESA-prior Pc #{event.ai_risk_assessment.research_pc_rank || "—"}. {event.ai_risk_assessment.explanation}</strong></span>
              <span>Quality and limitation<strong>{(event.ai_risk_assessment.model_quality?.limitations || []).join(" ")}</strong></span>
              <span>ESA historical model<strong>{mlResult?.model_name || "ESA log10-risk regressor"} is withheld for live inference: feature semantics remain unverified. Historical target is final ESA event log10 risk, not collision probability.</strong></span>
            </div>
          </Panel> : null}
          {physical && physics.status === "valid" ? <Panel title="Covariance, HBR and Pc Inputs" icon={Target}>
            <CollisionPcSummary sourceResult={pcResult} scenarioResult={event.scenario_collision_probability} />
            <p className="muted">Geometry above comes from the Stage 2A trajectory screen. A CDM can add a separate Foster Pc only when its object IDs and exact UTC TCA match this event and it supplies validated, same-epoch covariance and HBR. CelesTrak GP/OMM contains no covariance or HBR. Space-Track retrieval requires configured account credentials and CDM permissions.</p>
            <div className="split-grid">
              <form className="readout-list" onSubmit={async (submitEvent) => {
                submitEvent.preventDefault();
                if (!screeningJobId) { setPcInputMessage("A completed screening job ID is required."); return; }
                setPcInputBusy(true); setPcInputMessage("Validating CDM against the selected event…");
                try {
                  const result = await onImportCdm({ eventId: event.id, cdmXml, sourceLabel: cdmSourceLabel, assumeIndependentCovariances: cdmAssumeIndependent });
                  setPcInputMessage(`Imported CDM assessment: ${result.data?.collision_probability?.status || "unavailable"}${result.data?.collision_probability?.reason_codes?.length ? ` · ${result.data.collision_probability.reason_codes.join(", ")}` : ""}. Source authentication was not performed.`);
                } catch (error) { setPcInputMessage(error?.message || "CDM input was rejected."); }
                finally { setPcInputBusy(false); }
              }}>
                <strong>Upload Conjunction Data</strong>
                <label>CDM source label (user-declared)<input required maxLength={200} value={cdmSourceLabel} onChange={(e) => setCdmSourceLabel(e.target.value)} /></label>
                <label>CDM file<input required type="file" accept=".xml,.cdm,.kvn,.txt,.json,application/xml,text/xml,application/json,text/plain" onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) { setCdmXml(""); return; }
                  if (file.size > 1_000_000) { setCdmXml(""); setPcInputMessage("CDM input exceeds the 1 MB limit."); return; }
                  setCdmXml(await file.text());
                }} /></label>
                <small>The uploaded file must match both object IDs, exact TCA, and the event frame shown here ({physics.state_information?.source_frame || "unavailable"}). XML/KVN covariance uses its declared RTN convention. JSON is accepted when its supported inertial frame matches this event; unsupported terrestrial frames are rejected because no validated Earth-orientation transform is applied.</small>
                <label className="filter-checkbox"><input type="checkbox" checked={cdmAssumeIndependent} onChange={(e) => setCdmAssumeIndependent(e.target.checked)} /> Explicitly assume independent object covariance</label>
                <button className="secondary-action" type="submit" disabled={pcInputBusy || !screeningJobId || !cdmXml || !cdmSourceLabel.trim()}>{pcInputBusy ? "Validating..." : "Match CDM to event and calculate imported Pc"}</button>
              </form>
              <form className="readout-list" onSubmit={async (submitEvent) => {
                submitEvent.preventDefault();
                if (!screeningJobId) { setPcInputMessage("A completed screening job ID is required."); return; }
                let primaryMatrix; let secondaryMatrix; let hbrValue;
                try {
                  primaryMatrix = JSON.parse(scenarioPrimary);
                  secondaryMatrix = JSON.parse(scenarioSecondary);
                  hbrValue = Number(scenarioHbr);
                  if (!Number.isFinite(hbrValue) || hbrValue <= 0) throw new Error("Combined HBR must be a positive number in km.");
                } catch (error) { setPcInputMessage(error?.message || "Enter both covariance matrices as valid JSON."); return; }
                setPcInputBusy(true); setPcInputMessage("Calculating a separate assumed research scenario…");
                try {
                  const result = await onScenarioPc({ eventId: event.id, covariancePrimaryKm2: primaryMatrix, covarianceSecondaryKm2: secondaryMatrix, hbrKm: hbrValue, assumeIndependentCovariances: scenarioAssumeIndependent, assumptions: scenarioAssumptionsText });
                  const scenario = result.data?.scenario_collision_probability;
                  setPcInputMessage(`Research scenario status: ${scenario?.status || "unavailable"}${scenario?.reason_codes?.length ? ` · ${scenario.reason_codes.join(", ")}` : ""}. This result remains separate from imported CDM Pc.`);
                } catch (error) { setPcInputMessage(error?.message || "Scenario inputs were rejected."); }
                finally { setPcInputBusy(false); }
              }}>
                <strong>Explicit assumed scenario (not observed data)</strong>
                <small>Enter two positive-definite 3×3 position covariance matrices in km². They are bound to {physics.state_information?.source_frame || "the event frame unavailable"} at {physics.tca?.value || "the event TCA unavailable"}.</small>
                <label>Primary object covariance (JSON km²)<textarea required value={scenarioPrimary} onChange={(e) => setScenarioPrimary(e.target.value)} placeholder="[[...,...,...],[...,...,...],[...,...,...]]" rows={3} /></label>
                <label>Secondary object covariance (JSON km²)<textarea required value={scenarioSecondary} onChange={(e) => setScenarioSecondary(e.target.value)} placeholder="[[...,...,...],[...,...,...],[...,...,...]]" rows={3} /></label>
                <label>Assumed combined hard-body radius (km)<input required type="number" min="0" step="any" value={scenarioHbr} onChange={(e) => setScenarioHbr(e.target.value)} /></label>
                <label>Scenario assumptions and basis<textarea required minLength={10} maxLength={1000} value={scenarioAssumptionsText} onChange={(e) => setScenarioAssumptionsText(e.target.value)} rows={2} /></label>
                <label className="filter-checkbox"><input type="checkbox" checked={scenarioAssumeIndependent} onChange={(e) => setScenarioAssumeIndependent(e.target.checked)} /> Explicitly assume independent object covariance</label>
                <button className="secondary-action" type="submit" disabled={pcInputBusy || !screeningJobId}>{pcInputBusy ? "Calculating…" : "Calculate separate scenario Pc"}</button>
              </form>
            </div>
            {event.scenario_inputs ? <details className="muted"><summary>Reproducibility inputs and sensitivity</summary><p>Primary covariance (km², {event.scenario_inputs.frame}, TCA {event.scenario_inputs.tca_utc}): <code>{JSON.stringify(event.scenario_inputs.covariance_primary_km2)}</code></p><p>Secondary covariance (km²): <code>{JSON.stringify(event.scenario_inputs.covariance_secondary_km2)}</code></p><p>Combined HBR: {event.scenario_inputs.hbr_km} km. Independent covariances explicitly assumed: {event.scenario_inputs.assume_independent_covariances ? "yes" : "no"}. Declared basis: {event.scenario_inputs.declared_assumptions}</p><p>Sensitivity: not calculated because no uncertainty ranges were supplied for covariance or HBR. This scenario remains assumption-dependent and is not operationally calibrated.</p></details> : null}
            {pcInputMessage ? <p className="muted" role="status">{pcInputMessage}</p> : null}
            {event.scenario_collision_probability ? <p className="muted">Stored scenario result: {pcDisplayStatus(event.scenario_collision_probability)}{isUsablePc(event.scenario_collision_probability) ? ` · ${formatCollisionProbability(event.scenario_collision_probability.pc)}` : ` · ${(event.scenario_collision_probability.reason_codes || []).join(", ") || (event.scenario_collision_probability.status === "available" ? "INVALID_PC_VALUE" : "no numeric Pc produced")}`}. Assumptions: {(event.scenario_assumptions || []).join(" ")}</p> : null}
          </Panel> : physical ? <>
            <Panel title="Physical Pc Status" icon={Target}>
              <CollisionPcSummary sourceResult={pcResult} scenarioResult={event.scenario_collision_probability} />
            </Panel>
            <p className="muted">Covariance/HBR input is restricted to a valid interior-TCA physical event. Boundary and invalid events retain their explicit Pc status and reason; proxy results cannot receive a Pc assessment.</p>
          </> : null}
          <section className="split-grid">
            <Panel title="Physics Assessment" icon={Target}>
              <details>
                <summary>Detailed physical measurements, covariance and Pc provenance</summary>
                <PhysicsAvailability physics={physics} pcResult={pcResult} proxyOnly={!physical} />
              </details>
            </Panel>
          <Panel title="ESA Historical Model (not live Pc)" icon={Cpu}>
              <EventRiskEstimate eventId={event.id} physical={physical} mlResult={mlResult} comparisonResult={comparisonResult} explainReason={explainMlReason} />
            </Panel>
            <Panel title="AI Orbital Anomaly" icon={Radar}>
              <EventAnomalyPanel physical={physical} eventId={event.id} result={event.anomaly_result} />
            </Panel>
          </section>
          <section className="split-grid">
            <Panel title="Screening Run Status" icon={Radar}>
              <div className="readout-list">
                <span>Completion <strong>{eventStatus?.completion_status || (eventStatus?.result_status === "partial" ? "partial" : eventStatus?.result_status?.startsWith("valid_") ? "complete" : eventStatus?.result_status || "unavailable")}</strong></span>
                <span>Summary <strong>{screeningStatus?.reason_code || eventStatus?.reason || "See run summary and limits."}</strong></span>
                <span>Candidate pairs / minima / refinements <strong>{screeningStatus ? `${screeningStatus.candidate_pair_count ?? "?"} / ${screeningStatus.candidate_local_minimum_count ?? "?"} / ${screeningStatus.refinement_count ?? "?"}` : "Unavailable"}</strong></span>
                <span>Candidate cap reached <strong>{screeningStatus?.candidate_limit_reached == null ? "Unavailable" : screeningStatus.candidate_limit_reached ? "Yes · partial screen" : "No"}</strong></span>
                <span>Catalog provenance <strong>{provenance.source || provenance.source_type || "Unavailable"} · {provenance.input_hash || "input hash unavailable"}</strong></span>
              </div>
            </Panel>
            <Panel title={physical ? "Interpretation" : "Heuristic Rationale"} icon={Cpu}>
              {physical
                ? <p className="muted">TCA and miss distance come from two SGP4/SDP4 WGS-72 trajectories in TEME. The ESA model target is historical log10 event-risk; it is not Pc or a calibrated probability. Physical Pc remains unavailable unless valid covariance and HBR inputs are supplied. The model artifact is retained, but its output is withheld because equivalence between historical ESA CDM features and live TLE-derived features is unverified. On the mission-held-out test set it had MAE 6.8935 log10 units, Spearman 0.4424, and detected 0/145 high-risk labels at the fixed threshold.</p>
                : <><p className="briefing-text">{event.suggested_action}</p><p className="muted">The score ranks catalog-level candidate pairs. It is not a probability, confidence estimate, or validated conjunction result.</p></>}
            </Panel>
          </section>
          </details>
          <section className="split-grid">
            <Panel title="Object Information" icon={Satellite}>
              <ObjectPair event={event} screeningJobId={screeningJobId} toggleWatchlist={toggleWatchlist} watched={watched} onShowInGlobe={onShowInGlobe} />
            </Panel>
            <Panel title="Review Workflow" icon={ShieldAlert}>
              <div className="action-plan">
                <span>{event.suggested_action}</span>
                <button className="primary-action" type="button" onClick={() => selectEvent(event, "maneuver")}>Open Maneuver Availability</button>
                <button
                  className="secondary-action"
                  type="button"
                  onClick={() => physical
                    ? downloadTrajectoryCsv(csvScreeningJobId)
                    : download("/api/reports/screening-proxies.csv", "screening-proxies.csv")}
                >
                  Download {physical ? `${csvJobArchived ? "Archived " : ""}Trajectory Assessment` : "Heuristic Proxy"} CSV
                </button>
              </div>
            </Panel>
          </section>
        </div></details>
      </section>
    </div>
  );
}

export function ManeuverPage({ event, events = [], screeningJobId, screeningStatus, screeningAttempt, onSelectEvent = () => {}, onRunManeuver = () => {}, maneuver, download, referenceEvent = null, onClearReferenceEvent = () => {} }) {
  const [leadSeconds, setLeadSeconds] = useState("300");
  const [maxDeltaVMs, setMaxDeltaVMs] = useState("0.1");
  const [initialMassKg, setInitialMassKg] = useState("");
  const [specificImpulseS, setSpecificImpulseS] = useState("");
  const [configurationError, setConfigurationError] = useState("");
  const pageState = maneuverPageState(event, events, screeningStatus);
  const selectableEvents = pageState.selectable_events;
  const selectedEvent = pageState.selected_event;
  const m = selectedEvent
    ? maneuverAssessmentForSelection(maneuver, screeningJobId, selectedEvent) || {
      status: "not_run",
      reason: "Configure the bounded search and select Run Maneuver Search.",
    }
    : {};
  const physicsCandidates = m.physics_candidates?.candidates || (m.candidates || []).slice(1);
  const bestCandidate = m.best_candidate || null;
  const baseline = m.zero_burn_baseline || {};
  const maneuverBusy = m.status === "running";
  function submitManeuverSearch(submitEvent) {
    submitEvent.preventDefault();
    if ((initialMassKg === "") !== (specificImpulseS === "")) {
      setConfigurationError("Enter both initial mass and specific impulse, or leave both empty.");
      return;
    }
    setConfigurationError("");
    onRunManeuver({
      leadSeconds: Number(leadSeconds),
      maxDeltaVMs: Number(maxDeltaVMs),
      initialMassKg: initialMassKg === "" ? null : Number(initialMassKg),
      specificImpulseS: specificImpulseS === "" ? null : Number(specificImpulseS),
    });
  }
  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Bounded two-body research simulation"
        title="Maneuver Assessment"
        text="Compare a bounded set of impulsive RTN burns against a zero-burn two-body baseline. This simplified research simulation is not an operational maneuver recommendation."
        action={selectedEvent?.physics_result?.status === "valid" && screeningJobId ? <button className="primary-action" type="button" onClick={() => download(`/api/conjunction-jobs/${encodeURIComponent(screeningJobId)}/events/${encodeURIComponent(selectedEvent.id)}/assessment.pdf`, `${selectedEvent.id}-maneuver-assessment.pdf`)}>Download Assessment Report</button> : <button className="primary-action" type="button" disabled title="A validated physical event and its screening job are required.">Download Assessment Report</button>}
      />
      <ManeuverScreeningContext screeningJobId={screeningJobId} screeningStatus={screeningStatus} screeningAttempt={screeningAttempt} />
      {referenceEvent ? <ReferenceManeuverAssessment referenceEvent={referenceEvent} download={download} onClear={onClearReferenceEvent} /> : null}
      <Panel title="Accepted Stage 2A Event" icon={Rocket}>
        {selectableEvents.length ? <label className="maneuver-event-select">
          <span>Select a trajectory-derived event</span>
          <select value={selectedEvent?.id || ""} onChange={(e) => onSelectEvent(e.target.value)}>
            <option value="" disabled>Select an event…</option>
            {selectableEvents.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.primary?.name || item.primary?.id} vs {item.secondary?.name || item.secondary?.id}{item.physics_result?.status === "valid" ? " · valid" : ` · ${item.physics_result?.status || "unavailable"}`}</option>)}
          </select>
          <small>The earliest valid event is selected automatically after an accepted run. Choose another returned event here; invalid events can be reviewed with their exact reason but cannot produce maneuver candidates. Partial runs have incomplete catalog coverage.</small>
        </label> : <EmptyState title={pageState.empty_title} text={pageState.empty_text} />}
      </Panel>
      {selectedEvent ? <Panel title="Catalog object type" icon={ShieldCheck}>
        <p className="muted">Object type comes from explicit catalog metadata or a documented CelesTrak group fallback. It is not collision-risk severity.</p>
        <div className="object-classification-grid">{[selectedEvent.primary, selectedEvent.secondary].map((object) => <div key={object.id}>
          <strong>{object.name || object.id} · {object.id}</strong>
          <span>{object.object_type || "UNKNOWN"} · category {object.category || "unknown"}</span>
          <small>Classification source: {object.classification_source || "unavailable"}{object.source_classification ? ` · raw source class: ${object.source_classification}` : ""}</small>
        </div>)}</div>
      </Panel> : null}
      {selectedEvent ? <ManeuverEventContext event={selectedEvent} context={m.event_context} /> : null}
      {!selectedEvent ? null : <>
      {selectedEvent.physics_result?.status !== "valid" ? <Panel title="Stage 2A Validation" icon={Target}>
        <p className="muted">This selected event is invalid or unavailable for maneuver simulation. No candidate burns or recommendations are produced.</p>
        {(selectedEvent.physics_result?.reason_codes || []).map((code) => <p key={code}><strong>{code}</strong></p>)}
      </Panel> : null}
      {selectedEvent.physics_result?.status === "valid" ? <Panel title="Maneuver Search Configuration" icon={Rocket}>
        <form className="maneuver-search-form" onSubmit={submitManeuverSearch}>
          <label>Burn lead before baseline TCA (s)<input type="number" min="60" max="1800" step="1" required value={leadSeconds} onChange={(e) => setLeadSeconds(e.target.value)} /></label>
          <label>Maximum Δv (m/s)<input type="number" min="0.0001" max="0.1" step="any" required value={maxDeltaVMs} onChange={(e) => setMaxDeltaVMs(e.target.value)} /></label>
          <label>Initial mass (kg), optional<input type="number" min="0.0001" step="any" value={initialMassKg} onChange={(e) => setInitialMassKg(e.target.value)} /></label>
          <label>Specific impulse (s), optional<input type="number" min="0.0001" max="2000" step="any" value={specificImpulseS} onChange={(e) => setSpecificImpulseS(e.target.value)} /></label>
          <button className="primary-action" type="submit" disabled={!screeningJobId || maneuverBusy}>{maneuverBusy ? "Searching…" : "Run Maneuver Search"}</button>
        </form>
        {configurationError ? <p role="alert" className="muted">{configurationError}</p> : null}
        <p className="muted">The search applies impulses to the primary object's Cartesian state in its burn-epoch RTN frame. It samples six signed RTN axes, refines promising magnitudes, and searches encounter geometry from burn epoch through 30 minutes after baseline TCA.</p>
      </Panel> : null}
      <section className="maneuver-results-summary" aria-label="Maneuver assessment summary">
        <Panel title="Zero-burn baseline" icon={Target}>
          <div className="maneuver-summary-grid">
            <span>Baseline TCA<strong>{baseline.tca_utc || selectedEvent.physics_result?.tca?.value || "Unavailable"}</strong></span>
            <span>Baseline miss distance<strong>{Number.isFinite(baseline.miss_distance_km) ? `${baseline.miss_distance_km.toFixed(6)} km · two-body baseline` : selectedEvent.physics_result?.miss_distance?.status === "available" ? `${selectedEvent.physics_result.miss_distance.value} km · Stage 2A SGP4 reference` : "Unavailable"}</strong></span>
            <span>Baseline relative velocity<strong>{baseline.candidate?.relative_velocity_km_s ? `${baseline.candidate.relative_velocity_km_s.map((v) => Number(v).toFixed(6)).join(", ")} km/s` : "Available after search"}</strong></span>
          </div>
        </Panel>
        <Panel title="Best bounded candidate" icon={ShieldCheck}>
          {!m.best_candidate_status && !maneuverBusy ? <p className="muted">Run a search to compare candidates with the zero-burn baseline.</p> : null}
          {maneuverBusy ? <p role="status" className="muted">Propagating and comparing candidates…</p> : null}
          {m.best_candidate_status === "no_candidate_improved_separation_within_search_bounds" ? <p className="maneuver-no-improvement">No tested candidate improved miss distance within these search bounds.</p> : null}
          {bestCandidate ? <div className="maneuver-summary-grid">
            <span>Selected burn<strong>{bestCandidate.delta_v_m_s.toFixed(5)} m/s · {bestCandidate.direction} RTN</strong></span>
            <span>Candidate miss distance<strong>{bestCandidate.predicted_miss_distance_km.toFixed(6)} km</strong></span>
            <span>Change vs baseline<strong>{bestCandidate.change_from_zero_burn_km > 0 ? "+" : ""}{bestCandidate.change_from_zero_burn_km.toFixed(6)} km · {bestCandidate.change_from_zero_burn_baseline_percent == null ? "unavailable" : `${bestCandidate.change_from_zero_burn_baseline_percent.toFixed(3)}%`}</strong></span>
            <span>Candidate TCA<strong>{bestCandidate.closest_approach_utc}</strong></span>
            <span>Candidate relative velocity<strong>{bestCandidate.relative_velocity_km_s.map((v) => Number(v).toFixed(6)).join(", ")} km/s</strong></span>
            <span>Fuel estimate<strong>{m.fuel?.status === "estimated" ? `${m.fuel.propellant_consumption_kg.toPrecision(5)} kg · ideal rocket equation` : `Unavailable · ${m.fuel?.reason_code || "mass and specific impulse not supplied"}`}</strong></span>
            <span>Pc after maneuver<strong>Unavailable · {m.probability_after?.reason_code || "post-maneuver covariance propagation is not implemented"}</strong></span>
          </div> : null}
          {bestCandidate ? <p className="muted">Positive miss-distance change indicates greater separation in this simulated geometry only. It does not establish a Pc reduction or safety.</p> : null}
        </Panel>
      </section>
      <ManeuverBaselineComparison comparison={m.baseline_reference_comparison} stage2aReference={m.stage2a_reference} stage2aPhysics={selectedEvent.physics_result} zeroBurnBaseline={m.zero_burn_baseline} candidates={physicsCandidates} probabilityBefore={m.probability_before} probabilityAfter={m.probability_after} probabilityComparison={m.probability_comparison} />
      <details className="advanced-maneuver-details"><summary>Advanced propagation, baseline comparison, candidate table and provenance</summary>
      <section className="split-grid">
        <Panel title="Physics Inputs" icon={Rocket}>
          <PhysicsAvailability physics={selectedEvent.physics_result} />
        </Panel>
        <Panel title="Maneuver Result" icon={Target}>
          <div className="readout-list">
            <span>Status <strong>{m.status === "running" ? "evaluating" : m.status || "unavailable"}</strong></span>
            <span>Reason <strong>{m.reason || "No validated maneuver model is configured."}</strong></span>
            <span>Event key <strong>{selectedEvent.id}</strong></span>
            <span>Screening job key <strong>{m.screening_job_id || screeningJobId || "Unavailable"}</strong></span>
            <span>Physics candidate evaluation <strong>{m.physics_candidate_status || "not_evaluated"}</strong></span>
            <span>Collision-probability comparison <strong>Not applicable; maneuver simulation does not calculate post-maneuver Pc</strong></span>
            <span>Method <strong>{m.method || "Unavailable"}</strong></span>
            {m.candidate_interpretation ? <span>Candidate interpretation <strong>{m.candidate_interpretation}</strong></span> : null}
            {m.assumptions?.map((item, index) => <span key={index}>Assumption / limitation <strong>{item}</strong></span>)}
            {m.limitations?.map((item, index) => <span key={index}>Input limitation <strong>{item}</strong></span>)}
          </div>
        </Panel>
      </section>
      <Panel title="Optional Synthetic Simulator Surrogate" icon={ShieldCheck}>
        <ManeuverAiSummary result={m.surrogate_rank || m.ml_result} />
      </Panel>
      {physicsCandidates.length ? <Panel title="Physics Candidates · Two-Body RK4" icon={Target}>
        <p className="muted">This is a bounded axis-aligned local search, not a global optimum. Every candidate uses numerical two-body RK4 propagation and a refined closest-approach search. Synthetic surrogate scores do not affect selection.</p>
        <div className="table-scroll"><table><thead><tr><th>Δv (m/s)</th><th>Direction / frame</th><th>Candidate TCA</th><th>Miss distance (km)</th><th>Change (km / %)</th><th>Relative velocity (km/s)</th><th>Fuel estimate (kg)</th><th>Pc after burn</th><th>Search result</th></tr></thead><tbody>{physicsCandidates.map((candidate, index) => <tr key={`${candidate.delta_v_m_s}-${candidate.direction}-${index}`}><td>{Number.isFinite(candidate.delta_v_m_s) ? candidate.delta_v_m_s.toFixed(5) : "Unavailable"}</td><td>{candidate.direction || "Unavailable"} · RTN</td><td>{candidate.closest_approach_utc || "Unavailable"}</td><td>{Number.isFinite(candidate.predicted_miss_distance_km) ? candidate.predicted_miss_distance_km.toFixed(6) : "Unavailable"}</td><td>{Number.isFinite(candidate.change_from_zero_burn_km) ? `${candidate.change_from_zero_burn_km > 0 ? "+" : ""}${candidate.change_from_zero_burn_km.toFixed(6)} / ${candidate.change_from_zero_burn_baseline_percent?.toFixed(3) ?? "unavailable"}%` : "Unavailable"}</td><td>{candidate.relative_velocity_km_s?.map((v) => Number(v).toFixed(6)).join(", ") || "Unavailable"}</td><td>{candidate.fuel?.status === "estimated" ? candidate.fuel.propellant_consumption_kg.toPrecision(5) : "Unavailable · parameters not supplied"}</td><td>Unavailable · covariance propagation not implemented</td><td>{candidate.objective_status || "Unavailable"}</td></tr>)}</tbody></table></div>
      </Panel> : null}
      </details>
      </>}
    </div>
  );
}

function AnalyticsPage({ analytics, events, snapshot }) {
  return (
    <div className="page-stack">
      <PageHeader eyebrow="Catalog Analytics" title="Catalog Heuristic Analysis" text="Current catalog aggregates, generated heuristic proxy pairs, and a formula-based 168-hour score forecast. This page has no historical conjunction-event store; its charts are not historical collision records or physical collision probabilities." />
      <section className="split-grid">
        <Panel title="Current Catalog by Orbit Band" icon={BarChart3}>
          <BarList data={analytics?.band_distribution || {}} total={snapshot?.stats?.tracked_objects || 1} />
        </Panel>
        <Panel title="168-Hour Heuristic Forecast" icon={LineChart}>
          <p className="muted">Formula-based score projections from the current catalog snapshot at forecast-hour offsets; not historical observations or trajectory-propagated future conjunctions.</p>
          <TrendLine points={analytics?.risk_timeline || []} />
        </Panel>
      </section>
      <section className="split-grid">
        <Panel title="Current Screening Proxy Matrix" icon={Gauge}>
          <RiskMatrix events={events} />
        </Panel>
        <Panel title="Current Screening Proxy Scatter" icon={Target}>
          <Scatter events={events.slice(0, 24)} />
        </Panel>
      </section>
    </div>
  );
}

function ReportsPage({ event, screeningJobId, csvScreeningJobId, csvJobArchived, archivedJob, restoreBusy, onRestoreArchive, onClearArchivedJob, download, downloadTrajectoryCsv, smart }) {
  const [archiveIdInput, setArchiveIdInput] = useState("");
  const archivedResult = archivedJob?.result;
  const archivedEvents = archivedResult?.data || [];
  const archivedInvalidCount = archivedEvents.filter((item) => item.physics_result?.status === "invalid").length;
  const eventReportPath = event?.result_kind === "physics_assessment"
    ? screeningJobId ? selectedEventReportPath(screeningJobId, event.id) : null
    : event ? `/api/reports/${encodeURIComponent(event.id)}.pdf` : null;
  const eventReportUnavailable = event?.result_kind === "physics_assessment" && !screeningJobId;
  return (
    <div className="page-stack">
      <PageHeader eyebrow="Reports" title="Export Center" text="Download provenance-tagged research outputs from the backend report engine." />
      <Panel title="Restore Archived Screening Job" icon={DatabaseZap}>
        <p className="muted">Restoration reads a validated archive by job ID. It does not rerun screening or replace the latest live result.</p>
        <form className="archive-restore-form" onSubmit={(e) => { e.preventDefault(); onRestoreArchive(archiveIdInput.trim()); }}>
          <label>
            <span>Archived screening job ID</span>
            <input
              value={archiveIdInput}
              onChange={(e) => setArchiveIdInput(e.target.value)}
              maxLength={32}
              pattern="[A-Fa-f0-9]{32}"
              placeholder="32-character hexadecimal ID"
              aria-label="Archived screening job ID"
            />
          </label>
          <button className="secondary-action" type="submit" disabled={restoreBusy || !archiveIdInput.trim()}>
            {restoreBusy ? "Restoring archive…" : "Restore and select archive"}
          </button>
        </form>
        {archivedJob ? <section className="archived-result" aria-label="Selected archived screening result">
          <h3>ARCHIVED RESULT · {archivedJob.job_id}</h3>
          <div className="readout-list">
            <span>Historical status <strong>{archivedJob.status}</strong></span>
            <span>Created UTC <strong>{archivedJob.created_at}</strong></span>
            <span>Assessment records <strong>{archivedEvents.length}</strong></span>
            <span>Invalid assessments <strong>{archivedInvalidCount}</strong></span>
            <span>Candidate pairs / minima / refinements <strong>{archivedResult?.screening?.candidate_pair_count ?? "Unavailable"} / {archivedResult?.screening?.candidate_local_minimum_count ?? "Unavailable"} / {archivedResult?.screening?.refinement_count ?? "Unavailable"}</strong></span>
            <span>Catalog count in archive metadata <strong>{archivedResult?.source_summary?.object_count ?? "Unavailable"}</strong></span>
          </div>
          <p className="muted">Archived event records and their stored provenance are restored. The archive does not contain a complete 120-object catalog snapshot or all original TLEs.</p>
          <details>
            <summary>Show {archivedEvents.length} archived assessment records</summary>
            <ol className="archived-assessment-list">
              {archivedEvents.map((item) => <li key={item.id}>
                <strong>{item.id}</strong> · {item.primary?.id || item.physics_result?.object_primary_id} / {item.secondary?.id || item.physics_result?.object_secondary_id} · {item.physics_result?.status}
                {item.physics_result?.tca?.value ? ` · TCA ${item.physics_result.tca.value}` : ""}
                {item.physics_result?.miss_distance?.value != null ? ` · ${item.physics_result.miss_distance.value} km` : ""}
                {item.physics_result?.reason_codes?.length ? ` · ${item.physics_result.reason_codes.join("; ")}` : ""}
              </li>)}
            </ol>
          </details>
          <button className="secondary-action" type="button" onClick={onClearArchivedJob}>Use latest live screening for CSV exports</button>
        </section> : null}
      </Panel>
      <section className="report-grid">
        <ReportCard title="Mission Report" text="Catalog provenance, heuristic summaries, trajectory assessments, and Pc availability/provenance." onClick={() => download("/api/reports/mission.pdf", "orbital-mission-report.pdf")} icon={FileText} />
        <ReportCard title="Trajectory Assessment CSV" text={csvScreeningJobId ? `Export the complete assessment dataset for ${csvJobArchived ? "the selected archived job" : "the current screening job"}, including invalid records and their diagnostic reasons.` : "No screening job is selected. Restore an archive above or start an explicit live screening."} onClick={() => downloadTrajectoryCsv(csvScreeningJobId)} icon={Download} />
        <ReportCard title="Heuristic Proxy CSV" text="Catalog-level heuristic pairs kept separate from trajectory assessments." onClick={() => download("/api/reports/screening-proxies.csv", "screening-proxies.csv")} icon={ClipboardList} />
        <ReportCard title="Mission JSON" text="Catalog provenance, separate heuristic proxies, trajectory assessments, and Pc statuses." onClick={() => download("/api/reports/mission.json", "orbital-mission-report.json")} icon={DatabaseZap} />
        <ReportCard title="Selected Event PDF" text={eventReportUnavailable ? "The completed screening job for this event is unavailable." : event ? `${event.result_kind === "physics_assessment" ? "Trajectory assessment" : "Heuristic proxy"} · ${event.id}: ${event.primary.name} vs ${event.secondary.name}` : "Select an event first."} onClick={() => eventReportPath && download(eventReportPath, `${event.id}-report.pdf`)} icon={FileText} disabled={!eventReportPath} />
      </section>
      <Panel title="Summary" icon={BookOpen}>
        <p className="briefing-text">{smart?.briefing}</p>
      </Panel>
    </div>
  );
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

function StatusMetric({ icon, label, value, accent }) {
  return (
    <div className={`status-metric ${accent || ""}`}>
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
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
              {physical ? <em>ORION review priority: {event.review_priority?.category || "UNCLASSIFIED"}</em> : null}
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
  if (!entries.length) return <p className="muted">Awaiting backend analytics.</p>;
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

function TrendLine({ points }) {
  if (!points?.length) return <p className="muted">Heuristic forecast unavailable; no forecast frames were returned.</p>;
  const data = (points || []).map((point, index) => ({
    time: forecastHourLabel(point, index),
    risk: point.global_heuristic_risk_score != null && Number.isFinite(Number(point.global_heuristic_risk_score))
      ? Number(point.global_heuristic_risk_score)
      : null
  }));

  return (
    <div style={{ width: "100%", height: 250 }}>
      <ResponsiveContainer width="100%" height="100%">
        <RechartsLineChart
          data={data}
          margin={{
            top: 10,
            right: 20,
            left: 0,
            bottom: 10
          }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#26364d"
          />

          <XAxis
            dataKey="time"
            stroke="#9fb7d9"
            tick={{ fontSize: 11 }}
          />

          <YAxis
            stroke="#9fb7d9"
            tick={{ fontSize: 11 }}
            domain={[0, 1]}
          />

          <Tooltip
            contentStyle={{
              background: "#0f172a",
              border: "1px solid #334155",
              color: "#fff"
            }}
          />

          <Line
            type="monotone"
            dataKey="risk"
            stroke="#38bdf8"
            strokeWidth={3}
            dot={{ r: 4 }}
            activeDot={{ r: 6 }}
          />
        </RechartsLineChart>
      </ResponsiveContainer>
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

  const width = 520;
  const height = 260;
  const pad = { l: 52, r: 16, t: 18, b: 46 };

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
  const binsX = 22;
  const binsY = 12;

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
          <div style={{ width: 120, height: 10, border: "1px solid rgba(255,255,255,0.08)", background: `linear-gradient(90deg, ${colorScale(0)} 0%, ${colorScale(0.25)} 25%, ${colorScale(0.45)} 45%, ${colorScale(0.7)} 70%, ${colorScale(0.9)} 90%, ${colorScale(1)} 100%)` }} />
        </div>
      </div>
      <p className="muted">Each proxy-pair record is placed by its primary object's altitude and speed. Cell color uses a fixed ordinal mapping of relative priority labels; it is not a measured event-risk score. Catalog objects can appear in multiple pairs.</p>

      <div style={{ position: "relative", width: "100%", height: 290, border: "1px solid rgba(255,255,255,0.08)", background: "#02030a", borderRadius: 10, overflow: "hidden" }}>
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
              <rect
                key={`c-${cell.ix}-${cell.iy}`}
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
              left: Math.min(520 - 220, Math.max(6, hover.x)),
              top: Math.min(290 - 140, Math.max(6, hover.y)),
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

function Scatter({ events }) {
  const points = (events || []).map((event) => ({
    id: event.id,
    name: event.primary?.name || event.id,
    norad: event.primary?.id,
    altitude: Number(event.primary?.altitude_km),
    speed: Number(event.primary?.velocity_kms),
    score: Number(event.risk_score),
    risk: event.risk_level,
    priority: event.priority_score,
  })).filter((point) => Number.isFinite(point.altitude) && Number.isFinite(point.speed) && Number.isFinite(point.score));

  if (!points.length) return <p className="muted">No screening proxy pairs are available to plot.</p>;

  const minAltitude = Math.min(...points.map((point) => point.altitude));
  const maxAltitude = Math.max(...points.map((point) => point.altitude));
  const minSpeed = Math.min(...points.map((point) => point.speed));
  const maxSpeed = Math.max(...points.map((point) => point.speed));
  const tooltip = ({ active, payload }) => {
    const point = payload?.[0]?.payload;
    if (!active || !point) return null;
    return (
      <div className="heatmap-tooltip">
        <strong>{point.name}</strong>
        <Row label="Object ID" value={point.norad} />
        <Row label="Heuristic Risk Index" value={point.score.toFixed(3)} />
        <Row label="Heuristic Priority" value={point.priority} />
        <Row label="Object Altitude" value={`${point.altitude.toFixed(1)} km`} />
        <Row label="Object Speed Magnitude" value={`${point.speed.toFixed(3)} km/s`} />
      </div>
    );
  };

  return (
    <div className="scatter-graph" style={{ border: "1px solid rgba(255,255,255,0.08)", background: "#02030a", borderRadius: 10, overflow: "hidden" }}>
      <div style={{ padding: 12, color: "#38bdf8", fontWeight: 900, fontSize: 12, textTransform: "uppercase" }}>Screening Proxy Scatter · one primary-object marker per proxy pair; objects can repeat</div>
      <div style={{ width: "100%", height: 300 }}>
        <ResponsiveContainer width="100%" height="100%">
          <RechartsLineChart data={points} margin={{ top: 14, right: 18, left: 28, bottom: 24 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#26364d" />
            <XAxis dataKey="altitude" type="number" domain={[minAltitude, maxAltitude]} tick={{ fontSize: 11 }} stroke="#9fb7d9" unit=" km" />
            <YAxis dataKey="speed" type="number" domain={[minSpeed, maxSpeed]} tick={{ fontSize: 11 }} stroke="#9fb7d9" unit=" km/s" />
            <Tooltip content={tooltip} />
            <Line
              type="linear"
              dataKey="speed"
              stroke="rgba(255,255,255,0)"
              activeDot={false}
              dot={(props) => {
                const point = props.payload;
                const color = ({ Critical: "#ef4444", High: "#ff8a3d", Medium: "#ffd166", Low: "#38bdf8", Safe: "#22c55e" })[point?.risk] || "#38bdf8";
                return <circle cx={props.cx} cy={props.cy} r={3 + Math.max(0, Math.min(1, point?.score || 0)) * 8} fill={color} opacity={0.86} stroke="rgba(255,255,255,0.35)" strokeWidth={1} />;
              }}
            />
          </RechartsLineChart>
        </ResponsiveContainer>
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


function ReportCard({ title, text, icon: Icon, onClick, disabled }) {
  return (
    <button className="report-card" type="button" onClick={onClick} disabled={disabled}>
      <Icon size={22} />
      <strong>{title}</strong>
      <span>{text}</span>
      <em>Download</em>
    </button>
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

