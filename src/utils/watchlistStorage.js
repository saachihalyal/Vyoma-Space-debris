export function readWatchlist(storage = globalThis.localStorage) {
  try {
    const raw = storage?.getItem("ssa-watchlist");
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((value) => typeof value === "string" || typeof value === "number")
      : [];
  } catch (error) {
    // Browser storage may contain malformed or inaccessible persisted data.
    // The watchlist is optional and must not prevent the application from mounting.
    console.warn("[ORION startup] persisted watchlist could not be loaded; starting with an empty watchlist.", error);
    return [];
  }
}
