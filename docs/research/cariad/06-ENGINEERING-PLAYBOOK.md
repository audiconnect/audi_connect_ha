# 06 — Engineering Playbook: Implement Verified Audi Features, Not API Guesses

## Goal and branch policy

Deliver genuinely working, regression-safe improvements to the base [Audi Connect HA](https://github.com/audiconnect/audi_connect_ha), starting with trip statistics on an Audi Q8 PHEV. **This branch is documentation-only.** Start engineering changes on a separate feature/fix branch, review against upstream PR #915, and open a focused PR after tests.

## Phase 0 — Establish the exact baseline

1. Compare upstream `dev`/`master` and open PR #915 with fork `master`, `main` and existing fix branches; identify already merged tests, Auth0 controls, job-mapping changes and command-result improvements.
2. Preserve current unique IDs, services, config entry and HA device registry.
3. Locate v2.5.2 paths: `audi_connect_account.py` (trip gate, updates), `audi_services.py` (MBB trip endpoint), `audi_models.py` (legacy normalization), `sensor.py` (four entities).
4. Confirm the Q8 PHEV platform variant, market, available subscription and Auth0 mechanism **without persisting VIN or tokens**.
5. Record a baseline of existing working commands and sensors; no feature regressions are acceptable.

## Phase 1 — Audi Q8 Auth0 trip discovery (read-only, bounded)

Candidate sequence (**source-derived path, live Audi success not proven**):

1. `GET https://emea.bff.cariad.digital/vehicle/v1/trips/{VIN}/shortterm/last`
2. Only if authorized/meaningful: `.../longterm/last`, `.../cyclic/last`
3. Historical list `/vehicle/v1/trips/{VIN}/shortterm?from=...&to=...` only after permission and schema validation.
4. Lower priority: `GET /vehicle/v1/vehicles/{VIN}/tripstatistics?type=shortTerm` (commonly 404).
5. No blind retries or replacing an Auth0 session with an old MBB bearer.

**Per probe record:** route template, test time, car model/platform, market, auth family/audience (non-secret), HTTP status, top-level JSON keys (sanitized), field units, car-capture timestamp, whether the provider returned a real trip record, cooldown applied. Refuse to publish raw VIN/location/trip IDs.

**Stop:** 403/401 authorization, 429, unexpected redirects, non-JSON auth challenge, or a 404 route requiring repeated attempts. A denied endpoint is a finding, not a reason to invent a new token.

## Phase 2 — Implement provider-specific normalization

- Implement a modern CARIAD trip reader **only after** an Audi-approved HTTP 200 with valid data.
- Keep the existing legacy MBB reader for compatible sessions; do not simply toggle `support_trip_data`.
- Separate raw contracts:
  - legacy `tripDataList.tripData[]` with scaled integer consumption values;
  - BFF `data` payload with unit-suffixed fields and possible already-decimal values;
  - EU Data Act aggregates with timestamped fields; **not** individual trip records.
- Normalize mileage, start/end distance, elapsed/travel time, speed, fuel (L/100km), electric (kWh/100km), recuperation, zero-emissions distance.
- Distinguish **short-term last trip**, **long-term/cumulative**, **since-refuel cyclic** and **manual reset**; do not equate different concepts just to fill a sensor.
- Restore existing four trip entity IDs, maintaining their *meaning*; if a provider cannot supply "user reset", leave it unknown rather than mislabel `longterm/last`.

## Phase 3 — Cross-brand expansion hypotheses, not features yet

| Candidate | Where found | Preconditions for an Audi implementation |
| --- | --- | --- |
| Charging statistics/session power curve | Škoda + CUPRA central charging CARIAD host | Identify Audi auth audience/entitlement, correct request method/body, actual Audi 200 |
| Media `/media/v2/vehicle-images` | VW EU BFF client | Audi Auth0 authorization, response/images right to use |
| Tyre pressure, oil, low-voltage battery, HV temperatures | CARIAD selective-status jobs and Data Act field universe | Actual Q8 field presence, correct units, no stale value as live |
| Warning lamps, inspection, charging profiles | Škoda/OLA models + Audi existing status jobs | Per-feature capability and field mapping without duplication |
| Vehicle-specific controls | Audi/CARIAD BFF, Homey, PR #915 | Existing implementation overlap, permission, physical testing and command confirmation |

Do not open an "everything" PR mixing auth, media, history and command changes. One verified behavior per focused change.

## Phase 4 — Optional Data Act enrichment

- User configures consent and a **continuous data request** in the official VW Group portal.
- Adapter is **read-only** and never sends start/stop/lock/wake requests.
- Parse only authorized non-empty ZIP datasets; preserve every field's source capture time and separate ZIP generation time.
- Parked-car observations may be **hours/days old**. Empty 15-minute deliveries are not fresh status; repeated empty ZIPs can also indicate portal backend defects.
- Merge field by field using equivalent semantics + observed timestamp, never "last poll wins".
- Add limited diagnostics: `last_nonempty_dataset`, `last_vehicle_observed_at`, `last_portal_delivery`, `last_successful_fetch`, source, age and empty-feed count.

## Acceptance matrix

| Test | Required pass |
| --- | --- |
| Legacy data `averageFuelConsumption=81` | Parsed as **8.1 L/100km** |
| CARIAD data `averageFuelConsumption=8.1` | Remains **8.1 L/100km** |
| Valid zero fuel consumption | Preserved as **0**, never treated as missing via `a or b` |
| No trip entries | No crash, no fake zero trip, stable entities |
| Actual last trip vs short-term aggregate | No semantic substitution |
| `support_trip_data` under Auth0 | Capability based on verified provider, not auth gate alone |
| Known entity IDs | Unchanged |
| 207 partial jobs | Valid jobs update, missing/errored jobs remain separate |
| One 404 on trip/parking | Bounded retry/cooldown, not permanent disable |
| 403/401/429/502 | Authorization/backoff/diagnostics without request storm |
| 72-hour parked vehicle, same captured timestamp | **Stale/last-known**, not fresh |
| ZIP every 15 min, no content for 72 hours | No new vehicle observations or "connected" false-success |
| Old ZIP vs newer BFF | Older observation never overwrites newer equivalent field |
| Lock/charging state older than safety threshold | Not shown as current security/charging state |
| Manual command accepted but no car readback | **Unconfirmed**, not successful |
| OAuth token, S-PIN, VIN, GPS in diagnostics | Redacted |
| HA startup / restart / upgrade | Existing entry survives; no duplicate device/entity |
| Test suite and HA quality checks | Existing plus new tests green |

## Findings and evidence template

```yaml
id: AUDI-API-001
feature: trip.shortterm.last
source: cariad_bff
host: emea.bff.cariad.digital
method: GET
path_template: /vehicle/v1/trips/{vin}/shortterm/last
vehicle_platform: unknown
market: BE
auth_family: audi_auth0
evidence: CODE                  # OFFICIAL | CODE | REPORT | HYPOTHESIS
audi_q8_live_verified: false
http_status: null
response_keys: []
vehicle_observed_at: null
delivered_at: null
fetched_at: null
sensitive_data_redacted: true
next_action: One authorized, bounded GET probe with owner consent
```

Any response captured for tests must use a sanitized fixture that cannot reveal the VIN, account, route, coordinates, S-PIN or token.

## Engineering task

> **Task for the Engineer:** Take ownership of the base Audi Connect integration. Read all seven documents under `docs/research/cariad/` in order. Compare all proposed changes against upstream PR #915 and the fork's fix branches before writing code. First establish Q8 Auth0 read access to modern CARIAD trip data with explicit low-frequency GET probes. Next restore the existing trip entities with distinct source parsers and rigorous units/semantics. Treat VW Group EU Data Act as optional, delayed, read-only supplemental observations. Never confuse a successful poll or 15-minute ZIP delivery with a fresh parked-car measurement. Record proof, tests and unsupported cases. Avoid token leakage, remote command probing, false success and entity churn.

See [07 — Sources](07-SOURCES-AND-EVIDENCE.md).