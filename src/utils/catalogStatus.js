export function sourceLabel(status) {
  return ({
    live: "LIVE CelesTrak",
    stale_live: "STALE LIVE CelesTrak",
    stale: "STALE CATALOG SNAPSHOT",
    fallback: "BUNDLED FALLBACK DATA",
    unavailable: "SOURCE UNAVAILABLE",
    all_live: "LIVE CelesTrak",
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
