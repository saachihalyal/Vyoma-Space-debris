import React from "react";

const RISK_CLASS = {
  Critical: "critical",
  High: "high",
  Medium: "medium",
  Low: "low",
  Safe: "safe",
  valid: "low",
  boundary: "medium",
  invalid: "invalid",
  partial: "medium",
  unavailable: "safe",
};

export function RiskBadge({ risk, label }) {
  return React.createElement("span", { className: `risk-badge ${RISK_CLASS[risk] || "low"}` }, label || risk);
}
