# 05 — Authentication, Capabilities and Reliability Contracts

**Target-state clarification:** replace a single global authentication-generation assumption with an authorized strategy registry and per-feature API compatibility. Derive vehicle capabilities from OEM metadata, subscription/role, endpoint evidence and data quality; do not ask ordinary users to select speculative API variants. See [08 — Target Architecture](08-TARGET-ARCHITECTURE-AND-EXPERIMENTAL-DELIVERY.md).

## 1. Token boundaries are not interchangeable

| Source | Auth family | Key limitation |
| --- | --- | --- |
| Audi Connect v2.5.2 | Interactive Audi Auth0 / PKCE in affected regions | Used for modern CARIAD status, but legacy MBB trip readers are deliberately disabled |
| Historic Audi MBB | Old IDK/MBB bearer, market/region and often `X-Client-ID` | A current Auth0 bearer is not automatically accepted |
| Audi GraphQL/AZS | IDK→AZS exchange through CARIAD login service | Reported EU Auth0 `client does not have access to the IDP for token exchange` |
| VW EU CARIAD BFF | VW identity with service-specific entitlement | Shared hostname is not proof the Audi bearer is authorized for every resource |
| Škoda MyŠkoda | Škoda ID and app gateway | Distinct from official Škoda Public API key and from Audi |
| Škoda Public API | User-authorized API key | Vendor-specific entitlement; not a VW/Audi key |
| CUPRA/SEAT OLA | Brand IDK and OLA-specific app headers/device rules | 2026 attestation/header enforcement leads to 403 even with otherwise valid login |
| Porsche | Porsche OAuth / audience | Separate app endpoint and command-key semantics |
| VW Group EU Data Act | Consented identity + authorized portal request | **Read-only delayed ZIP data**, no remote actions |

**Policy:** Never guess scopes, cross-use refresh tokens, impersonate a mobile device, circumvent device attestation or store tokens in unredacted fixtures.

## 2. Capability ≠ endpoint job ≠ license ≠ permission ≠ real data

Examples observed in the code:

- BFF capability ID `oilLevelStatus` can differ from its `selectivestatus` job name `oilLevel`.
- BFF capability `tripStatistics` can be advertised while a trip endpoint returns 404.
- Škoda capabilities include upper-case `CHARGING` / `CHARGING_MEB`, while CUPRA may use kebab-case; mapping them by naive case transformation is unsafe.
- An empty or partial `userCapabilities` snapshot is **unknown**, not proof no features exist.
- A job may be disabled for a single poll, affected by subscription status, or not supported on this specific VIN; don't permanently remove entities after a transient 404.

**Concrete PR #915 review finding:** its `capability_jobs.py` selects jobs through exact literal membership in reported capability IDs. A `oilLevelStatus` capability versus `oilLevel` job mismatch could prune a valid job on later polls. Review the separate [fork branch `fix/cariad-capability-job-mapping`](https://github.com/npinguin/audi_connect_ha/tree/fix/cariad-capability-job-mapping) and coordinate changes with PR #915 instead of implementing a conflicting fix. This is a code-based regression hypothesis until proven with a real vehicle payload.

Use explicit capability↔job mapping and **never assume** that a reported subscription grants a command action.

## 3. HTTP response contract

| Status/result | Meaning | Required behavior |
| --- | --- | --- |
| **200** | Payload returned | Validate individual fields/timestamps |
| **202** | Action accepted / asynchronous | Pending until status/readback confirms effect |
| **204** | No content | Not "car moving", not zero, not necessarily unsupported |
| **207** | Partial multi-status | Process valid jobs; surface errors for failed jobs individually |
| **401** | Credential/authorization invalid or expired | Bounded refresh/re-authentication; no endless token refresh |
| **403** | Permission/app entitlement/attestation/brand restrictions | Do not interpret as absence of physical feature; explicit diagnostics and cooldown |
| **404** | Endpoint not served, unsupported or temporarily unavailable | Per-route/VIN cooldown; not permanently unsupported after one response |
| **429** | Rate limited | Honor Retry-After and backoff; protect account/vehicle |
| **5xx** | Gateway/back-end fault | Bounded retry, exponential backoff and preserve last known observation |
| **JSON schema drift** | Wrong/missing/moved/typed fields | Do not silently convert to zero; record sanitized parse issue |

Audi Connect v2.5.2 `audi_api.py` already accepts **207** as a successful HTTP status. Focus on **per-job completeness**, not just adding 207 to a success list.

## 4. Data model and command discipline

**Data:** value, unit, semantic field, source, field-observed timestamp, provider response time, last retrieval time and confidence. Numeric `0` is only valid if present in a valid response.

**Controls:** precondition/capability check → user-authorized action → accepted/pending status → bounded readback → confirmed/failed/unconfirmed result. Do not report success because an HTTP call returned 200 or 202. Avoid fanout requests/wake storms. Sequential commands should honor rate limiting.

**Privacy:** redact VIN (not necessarily reveal last six), S-PIN, GPS, account email, token, refresh token, cookie, exact trip routes, raw user data and URL query values where they may identify the vehicle. Prefer route templates in diagnostics.

## 5. Operational resilience

- Serialize refresh-token operations so parallel polls do not rotate one another's credential.
- Keep per-route **negative capability caches** bounded and recoverable.
- Respect app/brand-specific headers only if legitimately required by an authorized session.
- Do not turn a cloud refresh into a request for the car to wake.
- Keep API discovery opt-in, **GET-only** by default, with a small endpoint allowlist, per-VIN cooldown and sanitization.
- Never probe command endpoints (POST/PUT to controls, S-PIN, wake, lock, climate) merely to discover capability.
- Keep OEM source timestamps stable across repeated identical payloads.

## 6. Audi-specific code and overlapping work

- [`audi_connect_account.py`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/audi_connect_account.py) — `support_trip_data = not uses_auth0`, trip update method, support flag.
- [`audi_services.py`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/audi_services.py) — `get_tripdata`, legacy MBB request, `selectivestatus` jobs, auth flows.
- [`audi_models.py`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/audi_models.py) — `TripDataResponse` legacy normalization.
- [`sensor.py`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/sensor.py) — four stable trip entities.
- [PR #915](https://github.com/audiconnect/audi_connect_ha/pull/915) — overlapping command, capability and diagnostic work. Do not duplicate it.
- [Issue #1060](https://github.com/robinostlund/homeassistant-volkswagencarnet/issues/1060) — example of working trip API response while HA mapping still fails.

See [06 — Engineering Playbook](06-ENGINEERING-PLAYBOOK.md) and [08 — Target Architecture](08-TARGET-ARCHITECTURE-AND-EXPERIMENTAL-DELIVERY.md).