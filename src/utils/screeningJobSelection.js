export function getScreeningJobSelection(livePlatform, archivedJob) {
  if (archivedJob) {
    return {
      jobId: archivedJob.job_id,
      isArchived: true,
      archivedJob,
      livePlatform,
    };
  }
  return {
    jobId: livePlatform?.conjunctionStatus?.job_id || null,
    isArchived: false,
    archivedJob: null,
    livePlatform,
  };
}
