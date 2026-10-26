import React from "react";

const h = React.createElement;

export function CollisionPcSummary({ sourceResult, scenarioResult }) {
  const importedCdm = isImportedCdmResult(sourceResult);
  return h("div", { className: "readout-list", "aria-live": "polite" },
    h("h4", null, "Physical collision probability (Pc)"),
    resultLine(sourcePcLabel(sourceResult), sourceResult, "No covariance/HBR result is attached to this event."),
    sourceResult?.risk_assessment?.status === "classified" && Number.isFinite(sourceResult.risk_assessment.risk_score)
      ? h("span", null, "Physics Pc risk score and class", h("strong", null, `${sourceResult.risk_assessment.risk_score.toFixed(1)} / 100 · ${sourceResult.risk_assessment.final_risk_class} · based on ${sourceResult.risk_assessment.risk_score_pc_channel}`))
      : null,
    sourceResult?.risk_assessment?.status === "classified" && sourceResult.risk_assessment.classification_basis
      ? h("span", null, "Final classification policy", h("strong", null, sourceResult.risk_assessment.classification_basis))
      : null,
    sourceResult?.probability_classification?.status === "classified"
      ? h("span", null, "Pc reference category", h("strong", null, `${sourceResult.probability_classification.category} · ${sourceResult.probability_classification.explanation}`))
      : null,
    sourceResult?.status !== "available"
      ? h("span", null, "Next action", h("strong", null, unavailableNextAction(sourceResult)))
      : null,
    provenanceLines("Source Pc", sourceResult),
    sourceResult?.miss_distance_km != null
      ? h("span", null, importedCdm ? "CDM mean miss distance" : "Pc encounter mean miss distance", h("strong", null, `${Number(sourceResult.miss_distance_km).toFixed(6)} km`))
      : null,
    sourceResult?.tca_utc
      ? h("span", null, importedCdm ? "CDM mean-state TCA" : "Pc encounter TCA", h("strong", null, sourceResult.tca_utc))
      : null,
    sourceResult?.covariance_sources?.length || sourceResult?.hbr_provenance
      ? h("span", null, "Input authentication", h("strong", null, "User-declared source; not authenticated by Vyoma"))
      : null,
    resultLine("Research scenario Pc - ESTIMATED (assumed inputs)", scenarioResult, "No user-entered scenario has been run."),
    provenanceLines("Scenario Pc", scenarioResult),
    scenarioResult
      ? h("span", null, "Scenario meaning", h("strong", null, "Assumed inputs only; separate from source-supported Pc and not an observed collision probability"))
      : null,
    h("h4", null, "Input quality and limits"),
    h("span", null, "Live orbit source", h("strong", null, "CelesTrak GP/OMM provides orbital elements and state estimates; this feed does not supply event covariance or HBR.")),
    h("span", null, "Event-specific covariance input", h("strong", null, "Upload a conjunction message for event-specific states, covariance, and HBR. When those inputs are absent, the separate research Pc estimate uses documented assumptions.")),
    sourceResult?.status === "available"
      ? h("span", null, "Assessment scope", h("strong", null, importedCdm ? "CDM state and uncertainty inputs matched this event's object IDs and exact TCA; source authenticity remains unverified." : "See covariance and HBR provenance above; a numeric Pc is not an ML risk estimate."))
      : null);
}

export function CollisionProbabilityCard({ result, sourceReportedPc = null, sourceReportedMethod = null }) {
  const computedAvailable = isUsablePc(result);
  const reportedAvailable = isValidProbability(sourceReportedPc);
  const status = computedAvailable ? "COMPUTED" : reportedAvailable ? "SOURCE-REPORTED" : "UNAVAILABLE";
  const probability = computedAvailable ? result.pc : reportedAvailable ? sourceReportedPc : null;
  const method = computedAvailable ? `${result.method || "Foster 2D"} v${result.method_version || "unknown"}` : reportedAvailable ? (sourceReportedMethod || "Source method not declared") : null;
  const provenance = computedAvailable
    ? `${result.provenance?.source || "Vyoma calculation"}; covariance ${result.covariance_status || "unavailable"}; frame ${result.covariance_frame || "unavailable"}; epoch ${result.covariance_epoch || "unavailable"}; HBR ${result.hbr_provenance?.source_type || result.hbr_source || "unavailable"}`
    : reportedAvailable ? "Value transcribed from the selected source CDM; it is not an Vyoma calculation." : null;
  const reasons = result?.reason_codes?.length ? result.reason_codes.join(", ") : result?.reason || "Event-matched covariance and HBR are unavailable.";
  return React.createElement("section", { className: "collision-probability-card", "aria-label": "Collision probability summary" },
    React.createElement("div", { className: "collision-probability-heading" },
      React.createElement("div", null,
        React.createElement("span", { className: "muted" }, "Collision Probability (Pc)"),
        React.createElement("strong", { className: "collision-probability-value" }, probability == null ? "Unavailable" : formatProbabilityScientific(probability))),
      React.createElement("span", { className: `screening-state-badge pc-state-${status.toLowerCase()}` }, status)),
    probability == null
      ? React.createElement("p", { className: "muted" }, `Why is Pc unavailable? ${reasons}`)
      : React.createElement("div", { className: "collision-probability-readouts" },
        React.createElement("span", null, "Percentage", React.createElement("strong", null, formatProbabilityPercentage(probability))),
        React.createElement("span", null, "Approximate odds", React.createElement("strong", null, formatProbabilityOdds(probability))),
        React.createElement("span", null, "Method", React.createElement("strong", null, method)),
        React.createElement("span", null, "Data source", React.createElement("strong", null, provenance))),
    computedAvailable && reportedAvailable
      ? React.createElement("div", { className: "collision-probability-source-reported" },
        React.createElement("span", { className: "screening-state-badge pc-state-source-reported" }, "SOURCE-REPORTED"),
        React.createElement("strong", null, `${formatProbabilityScientific(sourceReportedPc)} · ${formatProbabilityPercentage(sourceReportedPc)} · ${formatProbabilityOdds(sourceReportedPc)}`),
        React.createElement("span", { className: "muted" }, `${sourceReportedMethod || "Source method not declared"}; kept separate from Vyoma's computed Pc.`),
        React.createElement("span", { className: "muted" }, `Declared source: ${result.source_reported_pc_provenance?.source || "CDM source unavailable"}; SHA-256 ${result.source_reported_pc_provenance?.input_sha256 || "unavailable"}; authenticated: ${result.source_reported_pc_provenance?.authenticated === true ? "yes" : "no"}.`))
      : null,
    result?.status === "available" && !computedAvailable
      ? React.createElement("p", { className: "muted" }, "The calculation returned an invalid numeric Pc; no probability is displayed.")
      : null);
}

export function unavailableNextAction(result) {
  const reasons = new Set(result?.reason_codes || []);
  const actions = [];
  if (reasons.has("NO_COVARIANCE")) actions.push("Import a CDM for this object pair and exact TCA that includes validated covariance for both objects.");
  if (reasons.has("HBR_UNAVAILABLE")) actions.push("Provide the CDM's documented hard-body radius input(s); Vyoma will not infer HBR from radar cross-section.");
  if (reasons.has("INVALID_COVARIANCE")) actions.push("Correct the covariance validation issues and provide positive-definite covariance for both objects.");
  if (reasons.has("COVARIANCE_OBJECT_ID_MISMATCH")) actions.push("Use covariance records whose object IDs match the selected event pair.");
  if (reasons.has("INVALID_HBR")) actions.push("Provide a finite, positive hard-body radius with supported source provenance.");
  if (reasons.has("RELATIVE_COVARIANCE_CORRELATION_UNKNOWN")) actions.push("Authorize the independent-covariance assumption explicitly, or provide a supported relative covariance.");
  if (reasons.has("COVARIANCE_EPOCH_MISMATCH")) actions.push("Use covariance evaluated at the event TCA.");
  if (reasons.has("COVARIANCE_FRAME_MISMATCH")) actions.push("Provide both covariances in the same supported frame.");
  if (reasons.has("INSUFFICIENT_ENCOUNTER_STATE")) actions.push("Use a valid TCA with both objects' finite states in a common frame.");
  if (reasons.has("DEGENERATE_ENCOUNTER_GEOMETRY")) actions.push("The encounter state does not define a stable Foster 2D encounter plane.");
  if (reasons.has("PC_METHOD_NOT_APPLICABLE")) actions.push("This event geometry is outside the supported Foster 2D method conditions.");
  if (reasons.has("NUMERICAL_FAILURE")) actions.push("The Foster integral failed its convergence or numerical validity checks; no Pc is reported.");
  if (!actions.length) actions.push("Import a compatible event CDM containing states, covariance and HBR, then review the validation result.");
  return actions.join(" ");
}

function provenanceLines(label, result) {
  if (!result) return null;
  const source = result.provenance;
  const covariance = Array.isArray(result.covariance_sources) && result.covariance_sources.length
    ? result.covariance_sources.map((item) => `${item.object_id || "object ID unavailable"}: ${item.source || "source unavailable"} (${item.source_type || "source type unavailable"}; ${item.frame || "frame unavailable"}; epoch ${item.epoch || "unavailable"}; ${item.matrix_dimension || "?"}×${item.matrix_dimension || "?"}; units ${item.units ? JSON.stringify(item.units) : "unavailable"}; SHA-256 ${item.input_hash || "unavailable"})`).join(" | ")
    : "unavailable";
  const hbr = result.hbr_provenance
    ? `${result.hbr_provenance.source_type || result.hbr_source || "unknown"}; ${result.hbr_provenance.description || "description unavailable"}; ${result.hbr_provenance.units || "km"}; SHA-256 ${result.hbr_provenance.input_hash || "unavailable"}`
    : "unavailable";
  const children = [
    h("span", { key: "method" }, `${label} method`, h("strong", null, `${result.method || "unavailable"} v${result.method_version || "unavailable"}; probability dimensionless`)),
    h("span", { key: "validation" }, `${label} input validation`, h("strong", null, `covariance ${result.covariance_status || "unavailable"}; frame ${result.covariance_frame || "unavailable"}; epoch ${result.covariance_epoch || "unavailable"}; independence assumption ${result.independence_assumption_authorized ? "authorized" : "not authorized"}`)),
    h("span", { key: "provenance" }, `${label} calculation source`, h("strong", null, `${source?.source || "unavailable"} (${source?.source_type || "unavailable"}; synthetic=${source?.is_synthetic ?? "unavailable"})`)),
    h("span", { key: "covariance" }, `${label} covariance provenance`, h("strong", null, covariance)),
    h("span", { key: "hbr" }, `${label} HBR provenance`, h("strong", null, hbr)),
  ];
  if (Array.isArray(result.warnings) && result.warnings.length) {
    children.push(h("span", { key: "warnings" }, `${label} warnings`, h("strong", null, result.warnings.join("; "))));
  }
  return children;
}

export function isImportedCdmResult(result) {
  const sources = result?.covariance_sources;
  const hbr = result?.hbr_provenance;
  return Array.isArray(sources)
    && sources.length === 2
    && sources.every((source) => source?.source_type === "user_supplied")
    && hbr?.source_type === "user_supplied"
    && /CDM/i.test(hbr.description || "")
    && Array.isArray(result.warnings)
    && result.warnings.some((warning) => /imported CDM/i.test(warning));
}

export function sourcePcLabel(result) {
  return isImportedCdmResult(result)
    ? "Imported CDM-based Foster Pc (source unverified)"
    : "Event collision probability";
}

function resultLine(label, result, emptyText) {
  if (!result) return h("span", { key: label }, label, h("strong", null, emptyText));
  const hasNumericPc = isUsablePc(result);
  const value = hasNumericPc
    ? ` - ${result.pc.toExponential(5)}`
    : "";
  const reasonCodes = Array.isArray(result.reason_codes) ? [...result.reason_codes] : [];
  if (result.status === "available" && !hasNumericPc && !reasonCodes.includes("INVALID_PC_VALUE")) reasonCodes.push("INVALID_PC_VALUE");
  const status = result.status === "available" && !hasNumericPc ? "invalid" : result.status;
  const reasons = reasonCodes.length ? ` - ${reasonCodes.join(", ")}` : "";
  return h("span", { key: label }, label, h("strong", null, `${status}${value}${reasons}`));
}

export function isUsablePc(result) {
  return result?.status === "available"
    && typeof result.pc === "number"
    && Number.isFinite(result.pc)
    && result.pc > 0
    && result.pc <= 1;
}

export function pcDisplayStatus(result) {
  return result?.status === "available" && !isUsablePc(result)
    ? "invalid · INVALID_PC_VALUE"
    : result?.status || "unavailable";
}

export function formatCollisionProbability(value) {
  if (!Number.isFinite(value) || value <= 0 || value > 1) return "Pc unavailable";
  if (value > 0 && value < 1e-300) return "< 1e-300";
  return value.toExponential(3);
}

export function formatProbabilityScientific(value) {
  if (!isValidProbability(value)) return "Pc unavailable";
  if (value > 0 && value < 1e-300) return "< 1e-300";
  return value.toExponential(3).replace("e", " × 10^");
}

export function formatProbabilityPercentage(value) {
  return isValidProbability(value) ? `${(value * 100).toExponential(3)}%` : "Unavailable";
}

export function formatProbabilityOdds(value) {
  if (!isValidProbability(value)) return "Unavailable";
  if (value === 0) return "not defined for Pc = 0";
  const reciprocal = 1 / value;
  return Number.isFinite(reciprocal) ? `about 1 in ${Math.round(reciprocal).toLocaleString("en-US")}` : "1 in an extremely large number";
}

export function isValidProbability(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}
