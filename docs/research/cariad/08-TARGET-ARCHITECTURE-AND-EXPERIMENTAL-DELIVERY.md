# 08 — Target Architecture: Adaptive Audi Connect Across VW Group API Generations

**Status:** Proposed strategic architecture and delivery policy — not an implemented feature and not a confirmed Volkswagen Group roadmap.  
**Date:** 2026-11-11 · **Scope:** The base Audi Connect Home Assistant integration, with an Audi-first user experience and reusable VW Group API knowledge.  
**Read alongside:** [01 — Architecture and evolution](01-ARCHITECTURE-EVOLUTION.md), [05 — Authentication and capability contracts](05-AUTH-CAPABILITIES-RELIABILITY.md), [06 — Engineering playbook](06-ENGINEERING-PLAYBOOK.md).

## 1. Strategic vision

Today the integration is largely **Audi-specific and API-era-specific**, while the vehicle ecosystem underneath it is heterogeneous. A newer Audi might use Auth0 plus CARIAD BFF for status, an older car may require a legacy MBB service for a permitted feature, and a consented EU Data Act export can provide additional but delayed observations. Even within one car, different functions may use distinct service hosts and authorizations.

**Working strategic hypothesis:** VW Group has economic incentives over time to reuse more identity infrastructure, vehicle connectivity, telematics contracts, domain services, security controls and API conventions across Audi, VW, Škoda, CUPRA/SEAT and other brands. Existing CARIAD BFF vocabulary and the shared charging-statistics host are evidence of **some current convergence**, while MyŠkoda, OLA, Porsche PPA and Audi Auth0 are evidence of **substantial continuing divergence**. Neither complete convergence nor a specific VW Group migration timetable is established by our sources.

**Design response:** support both **convergence and long-lived exceptions**. Introduce a small set of versioned authentication, API, vehicle and capability adapters. Do not rewrite Audi Connect into a full multi-brand product or force every legacy vehicle through one newest API. The user should configure an Audi account, authorize the available sign-in method, and obtain the supported features automatically. Manual endpoint guessing should become an exceptional, diagnostic/developer activity.

### Business and engineering outcomes

- Extend useful life across older/newer Audi vehicles and PHEV/BEV/ICE variants without per-model branches throughout the codebase.
- Reduce user configuration and support burden: infer safely instead of asking users to test arbitrary combinations.
- Introduce new endpoints faster while preserving existing HA entities, device registry and user automation.
- Make vendor churn (backend split, auth migration, field drift, 404s, new capabilities) a **localized provider compatibility problem**, not a systemic integration failure.
- Design for mixed state sources and **honest freshness**. A parked Audi/Data Act reading can be hours or days old.
- Keep an auditable bridge between evidence from other VW brands and verified compatibility on a specific Audi.

## 2. Target flow: discovery before entity exposure

```text
Home Assistant config entry (Audi account + region/market)
          |
          v
[1] AUTH DISCOVERY & AUTHORIZATION
    Auth0/PKCE | supported legacy grant | device flow | consented Data Act
    - discover legitimate supported methods; user authorizes when needed
    - optional multiple independently authorized sessions
    - tokens isolated by issuer/audience/provider; safe refresh + reauth
          |
          v
[2] API / SERVICE DISCOVERY
    registered, allowlisted gateway/endpoint profiles
    - CARIAD BFF | historic MBB | Audi media | future Audi service
    - verify service access with bounded read-only requests
    - independent support/health/rate-limit state per provider and route
          |
          v
[3] VEHICLE IDENTIFICATION
    authorized garage/vehicle metadata
    - VIN (internal), model/year, generation, market, engine BEV/PHEV/ICE
    - platform / connectivity generation / capability schema when reported
    - confidence + provenance; UNKNOWN is permitted
          |
          v
[4] CAPABILITY RESOLUTION — PER VEHICLE, PER FEATURE
    advertised OEM capabilities + license/role/consent + valid endpoint
    + actual field/command response + freshness + provider preference
    - distinguish available, unknown, unsupported, denied, stale
    - retain fallback candidates where independently authorized
          |
          v
[5] STABLE AUDI DEVICE & ENTITY MODEL
    existing unique IDs, controls and services
    + optional new opt-in experimental entities/features
    - source, observation time, quality, diagnostic explanation
          |
          v
[6] MONITOR / REVALIDATE
    bounded retries, capability drift, API migration, reauth repair,
    compatibility evidence for community and maintainers
```

**Discovery order is logical, not one irreversible waterfall.** Account discovery may return limited vehicle metadata before all service authorization is known; vehicle identity can help select which low-cost API profile to try. Providers may be selected at **feature level** (e.g., current charging through BFF and historical trip metrics from an authorized historical API) instead of assigning the whole vehicle to one backend. Cache valid decisions and re-evaluate only on relevant changes.

## 3. Authentication discovery and compatibility

Treat authentication as a **registry of independently authorized strategies**, not a global boolean `uses_auth0`.

| Strategy | Reason to retain/support | Non-negotiable boundary |
| --- | --- | --- |
| Audi Auth0 + PKCE | Currently necessary for affected EU/CA login flows | Interactive authorization; respect issuer/audience and token scope |
| Existing authorized legacy IDK/MBB credentials | Legacy vehicles/features may still legitimately serve old paths | Never treat Auth0 token as equivalent; don't bypass deprecated/rejected login or device-attestation protection |
| Supported device authorization grant | May be offered by a supported Audi account flow | No background authorization without user participation |
| Auth0/IDK → approved service-specific exchange | Additional host such as Audi AZS/media may legitimately require a different token | A 403 is a real boundary; do not force exchange or replay across services |
| VW Group EU Data Act consent/session | Independent read-only information channel | Explicit opt-in; separate credentials/storage and timestamps, no vehicle controls |
| Future official Audi API | Future-proof extension point, not a present commitment | Register only on published/documented or user-authorized access |

**Proposed resolution process:** discover available *documented* sign-in modes for the account/market; prefer an already authorized working session; offer a clear HA repair/reauth flow when interactive authorization is needed. A single Audi account may use more than one authorized provider session if a feature genuinely requires it. Do not prompt users to try protocols at random.

**Implementation principles:** per-provider credential vault and refresh lock, never silently overwrite one provider's refresh token with another's; distinguish auth failed from service forbidden; no unsafe downgrade to an obsolete password grant; no login storms. Diagnostics expose auth **type and status**, never secrets.

## 4. API/service detection and profile registry

An endpoint registry defines **known candidates**, not guessed URL permutations.

```yaml
# Illustrative contract, not current configuration or a runnable Audi endpoint.
provider: cariad_bff
feature: trips.shortterm.last
host_family: emea_cariad_bff
method: GET
path_template: /vehicle/v1/trips/{vin}/shortterm/last
supported_auth: [authorized_audi_auth0]    # hypothesis until Audi live proof
market_constraints: unknown
platform_constraints: unknown
probe_mode: explicit_opt_in
request_budget: bounded
confidence: source_code_vw             # not audi_verified
error_policy:
  forbidden: stop_and_explain
  not_found: cooldown_then_revalidate
```

For each route, distinguish:

- **Defined**: present in a versioned implementation or official contract.
- **Reachable**: an authorized session can call it without a policy violation.
- **Valid**: response matches its schema and has meaningful data.
- **Supported for this VIN**: vehicle reports a capability or valid evidence for a field.
- **Operational**: suitable freshness/quality for the specific Home Assistant feature.

A `404` on the old trip API must not poison the modern trip provider. A route returning valid data must not be disabled because a different API's capabilities list is empty. Use a per-account/per-VIN/per-route compatibility cache with version, TTL, last result and reasons; invalidate on reauth, vehicle/platform change, backend migration or repeated contract changes. A future API can be inserted without replacing the whole vehicle abstraction.

**No indiscriminate active endpoint scanning.** Prefer capabilities and ordinary already scheduled calls. Optional read-only discovery is user-initiated or tightly budgeted, allowlisted and rate-safe, with clear HTTP classification.

## 5. Vehicle identification then capability inference

Vehicle identity and capabilities should be **derived from reported metadata and behavior**, not from users selecting API versions or guessing their vehicle support manually.

- Start with the authorized garage/vehicle listing; collect available metadata such as model code, model year, drivetrain, platform and connectivity generation. VIN remains internal and private.
- Use a **vehicle profile** to narrow possible API families; it must not be used as definitive proof that a function works. Model-year heuristics are fallible.
- Normalize OEM capability IDs into stable feature concepts: `trip_history`, `charging_history`, `target_soc`, `charging_power`, `climate`, `vehicle_lock`, `vehicle_health`, `tyre_pressure`, `media`, etc.
- Store both source identifiers and mapping: `oilLevelStatus` capability is not automatically the `oilLevel` selective-status job. Škoda `CHARGING_MEB` and CUPRA `charging` may map to the same abstract feature but require different adapters.
- Resolve feature support using multiple signals: **vehicle identity + advertised capability + service entitlement/role + endpoint response + field validation + data quality**. Negative evidence from one service is not global feature absence.
- Expose only actually supported stable features automatically. When the state is `unknown`, avoid declaring the vehicle unsupported; preserve existing HA entities and diagnostic explanations.
- Treat read capabilities separately from writable commands. A remotely controllable function also requires safe authorization, explicit user action and state confirmation.

**Expected UX:** the user sees “Connected: Audi account”; the integration shows discovered vehicles, current source(s), supported features and clear causes of unavailable capabilities. Advanced diagnostics may show route-family support states without inviting trial-and-error.

## 6. Multiple providers and cross-generation coexistence

It must be possible to bind a single Audi to multiple **authorized** providers concurrently while keeping one HA device:

| Feature | Possible preferred source | Permitted fallback | Caution |
| --- | --- | --- | --- |
| Current battery/charging state | Fresh Audi/CARIAD BFF | Another confirmed current Audi source | Never silently fall back to days-old Data Act |
| Individual trip records | Modern CARIAD trip API if verified | Legacy MBB if separately authorized and semantically equivalent | Long-term aggregates and reset records are not identical |
| Historical energy aggregates | Authenticated Audi trip history | EU Data Act, labeled aggregate/slow when present | Data Act may be missing or delayed for days |
| Charging sessions | Verified Audi service | No speculative cross-brand calls | Shared Škoda/CUPRA charging host does not grant Audi access |
| Vehicle image | Authorized Audi image service | Confirmed CARIAD media route | GraphQL AZS and Auth0 have different permissions |
| Commands | Valid authorized Audi command adapter | No read-only portal fallback | Accepted ≠ confirmed |
| Data Act observational enrichment | Consent-based EU Data Act feed | None | Independent delay and freshness policies |

**Selection** is per **feature and field**, not “new API always wins.” Prefer semantic equality, authorization and meaningful vehicle timestamps. Older readings must not overwrite newer readings even if they were downloaded last. Each entity should retain provenance, last successful value and observed-at time where useful.

## 7. Non-functional requirements (NFRs)

These are **proposed acceptance requirements** and configurable defaults to validate during engineering, not current commitments or VW Group SLAs.

| NFR | Proposed target and measurable test |
| --- | --- |
| **Compatibility** | One existing Audi config entry and one HA device per VIN; preserve unique IDs, services, migrations and entity history across auth/API provider change; no mandatory reinstall/re-pair. |
| **Availability / graceful degradation** | Partial 207/job failures never invalidate healthy fields; transient provider outage preserves last-known readings with stale metadata; unrelated controls/sensors continue. |
| **Freshness / data integrity** | Record vehicle-observed, provider-delivered and HA-fetched times separately; a 72-hour parked-car reading remains stale regardless of successful 15-minute polls; no missing→zero and no out-of-order overwrite. |
| **Performance / cloud load** | Coalesce duplicate requests; serialize refresh tokens and commands; minimum polling interval enforced; no vehicle wake for discovery; bounded per-route timeout and requests; rate-limit 429/Retry-After adherence. |
| **Account safety** | One failed 401/403 does not cause a high-rate reauth/alternate-host scan; specific repair guidance, cooldown and a circuit-breaker on repeated failures. |
| **Security/privacy** | Never log/store tokens, PIN, full VIN, location or raw trip history in diagnostics; separate credential audiences; avoid cross-brand unauthorized requests. |
| **Correctness** | Source-specific payload parsers and units, support for zero/null/partial schemas, strict timestamp/UTC normalization, 204/207/404 handling and unconfirmed command outcomes. |
| **Observability** | Sanitized per-account/vehicle/feature status: chosen provider, compatibility confidence, last successful check, last observed-at, freshness, route-category error and cooldown. |
| **Maintainability** | Versioned provider contracts, small independent modules, fixture-backed tests, source/evidence register, provider-level unit/integration tests; no hard-coded VIN/model branching. |
| **Testability** | Synthetic/redacted BEV/PHEV/ICE, legacy/modern auth and API fixtures; HA startup/upgrade/regression checks; bounded live owner-run cohort tests. |
| **Scalability** | Multiple vehicles and providers per account with shared sessions/cache and bounded per-vehicle request budgets; no O(vehicles × guessed endpoints) background scan. |
| **Accessibility / UX** | Normal setup does not ask for hidden API levels; experimental settings clearly disclose risks; unsupported vs unauthorized vs stale are comprehensible. |

Suggested quantitative engineering gates (tunable, **not observed OEM limits**): zero sensitive values in diagnostic fixtures; zero extra probe calls unless explicitly opted in; no repeated 403/404 loops; one vehicle per HA unique ID; 100% pass for core auth, entity-stability, unit-conversion and command-confirmation regressions; test 15-minute, 3-hour, 24-hour and 72-hour data ages. Avoid inventing universal “fresh within five minutes” SLAs: parked OEM telemetry cannot meet that promise.

## 8. Experimental-first community release model

**Objective:** release candidate features **earlier** into normal test/pre-release builds behind an explicit experimental setting, so the broad Audi community can validate real vehicles and markets. This avoids waiting for one engineer to own every model while keeping default users safe.

### Existing implementation and migration

The fork already has `experimental_commands` in `custom_components/audiconnect/config_flow.py` and experimental charge/window-heating/wakeup buttons in `button.py`; [2.5.3b11 test notes](https://github.com/npinguin/audi_connect_ha/blob/main/docs/COMMUNITY_TEST_RELEASE_2.5.3b11.md) call these opt-in. **Preserve this behavior and existing user settings.**

Proposed progression:

- A clearly labeled **“Enable experimental features”** umbrella (opt-in, off by default) for early read-only capabilities; feature-level availability is still constrained by detected VIN/API support.
- Keep **“Enable experimental remote commands”** separately opt-in, potentially nested underneath the umbrella, and migrate the existing `experimental_commands` setting without silently enabling new remote actions.
- **Do not imply the umbrella or command toggle grants authorization.** A denied route remains denied; a missing capability remains unavailable.
- Stable features migrate out of the experimental umbrella when validated; preserve their HA unique IDs and entity semantics. Users should not lose a feature/entity solely because its classification changes from experimental to stable.
- Include an in-product diagnostic toggle to share **privacy-safe metadata only** (never raw trip bodies, VIN, GPS, tokens); opt-in per sharing event.

### Feature lifecycle

```text
RESEARCH
  -> CONTRACT (documented route + test fixture)
  -> EXPERIMENTAL / OPT-IN (safe implementation + CI + diagnostics)
  -> COMMUNITY PILOT (different vehicles/markets/auth profiles)
  -> STABLE (evidence gates met, flag removed without ID churn)
  -> DEPRECATED (compatibility period + migration)
```

A feature may be **shipped experimental with no Audi Q8 live proof** only when it is safe, gated, fail-closed, test-covered, explicitly labeled experimental and does not run aggressive automatic discovery. For a remote **write** command, require stronger minimum proof and fail-safe authorization before release. An experimental flag must **not** become a shortcut around basic quality, privacy or safety gates.

### Release and feedback mechanics

1. Ship small, independently revertible feature slices in frequent pre-release builds; allow disabled-by-default experimental code in normal releases when core regressions pass.
2. Advertise precisely which account/auth/vehicle platforms were tested, and which remain unknown. Avoid claiming global compatibility after one Q8 success.
3. Surface per-feature telemetry in diagnostics: `not_seen`, `eligible`, `available`, `denied`, `404_cooldown`, `schema_mismatch`, `stale`, `command_unconfirmed`.
4. Provide a minimal anonymous feedback template: integration version, market, drivetrain/generation (if known), auth family, feature, response status class, expected/observed, redacted schema keys, vehicle capture age.
5. Collect cross-platform results from a small pilot first, then expand. **Not all experimental APIs may be polled by every opted-in user automatically.**
6. Promote a feature only when multiple relevant vehicle types/regions and failure paths have been exercised (or when scope is explicitly limited to one verified segment).
7. Use feature-specific remote kill switches or server-independent local disable switches where appropriate; do not force all users into immediate reauthorization for a single experimental feature.
8. Keep a short experiment changelog, active limitations, regression tests, deprecation plan and owner for every feature.

### Promotion gates

| Dimension | Experimental | Stable |
| --- | --- | --- |
| Authorization | Explicit supported auth and user opt-in; no forbidden workaround | Tested and documented for supported account types |
| Vehicle coverage | Narrow/test cohort and declared unknowns | Repeatable matrix for the declared supported models/generations |
| API contract | Fixture, schema validation, bounded failure handling | Real-world evidence plus schema drift/recovery tests |
| Data freshness | Explicit provenance/age, unknown possible | Verified source and quality for feature semantics |
| Commands | Fail-closed, explicit action, stronger pilot proof | Acceptance/readback confirmed or explicit unconfirmed state |
| HA compatibility | Feature disabled by default, no ID breakage | Entity registry stable, upgrades and reauth tested |
| Release QA | Unit/CI/HA baseline green | Broad tests and declared regression gate green |

## 9. Concrete engineering epics

1. **ENG-AUTH — Authentication registry.** Separate Auth0, supported legacy, consented Data Act and future authorized strategies; per-provider session/refresh and HA repairs; preserve config entries.
2. **ENG-API — API compatibility registry.** Register host+method+schema+auth/market/version, bounded discovery, negative caching, diagnostics and no guessed cross-brand access.
3. **ENG-VEHICLE — Vehicle profile.** Build from authorized garage metadata; drivetrain/platform/generation with provenance and unknown handling.
4. **ENG-CAPS — Feature resolver.** Normalize advertised capability IDs, roles, license, field availability and endpoint results; derive eligible HA entities automatically.
5. **ENG-DATA — Read adapters and freshness.** Restore trip semantics first; later charging history, images, TPMS/12V/health, and delayed Data Act enrichment without false-live values.
6. **ENG-RELEASE — Experimental program.** Backward-compatible feature flags, CI tests, pre-release cadence, safe public test cases, sample redacted diagnostics, promotion/deprecation gates.
7. **ENG-NFR — Observability and reliability.** Per-provider request budgets, 401/403/404/429/5xx discipline, schema-drift tests, startup/multi-vehicle, command confirmation and stability.

**Sequence to deliver value without a rewrite:** first inventory current code/PR overlap; make compatibility/diagnostics explicit; restore trip data via a minimal read adapter; use those learnings to extract the auth/API/vehicle/capability registries incrementally. Ship isolated read-only experimental discoveries before attempting broad new command coverage.

## 10. Architecture decisions to record

| ADR | Proposed decision |
| --- | --- |
| ADR-001 | Product remains **Audi Connect**, not a full VW Group integration; reuse cross-brand domain contracts rather than pretending tokens/hosts are interchangeable. |
| ADR-002 | Support **multiple independently authorized provider sessions** where a single Audi feature legitimately needs them. |
| ADR-003 | Select provider **per feature/field and VIN**, not one global API/legacy toggle. |
| ADR-004 | Detect and derive capabilities from authorized evidence; never require the normal end user to select API levels manually. |
| ADR-005 | EU Data Act is **consent-based, read-only and potentially days delayed**, never a command/instant-status channel. |
| ADR-006 | New features are **experimental by default** until proven; opt-in has strict privacy, authorization, request-budget and compatibility gates. |
| ADR-007 | The existing `experimental_commands` contract remains backward compatible; never auto-enable experimental writes. |
| ADR-008 | Preserve original Home Assistant entity IDs and semantics during backend or flag transitions. |

**Boundary of evidence:** the architectural pressure toward VW Group normalization is a **strategic inference**, not a manufacturer promise. Everything in this document is a proposed solution design unless explicitly identified as inspected code or a sourced observation.
