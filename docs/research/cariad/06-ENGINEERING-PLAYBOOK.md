# 06 — Engineering Playbook: Implement Verified Audi Features, Not API Guesses

## Validation principles

Use the [architecture and ownership contract](../../V3_ARCHITECTURE_CLOSURE.md) and existing catalog, profiles, Status and Command owners. Preserve identities, permissions and verified behavior.

## Evidence-driven research workflow

1. Identify an unresolved question and review the actual installed runtime, catalog, issue evidence and existing tests. Do not repeat completed discovery.
2. Use only reviewed, authorized, bounded read probes. Record route template, market, model, auth family, status, sanitized schema keys, field units and capture time. Stop on authorization failure, throttling, unexpected redirects or unsupported routes; no blind retries.
3. Preserve provider-specific semantics: legacy scaled integers versus modern unit-suffixed values, current/last/reset trip distinctions, valid zero and unknown values.
4. Reuse the existing normalized observation writer and stable entities. Add focused regression tests and independently validate actual vehicle behavior.
5. Treat feature hypotheses as unverified; never perform speculative writes.

## Cross-brand expansion hypotheses, not features yet

| Candidate                                                | Where found                                              | Preconditions for an Audi implementation                                               |
| -------------------------------------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Charging statistics/session power curve                  | Škoda + CUPRA central charging CARIAD host               | Identify Audi auth audience/entitlement, correct request method/body, actual Audi 200  |
| Media `/media/v2/vehicle-images`                         | VW EU BFF client                                         | Audi Auth0 authorization, response/images right to use                                 |
| Tyre pressure, oil, low-voltage battery, HV temperatures | CARIAD selective-status jobs and Data Act field universe | Actual Q8 field presence, correct units, no stale value as live                        |
| Warning lamps, inspection, charging profiles             | Škoda/OLA models + Audi existing status jobs             | Per-feature capability and field mapping without duplication                           |
| Vehicle-specific controls                                | Audi/CARIAD BFF, Homey, PR #915                          | Existing implementation overlap, permission, physical testing and command confirmation |

Do not open an "everything" PR mixing auth, media, history and command changes. One verified behavior per focused change.

## Optional Data Act enrichment

- User configures consent and a **continuous data request** in the official VW Group portal.
- Adapter is **read-only** and never sends start/stop/lock/wake requests.
- Parse only authorized non-empty ZIP datasets; preserve every field's source capture time and separate ZIP generation time.
- Parked-car observations may be **hours/days old**. Empty 15-minute deliveries are not fresh status; repeated empty ZIPs can also indicate portal backend defects.
- Merge field by field using equivalent semantics + observed timestamp, never "last poll wins".
- Add limited diagnostics: `last_nonempty_dataset`, `last_vehicle_observed_at`, `last_portal_delivery`, `last_successful_fetch`, source, age and empty-feed count.

## Acceptance matrix

| Test                                            | Required pass                                              |
| ----------------------------------------------- | ---------------------------------------------------------- |
| Legacy data `averageFuelConsumption=81`         | Parsed as **8.1 L/100km**                                  |
| CARIAD data `averageFuelConsumption=8.1`        | Remains **8.1 L/100km**                                    |
| Valid zero fuel consumption                     | Preserved as **0**, never treated as missing via `a or b`  |
| No trip entries                                 | No crash, no fake zero trip, stable entities               |
| Actual last trip vs short-term aggregate        | No semantic substitution                                   |
| `support_trip_data` under Auth0                 | Capability based on verified provider, not auth gate alone |
| Known entity IDs                                | Unchanged                                                  |
| 207 partial jobs                                | Valid jobs update, missing/errored jobs remain separate    |
| One 404 on trip/parking                         | Bounded retry/cooldown, not permanent disable              |
| 403/401/429/502                                 | Authorization/backoff/diagnostics without request storm    |
| 72-hour parked vehicle, same captured timestamp | **Stale/last-known**, not fresh                            |
| ZIP every 15 min, no content for 72 hours       | No new vehicle observations or "connected" false-success   |
| Old ZIP vs newer BFF                            | Older observation never overwrites newer equivalent field  |
| Lock/charging state older than safety threshold | Not shown as current security/charging state               |
| Manual command accepted but no car readback     | **Unconfirmed**, not successful                            |
| OAuth token, S-PIN, VIN, GPS in diagnostics     | Redacted                                                   |
| HA startup / restart / upgrade                  | Existing entry survives; no duplicate device/entity        |
| Test suite and HA quality checks                | Existing plus new tests green                              |

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
evidence: CODE # OFFICIAL | CODE | REPORT | HYPOTHESIS
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

See [07 — Sources](07-SOURCES-AND-EVIDENCE.md).
