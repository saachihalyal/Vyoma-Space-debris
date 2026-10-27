from __future__ import annotations

import asyncio
import json
import hashlib
import io
import logging
import math
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sgp4.api import Satrec, WGS72
from sgp4.omm import initialize as initialize_omm, parse_xml as parse_omm_xml_document
from app.services.object_classification import classify_object


logger = logging.getLogger(__name__)
CELESTRAK_REFRESH_INTERVAL_SECONDS = 2 * 60 * 60
CELESTRAK_NONRETRYABLE_HTTP_CODES = {301, 403, 404}
CELESTRAK_CACHE_PATH = Path(__file__).resolve().parents[2] / "exports" / "celestrak-live-cache.json"


def _sanitize_exception_message(message: str, max_length: int = 500) -> str:
    """Remove URLs and common credential values before writing request errors to logs."""
    sanitized = re.sub(
        r"(?im)\b(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*[^\r\n]+",
        r"\1: [REDACTED]", message,
    )
    sanitized = re.sub(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [REDACTED]", sanitized)
    sanitized = re.sub(r"(?i)\bhttps?://[^\s'\"<>]+", "[URL]", sanitized)
    sanitized = re.sub(
        r"(?i)\b(password|passwd|token|access_token|authorization|cookie|api[_-]?key)\b\s*([=:])\s*[^\s,;]+",
        r"\1\2[REDACTED]", sanitized,
    )
    sanitized = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP_REDACTED]", sanitized)
    return sanitized[:max_length]


CELESTRAK_GROUPS = {
    "stations": "https://celestrak.org/NORAD/elements/gp.php?GROUP=STATIONS&FORMAT=XML",
    "visual": "https://celestrak.org/NORAD/elements/gp.php?GROUP=VISUAL&FORMAT=XML",
    "weather": "https://celestrak.org/NORAD/elements/gp.php?GROUP=WEATHER&FORMAT=XML",
    "geo": "https://celestrak.org/NORAD/elements/gp.php?GROUP=GEO&FORMAT=XML",
    "gps_ops": "https://celestrak.org/NORAD/elements/gp.php?GROUP=GPS-OPS&FORMAT=XML",
    "iridium_debris": "https://celestrak.org/NORAD/elements/gp.php?GROUP=IRIDIUM-33-DEBRIS&FORMAT=XML",
    "cosmos_debris": "https://celestrak.org/NORAD/elements/gp.php?GROUP=COSMOS-2251-DEBRIS&FORMAT=XML",
}


FALLBACK_TLES = """VANGUARD 1
1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753
2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667
ISS (ZARYA)
1 25544U 98067A   24001.00000000  .00016717  00000+0  10270-3 0  9003
2 25544  51.6400  22.5000 0006703  45.1000  31.2000 15.50000000400004
NOAA 19
1 33591U 09005A   24001.50000000  .00000110  00000+0  86100-4 0  9997
2 33591  99.1900  20.4000 0014500  73.1000 287.2000 14.12400000770003
GOES 16
1 41866U 16071A   24001.00000000 -.00000260  00000+0  00000+0 0  9994
2 41866   0.0300  80.1000 0001200  93.1000 211.5000  1.00270000 26002
GALILEO 5
1 40128U 14050A   24001.00000000 -.00000055  00000+0  00000+0 0  9991
2 40128  49.9000 121.0000 0003000  18.0000 342.0000  1.70474000 57009
IRIDIUM 33 DEB
1 33772U 97051DV  24001.00000000  .00000410  00000+0  12622-3 0  9991
2 33772  86.3900 183.9000 0018000 215.0000 145.0000 14.39000000750007
COSMOS 2251 DEB
1 34420U 93036SV  24001.00000000  .00000900  00000+0  23801-3 0  9996
2 34420  74.0000  13.7000 0021000  39.0000 321.0000 14.48000000780000
"""


@dataclass(frozen=True)
class TleRecord:
    name: str
    line1: str
    line2: str
    source_group: str
    source_type: str = "live"
    source_timestamp: str | None = None
    source_url: str | None = None
    retrieval_http_status: int | None = None
    raw_response_hash: str | None = None
    original_line1: str | None = None
    original_line2: str | None = None
    raw_record_hash: str | None = None
    object_type: str | None = None
    source_classification: str | None = None
    source_format: str = "TLE"
    omm_fields: dict[str, str] | None = None

    @property
    def element_epoch(self) -> str | None:
        if self.omm_fields:
            return self.omm_fields.get("EPOCH")
        return self.line1[18:32].strip() or None if len(self.line1) >= 32 else None

    @property
    def catalog_id(self) -> str | None:
        if self.omm_fields:
            return str(self.omm_fields.get("NORAD_CAT_ID", "")) or None
        return self.line1[2:7].strip() or None if len(self.line1) >= 7 else None

    @property
    def input_hash(self) -> str:
        source_elements = json.dumps(self.omm_fields, sort_keys=True, separators=(",", ":")) if self.omm_fields else f"{self.line1}\0{self.line2}"
        payload = "\0".join((self.name, self.source_format, source_elements)).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @property
    def normalized_record_hash(self) -> str:
        return self.input_hash

    @property
    def propagation_input_hash(self) -> str:
        source_elements = json.dumps(self.omm_fields, sort_keys=True, separators=(",", ":")) if self.omm_fields else f"{self.line1}\0{self.line2}"
        return hashlib.sha256(source_elements.encode("utf-8")).hexdigest()


class TleProvider:
    def __init__(
        self,
        ttl_seconds: int = CELESTRAK_REFRESH_INTERVAL_SECONDS,
        retry_attempts: int = 2,
        retry_state_path: Path | None = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.retry_attempts = max(1, retry_attempts)
        self._cached_live: list[TleRecord] | None = None
        self._fallback: list[TleRecord] | None = None
        self._cached_at = 0.0
        self._last_attempt_at = 0.0
        self._last_attempt_at_utc: str | None = None
        self._last_success_at: str | None = None
        self._last_error_code: str | None = None
        self._last_error_group: str | None = None
        self._status = "unavailable"
        self._accepted_record_count = 0
        self._rejected_record_count = 0
        self._last_response_status: int | None = None
        self._last_source_format: str | None = None
        self._last_source_group: str | None = None
        self._last_valid_empty = False
        self._refresh_lock = asyncio.Lock()
        self._retry_state_path = Path(retry_state_path) if retry_state_path is not None else None
        self._restore_persisted_state()

    @property
    def source(self) -> str:
        return self.source_state["source"]

    @property
    def source_type(self) -> str:
        return "live" if self._cached_live else "fallback" if self._fallback else "unavailable"

    @property
    def source_state(self) -> dict[str, str | int | float | bool | None]:
        labels = {
            "live": "CelesTrak live GP/OMM XML",
            "stale_live": "CelesTrak stale live cache",
            "fallback": "Bundled fallback TLE sample",
            "valid_empty": "CelesTrak returned a valid empty catalog",
            "unavailable": "Source unavailable",
        }
        age = self.latency_seconds if self._cached_at else None
        is_stale = self._status == "stale_live" or bool(
            self._cached_live and age is not None and age >= self.ttl_seconds
        )
        reported_status = "stale_live" if is_stale else self._status
        acquisition_status = "LIVE_PARTIAL" if (reported_status == "live" and self._last_error_code) else {
            "live": "FRESH_LIVE",
            "stale_live": "STALE_LIVE_CACHE",
            "fallback": "FALLBACK",
            "valid_empty": "VALID_EMPTY",
            "unavailable": "LIVE_ACQUISITION_FAILED",
        }[reported_status]
        return {
            "status": reported_status,
            "acquisition_status": acquisition_status,
            "source": labels[reported_status],
            "last_attempt_at": self._last_attempt_at_utc,
            "last_success_at": self._last_success_at,
            "last_error_code": self._last_error_code,
            "last_error_group": self._last_error_group,
            "last_response_status": self._last_response_status,
            "accepted_record_count": self._accepted_record_count if self._cached_live else len(self._fallback or []),
            "rejected_record_count": self._rejected_record_count,
            "source_format": self._last_source_format or ("TLE" if self._fallback else None),
            "source_group": self._last_source_group,
            "source_url": CELESTRAK_GROUPS.get(self._last_source_group or ""),
            "cache_age_seconds": round(age, 2) if age is not None else None,
            "stale": is_stale,
        }

    @property
    def latency_seconds(self) -> float:
        if not self._cached_at:
            return 0.0
        return max(0.0, time.time() - self._cached_at)

    async def get_catalog(self, limit: int = 900) -> list[TleRecord]:
        records, _ = await self.get_catalog_with_state(limit)
        return records

    async def get_catalog_with_state(self, limit: int = 900) -> tuple[list[TleRecord], dict[str, str | None]]:
        now = time.time()
        if self._cached_live:
            if not self._is_fresh(now):
                asyncio.create_task(self._refresh_live_background())
            return self._selected(limit), self.source_state
        failure_cooldown = self._failure_cooldown_seconds()
        if self._is_fresh(now):
            return self._selected(limit), self.source_state

        async with self._refresh_lock:
            now = time.time()
            if self._is_fresh(now):
                return self._selected(limit), self.source_state
            if self._last_attempt_at and now - self._last_attempt_at < failure_cooldown:
                self._ensure_fallback()
                return self._selected(limit), self.source_state

            self._last_attempt_at = now
            self._last_attempt_at_utc = datetime.now(timezone.utc).isoformat()
            fetched = await self._fetch_live()
            if fetched:
                self._cached_live = fetched
                self._cached_at = time.time()
                self._last_success_at = datetime.now(timezone.utc).isoformat()
                self._status = "live"
            elif self._cached_live:
                self._status = "stale_live"
                self._accepted_record_count = len(self._cached_live)
            elif self._last_valid_empty:
                self._status = "valid_empty"
            elif not self._fallback:
                self._ensure_fallback()
            self._persist_state()
            return self._selected(limit), self.source_state

    async def _refresh_live_background(self) -> None:
        if self._refresh_lock.locked():
            return
        async with self._refresh_lock:
            now = time.time()
            if self._is_fresh(now) or (self._last_attempt_at and now - self._last_attempt_at < self._failure_cooldown_seconds()):
                return
            self._last_attempt_at = now
            self._last_attempt_at_utc = datetime.now(timezone.utc).isoformat()
            fetched = await self._fetch_live()
            if fetched:
                self._cached_live = fetched
                self._cached_at = time.time()
                self._last_success_at = datetime.now(timezone.utc).isoformat()
                self._status = "live"
            elif self._cached_live:
                self._status = "stale_live"
            self._persist_state()

    def _is_fresh(self, now: float) -> bool:
        if self._cached_live:
            return self._status == "live" and now - self._cached_at < self.ttl_seconds
        return bool(self._fallback) and now - self._last_attempt_at < min(60, self.ttl_seconds)

    def _failure_cooldown_seconds(self) -> int:
        if self._last_error_code:
            # Do not turn any upstream failure into a tight retry loop. CelesTrak
            # publishes GP updates on a two-hour cadence and asks clients to cache.
            return max(self.ttl_seconds, CELESTRAK_REFRESH_INTERVAL_SECONDS)
        return min(60, self.ttl_seconds)

    def _ensure_fallback(self) -> None:
        if self._cached_live or self._fallback:
            return
        fetched_at = datetime.now(timezone.utc).isoformat()
        self._fallback = parse_tle_text(
            FALLBACK_TLES, "fallback", source_timestamp=fetched_at, source_type="fallback"
        )
        self._status = "fallback" if self._fallback else "unavailable"

    def _restore_persisted_state(self) -> None:
        if self._retry_state_path is None or not self._retry_state_path.exists():
            return
        try:
            payload = json.loads(self._retry_state_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != 1:
                return
            self._last_attempt_at_utc = payload.get("last_attempt_at")
            self._last_success_at = payload.get("last_success_at")
            self._last_error_code = payload.get("last_error_code")
            self._last_error_group = payload.get("last_error_group")
            self._last_response_status = payload.get("last_response_status")
            self._last_source_format = payload.get("source_format")
            self._last_source_group = payload.get("source_group")
            self._accepted_record_count = int(payload.get("accepted_record_count", 0))
            self._rejected_record_count = int(payload.get("rejected_record_count", 0))
            self._last_valid_empty = payload.get("status") == "valid_empty"
            if self._last_attempt_at_utc:
                parsed_attempt = datetime.fromisoformat(self._last_attempt_at_utc.replace("Z", "+00:00"))
                if parsed_attempt.tzinfo is not None and parsed_attempt.utcoffset() is not None:
                    self._last_attempt_at = parsed_attempt.timestamp()
            if self._last_success_at:
                parsed_success = datetime.fromisoformat(self._last_success_at.replace("Z", "+00:00"))
                if parsed_success.tzinfo is None or parsed_success.utcoffset() is None:
                    raise ValueError("persisted cache timestamp is not timezone-aware")
                records = [TleRecord(**item) for item in payload.get("records", []) if isinstance(item, dict)]
                records = [record for record in records if record.source_type == "live" and _valid_tle_record(record)]
                if records:
                    self._cached_live = records
                    self._accepted_record_count = len(records)
                    self._cached_at = parsed_success.timestamp()
            if self._cached_live:
                self._status = "live" if time.time() - self._cached_at < self.ttl_seconds else "stale_live"
        except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("Ignoring unreadable persisted CelesTrak cache: %s", _sanitize_exception_message(str(exc)))

    def _persist_state(self) -> None:
        if self._retry_state_path is None:
            return
        payload = {
            "version": 1,
            "last_attempt_at": self._last_attempt_at_utc,
            "last_success_at": self._last_success_at,
            "last_error_code": self._last_error_code,
            "last_error_group": self._last_error_group,
            "last_response_status": self._last_response_status,
            "accepted_record_count": self._accepted_record_count,
            "rejected_record_count": self._rejected_record_count,
            "source_format": self._last_source_format,
            "source_group": self._last_source_group,
            "status": self._status,
            "records": [asdict(record) for record in self._cached_live or []],
        }
        try:
            self._retry_state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self._retry_state_path.with_suffix(self._retry_state_path.suffix + ".tmp")
            temporary_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            temporary_path.replace(self._retry_state_path)
        except OSError as exc:
            logger.warning("Could not persist CelesTrak cache state: %s", _sanitize_exception_message(str(exc)))

    def _selected(self, limit: int) -> list[TleRecord]:
        records = self._cached_live or self._fallback or []
        return select_balanced_records(records, limit)

    async def _fetch_live(self) -> list[TleRecord]:
        timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
        results: list[tuple[str, list[TleRecord], str | None]] = []
        self._rejected_record_count = 0
        self._last_valid_empty = False
        self._last_error_group = None
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for group, url in CELESTRAK_GROUPS.items():
                group_records, error_code = await self._fetch_group(client, group, url)
                results.append((group, group_records, error_code))
                if error_code and any(
                    error_code.startswith(f"upstream_http_{status}")
                    for status in CELESTRAK_NONRETRYABLE_HTTP_CODES
                ):
                    self._last_error_group = group
                    break
        records_by_catalog_id: dict[str, TleRecord] = {}
        for _, group_records, _ in results:
            for record in group_records:
                catalog_id = record.catalog_id
                if not catalog_id:
                    self._rejected_record_count += 1
                    continue
                previous = records_by_catalog_id.get(catalog_id)
                if previous is None or _epoch_sort_key(record.element_epoch) > _epoch_sort_key(previous.element_epoch):
                    if previous is not None:
                        self._rejected_record_count += 1
                    records_by_catalog_id[catalog_id] = record
                else:
                    self._rejected_record_count += 1
        records = list(records_by_catalog_id.values())
        self._accepted_record_count = len(records)
        failures = [(group, code) for group, _, code in results if code and code != "valid_empty_response"]
        if not records:
            self._last_error_group = failures[0][0] if failures else None
            self._last_valid_empty = not failures and bool(results)
            self._last_error_code = failures[0][1] if failures else None
            return []
        # A valid subset is useful, but expose partial upstream failure for diagnosis.
        hard_failures = [(group, code) for group, code in failures if any(
            code.startswith(f"upstream_http_{status}") for status in CELESTRAK_NONRETRYABLE_HTTP_CODES
        )]
        if hard_failures:
            self._last_error_group, self._last_error_code = hard_failures[0]
        elif failures:
            self._last_error_group = failures[0][0]
            self._last_error_code = f"partial_upstream_failure_{len(failures)}_groups"
        else:
            self._last_error_group = None
            self._last_error_code = None
        return records

    async def _fetch_group(self, client: httpx.AsyncClient, group: str, url: str) -> tuple[list[TleRecord], str | None]:
        for attempt in range(self.retry_attempts):
            try:
                response = await client.get(url)
                self._last_response_status = response.status_code
                self._last_source_group = group
                self._last_source_format = "OMM-XML" if "FORMAT=XML" in url else "TLE"
                if response.status_code in CELESTRAK_NONRETRYABLE_HTTP_CODES:
                    headers = getattr(response, "headers", {})
                    diagnostic = _sanitize_exception_message(getattr(response, "text", ""), max_length=300)
                    logger.warning(
                        "CelesTrak non-retryable response group=%s status=%d content_type=%s diagnostic=%s",
                        group, response.status_code, headers.get("content-type", "unknown"), diagnostic or "[empty body]",
                    )
                    return [], f"upstream_http_{response.status_code}"
                if 300 <= response.status_code < 400:
                    return [], f"upstream_http_{response.status_code}"
                if response.status_code >= 500 or response.status_code in {408, 429}:
                    code = f"upstream_http_{response.status_code}"
                    if attempt + 1 < self.retry_attempts:
                        await asyncio.sleep(0.2 * (2 ** attempt))
                        continue
                    return [], code
                if response.status_code >= 400:
                    return [], f"upstream_http_{response.status_code}"
                retrieved_at = datetime.now(timezone.utc).isoformat()
                raw_bytes = getattr(response, "content", None)
                if raw_bytes is None:
                    raw_bytes = response.text.encode("utf-8")
                raw_hash = hashlib.sha256(raw_bytes).hexdigest()
                stripped = response.text.lstrip()
                if stripped.startswith("<"):
                    valid = parse_omm_xml(
                        response.content, group, source_timestamp=retrieved_at, source_url=url,
                        retrieval_http_status=response.status_code, raw_response_hash=raw_hash,
                    )
                    self._last_source_format = "OMM-XML"
                elif stripped.startswith("[") or stripped.startswith("{"):
                    valid = parse_omm_json(
                        response.text, group, source_timestamp=retrieved_at, source_url=url,
                        retrieval_http_status=response.status_code, raw_response_hash=raw_hash,
                    )
                    self._last_source_format = "OMM-JSON"
                else:
                    valid = [record for record in parse_tle_text(
                        response.text, group, source_timestamp=retrieved_at, source_url=url,
                        retrieval_http_status=response.status_code, raw_response_hash=raw_hash,
                    ) if _valid_tle_record(record)]
                    self._last_source_format = "TLE"
                if valid:
                    return valid, None
                return [], "valid_empty_response" if stripped in {"[]", "{}"} else "invalid_or_empty_response"
            except httpx.TimeoutException as exc:
                code = "upstream_timeout"
                logger.warning(
                    "CelesTrak request timeout group=%s attempt=%d/%d exception=%s message=%s",
                    group, attempt + 1, self.retry_attempts, type(exc).__name__,
                    _sanitize_exception_message(str(exc)),
                )
            except httpx.RequestError as exc:
                code = "upstream_network_error"
                logger.warning(
                    "CelesTrak request error group=%s attempt=%d/%d exception=%s message=%s",
                    group, attempt + 1, self.retry_attempts, type(exc).__name__,
                    _sanitize_exception_message(str(exc)),
                )
            except ValueError as exc:
                code = "invalid_omm_response" if "omm" in str(exc).lower() else "invalid_catalog_response"
                self._rejected_record_count += 1
                logger.warning("CelesTrak response parsing failed group=%s format=%s reason=%s", group, self._last_source_format, code)
            except Exception:
                code = "upstream_response_error"
            if attempt + 1 < self.retry_attempts:
                await asyncio.sleep(0.2 * (2 ** attempt))
        return [], code


def _valid_tle_record(record: TleRecord) -> bool:
    if record.omm_fields is not None:
        return _valid_omm_record(record)
    if record.original_line1 is not None and record.original_line1 != record.line1:
        return False
    if record.original_line2 is not None and record.original_line2 != record.line2:
        return False
    return _valid_tle_lines(record.line1, record.line2)


def _valid_tle_lines(line1: str, line2: str) -> bool:
    if len(line1) != 69 or len(line2) != 69:
        return False
    if line1[:2] != "1 " or line2[:2] != "2 ":
        return False
    if not (line1[2:7].isdigit() and line1[2:7] == line2[2:7]):
        return False
    if not re.fullmatch(r"[A-Z]", line1[7]) or line1[8] != " ":
        return False
    if not re.fullmatch(r"[ 0-9A-Z]{8}", line1[9:17]):
        return False
    if not re.fullmatch(r"\d{5}\.\d{8}", line1[18:32]):
        return False
    if not re.fullmatch(r" *[+\-]?\.\d{8}", line1[32:43]):
        return False
    if not re.fullmatch(r" *\d{5}[+\-]\d", line1[43:52]):
        return False
    if not re.fullmatch(r" *\d{5}[+\-]\d", line1[52:61]):
        return False
    if not line1[62].isdigit() or line1[63] != " " or not re.fullmatch(r" *\d{1,4}", line1[64:68]):
        return False
    if not line2[7].isspace() or not re.fullmatch(r" *\d{1,3}\.\d{4}", line2[8:16]):
        return False
    if not re.fullmatch(r" *\d{1,3}\.\d{4}", line2[17:25]):
        return False
    if not line2[26:33].isdigit():
        return False
    if not re.fullmatch(r" *\d{1,3}\.\d{4}", line2[34:42]):
        return False
    if not re.fullmatch(r" *\d{1,3}\.\d{4}", line2[43:51]):
        return False
    if not re.fullmatch(r" *\d{1,2}\.\d{8}", line2[52:63]):
        return False
    if not re.fullmatch(r" *\d{1,5}", line2[63:68]):
        return False
    return _tle_checksum_valid(line1) and _tle_checksum_valid(line2)


def _tle_checksum_valid(line: str) -> bool:
    return line[68].isdigit() and sum(int(char) if char.isdigit() else char == "-" for char in line[:68]) % 10 == int(line[68])


def parse_tle_text(
    text: str,
    group_name: str,
    *,
    source_timestamp: str | None = None,
    source_type: str | None = None,
    source_url: str | None = None,
    retrieval_http_status: int | None = None,
    raw_response_hash: str | None = None,
) -> list[TleRecord]:
    record_source_type = source_type or ("fallback" if group_name == "fallback" else "live")
    timestamp = source_timestamp or datetime.now(timezone.utc).isoformat()
    lines = [line for line in text.splitlines() if line.strip()]
    records: list[TleRecord] = []
    i = 0
    while i + 2 < len(lines):
        if lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            records.append(
                TleRecord(
                    name=lines[i].strip()[:80],
                    line1=lines[i + 1].strip(),
                    line2=lines[i + 2].strip(),
                    source_group=group_name,
                    source_type=record_source_type,
                    source_timestamp=timestamp,
                    source_url=source_url,
                    retrieval_http_status=retrieval_http_status,
                    raw_response_hash=raw_response_hash,
                    original_line1=lines[i + 1],
                    original_line2=lines[i + 2],
                    raw_record_hash=hashlib.sha256("\n".join(lines[i:i + 3]).encode("utf-8")).hexdigest(),
                )
            )
            i += 3
        else:
            i += 1
    return records


OMM_REQUIRED_FIELDS = (
    "OBJECT_NAME", "OBJECT_ID", "CENTER_NAME", "REF_FRAME", "TIME_SYSTEM",
    "MEAN_ELEMENT_THEORY", "EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION",
    "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY", "EPHEMERIS_TYPE",
    "CLASSIFICATION_TYPE", "NORAD_CAT_ID", "ELEMENT_SET_NO", "REV_AT_EPOCH",
    "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT",
)


def parse_omm_json(
    text: str,
    group_name: str,
    *,
    source_timestamp: str | None = None,
    source_type: str = "live",
    source_url: str | None = None,
    retrieval_http_status: int | None = None,
    raw_response_hash: str | None = None,
) -> list[TleRecord]:
    """Parse CelesTrak's documented GP JSON representation of OMM keywords.

    The full response is rejected on any malformed record or duplicate catalog
    identifier so a partial/bad payload cannot be mistaken for a valid catalog.
    """
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_omm_json") from exc
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise ValueError("omm_json_must_be_object_or_array")
    if not payload:
        return []
    return _records_from_omm_fields(
        payload, group_name, source_type=source_type, source_timestamp=source_timestamp,
        source_url=source_url, retrieval_http_status=retrieval_http_status,
        raw_response_hash=raw_response_hash, source_format="OMM-JSON",
    )


def parse_omm_xml(
    payload: bytes,
    group_name: str,
    *,
    source_timestamp: str | None = None,
    source_type: str = "live",
    source_url: str | None = None,
    retrieval_http_status: int | None = None,
    raw_response_hash: str | None = None,
) -> list[TleRecord]:
    """Parse CCSDS OMM XML using the installed SGP4 package's XML reader."""
    try:
        fields = list(parse_omm_xml_document(io.BytesIO(payload)))
    except Exception as exc:
        raise ValueError("invalid_omm_xml") from exc
    return _records_from_omm_fields(
        fields, group_name, source_type=source_type, source_timestamp=source_timestamp,
        source_url=source_url, retrieval_http_status=retrieval_http_status,
        raw_response_hash=raw_response_hash, source_format="OMM-XML",
    )


def _records_from_omm_fields(
    payload: list[dict],
    group_name: str,
    *,
    source_type: str,
    source_timestamp: str | None,
    source_url: str | None,
    retrieval_http_status: int | None,
    raw_response_hash: str | None,
    source_format: str,
) -> list[TleRecord]:
    timestamp = source_timestamp or datetime.now(timezone.utc).isoformat()
    records: list[TleRecord] = []
    identifiers: set[str] = set()
    for item in payload:
        if not isinstance(item, dict) or any(key not in item or item[key] is None for key in OMM_REQUIRED_FIELDS):
            raise ValueError("omm_record_missing_required_fields")
        fields = {key: str(item[key]).strip() for key in OMM_REQUIRED_FIELDS}
        catalog_id = fields["NORAD_CAT_ID"]
        if not re.fullmatch(r"\d{1,9}", catalog_id) or int(catalog_id) <= 0:
            raise ValueError("invalid_omm_catalog_id")
        if catalog_id in identifiers:
            raise ValueError("duplicate_omm_catalog_id")
        identifiers.add(catalog_id)
        record = TleRecord(
            name=fields["OBJECT_NAME"][:80], line1="", line2="", source_group=group_name,
            source_type=source_type, source_timestamp=timestamp, source_url=source_url,
            retrieval_http_status=retrieval_http_status, raw_response_hash=raw_response_hash,
            raw_record_hash=hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            object_type=str(item.get("OBJECT_TYPE") or item.get("OBJECT_TYPE_CODE") or "").strip() or None,
            source_format=source_format, omm_fields=fields,
        )
        if not _valid_omm_record(record):
            raise ValueError("invalid_omm_record_values")
        records.append(record)
    return records


def _valid_omm_record(record: TleRecord) -> bool:
    fields = record.omm_fields
    if not fields or any(not fields.get(key) for key in OMM_REQUIRED_FIELDS):
        return False
    if fields["CENTER_NAME"].upper() != "EARTH" or fields["REF_FRAME"].upper() != "TEME":
        return False
    if fields["TIME_SYSTEM"].upper() != "UTC" or fields["MEAN_ELEMENT_THEORY"].upper() != "SGP4":
        return False
    if fields["CLASSIFICATION_TYPE"].upper() not in {"U", "C", "S"}:
        return False
    try:
        epoch = datetime.fromisoformat(fields["EPOCH"].replace("Z", "+00:00"))
        if epoch.tzinfo is None or epoch.utcoffset() is None:
            # OMM EPOCH is interpreted using the required TIME_SYSTEM field;
            # CelesTrak's UTC JSON commonly emits the timestamp without a Z.
            if fields["TIME_SYSTEM"].upper() != "UTC":
                return False
            epoch = epoch.replace(tzinfo=timezone.utc)
        numeric = {key: float(fields[key]) for key in (
            "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE",
            "ARG_OF_PERICENTER", "MEAN_ANOMALY", "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT",
        )}
        if not all(math.isfinite(value) for value in numeric.values()):
            return False
        if not (0.0 < numeric["MEAN_MOTION"] <= 20.0 and 0.0 <= numeric["ECCENTRICITY"] < 1.0):
            return False
        if not (0.0 <= numeric["INCLINATION"] <= 180.0):
            return False
        if any(not 0.0 <= numeric[key] < 360.0 for key in ("RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY")):
            return False
        if any(not re.fullmatch(r"\d+", fields[key]) for key in ("EPHEMERIS_TYPE", "ELEMENT_SET_NO", "REV_AT_EPOCH")):
            return False
        # Verify that the installed SGP4 OMM initializer accepts the supplied
        # required values and preserves the full NORAD catalog number.
        normalized = dict(fields)
        normalized["EPOCH"] = epoch.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
        sat = Satrec()
        initialize_omm(sat, normalized, WGS72)
        return str(sat.satnum) == fields["NORAD_CAT_ID"]
    except (ValueError, TypeError, OverflowError, KeyError):
        return False


def satellite_from_record(record: TleRecord) -> Satrec:
    if record.omm_fields is None:
        return Satrec.twoline2rv(record.line1, record.line2, WGS72)
    if not _valid_omm_record(record):
        raise ValueError("invalid_omm_record")
    fields = dict(record.omm_fields)
    epoch = datetime.fromisoformat(fields["EPOCH"].replace("Z", "+00:00"))
    if epoch.tzinfo is None or epoch.utcoffset() is None:
        if fields["TIME_SYSTEM"].upper() != "UTC":
            raise ValueError("unsupported_omm_time_system")
        epoch = epoch.replace(tzinfo=timezone.utc)
    fields["EPOCH"] = epoch.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    sat = Satrec()
    initialize_omm(sat, fields, WGS72)
    return sat


def _epoch_sort_key(value: str | None) -> float:
    if not value:
        return float("-inf")
    try:
        epoch = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if epoch.tzinfo is None:
            epoch = epoch.replace(tzinfo=timezone.utc)
        return epoch.timestamp()
    except ValueError:
        return float("-inf")


def select_balanced_records(records: list[TleRecord], limit: int) -> list[TleRecord]:
    if len(records) <= limit:
        return records

    debris = [record for record in records if is_debris_record(record)]
    active = [record for record in records if not is_debris_record(record)]
    if not debris:
        return round_robin_by_group(active, limit)

    debris_target = min(len(debris), max(limit // 4, min(limit // 3, len(debris))))
    active_target = max(0, limit - debris_target)
    selected = round_robin_by_group(active, active_target) + round_robin_by_group(debris, debris_target)

    if len(selected) < limit:
        selected_ids = {(record.name, record.line1) for record in selected}
        for record in records:
            key = (record.name, record.line1)
            if key not in selected_ids:
                selected.append(record)
                selected_ids.add(key)
            if len(selected) >= limit:
                break

    return selected[:limit]


def is_debris_record(record: TleRecord) -> bool:
    return classify_object(
        object_type=record.object_type,
        source_classification=record.source_classification,
        source_group=record.source_group,
        name=record.name,
    ).category == "debris"


def round_robin_by_group(records: list[TleRecord], limit: int) -> list[TleRecord]:
    groups: dict[str, list[TleRecord]] = {}
    for record in records:
        groups.setdefault(record.source_group, []).append(record)

    selected: list[TleRecord] = []
    cursors = {group: 0 for group in groups}
    group_names = sorted(groups)
    while len(selected) < limit:
        added = False
        for group in group_names:
            index = cursors[group]
            if index < len(groups[group]):
                selected.append(groups[group][index])
                cursors[group] += 1
                added = True
                if len(selected) >= limit:
                    break
        if not added:
            break
    return selected
