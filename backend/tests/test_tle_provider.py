from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

from app.services.tle_provider import (
    CELESTRAK_GROUPS, FALLBACK_TLES, TleProvider, _valid_tle_record,
    parse_omm_json, parse_omm_xml, parse_tle_text, satellite_from_record,
)


def omm_record(catalog_id="100123"):
    return {
        "OBJECT_NAME": "NEW OBJECT",
        "OBJECT_ID": "2026-123A",
        "CENTER_NAME": "EARTH",
        "REF_FRAME": "TEME",
        "TIME_SYSTEM": "UTC",
        "MEAN_ELEMENT_THEORY": "SGP4",
        "EPOCH": "2026-10-18T12:34:56.123456",
        "MEAN_MOTION": "15.2",
        "ECCENTRICITY": "0.001",
        "INCLINATION": "51.6",
        "RA_OF_ASC_NODE": "120.0",
        "ARG_OF_PERICENTER": "40.0",
        "MEAN_ANOMALY": "210.0",
        "EPHEMERIS_TYPE": "0",
        "CLASSIFICATION_TYPE": "U",
        "NORAD_CAT_ID": str(catalog_id),
        "ELEMENT_SET_NO": "1",
        "REV_AT_EPOCH": "10",
        "BSTAR": "0.0001",
        "MEAN_MOTION_DOT": "0.00001",
        "MEAN_MOTION_DDOT": "0.0",
    }


def omm_xml(catalog_id="100123"):
    fields = omm_record(catalog_id)
    metadata = ("OBJECT_NAME", "OBJECT_ID", "CENTER_NAME", "REF_FRAME", "TIME_SYSTEM", "MEAN_ELEMENT_THEORY")
    mean_elements = ("EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY")
    tle_parameters = ("EPHEMERIS_TYPE", "CLASSIFICATION_TYPE", "NORAD_CAT_ID", "ELEMENT_SET_NO", "REV_AT_EPOCH", "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT")
    def part(tag, names):
        return f"<{tag}>" + "".join(f"<{key}>{fields[key]}</{key}>" for key in names) + f"</{tag}>"
    return "<omm><body><segment>" + part("metadata", metadata) + "<data>" + part("meanElements", mean_elements) + part("tleParameters", tle_parameters) + "</data></segment></body></omm>"


class _Response:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")


class _Client:
    behavior = None
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        type(self).calls += 1
        value = type(self).behavior(url)
        if asyncio.iscoroutine(value):
            value = await value
        return value


class TleProviderLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _Client.calls = 0

    def _use(self, behavior):
        _Client.behavior = behavior
        return patch("app.services.tle_provider.httpx.AsyncClient", _Client)

    async def test_valid_live_response_is_accepted(self):
        with self._use(lambda _url: _Response(200, FALLBACK_TLES)):
            records, state = await TleProvider().get_catalog_with_state(20)
        self.assertGreater(len(records), 0)
        self.assertEqual(state["status"], "live")
        self.assertTrue(all(item.source_type == "live" for item in records))
        self.assertIsNotNone(state["last_success_at"])
        self.assertTrue(all(item.source_url and item.retrieval_http_status == 200 for item in records))
        self.assertTrue(all(item.raw_response_hash and item.raw_record_hash for item in records))

    async def test_documented_gp_omm_xml_url_parses_and_preserves_large_catalog_id(self):
        payload = omm_xml()
        with self._use(lambda _url: _Response(200, payload)):
            records, state = await TleProvider().get_catalog_with_state(20)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].catalog_id, "100123")
        self.assertEqual(records[0].source_format, "OMM-XML")
        self.assertEqual(records[0].omm_fields["OBJECT_ID"], "2026-123A")
        self.assertEqual(state["status"], "live")
        self.assertEqual(state["source_format"], "OMM-XML")
        self.assertEqual(state["accepted_record_count"], 1)
        self.assertEqual(state["last_response_status"], 200)
        self.assertEqual(records[0].source_url, next(iter(CELESTRAK_GROUPS.values())))
        sat = satellite_from_record(records[0])
        self.assertEqual(sat.satnum, 100123)

    async def test_valid_omm_json_keywords_are_supported_when_metadata_is_present(self):
        record = parse_omm_json(json.dumps([omm_record()]), "fixture")[0]
        self.assertEqual(record.catalog_id, "100123")
        self.assertEqual(record.source_format, "OMM-JSON")
        self.assertTrue(_valid_tle_record(record))
        xml_record = parse_omm_xml(omm_xml().encode(), "fixture")[0]
        self.assertEqual(xml_record.catalog_id, "100123")
        self.assertEqual(xml_record.source_format, "OMM-XML")

    async def test_httpx_transport_success_sets_live_provenance_and_persists_cache(self):
        requested_urls = []
        response_text = FALLBACK_TLES

        def handler(request):
            requested_urls.append(str(request.url))
            return httpx.Response(200, text=response_text, headers={"content-type": "text/plain"}, request=request)

        transport = httpx.MockTransport(handler)
        real_async_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            self.assertFalse(kwargs["follow_redirects"])
            self.assertEqual(kwargs["timeout"].connect, 5.0)
            self.assertEqual(kwargs["timeout"].read, 15.0)
            return real_async_client(*args, transport=transport, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "celestrak-cache.json"
            with patch("app.services.tle_provider.httpx.AsyncClient", side_effect=client_factory):
                provider = TleProvider(retry_state_path=state_path)
                records, state = await provider.get_catalog_with_state(100)

                restored = TleProvider(retry_state_path=state_path)
                restored_records, restored_state = await restored.get_catalog_with_state(100)

            self.assertEqual(requested_urls, list(CELESTRAK_GROUPS.values()))
            self.assertTrue(records)
            self.assertEqual(state["status"], "live")
            self.assertEqual(state["acquisition_status"], "FRESH_LIVE")
            self.assertIsNotNone(state["last_success_at"])
            self.assertTrue(all(record.source_type == "live" for record in records))
            self.assertTrue(all(record.source_url in CELESTRAK_GROUPS.values() for record in records))
            self.assertTrue(all(record.retrieval_http_status == 200 for record in records))
            self.assertEqual(restored_state["status"], "live")
            self.assertEqual(restored_state["last_success_at"], state["last_success_at"])
            self.assertEqual([record.input_hash for record in restored_records], [record.input_hash for record in records])

    async def test_persisted_timeout_suppresses_attempt_until_two_hour_cooldown_expires(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "celestrak-cache.json"
            attempted_at = datetime.now(timezone.utc).isoformat()
            state_path.write_text(json.dumps({
                "version": 1,
                "last_attempt_at": attempted_at,
                "last_success_at": None,
                "last_error_code": "upstream_timeout",
                "last_error_group": "stations",
                "records": [],
            }), encoding="utf-8")

            with self._use(lambda _url: self.fail("the persisted timeout cooldown must prevent a new request")):
                records, state = await TleProvider(retry_attempts=1, retry_state_path=state_path).get_catalog_with_state(20)

        self.assertTrue(records)
        self.assertTrue(all(record.source_type == "fallback" for record in records))
        self.assertEqual(_Client.calls, 0)
        self.assertEqual(state["status"], "fallback")
        self.assertEqual(state["acquisition_status"], "FALLBACK")
        self.assertEqual(state["last_error_code"], "upstream_timeout")
        self.assertEqual(state["last_attempt_at"], attempted_at)
        self.assertIsNone(state["last_success_at"])

    async def test_records_retain_raw_and_normalized_source_identity(self):
        url = "https://example.test/catalog"
        captured = "VANGUARD 1\n" + FALLBACK_TLES.splitlines()[1] + "\n" + FALLBACK_TLES.splitlines()[2] + "\n"
        record = parse_tle_text(captured, "fixture", source_timestamp="2026-10-13T00:00:00Z", source_url=url,
                                retrieval_http_status=200, raw_response_hash="response-digest")[0]
        self.assertTrue(_valid_tle_record(record))
        self.assertFalse(_valid_tle_record(replace(record, original_line1=" " + record.line1)),
                         "surrounding whitespace must not be silently normalized into a valid TLE")
        self.assertEqual(record.source_url, url)
        self.assertEqual(record.retrieval_http_status, 200)
        self.assertEqual(record.raw_response_hash, "response-digest")
        self.assertEqual(record.original_line1, FALLBACK_TLES.splitlines()[1])
        self.assertEqual(record.normalized_record_hash, record.input_hash)
        self.assertNotEqual(record.raw_record_hash, record.normalized_record_hash)

    async def test_invalid_length_field_and_checksum_are_rejected(self):
        name, line1, line2 = FALLBACK_TLES.splitlines()[:3]
        for bad1, bad2 in ((line1[:-1], line2), (line1[:7] + "!" + line1[8:], line2),
                           (line1[:-1] + str((int(line1[-1]) + 1) % 10), line2),
                           (line1, line2[:2] + "99999" + line2[7:])):
            with self.subTest(line1=bad1, line2=bad2):
                record = parse_tle_text(f"{name}\n{bad1}\n{bad2}", "fixture")[0]
                self.assertFalse(_valid_tle_record(record))

    async def test_omm_malformed_missing_and_duplicate_records_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_omm_json"):
            parse_omm_json("{bad json", "fixture")
        missing = omm_record()
        del missing["MEAN_MOTION"]
        with self.assertRaisesRegex(ValueError, "missing_required_fields"):
            parse_omm_json(json.dumps([missing]), "fixture")
        with self.assertRaisesRegex(ValueError, "duplicate_omm_catalog_id"):
            parse_omm_json(json.dumps([omm_record(), omm_record()]), "fixture")
        malformed = omm_record()
        malformed["ECCENTRICITY"] = "1.2"
        with self.assertRaisesRegex(ValueError, "invalid_omm_record_values"):
            parse_omm_json(json.dumps([malformed]), "fixture")
        with self.assertRaisesRegex(ValueError, "invalid_omm_xml"):
            parse_omm_xml(b"<omm><segment>", "fixture")
        missing_xml = omm_xml().replace("<REF_FRAME>TEME</REF_FRAME>", "")
        with self.assertRaisesRegex(ValueError, "missing_required_fields"):
            parse_omm_xml(missing_xml.encode(), "fixture")
        duplicate_xml = omm_xml()[:-len("</omm>")] + omm_xml()[len("<omm>"):]
        with self.assertRaisesRegex(ValueError, "duplicate_omm_catalog_id"):
            parse_omm_xml(duplicate_xml.encode(), "fixture")

    async def test_omm_source_requires_supported_frame_and_sgp4_theory(self):
        for key, value in (("REF_FRAME", "GCRF"), ("MEAN_ELEMENT_THEORY", "OTHER"), ("TIME_SYSTEM", "TAI")):
            payload = omm_record()
            payload[key] = value
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, "invalid_omm_record_values"):
                parse_omm_json(json.dumps([payload]), "fixture")

    async def test_duplicate_records_across_groups_are_deduplicated(self):
        with self._use(lambda _url: _Response(200, FALLBACK_TLES)):
            records, _ = await TleProvider().get_catalog_with_state(100)
        self.assertEqual(len(records), len(parse_tle_text(FALLBACK_TLES, "fixture")))
        self.assertEqual(len({(r.line1[2:7], r.line1, r.line2) for r in records}), len(records))

    async def test_invalid_refresh_preserves_last_known_good_live_cache(self):
        provider = TleProvider()
        with self._use(lambda _url: _Response(200, FALLBACK_TLES)):
            original, _ = await provider.get_catalog_with_state(20)
        provider._cached_at = 0
        provider._last_attempt_at = 0
        with self._use(lambda _url: _Response(200, "<html>maintenance</html>")):
            records, state = await provider.get_catalog_with_state(20)
        self.assertEqual([r.input_hash for r in records], [r.input_hash for r in original])
        self.assertEqual(state["status"], "stale_live")
        self.assertEqual(state["last_error_code"], "invalid_or_empty_response")
        self.assertTrue(all(item.source_type == "live" for item in records))

    async def test_failed_refresh_serves_stale_live_provenance(self):
        provider = TleProvider()
        with self._use(lambda _url: _Response(200, FALLBACK_TLES)):
            await provider.get_catalog_with_state(20)
        provider._cached_at = 0
        provider._last_attempt_at = 0
        with self._use(lambda _url: _Response(503, "upstream detail")):
            records, state = await provider.get_catalog_with_state(20)
        self.assertEqual(state["status"], "stale_live")
        self.assertTrue(state["last_error_code"].startswith("upstream_http_503"))
        self.assertTrue(all(r.source_type == "live" for r in records))

    async def test_fallback_is_explicit_and_never_marked_live(self):
        with self._use(lambda _url: _Response(503, "unavailable")):
            records, state = await TleProvider().get_catalog_with_state(20)
        self.assertEqual(state["status"], "fallback")
        self.assertEqual(state["acquisition_status"], "FALLBACK")
        self.assertFalse(state["stale"])
        self.assertIn("Bundled fallback", state["source"])
        self.assertTrue(all(r.source_type == "fallback" for r in records))

    async def test_partial_live_refresh_keeps_success_and_group_failure_status(self):
        def one_group_fails(url):
            return _Response(503, "temporarily unavailable") if "GROUP=STATIONS" in url else _Response(200, FALLBACK_TLES)

        with self._use(one_group_fails):
            records, state = await TleProvider().get_catalog_with_state(20)
        self.assertTrue(records)
        self.assertEqual(state["status"], "live")
        self.assertEqual(state["acquisition_status"], "LIVE_PARTIAL")
        self.assertEqual(state["last_error_code"], "partial_upstream_failure_1_groups")
        self.assertIsNotNone(state["last_success_at"])
        self.assertIsNotNone(state["cache_age_seconds"])

    async def test_successful_catalog_is_not_refetched_before_the_two_hour_update_interval(self):
        provider = TleProvider()
        with self._use(lambda _url: _Response(200, FALLBACK_TLES)):
            records, state = await provider.get_catalog_with_state(20)
            self.assertTrue(records)
            self.assertEqual(state["status"], "live")
            self.assertEqual(_Client.calls, len(CELESTRAK_GROUPS))
            provider._cached_at -= 30 * 60
            _, cached_state = await provider.get_catalog_with_state(20)

        self.assertEqual(_Client.calls, len(CELESTRAK_GROUPS))
        self.assertEqual(cached_state["status"], "live")

    async def test_403_stops_group_requests_and_backs_off_for_two_hours(self):
        provider = TleProvider()

        def blocked(_url):
            return _Response(403, "GP data blocked for 192.0.2.17; wait before retrying")

        with self._use(blocked), self.assertLogs("app.services.tle_provider", level="WARNING") as captured:
            records, state = await provider.get_catalog_with_state(20)

        self.assertTrue(records)
        self.assertEqual(_Client.calls, 1)
        self.assertEqual(state["status"], "fallback")
        self.assertEqual(state["last_error_code"], "upstream_http_403")
        self.assertEqual(state["last_error_group"], "stations")
        self.assertTrue(all("192.0.2.17" not in line for line in captured.output))

        provider._last_attempt_at -= 61
        with self._use(lambda _url: self.fail("403 cooldown must suppress another request")):
            records, state = await provider.get_catalog_with_state(20)
        self.assertTrue(records)
        self.assertEqual(_Client.calls, 1)
        self.assertEqual(state["last_error_code"], "upstream_http_403")

    async def test_403_retry_state_survives_provider_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "celestrak-state.json"
            with self._use(lambda _url: _Response(403, "blocked")):
                _, first_state = await TleProvider(retry_state_path=state_path).get_catalog_with_state(20)
            self.assertEqual(first_state["last_error_code"], "upstream_http_403")

            with self._use(lambda _url: self.fail("persisted 403 cooldown must suppress a restart request")):
                records, restored_state = await TleProvider(retry_state_path=state_path).get_catalog_with_state(20)

            self.assertTrue(records)
            self.assertTrue(all(record.source_type == "fallback" for record in records))
            self.assertEqual(restored_state["status"], "fallback")
            self.assertEqual(restored_state["last_error_code"], "upstream_http_403")
            self.assertEqual(restored_state["last_attempt_at"], first_state["last_attempt_at"])

    async def test_request_error_details_are_logged_safely_without_changing_fallback_code(self):
        def fail(_url):
            raise httpx.ConnectError(
                "proxy failed https://user:secret@proxy.example/path?token=hidden "
                "Authorization: Bearer authsecret"
            )

        with self._use(fail), self.assertLogs("app.services.tle_provider", level="WARNING") as captured:
            records, state = await TleProvider(retry_attempts=1).get_catalog_with_state(20)

        self.assertEqual(state["status"], "fallback")
        self.assertEqual(state["last_error_code"], "upstream_network_error")
        self.assertTrue(records)
        self.assertTrue(all(record.source_type == "fallback" for record in records))
        self.assertTrue(any("exception=ConnectError" in line for line in captured.output))
        self.assertTrue(any("group=stations attempt=1/1" in line for line in captured.output))
        self.assertTrue(any("request error" in line for line in captured.output))
        self.assertTrue(all("secret" not in line and "hidden" not in line for line in captured.output))
        self.assertTrue(all("authsecret" not in line for line in captured.output))
        self.assertTrue(all("proxy.example" not in line for line in captured.output))

        provider = TleProvider(retry_attempts=1)
        provider._last_error_code = "upstream_timeout"
        provider._last_attempt_at = time.time() - 61
        with self._use(lambda _url: self.fail("upstream failures must respect the two-hour refresh interval")):
            records, state = await provider.get_catalog_with_state(20)
        self.assertTrue(records)
        self.assertEqual(state["last_error_code"], "upstream_timeout")

    async def test_fallback_recovers_to_live_after_refresh(self):
        provider = TleProvider()
        with self._use(lambda _url: _Response(503, "unavailable")):
            _, state = await provider.get_catalog_with_state(20)
        self.assertEqual(state["status"], "fallback")
        provider._last_attempt_at = 0
        with self._use(lambda _url: _Response(200, FALLBACK_TLES)):
            records, state = await provider.get_catalog_with_state(20)
        self.assertEqual(state["status"], "live")
        self.assertTrue(all(r.source_type == "live" for r in records))

    async def test_concurrent_refreshes_share_one_upstream_refresh(self):
        async def delayed_response(_url):
            await asyncio.sleep(0.01)
            return _Response(200, FALLBACK_TLES)

        with self._use(delayed_response):
            provider = TleProvider()
            results = await asyncio.gather(*(provider.get_catalog_with_state(20) for _ in range(4)))
        self.assertEqual(_Client.calls, 7)
        self.assertTrue(all(state["status"] == "live" for _, state in results))
        self.assertTrue(all([r.input_hash for r in results[0][0]] == [r.input_hash for r in result[0]]) for result in results[1:])


if __name__ == "__main__":
    unittest.main()
