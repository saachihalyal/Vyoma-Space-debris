# Screening job lifecycle and identity

The backend job registry is authoritative for a screening job's lifecycle and event records. The frontend carries the accepted `job_id` through polling, event selection, maneuver requests, and job-scoped reports. Event IDs are only meaningful within that job.

## Existing wire statuses

`GET /api/conjunction-jobs/{job_id}` returns `status` as `queued`, `running`, `complete`, `partial`, or `failed`. On terminal jobs it also returns `completion_status`. The result carries `result_status`: `valid_non_empty`, `valid_empty`, `partial`, `unavailable`, or an error/timeout state at the API client boundary. Progress is `null` while propagation runs because the propagator does not provide truthful fine-grained progress.

Each job's `configuration` echoes requested and effective catalog limit, horizon, sample step, and threshold. The result's `screening` metadata reports `objects_requested` (the catalog limit), `catalog_records_received`, `objects_used` (tracks admitted to propagation), `candidate_pairs`, `refinements`, and `physical_events`, alongside the original detailed count names. `caps_hit` identifies sampling, pair, or refinement caps; `partial_reasons` identifies caps and source/propagation gaps. Any such coverage reduction makes the job `partial`. When a sample epoch cap is reached, the job reports the sampled coverage end separately from the requested horizon end.

The existing fields already distinguish the required meanings, so the wire values stay backward compatible:

| Shared meaning | Existing backend/API combination |
| --- | --- |
| `queued` | `status=queued` |
| `running` | `status=running` |
| `complete_with_events` | `status=complete`, `result_status=valid_non_empty`; at least one event is a non-synthetic `physics_assessment` with valid physics status and valid provenance |
| `valid_empty` | `status=complete`, `result_status=valid_empty`; no returned event passed physical validity, even if invalid assessment records are included for review |
| `partial` | `status=partial` or `result_status=partial` |
| `failed` | `status=failed`, or an API failure result with `completion_status=failed` |
| `stale` | Not a stored screening status. A restored archive is explicitly marked archived and rejected for new maneuver assessment with `STALE_JOB`. |
| `unavailable` | A requested job/event is missing or the result cannot be retrieved; the API response includes a reason code. |

An HTTP 200 response alone is not evidence of a valid event. Maneuver assessment requires a current complete job and an event whose stored trajectory status and provenance validity are both `valid`. Physical event PDFs resolve the exact event from the supplied job and event IDs and preserve the stored object IDs and provenance. The legacy `/api/reports/{event_id}.pdf` route is proxy-only; physical event requests receive `SCREENING_JOB_REQUIRED`. Proxy, synthetic, malformed, or physically invalid events are rejected at these operation boundaries.
