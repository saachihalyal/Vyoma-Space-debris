export function sourceLabel(status, cacheAgeSeconds = null) {
  if (status === "live") return "Live";
  if (status === "stale_live" || status === "stale") {
    if (cacheAgeSeconds == null) return "Catalog cached";
    const age = Number(cacheAgeSeconds);
    if (!Number.isFinite(age) || age < 0) return "Catalog cached";
    const minutes = Math.floor(age / 60);
    const value = minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
    return `Catalog cached · updated ${value} ago`;
  }
  return ({
    fallback: "BUNDLED FALLBACK DATA",
    unavailable: "SOURCE UNAVAILABLE",
    all_live: "Live",
    mixed_live_fallback: "Live + Fallback",
    mixed_live_synthetic: "Live + Synthetic Demo",
    synthetic_demo: "Synthetic Demo",
  })[status] || "SOURCE UNAVAILABLE";
}

export function datasetLabel(loading, sourceStatus) {
  if (loading) return "Loading dataset";
  return ["live", "stale_live", "stale", "fallback"].includes(sourceStatus) ? "Dataset loaded" : "Source unavailable";
}

export function retainCatalogSnapshot(previous, incoming) {
  if (incoming?.source_state?.status !== "unavailable" || !Array.isArray(previous?.objects) || previous.objects.length === 0) {
    return incoming;
  }
  return {
    ...previous,
    source_state: {
      ...previous.source_state,
      status: "stale",
      last_error_code: incoming.source_state.last_error_code || "catalog_refresh_unavailable",
    },
  };
}
