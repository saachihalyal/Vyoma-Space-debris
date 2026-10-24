export function createRequestSequence() {
  let latest = 0;
  return {
    next: () => ++latest,
    isCurrent: (requestId) => requestId === latest,
  };
}

export function ignoreAbort(promise, onError = () => {}) {
  return promise.catch((error) => {
    if (error?.name !== "AbortError") onError(error);
  });
}
