const STORAGE_KEY = "orion.activeScreeningJobId";

function defaultSessionStorage() {
  try {
    return globalThis.sessionStorage;
  } catch {
    return null;
  }
}

export function readActiveScreeningJobId(storage = defaultSessionStorage()) {
  try {
    const value = storage?.getItem(STORAGE_KEY);
    return typeof value === "string" && value.trim() ? value.trim() : null;
  } catch {
    return null;
  }
}

export function saveActiveScreeningJobId(jobId, storage = defaultSessionStorage()) {
  if (typeof jobId !== "string" || !jobId.trim()) return false;
  try {
    storage?.setItem(STORAGE_KEY, jobId.trim());
    return Boolean(storage);
  } catch {
    return false;
  }
}

export function clearActiveScreeningJobId(expectedJobId, storage = defaultSessionStorage()) {
  try {
    if (!storage) return false;
    const current = storage.getItem(STORAGE_KEY);
    if (expectedJobId && current !== expectedJobId) return false;
    storage.removeItem(STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}
