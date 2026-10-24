"""Authenticated, rate-limited retrieval of event-specific Space-Track CDMs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
from typing import Any
from urllib.parse import quote

import httpx


logger = logging.getLogger(__name__)
SPACE_TRACK_BASE = "https://www.space-track.org"
LOGIN_URL = f"{SPACE_TRACK_BASE}/ajaxauth/login"
PUBLIC_CDM_URL = f"{SPACE_TRACK_BASE}/basicspacedata/query/class/cdm_public"
FULL_CDM_URL = f"{SPACE_TRACK_BASE}/expandedspacedata/query/class/cdm/CONSTELLATION/ALL"
EVENT_TCA_MATCH_TOLERANCE_SECONDS = 60
EVENT_QUERY_TCA_WINDOW_SECONDS = 5 * 60
EVENT_REQUEST_COOLDOWN_SECONDS = 60 * 60
GLOBAL_REQUESTS_PER_MINUTE = 30
GLOBAL_REQUESTS_PER_HOUR = 300
MAX_CDM_SUMMARIES = 200
MAX_CDM_BYTES = 1_000_000
DEFAULT_STATE_PATH = Path(__file__).resolve().parents[2] / "exports" / "spacetrack-cdm-throttle.json"


@dataclass(frozen=True)
class SpaceTrackCdmOutcome:
    status: str
    reason_code: str | None = None
    message: str = ""
    source: str = "Space-Track"
    retrieved_at_utc: str | None = None
    cdm_id: str | None = None
    cdm_text: str | None = None
    candidate_tca_utc: str | None = None
    upstream_status: int | None = None


class SpaceTrackCdmProvider:
    """Fetch a full CDM only after a bounded exact-pair/TCA summary lookup.

    Space-Track credentials and event/global request accounting are never put
    in logs or the throttle state file. The state file contains only hashed
    event keys and request timestamps.
    """

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        state_path: Path | None = None,
        clock=time.time,
    ) -> None:
        self._transport = transport
        self._state_path = Path(state_path) if state_path else DEFAULT_STATE_PATH
        self._clock = clock
        self._lock = threading.Lock()

    def retrieve_for_event(self, event: Any) -> SpaceTrackCdmOutcome:
        identity = os.environ.get("SPACE_TRACK_IDENTITY", "").strip()
        password = os.environ.get("SPACE_TRACK_PASSWORD", "")
        if not identity or not password:
            return SpaceTrackCdmOutcome(
                status="not_configured",
                reason_code="SPACETRACK_CREDENTIALS_NOT_CONFIGURED",
                message="Set SPACE_TRACK_IDENTITY and SPACE_TRACK_PASSWORD to enable authenticated CDM retrieval.",
            )

        try:
            object_1 = _catalog_id(event.primary.id)
            object_2 = _catalog_id(event.secondary.id)
            tca = _parse_utc(event.physics_result.tca.value)
        except (AttributeError, TypeError, ValueError):
            return SpaceTrackCdmOutcome(
                status="unavailable", reason_code="EVENT_IDENTITY_OR_TCA_UNAVAILABLE",
                message="The selected physical event has no valid object IDs or UTC TCA.",
            )
        if object_1 == object_2:
            return SpaceTrackCdmOutcome(
                status="unavailable", reason_code="EVENT_OBJECT_IDS_NOT_DISTINCT",
                message="The selected event does not contain two distinct catalog IDs.",
            )

        event_key = hashlib.sha256(
            "|".join(sorted((object_1, object_2)) + [tca.isoformat()]).encode("utf-8")
        ).hexdigest()
        now = self._clock()
        throttle_error = self._reserve_requests(event_key, now, expected_requests=3)
        if throttle_error:
            return throttle_error

        retrieved_at = datetime.fromtimestamp(now, timezone.utc).isoformat()
        timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, transport=self._transport) as client:
                login = client.post(LOGIN_URL, data={"identity": identity, "password": password})
                if login.status_code in {401, 403}:
                    return _outcome("authentication_failed", "SPACETRACK_AUTHENTICATION_FAILED", "Space-Track did not establish an authenticated session.", retrieved_at, login.status_code)
                if login.status_code >= 400:
                    return _http_outcome(login.status_code, retrieved_at)
                if "chocolatechip" not in client.cookies:
                    return _outcome("authentication_failed", "SPACETRACK_AUTHENTICATION_FAILED", "Space-Track did not establish an authenticated session.", retrieved_at, login.status_code)

                lower = (tca - timedelta(seconds=EVENT_QUERY_TCA_WINDOW_SECONDS)).strftime("%Y-%m-%d %H:%M:%S")
                upper = (tca + timedelta(seconds=EVENT_QUERY_TCA_WINDOW_SECONDS)).strftime("%Y-%m-%d %H:%M:%S")
                id_values = f"{quote(object_1, safe='')},{quote(object_2, safe='')}"
                range_value = f"{quote(lower, safe=':-') }--{quote(upper, safe=':-')}"
                summary_url = (
                    f"{PUBLIC_CDM_URL}/SAT_1_ID/{id_values}/SAT_2_ID/{id_values}"
                    f"/TCA/{range_value}/orderby/TCA%20asc/limit/{MAX_CDM_SUMMARIES}/format/json"
                )
                summary_response = client.get(summary_url)
                if summary_response.status_code >= 400:
                    return _http_outcome(summary_response.status_code, retrieved_at)
                try:
                    summaries = summary_response.json()
                except (ValueError, json.JSONDecodeError):
                    return _outcome("invalid_response", "SPACETRACK_SUMMARY_INVALID", "Space-Track returned an unreadable CDM summary response.", retrieved_at, summary_response.status_code)
                if not isinstance(summaries, list):
                    return _outcome("invalid_response", "SPACETRACK_SUMMARY_INVALID", "Space-Track returned an unexpected CDM summary structure.", retrieved_at, summary_response.status_code)
                candidates = _matching_summaries(summaries, object_1, object_2, tca)
                if not candidates:
                    return _outcome("no_match", "SPACETRACK_CDM_NOT_FOUND", "No CDM summary matched both object IDs and the selected event TCA window.", retrieved_at, summary_response.status_code)

                candidate = candidates[0]
                cdm_id = str(candidate.get("CDM_ID", "")).strip()
                if not re.fullmatch(r"\d{1,20}", cdm_id):
                    return _outcome("invalid_response", "SPACETRACK_CDM_ID_INVALID", "The matching summary did not contain a valid CDM identifier.", retrieved_at)
                full_url = f"{FULL_CDM_URL}/CDM_ID/{quote(cdm_id, safe='')}/format/xml/emptyresult/show"
                full_response = client.get(full_url, headers={"Accept": "application/xml, text/xml"})
                if full_response.status_code >= 400:
                    return _http_outcome(full_response.status_code, retrieved_at)
                if len(full_response.content) > MAX_CDM_BYTES:
                    return _outcome("invalid_cdm", "CDM_XML_TOO_LARGE", "The retrieved CDM exceeds ORION's 1 MB input limit.", retrieved_at, full_response.status_code, cdm_id=cdm_id)
                content_type = full_response.headers.get("content-type", "").lower()
                if "html" in content_type or full_response.text.lstrip().lower().startswith(("<!doctype html", "<html")):
                    return _outcome("authorization_required", "SPACETRACK_FULL_CDM_ACCESS_REQUIRED", "The account could query the summary but could not retrieve the full covariance-bearing CDM.", retrieved_at, full_response.status_code, cdm_id=cdm_id)
                return SpaceTrackCdmOutcome(
                    status="retrieved", reason_code=None,
                    message="A full Space-Track CDM was retrieved for event validation.",
                    retrieved_at_utc=retrieved_at,
                    cdm_id=cdm_id,
                    cdm_text=full_response.text,
                    candidate_tca_utc=str(candidate.get("TCA") or "") or None,
                    upstream_status=full_response.status_code,
                )
        except httpx.TimeoutException:
            return _outcome("timeout", "SPACETRACK_REQUEST_TIMEOUT", "The Space-Track request timed out; retry after the event cooldown.", retrieved_at)
        except httpx.RequestError:
            return _outcome("unavailable", "SPACETRACK_NETWORK_ERROR", "Space-Track could not be reached; request details were not logged.", retrieved_at)

    def _reserve_requests(self, event_key: str, now: float, *, expected_requests: int) -> SpaceTrackCdmOutcome | None:
        with self._lock:
            try:
                state = self._read_state()
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return _outcome("unavailable", "SPACETRACK_THROTTLE_STATE_UNAVAILABLE", "Local Space-Track rate-limit state is unavailable; no request was sent.")
            event_last = state.get("events", {}).get(event_key)
            if isinstance(event_last, (int, float)) and now - float(event_last) < EVENT_REQUEST_COOLDOWN_SECONDS:
                remaining = int(EVENT_REQUEST_COOLDOWN_SECONDS - (now - float(event_last)))
                return _outcome("rate_limited", "SPACETRACK_EVENT_COOLDOWN", f"This conjunction was queried recently. Try again in about {remaining} seconds.")
            requests = [float(value) for value in state.get("requests", []) if isinstance(value, (int, float))]
            requests = [value for value in requests if 0 <= now - value < 3600]
            recent_minute = sum(now - value < 60 for value in requests)
            if recent_minute + expected_requests >= GLOBAL_REQUESTS_PER_MINUTE or len(requests) + expected_requests >= GLOBAL_REQUESTS_PER_HOUR:
                return _outcome("rate_limited", "SPACETRACK_GLOBAL_COOLDOWN", "ORION's conservative Space-Track request limit is reached; retry later.")
            state["events"][event_key] = now
            state["requests"] = requests + [now] * expected_requests
            try:
                self._write_state(state)
            except OSError:
                return _outcome("unavailable", "SPACETRACK_THROTTLE_STATE_UNAVAILABLE", "Rate-limit state could not be saved; no request was sent.")
        return None

    def _read_state(self) -> dict[str, Any]:
        if not self._state_path.exists():
            return {"version": 1, "events": {}, "requests": []}
        payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("invalid throttle state")
        if not isinstance(payload.get("events", {}), dict) or not isinstance(payload.get("requests", []), list):
            raise ValueError("invalid throttle state")
        return payload

    def _write_state(self, payload: dict[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        temporary_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temporary_path.replace(self._state_path)


def _matching_summaries(summaries: list[Any], object_1: str, object_2: str, event_tca: datetime) -> list[dict[str, Any]]:
    matches = []
    wanted = {_catalog_id(object_1), _catalog_id(object_2)}
    for item in summaries:
        if not isinstance(item, dict):
            continue
        try:
            ids = {_catalog_id(item.get("SAT_1_ID")), _catalog_id(item.get("SAT_2_ID"))}
            tca = _parse_utc(item.get("TCA"))
        except (TypeError, ValueError):
            continue
        if ids != wanted or abs((tca - event_tca).total_seconds()) > EVENT_TCA_MATCH_TOLERANCE_SECONDS:
            continue
        if not re.fullmatch(r"\d{1,20}", str(item.get("CDM_ID", ""))):
            continue
        matches.append(item)
    return sorted(matches, key=lambda item: (
        abs((_parse_utc(item["TCA"]) - event_tca).total_seconds()),
        str(item.get("CREATED", "")),
    ))


def _catalog_id(value: Any) -> str:
    if value is None or isinstance(value, bool):
        raise ValueError("catalog id unavailable")
    text = str(value).strip()
    if not text:
        raise ValueError("catalog id unavailable")
    if text.isdigit():
        return str(int(text))
    return text


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("UTC timestamp unavailable")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("UTC timestamp must have an offset")
    return parsed.astimezone(timezone.utc)


def _http_outcome(status: int, retrieved_at: str | None) -> SpaceTrackCdmOutcome:
    if status == 401:
        return _outcome("authentication_failed", "SPACETRACK_AUTHENTICATION_FAILED", "Space-Track rejected the authenticated session.", retrieved_at, status)
    if status == 403:
        return _outcome("authorization_required", "SPACETRACK_CDM_ACCESS_REQUIRED", "This account is not authorized to access the requested CDM data.", retrieved_at, status)
    if status == 429:
        return _outcome("rate_limited", "SPACETRACK_RATE_LIMITED", "Space-Track rate-limited this request; retry later.", retrieved_at, status)
    return _outcome("upstream_error", "SPACETRACK_UPSTREAM_HTTP_ERROR", f"Space-Track returned HTTP {status}.", retrieved_at, status)


def _outcome(status: str, reason_code: str, message: str, retrieved_at: str | None = None, upstream_status: int | None = None, *, cdm_id: str | None = None) -> SpaceTrackCdmOutcome:
    logger.info("Space-Track CDM retrieval status=%s reason=%s", status, reason_code)
    return SpaceTrackCdmOutcome(
        status=status, reason_code=reason_code, message=message,
        retrieved_at_utc=retrieved_at, upstream_status=upstream_status, cdm_id=cdm_id,
    )
