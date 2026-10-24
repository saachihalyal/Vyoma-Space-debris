import React from "react";
import { AlertTriangle, ClipboardList, Cpu, DatabaseZap, Filter, ShieldCheck } from "lucide-react";
import { SMART_FILTER_RULES, smartFilterObjectDecision, smartFilterObjectReasons, smartFilterRecordIdentity } from "../../utils/smartFilterView.js";
import { hasUsableEventPrediction, predictedEventRiskEstimate, thresholdFlagAtMinus6 } from "../../utils/mlPrediction.js";

const h = React.createElement;
const numberFormat = new Intl.NumberFormat("en-US");
const BrowserGlobe = React.lazy(() => import("../Scene/SmartFilterGlobe.jsx").then((module) => ({ default: module.SmartFilterGlobe })));

function queueRiskClass(assessment) {
  if (!Number.isFinite(assessment?.score) || !assessment?.category) return "review";
  if (assessment.category === "Critical") return "critical";
  if (assessment.category === "High") return "high";
  if (assessment.category === "Medium") return "medium";
  if (assessment.category === "Low") return "low";
  return "review";
}

export function SmartFilterPage({ snapshot, smartSnapshot, platform = {}, selectEvent = () => {}, navigate = () => {} }) {
  const smart = platform.smart && typeof platform.smart === "object" ? platform.smart : {};
  const raw = Array.isArray(snapshot?.objects) ? snapshot.objects.length : 0;
  const after = Array.isArray(smartSnapshot?.objects) ? smartSnapshot.objects.length : 0;
  const physicalEvents = (Array.isArray(platform.conjunctions) ? platform.conjunctions : [])
    .filter((event) => event?.result_kind === "physics_assessment");
  const validPrediction = (event) => hasUsableEventPrediction(event?.ml_result, event?.id)
    && event?.ml_result?.provenance?.live_feature_semantics_compatibility === "verified";
  const mlEvents = physicalEvents.filter(validPrediction)
    .sort((a, b) => Number(b.ml_result.prediction.predicted_log_risk) - Number(a.ml_result.prediction.predicted_log_risk));
  const priorityEvents = physicalEvents.filter((event) => Number.isFinite(event.ai_risk_assessment?.score))
    .sort((a, b) => (a.ai_risk_assessment.final_priority_rank ?? Number.MAX_SAFE_INTEGER) - (b.ai_risk_assessment.final_priority_rank ?? Number.MAX_SAFE_INTEGER) || String(a.id).localeCompare(String(b.id)));
  const highRiskEvents = mlEvents.filter((event) => thresholdFlagAtMinus6(event.ml_result.prediction));
  const mlUnavailable = physicalEvents.filter((event) => !validPrediction(event));
  const unavailableReasons = [...mlUnavailable.reduce((counts, event) => {
    const reason = event.ml_result?.status === "available" && event.ml_result?.provenance?.live_feature_semantics_compatibility !== "verified"
      ? "ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED"
      : event.ml_result?.reason_code || event.ml_result?.reason || "prediction_not_available";
    counts.set(reason, (counts.get(reason) || 0) + 1);
    return counts;
  }, new Map()).entries()];
  const proxyEvents = (Array.isArray(platform.screeningProxies) ? platform.screeningProxies : []).filter(Boolean);
  const sourceObjects = Array.isArray(snapshot?.objects) ? snapshot.objects : [];
  const catalogDecisions = sourceObjects.map((object) => smartFilterObjectDecision(object, proxyEvents, sourceObjects, snapshot?.source_state?.status || "unknown"));
  const catalogRetained = catalogDecisions.filter((decision) => decision.decision === "retain").length;
  const catalogInconclusive = catalogDecisions.filter((decision) => decision.decision === "inconclusive").length;
  const catalogExcluded = catalogDecisions.filter((decision) => decision.decision === "exclude").length;
  const selectedRecordIdentities = new Set((smartSnapshot?.objects || [])
    .map((object) => smartFilterRecordIdentity(object, sourceObjects))
    .filter(Boolean));
  const modelStatus = smart.ml_model_status && typeof smart.ml_model_status === "object"
    ? smart.ml_model_status
    : platform.conjunctionStatus?.ml_model || {};
  const classes = smart.by_class && typeof smart.by_class === "object" && !Array.isArray(smart.by_class) ? smart.by_class : {};
  const stages = Array.isArray(smart.pipeline_stages) ? smart.pipeline_stages : [];
  const evaluation = smart.evaluation || {};
  const catalogStatus = snapshot?.source_state?.status || "unknown";
  const stageDefaults = [
    { name: "Catalog records", count: 0 }, { name: "Heuristic shell features", count: 0 },
    { name: "Candidate-pair screening proxy", count: 0 }, { name: "Heuristic triage", count: 0 },
    { name: "Heuristic proxy review list", count: 0 },
  ];
  return h("div", { className: "page-stack" },
    h("section", { className: "page-header" },
      h("div", null, h("p", { className: "eyebrow" }, "Hybrid Physics + ML"), h("h1", null, "Smart Filter"),
        h("p", null, "Catalog screening proxies remain explicitly heuristic. The ESA historical-risk model is separate from physical Pc; its outputs are withheld because equivalence between historical CDM and live TLE feature semantics is unverified.")),
      h("div", { className: "page-action" }, h("button", { className: "primary-action", type: "button", onClick: () => navigate("collision") }, "Review Events"))),
    h("section", { className: "before-after-grid" },
      comparison("Before Filter", "Catalog snapshot · positions transformed from TEME at their propagation epoch", snapshot?.objects || []),
      h("div", { className: "reduction-column" }, h(Filter, { size: 28 }), h("strong", null, `${numberFormat.format(after)} / ${numberFormat.format(raw)}`), h("span", null, "objects selected by heuristic; validated workload reduction not measured")),
      comparison("After Heuristic Filter", "Actual heuristic-selected subset of the same catalog snapshot", smartSnapshot?.objects || [], true)),
    h("p", { className: "muted" }, "Catalog object selection retains proxy-pair members or objects above the forecast (>0.72) or heuristic-risk (>0.68) cutoffs. Missing/invalid provenance, unknown class, ambiguous identity, and stale catalog records remain in the review view as inconclusive. AI confidence is not a catalog selection input. Physical screening uses its independent catalog inputs. Catalog workload reduction is not measured."),
    h("details", { className: "filter-object-rules" }, h("summary", null, "Why each catalog object was retained or excluded"),
      h("div", { className: "table-scroll" }, h("table", null,
        h("thead", null, h("tr", null, h("th", null, "Object"), h("th", null, "Class"), h("th", null, "View result"), h("th", null, "Rule evidence"))),
        h("tbody", null, sourceObjects.map((object) => {
          const identity = smartFilterRecordIdentity(object, sourceObjects);
          const decision = smartFilterObjectDecision(object, proxyEvents, sourceObjects, catalogStatus);
          const reasons = smartFilterObjectReasons(object, proxyEvents, sourceObjects, catalogStatus);
          const status = identity
            ? selectedRecordIdentities.has(identity) ? `${decision.decision} · in review view` : "exclude · not selected"
            : "inconclusive · identity ambiguous; kept in review view";
          const key = identity || `ambiguous:${object.id}:${object.provenance?.element_epoch || "epoch-unavailable"}:${object.name || "name-unavailable"}:${JSON.stringify(object.position || [])}:${JSON.stringify(object.velocity || [])}`;
          return h("tr", { key }, h("td", null, `${object.name} · ${object.id}`), h("td", null, object.category || "unknown"), h("td", null, status), h("td", null, reasons.join("; ") || "No retention predicate met."));
        }))))),
    h("details", { className: "filter-object-rules" }, h("summary", null, "Selection rules and evaluation"),
      h("ul", null, [...SMART_FILTER_RULES, ...(Array.isArray(smart.rule_catalog) ? smart.rule_catalog : [])].map((rule) => h("li", { key: rule.rule_id }, h("code", null, rule.rule_id), ` · ${rule.source} · ${rule.decision}: ${rule.description}`))),
      h("p", { className: "muted" }, `Catalog objects: ${sourceObjects.length} before; ${after} in view (${catalogRetained} retained, ${catalogInconclusive} inconclusive, ${catalogExcluded} excluded). Validated workload reduction: not measured. Proxy pairs: ${evaluation.candidate_count_before ?? smart.raw_events ?? 0} before, ${evaluation.candidate_count_after ?? smart.after_filter ?? 0} retained (${evaluation.retained_count ?? 0} retained, ${evaluation.excluded_count ?? 0} excluded, ${evaluation.inconclusive_count ?? 0} inconclusive). Reduction: ${evaluation.reduction_pct == null ? "not measured" : `${evaluation.reduction_pct}%`}. False negatives: ${evaluation.false_negative_count == null ? "not measured (no labeled proxy-pair subset)" : evaluation.false_negative_count}.`)),
    h("section", { className: "split-grid wide-left" },
      panel("Heuristic Proxy Pipeline", Cpu,
        h(React.Fragment, null,
          h("div", { className: "pipeline" }, (stages.length ? stages : stageDefaults).map((stage, index) => h("div", { key: `${stage?.name || "Stage"}-${index}` },
            h("span", null, index + 1), h("strong", null, stage?.name || "Stage"),
            h("small", null, `${stage?.count ?? 0} records | ${stage?.kept_pct == null ? "retained % unavailable" : `${stage.kept_pct}% retained`}`)))),
          h("p", { className: "muted" }, "Relative priority bands within generated proxy pairs. These are not physical event severity classes."),
          barList(classes, smart.raw_events || 1))),
      panel("ML Model Status", ShieldCheck,
        h(React.Fragment, null,
          h("div", { className: "confidence-readout" }, modelStatus.status === "available" ? "Available" : modelStatus.artifact_status === "available" ? "Artifact available · inference unavailable" : "Unavailable"),
          h("p", { className: "muted" }, modelStatus.status === "available"
            ? `${modelStatus.model_name || "Trained model"} v${modelStatus.model_version || "version unavailable"}; predictions are limited to physical events with all nine features. The model estimates ESA historical event log-risk, not Pc.`
            : `${modelStatus.model_name || "ESA historical model"}${modelStatus.model_version ? ` v${modelStatus.model_version}` : ""}. No ML prediction is emitted: ${modelStatus.reason_code || "model status unavailable"}.`)))),
    panel("Result Category Counts", DatabaseZap,
      h("div", { className: "readout-list" },
        countRow("Physics-only, ML unavailable", mlUnavailable.length), countRow("ML-supported physical events", mlEvents.length),
        countRow("Heuristic-only proxy pairs", proxyEvents.length),
        countRow("Stage 2A close approaches reported", platform.conjunctionStatus?.screening?.close_approach_count ?? physicalEvents.length))),
    panel("Physical Events for Review", AlertTriangle,
      physicalEvents.length
        ? h(React.Fragment, null,
          h("p", { className: "muted" }, "Every physical event remains available for analyst review regardless of ESA model eligibility, availability, class, or score. AI status is informational and never filters this list."),
          h("div", { className: "event-list" }, physicalEvents.map((event) => {
            const predictionValid = validPrediction(event);
            const reason = predictionValid ? "ESA estimate available; not a selection gate" : event.ml_result?.status === "available" && event.ml_result?.provenance?.live_feature_semantics_compatibility !== "verified"
              ? "ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED" : event.ml_result?.reason_code || event.ml_result?.reason || "prediction_not_available";
            const ai = event.ai_risk_assessment;
            return h("button", { className: "event-row", type: "button", key: event.id, onClick: () => selectEvent(event, "collision") },
              h("span", { className: `risk-badge ${queueRiskClass(ai)}` }, ai && Number.isFinite(ai.score) ? `${ai.category || "Unclassified"} · ${(ai.score * 100).toFixed(1)} / 100` : "retain for review"),
              h("span", null, h("strong", null, `${event.primary?.name || event.primary?.id || "Object unavailable"} vs ${event.secondary?.name || event.secondary?.id || "Object unavailable"}`), h("small", null, `${event.id} · final priority #${ai?.final_priority_rank ?? "—"} · ${ai?.model_name || reason} · not Pc`)),
              h("b", null, "Open event"));
          })))
        : h("p", { className: "muted" }, "No physical event records are currently loaded. The ESA model does not decide whether events appear here.")),
    panel("Live Event Queue · Deterministic AI Fallback", ShieldCheck,
      priorityEvents.length ? h(React.Fragment, null,
        h("p", { className: "muted" }, "Sorted by backend final priority. Score uses normalized miss-distance proximity and relative speed; within-set numerical Pc evidence is included only when event-bound and is never treated as calibrated."),
        h("div", { className: "event-list" }, priorityEvents.slice(0, 8).map((event) => {
          const ai = event.ai_risk_assessment;
          return h("button", { className: "event-row", type: "button", key: event.id, onClick: () => selectEvent(event, "collision") },
            h("span", { className: `risk-badge ${queueRiskClass(ai)}` }, `${ai.category || "Unclassified"} · ${(ai.score * 100).toFixed(1)} / 100`),
            h("span", null, h("strong", null, `${event.primary?.name || event.primary?.id} vs ${event.secondary?.name || event.secondary?.id}`), h("small", null, `Final priority #${ai.final_priority_rank} · geometry #${ai.geometry_rank} · Foster Pc #${ai.foster_pc_rank ?? "—"} · ESA-prior Pc #${ai.research_pc_rank ?? "—"}`)),
            h("b", null, "Open event"));
        }))) : h("p", { className: "muted" }, "No valid physical conjunctions with required geometry features are loaded.")),
    panel("ESA Historical Model · Log-Risk", ShieldCheck,
      h(React.Fragment, null,
        h("p", { className: "muted" }, "Predicted log10 ESA event-risk and its exponentiated estimate. It is not a calibrated probability or Foster Pc and has no confidence interval."),
        mlEvents.length ? h("div", { className: "event-list" }, mlEvents.slice(0, 8).map((event) => predictionRow(event, selectEvent)))
          : h("p", { className: "muted" }, "No physics-assessed event currently has an available ML estimate."),
        h("p", { className: "muted" }, `Available estimates: ${mlEvents.length} · threshold flags at log10 risk ≥ -6: ${highRiskEvents.length} · physics-only events without valid ML features: ${mlUnavailable.length} · proxy pairs are heuristic-only.`),
        h("p", { className: "muted" }, "Mission-held-out test: MAE 6.8935 log10 units, Spearman 0.4424; fixed threshold detected 0/145 high-risk labels. Historical ESA CDM and live TLE feature semantics are unverified; model outputs are withheld. Threshold flags are not validated alert rules."),
        unavailableReasons.length ? h("p", { className: "muted" }, `Unavailable prediction reasons: ${unavailableReasons.map(([reason, count]) => `${reason} (${count})`).join("; ")}`) : physicalEvents.length === 0 ? h("p", { className: "muted" }, "No eligible physics-assessed event is currently available for inference.") : null)),
    panel("Heuristic-Only Proxy Pairs · Relative Priority Bands", ClipboardList,
      proxyEvents.length ? h("div", { className: "event-list" }, proxyEvents.slice(0, 8).map((event) => proxyRow(event, selectEvent)))
        : h("p", { className: "muted" }, "No screening events are available.")));
}

function comparison(title, label, objects, accent = false) {
  const count = Array.isArray(objects) ? objects.length : 0;
  return h("div", { className: `scene-comparison ${accent ? "accent" : ""}` },
    h("div", { className: "scene-comparison-head" }, h("span", null, title), h("strong", null, numberFormat.format(count))),
    typeof window === "undefined" ? h("div", { className: "smart-globe-unavailable" }, "Globe view loads in the browser.") : h(React.Suspense, { fallback: h("div", { className: "smart-globe-unavailable" }, "Loading propagated catalog globe…") }, h(BrowserGlobe, { title, objects: objects || [] })), h("small", null, label));
}

function panel(title, Icon, content) {
  return h("section", { className: "panel" }, h("div", { className: "panel-heading" }, h(Icon, { size: 17 }), h("h2", null, title)), content);
}

function countRow(label, value) {
  return h("span", { key: label }, label, h("strong", null, value));
}

function barList(data, total) {
  const entries = Object.entries(data);
  if (!entries.length) return h("p", { className: "muted" }, "Awaiting backend analytics.");
  return h("div", { className: "bar-list" }, entries.map(([label, value]) => h("div", { key: label },
    h("span", null, label), h("strong", null, value),
    h("i", { style: { width: `${Math.max(4, (Number(value) / Math.max(1, Number(total))) * 100)}%` } }))));
}

function predictionRow(event, onSelect) {
  const prediction = event.ml_result.prediction;
  return h("button", { className: "event-row", type: "button", key: event.id, onClick: () => onSelect(event, "collision") },
    h("span", { className: `risk-badge ${thresholdFlagAtMinus6(prediction) ? "high" : "low"}` }, thresholdFlagAtMinus6(prediction) ? "ESA threshold flag ≥ -6" : "ESA estimate < -6"),
    h("span", null, h("strong", null, `${event.primary?.name || event.primary?.id || "Object unavailable"} vs ${event.secondary?.name || event.secondary?.id || "Object unavailable"}`),
      h("small", null, `${event.id} · comparison: ${event.comparison_result?.status || "unavailable"}`)),
    h("b", null, h("em", null, `${Number(prediction.predicted_log_risk).toFixed(3)} log10`),
      h("small", null, `${Number(predictedEventRiskEstimate(prediction)).toExponential(3)} exponentiated ESA risk estimate`)));
}

function proxyRow(event, onSelect) {
  const priority = Number.isFinite(Number(event.priority_score)) ? Number(event.priority_score) : null;
  return h("button", { className: "event-row", type: "button", key: event.id, onClick: () => onSelect(event) },
    h("span", { className: "risk-badge high" }, `Rank ${event.risk_level || "Unavailable"}`),
    h("span", null, h("strong", null, `${event.primary?.name || event.primary?.id || "Object unavailable"} vs ${event.secondary?.name || event.secondary?.id || "Object unavailable"}`),
      h("small", null, `Heuristic proxy ${event.id || "ID unavailable"} · Heuristic score: ${Number.isFinite(Number(event.risk_score)) ? (Number(event.risk_score) * 100).toFixed(1) : "unavailable"}/100`)),
    h("b", { title: "Batch-relative heuristic ranking, not collision probability or physical severity." }, priority == null ? "Relative priority unavailable" : `Relative priority: ${event.risk_level || "unavailable"}`));
}
