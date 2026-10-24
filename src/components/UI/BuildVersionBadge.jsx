import { useEffect, useState } from "react";
import { API_BASE } from "../../api/ssaClient";

const frontendCommit = import.meta.env.VITE_COMMIT || "development";

export function BuildVersionBadge() {
  const [backend, setBackend] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/api/version`, { signal: controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then(setBackend)
      .catch((error) => { if (error.name !== "AbortError") setBackend({ error: true }); });
    return () => controller.abort();
  }, []);
  const mismatch = backend?.commit && frontendCommit !== "development" && backend.commit !== frontendCommit;
  const warning = backend?.error || mismatch;
  return <div className={`build-version-badge${warning ? " warning" : ""}`} role={warning ? "alert" : "status"}>
    Frontend {frontendCommit.slice(0, 8)} · Backend {backend?.commit?.slice(0, 8) || (backend?.error ? "unreachable" : "checking…")}
    {warning ? <strong>{backend?.error ? "Backend is unreachable" : "Builds differ; restart both servers"}</strong> : null}
  </div>;
}
