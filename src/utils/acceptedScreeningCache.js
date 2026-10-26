const CACHE_KEY = "orion.acceptedScreening.v1";

function storage() { try { return globalThis.localStorage; } catch { return null; } }

export function readAcceptedScreeningCache(store = storage()) {
  try {
    const value = JSON.parse(store?.getItem(CACHE_KEY) || "null");
    return value?.status?.job_id && Array.isArray(value.events) ? value : null;
  } catch { return null; }
}

export function saveAcceptedScreeningCache(status, events, store = storage()) {
  if (!status?.job_id || !["complete", "partial"].includes(status.completion_status) || !Array.isArray(events)) return false;
  const { data, ...acceptedStatus } = status;
  try { store?.setItem(CACHE_KEY, JSON.stringify({ status: acceptedStatus, events, acceptedAt: new Date().toISOString() })); return Boolean(store); }
  catch { return false; }
}
