const REVIEW_PAIR_BANDS = new Set(["Critical", "High", "Medium"]);

export const SMART_FILTER_RULES = [
  { rule_id: "PROXY_PAIR_REVIEW_BAND", source: "HEURISTIC", decision: "retain", description: "Object is referenced by a Critical, High, or Medium relative proxy pair." },
  { rule_id: "HEURISTIC_FORECAST_GT_0_72", source: "HEURISTIC", decision: "retain", description: "Forecast heuristic score is greater than 0.72." },
  { rule_id: "HEURISTIC_RISK_GT_0_68", source: "HEURISTIC", decision: "retain", description: "Risk heuristic score is greater than 0.68." },
  { rule_id: "RISK_CELL_SCORE_GT_0_48", source: "HEURISTIC", decision: "retain", description: "Show risk cells with heuristic risk score greater than 0.48." },
  { rule_id: "UNKNOWN_CLASS_REVIEW", source: "HEURISTIC", decision: "inconclusive", description: "Object class is unknown or missing; keep for review." },
  { rule_id: "AMBIGUOUS_RECORD_IDENTITY_REVIEW", source: "HEURISTIC", decision: "inconclusive", description: "Record identity cannot be uniquely resolved; keep for review." },
  { rule_id: "INVALID_OR_MISSING_PROVENANCE_REVIEW", source: "HEURISTIC", decision: "inconclusive", description: "Provenance validity is missing or not valid; keep for review." },
  { rule_id: "STALE_CATALOG_REVIEW", source: "HEURISTIC", decision: "inconclusive", description: "Catalog snapshot is stale; keep its records for review." },
];

export function smartFilterRecordIdentity(object, records = []) {
  const id = typeof object?.id === "string" ? object.id.trim() : "";
  if (!id) return null;
  const sameIdRecords = records.filter((record) => record?.id === object.id);
  const inputHash = object?.provenance?.input_hash;
  if (typeof inputHash === "string" && inputHash.trim()) {
    const matchingHashCount = sameIdRecords.filter((record) => record?.provenance?.input_hash === inputHash).length;
    return matchingHashCount === 1 ? `record:${id}:${inputHash}` : null;
  }
  return sameIdRecords.length === 1 ? `catalog:${id}` : null;
}

function proxyReferencesRecord(event, object, records) {
  const objectIdentity = smartFilterRecordIdentity(object, records);
  if (!objectIdentity || !REVIEW_PAIR_BANDS.has(event?.risk_level)) return false;
  return [event.primary, event.secondary].some((summary) =>
    summary?.id === object.id && smartFilterRecordIdentity(summary, records) === objectIdentity,
  );
}

export function smartFilterObjectDecision(object, proxyEvents = [], records = [object], snapshotStatus = "live") {
  const rules = [];
  if (proxyEvents.some((event) => proxyReferencesRecord(event, object, records))) rules.push("PROXY_PAIR_REVIEW_BAND");
  const forecastScore = Number(object?.heuristic_forecast_score);
  if (Number.isFinite(forecastScore) && forecastScore > 0.72) rules.push("HEURISTIC_FORECAST_GT_0_72");
  const heuristicScore = Number(object?.heuristic_risk_score);
  if (Number.isFinite(heuristicScore) && heuristicScore > 0.68) rules.push("HEURISTIC_RISK_GT_0_68");

  const category = typeof object?.category === "string" ? object.category.trim().toLowerCase() : "";
  if (!category || category.includes("unknown") || category.includes("unclassified")) rules.push("UNKNOWN_CLASS_REVIEW");
  if (!smartFilterRecordIdentity(object, records)) rules.push("AMBIGUOUS_RECORD_IDENTITY_REVIEW");
  if (object?.provenance?.validity_status !== "valid") rules.push("INVALID_OR_MISSING_PROVENANCE_REVIEW");
  if (snapshotStatus === "stale") rules.push("STALE_CATALOG_REVIEW");

  const inconclusive = rules.some((id) => SMART_FILTER_RULES.find((rule) => rule.rule_id === id)?.decision === "inconclusive");
  const decision = inconclusive ? "inconclusive" : rules.length ? "retain" : "exclude";
  return { decision, included: decision !== "exclude", rules };
}

export function smartFilterObjectReasons(object, proxyEvents = [], records = [object], snapshotStatus = "live") {
  const result = smartFilterObjectDecision(object, proxyEvents, records, snapshotStatus);
  return result.rules.map((id) => {
    const rule = SMART_FILTER_RULES.find((item) => item.rule_id === id);
    return `${id} (${rule?.source || "HEURISTIC"}): ${rule?.description || "Rule matched."}`;
  });
}

export function buildSmartFilterView(snapshot, proxyEvents = []) {
  if (!snapshot) return snapshot;
  const sourceObjects = snapshot.objects || [];
  const status = snapshot.source_state?.status || "unknown";
  const objects = sourceObjects.filter((object) => smartFilterObjectDecision(object, proxyEvents, sourceObjects, status).included);
  const risk_cells = (snapshot.risk_cells || []).filter((cell) => cell.heuristic_risk_score > 0.48);
  return { ...snapshot, objects, risk_cells, stats: { ...snapshot.stats, tracked_objects: objects.length } };
}
