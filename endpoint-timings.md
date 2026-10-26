# First-load API timing and Playwright verification

Times are seconds from one `curl.exe --compressed` request per endpoint. The before sample was taken on port 8001 before response trimming and gzip. The after sample was taken from current source on port 8002. Cache and upstream state differed, so compare transfer sizes directly; request durations are individual samples.

| Endpoint | Before (s) | Before bytes | After (s) | After bytes | After encoding |
| --- | ---: | ---: | ---: | ---: | --- |
| `GET /api/catalog?limit=900&forecast_hours=0` | 1.606 | 4,956,360 | 0.710 | 142,412 | gzip |
| `GET /api/forecast?horizon_hours=168&steps=9` | 0.852 | 292,046 | 0.676 | 8,525 | gzip |
| `GET /api/system-health` | 1.632 | 27,265 | 0.895 | 5,968 | gzip |
| `GET /api/analytics` | 2.599 | 6,807 | 0.979 | 922 | gzip |
| `GET /api/smart-filter` | 1.103 | 59,035 | 0.939 | 7,180 | gzip |
| `GET /api/screening-proxies?limit=120` | 1.357 | 3,057,172 | 0.990 | 96,840 | gzip |

Catalog plus proxy transfer fell from 8,013,532 bytes to 239,252 bytes (97.0%). Browser verification saw no initial proxy request; the page fetches proxies when opening Smart Filter or Catalog Analytics.

## Headless Chromium

Production preview at 1600×1050; demo snapshot `fcec3945251c45f38f215485ecbb5605` (109 assessments):

- Cold first contentful paint: 1,556 ms; Home dataset ready: 10,726 ms.
- Cold Collision Analysis populated after explicitly loading the DEMO snapshot: 1,261 ms.
- Warm first contentful paint after reload: 312 ms.
- Warm Collision Analysis populated from accepted cache: 5,580 ms.
- No automatic screening request was made.

The DEMO maneuver result uses a 5,400-second lead and the CDM covariances held fixed at both encounter times: before Pc `1.8622e-5`, after Pc `1.2571e-5`, reduction `32.50%`; miss distance changes from 12.3033 km to 13.1747 km.

Screenshots and detailed timing data are in `screenshots/`. Raw endpoint samples: [before](./endpoint-timings-before.json), [after](./endpoint-timings-after.json); browser measurements: [performance.json](./screenshots/performance.json).
