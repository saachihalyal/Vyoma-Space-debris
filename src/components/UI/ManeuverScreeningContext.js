import React from "react";
import { Radar } from "lucide-react";

export function ManeuverScreeningContext({ screeningJobId, screeningStatus = {}, screeningAttempt = null }) {
  const partial = screeningStatus.result_status === "partial" || screeningStatus.completion_status === "partial";
  return React.createElement("section", { className: "panel" },
    React.createElement("div", { className: "panel-heading" }, React.createElement(Radar, { size: 17 }), React.createElement("h2", null, "Screening Context")),
    React.createElement("div", { className: "readout-list" },
      React.createElement("span", null, "Accepted screening job ", React.createElement("strong", null, screeningJobId || "Unavailable")),
      React.createElement("span", null, "Accepted result ", React.createElement("strong", null, `${screeningStatus.result_status || "Unavailable"} · ${screeningStatus.completion_status || "completion unavailable"}`)),
      screeningAttempt?.run_id
        ? React.createElement("span", null, "Latest screening attempt ", React.createElement("strong", null, `${screeningAttempt.result_status || "pending"} · ${screeningAttempt.completion_status || "not complete"} · job ${screeningAttempt.job_id || "pending"}${screeningAttempt.reason ? ` · ${screeningAttempt.reason}` : ""}`))
        : null,
      partial
        ? React.createElement("p", { className: "muted" }, "The accepted screening result is partial. An event-specific maneuver assessment uses the selected event's accepted stored states, while catalog coverage or other calculations from that run remain incomplete.")
        : null,
    ),
  );
}
