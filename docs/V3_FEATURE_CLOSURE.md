# V3 feature closure review

Review baseline: `a614109746e32edd2e13e7e480b682dc8b14280d` on the ownership closure branch, derived from upstream review #918. This is a gap review, not acceptance evidence.

## Existing authoritative inventories

- [V2 parity baseline](V2_V3_PARITY_BASELINE.json): 109 historical entity slots, 9 platforms, 11 services, 11 execute-action choices and 19 control workstreams. The baseline is a historical snapshot, not a current generated inventory.
- [Product entity contract](../custom_components/audiconnect/v3/product_entities.json): native HA identities, metadata references and declared product extensions.
- [Capability catalog](../custom_components/audiconnect/v3/full_catalog.json): executable operation variants; applicability and evidence are separate.
- [Ownership](../governance/OWNERSHIP.json): responsibility and architecture constraints.

Do not reproduce these inventories in a second editable catalog. A declared row is not evidence that its implementation works on a real vehicle.

## Open functional closure

| Area             | Gap / required evidence                                                                                                    |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Vehicle identity | OEM manufacturer model/year and image variants; real account evidence, restart and missing metadata behavior               |
| ICE/PHEV/BEV     | Representative vehicle evidence for applicable readings, controls and powertrain-specific projections                      |
| Trips            | CARIAD reset history not established; confirm MBB current/reset and CARIAD current/last, local archive and restart         |
| Legacy reads     | Verify actual MBB status, timers, preheater, vehicle data and unsupported modern equivalents                               |
| Charging         | Physical start/stop, manual/timer mode, target SOC, active and individual profile writes and readback                      |
| Climate          | Stored and parameterized start, stop, settings, windows, auxiliary duration; Auth0 and legacy acceptance                   |
| Access / remote  | Lock/unlock, flash, refresh/wake, engine start/stop where eligible; confirm actual outcome and fail-closed behavior        |
| HA lifecycle     | All nine native platforms, historical service contracts, user preferences, recorder history, restart and V2/V3/V2 rollback |
| Workbench        | Definition copy/paste exists; community sharing/import portability, roundtrip and redaction need explicit acceptance       |
| Operations       | Quota, expiry, partial responses, failed refresh, multi-account ownership, privacy and removal evidence                    |

## Release decision

NO GO. All rows require closure with code/test references and, where relevant, explicit real-vehicle acceptance. Unsupported OEM behavior must be evidenced and distinguished from product implementation gaps; do not silently narrow the agreed scope. No changes to upstream release metadata or stable HACS distribution are authorized by this review.

The latest known full Python pass before the product-contract refactor was 1,087 tests; the subsequent run at the review baseline had 1,070 passes and 20 failures caused by an obsolete diagnostics import. Exact-head CI must be green after correction. This document does not claim a new CI result.

## Sharing implementation increment

Saved local read/control definitions can be copied via the backend privacy check, then pasted as a new draft. The export includes a custom attribute definition where needed, but never activation or evidence. The check refuses potential private values rather than modifying the template. Manual inspection before external sharing and live import/roundtrip acceptance remain required.

## b23 corrective development

Audit baseline: published b22, `a22dce6c7398cb797b2510a2f2c5cc721dbfec7b`. b22 passed 1,102 Python tests on HA 2026.7.0 and 2026.11.1, 37 frontend tests and all package gates. PR #24 addresses the audit findings without expanding the vehicle-operation catalog. Charge mode, registry transactions, portable definition privacy, typed climate settings, discovery state ownership and minimum HA metadata have focused corrections. Shared fixtures cover backend export/import and frontend editor shape; full websocket-to-vehicle acceptance remains open. Remaining engine orchestration, protocol-specific route exceptions, full requirement-to-test traceability and real vehicle evidence remain explicit closure gates. Stable release remains NO GO.

## Climate continuity follow-up

Preserve only validated, timestamped last-known climate state in the existing private VIN-scoped profile. Restore as display-only evidence, never as fresh telemetry or command permission. A normal command with verified physical readback can supply historical fallback for older profiles. HTTP acceptance alone is not persisted as actual state. No additional vehicle requests. HA HVAC action remains unknown for historical display; automatic climate expiry or external actions require a newer observation. Physical restart acceptance remains open.

The sparse Q8 climate settings shape is handled by the existing settings PUT handler, using only the reported Celsius/Fahrenheit fields and preserving unrelated settings. Native setpoint-only requests do not start climatization when a settings route is enabled. A temperature-bearing start requires both fresh climate-on and requested temperature readback to be verified. The sparse payload is a tested candidate, not proof of physical OEM support; live Q8 confirmation is required.

## Vehicle data age provenance

The existing vehicle data age and freshness sensors share the newest valid vehicle capture, excluding their own derived `last_update_time` and model metadata. Age keeps its historical meaning and unit; source attribute, job, capture and observation timestamps, clock skew, oldest observed age and per-job coverage explain partial freshness. A successful cloud poll is separate and does not establish a vehicle capture. Coverage describes observed fields only, not all supported or missing fields. Use the individual reading and its capture time for automation decisions; do not interpret a zero global age as fresh SOC, access or climate data. No additional requests or entities. Live Q8 validation remains open.

Individual telemetry sensors and binary sensors share the same capture/observation metadata (`vehicle_captured`, `age_minutes`, `cloud_observed`, `cloud_age_minutes`, `vehicle_freshness`, `verification`); live climate, access, lock, charging, preheater, position and settings entities reuse it without confusing projected commands with measurements. Existing position-specific and access-specific aliases remain compatible. The reported freshness is not a command authorization or proof of the effective projected state. Age attributes are evaluated when HA writes the entity state; use the absolute capture timestamp to calculate live age in templates. No per-entity clock timers or extra polling. Historical trip end, inventory identity and local configuration retain their distinct time semantics.

Diagnostics reuse the same global capture provenance and individual freshness classification. The existing per-job report remains the only diagnostic coverage table. Custom source identifiers are not exported.

## B28 live evidence follow-up

Global age and job capture coverage consider usable normalized scalar readings only; structural detail envelopes do not qualify as measurements. The global freshness entity adds `partial` when an observed scalar is within 60 minutes and another is older than 60 minutes. The historical fresh/delayed/stale thresholds otherwise remain unchanged. Missing or invalid evidence is not proof of an actual measurement. Individual entity freshness is authoritative for automation; old automations using the global enum must account for `partial`. Aliases and completion estimates preserve source observation time, and schema coverage excludes empty value objects and request-only envelopes. Derived references are marked as implemented without claiming unavailable OEM values. Persisted normalization evidence without a current reading is separately identified in diagnostics.

## User-first control feedback

An accepted climate or charging command immediately publishes the existing effective state via the shared command projection, after durable acceptance and before read-only confirmation. A missing status response or quota-limited follow-up does not undo an accepted mutation; its backend outcome remains visible in the journal. Newer valid vehicle readback wins, explicit rejection removes optimism, and the existing bounded projection expiry applies. No synthetic readings, extra requests or retries. Lock and security-sensitive operations retain conservative confirmation semantics. The user must be able to see requested state immediately after API acceptance, independent of the actual telemetry timestamp. Physical Q8 response time and UI acceptance remain release validation items.

## Access command recovery

A successful lock/unlock POST is not physical confirmation. Keep the native lock entity visible as locking/unlocking while awaiting readback, even while the command guard blocks a second dispatch. A matching valid newer capture verifies the command. A contrary valid lock capture at least 30 seconds after an accepted normal HA command closes the interlock as `readback_mismatch`, not a failed route or physical failure. The user can then issue a new authorized action; no command is replayed. Without new evidence, or after an uncertain transport mutation, the explicit review guard remains. The reported state and command status are separate entity attributes. The 30-second interval reuses the existing temporary error cooldown; real-car validation is required.

## Uniform native control metadata

All native V3 controls use the common entity metadata builder and command journal selector. Stateful controls expose `state_source`, `last_reported_state`, the shared freshness fields and scoped `command_status`, `command_action`, `command_backend_result`, `command_http_status` and `control_actions`. Buttons expose only command fields and action availability, not fabricated vehicle captures. Existing compatibility aliases remain. The location-specific charge target exposes its actual profile snapshot but cannot correlate a command to a specific profile with the current journal contract; command fields remain null rather than borrowing another profile's status. Climate setpoint metadata stays separate from HVAC state. Historical trips, local settings and identity retain their distinct time semantics. No extra entities, requests or command store.

## B29 lock and Workbench recovery

A known HTTP 2xx normal access mutation is distinct from an uncertain transport. The existing 30-second cooldown bounds its transition and permits a subsequent explicit authorized command after the cooldown; no automatic retries or fabricated locked/unlocked state. A status GET returning unknown, pending or quota-limited does not turn acceptance into a failed mutation. A truly uncertain mutation, missing S-PIN, unapproved route or open engineering experiment still prevents unsafe dispatch. Persisted B29 access outcomes with known 2xx and only missing GET confirmation migrate to accepted-unconfirmed. A one-shot local HA state write ends the transition even without a new cloud poll. Engineering tests still require explicit review; Test buttons remain visible with a reason when blocked. The pending action and relevant command evidence are exported structurally in diagnostics without payloads, VIN, request or command IDs. Physical Q8 verification remains mandatory.

## B31 charging and dispatch evidence

When Audi explicitly reports an empty availableChargeModes list but a valid preferred mode, the existing V2 manual/timer enum is a candidate, not normal dispatch authority. Explicit Workbench parameterized verification of the built-in mode route is required before the locally selected, revision-matched route enables this fallback. Nonempty advertised options take precedence; invalid or absent options do not permit the fallback. A verified route does not prove both enum values physically: each fallback value requires its own explicitly reviewed Workbench attempt, with vehicle-context and operation-revision matching. Older route-only evidence cannot enable either value. The private journal retains the requested enum before dispatch and the profile retains only reviewed parameter evidence; a context change invalidates it. Native controls, diagnostics and end-user validation expose independent route availability/status and temporal dispatch readiness/reason. A pending review retains route evidence while continuing to block normal dispatch. Discovery candidates are never normal dispatch-ready. No new polling. Next single climate timer excludes past local times; without a fresh vehicle clock and capture, the next time is omitted when an earlier candidate might still be future. An enabled single timer with an unknown start blocks the derived next single value; recurring schedules are retained separately and not presented as single starts. Schedule details are preserved. Physical verification and full quota/parameter preflight are still separate from temporal readiness.

## B31 live B30 diagnostic follow-up (2026-11-13)

The structural diagnostic snapshot on HA 2026.11.1 / B30 confirms successful cloud polling with partial vehicle freshness, 124 registry entries, 96 runtime offers, no category drift, 393 normalized trip records, and six stored physically verified controls (access lock/unlock, climate start/stop, wake and flash). It is baseline evidence, not acceptance of B31. Eleven of 23 jobs have current value schema; 12 remain not observed, none explicitly unsupported. Read assessment 28/28 is not functional completion. Charging has zero physically verified controls. Start returned HTTP 200 but failed physical review; the combined alternative is untested. Mode options were explicitly empty and the mode PUT untested; target SOC and profiles remain unobserved. Verify independently before enabling. A partial fallback select exposes only proven writable options while retaining a different reported mode in metadata; no unsupported option is introduced. Route availability, temporal readiness and ineligibility are counted separately from stored physical evidence. Window heating start failed (HTTP 502); do not classify this as unsupported. Timer job schemas omit a vehicle capture timestamp and climate timers omit a vehicle clock; charging clock is a vendor sentinel. Preserve schedule details and unknown freshness, never invent local time or a capture timestamp. GraphQL identity is incomplete (core INTERNAL_SERVER_ERROR, media/classification null); image/web variants returned 401. No identity/auth workaround is justified without further evidence. No additional requests or raw diagnostics are committed. Relevant physical and HA acceptance remains open.

B31 Workbench exposes current-revision per-mode proof separately from writable options and route/temporal readiness. A mode test must demonstrate an actual change, not merely an HTTP success or the existing setting. HA unknown select state outside executable options is explicitly classified. No new polling, requests or endpoints are introduced.

The native next-climate-timer diagnostic now distinguishes an absent source, incomplete schedule, zero enabled timers, and an observed schedule without a safely determined next single start. This is an explanation of missing projection, not a claim of timer capability or a fabricated timestamp.

## B32 — experimental candidate audit (issue #44)

Scope: the B31 published source, the merged family priority, shared observation,
auth isolation, deterministic selection and passive discovery changes, and PR
#41 (optional EU Data Act). This is the code/evidence audit for a HACS test
candidate; it does not close the stable product acceptance gate.

| Objective                   | Audit evidence and remaining gate                                                                                                                                                                                                                                                                                                   |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Correctness and consistency | One normalized observation per family, shared priority and aging selection; same-family alias handling; exact UUID/name mapping, units, enum validation and per-field capture. Regression tests in test_v3_attribute_runtime, test_v3_data_act and test_v3_product_entity_contract.                                                 |
| Completeness                | Nineteen mapped semantic attributes from the owner-supplied Q8 dataset; 91 rows with per-field timestamps, about 35h delivery lag. No claim of full Data Act coverage or 100% V2/V3 parity. Right-door metadata conflicts, service signs, charging/timer semantics and other variants remain open. Identity issue #35 remains open. |
| Simplicity and ownership    | Existing API, Catalog, Status, Vehicle and HA owners, two bounded provider modules; one coordinator and one normalized writer. No per-model routing or parallel entity model. Existing native direct writes and capability-level compatibility paths remain audit/cleanup subjects, not a claim of zero technical debt.             |
| UX and lifecycle            | Existing entity IDs, opt-in options and password masking, independent background read, source/age attributes; mocked setup, disable, failure and cancellation coverage. Live HA registry/history, Workbench and V2 rollback acceptance remain open.                                                                                 |
| Security and privacy        | Fixed reviewed sign-in destinations, isolated session and quota, no consent creation, bounded ZIP/JSON, VIN match, explicit command evidence guard and per-VIN denial. No owner raw ZIP, VIN or user identifiers committed. Live authorization, credential rejection and revocation still require acceptance.                       |
| Efficiency and resilience   | Existing native polling/budget retained; passive full batch and request reuse; optional 30-minute due interval and independent backoff; no native publication wait. Live request counts, portal protocol and quota behavior remain unverified.                                                                                      |
| Engineering and governance  | Exact-head CI required before merge; dual HA version, Workbench, lint, hassfest, HACS and checksum required by the existing candidate workflow. B31 product source offered in existing PR #918; no stable version or upstream merge.                                                                                                |

Audit corrections included command readback isolation (even with fresh portal
capture), aliases considering cached candidates, re-selection on aging, explicit
revocation removing only that family's observations, and aggregate source
provenance. Experimental opt-in only; the portal protocol is not a documented
consumer API contract. Real Q8 portal sign-in, restart, disable, VIN isolation,
freshness and no extra native requests are acceptance tasks. The 91-row dataset
is evidence of actual schema and delivery lag, not a successful V3 login.
Full stable release remains **NO GO**. Issue #44 remains open for evidence and
the final product release decision.

## B33 — B32 live follow-up (2026-11-13, issue #44)

Three snapshots of the same B32 runtime show recovery from 0 to 49 verified attributes, 90 to 93 known HA states, and vehicle capture age from 111 to 13 minutes. Registry remains 124 entries, 96 offers, 62 normalized attributes, and 393 trip records. Seven expected 15-minute native cycles plus three inventory reads are consistent with the ten additional requests over 105 minutes; this is not a complete request trace. Climate state and charging-ready recovered without a code change. Do not relax freshness, change native polling, or add a second coordinator to fix these transient differences. Four identical partial GraphQL inventory responses persisted through bearer renewal, with no successful identity recovery. Bound automatic incomplete inventory retries to one hour, complete inventory to 24 hours, and remove the independent routine token-renewal trigger. Initial enumeration and explicit reviewed identity experiments remain unchanged; slower automatic identity recovery is the deliberate tradeoff. Existing quota reserve remains authoritative. No new requests, auth owners, scheduler, or persisted state. Live candidate verification remains required.

Open: quota visibility/scope, movement evidence without capture time, operational mobility versus archive cadence, remaining charging time during active charging, charging commands/timers, real Data Act authorization, identity issue #35, and final audit #44. Preserve truthful unknown states and physical-command verification. No raw owner diagnostics committed.

### B33 follow-up: user, engineer and maintainer closure

- User: preserve existing entities and last-known parked position. Do not turn a parking response (including HTTP 204) into a fresh motion measurement. Explain optional portal setup, stale data, unavailable controls and V2 rollback in the existing V3 review guide.
- Engineer: route parking timestamps and undated movement indications through the shared observation writer instead of direct state assignments; do not change normal request cadence. The diagnostics reuse the existing coordinator counter and distinguish native reachability, current transport request count, latest-per-operation evidence and unknown OEM quota. No added polling history, persisted state or parallel diagnostics model. Regression tests cover older parked samples, undated movement and diagnostic scope.
- Maintainer: one focused PR to dev, existing upstream review and immutable HACS candidates. Review the exact final head and the remaining acceptance gates above. No claim of live acceptance or stable release from CI alone.

Movement remains deliberately unavailable without reliable vehicle capture. Operational parking/last-trip cadence is still an optimization candidate, not a completed fix: measure native quota scope and prioritize essential status reads before increasing request volume. The missing vehicle model, charge-mode and charging-control proof, active charging duration, Data Act authorization and representative live lifecycle acceptance remain open.

The V3 options form no longer exposes the V2-only startup update toggle: V3 must enumerate vehicles during setup. The stored V2 preference survives editing and rollback. Active V3 option labels and help now cover English, Dutch, German and French, with schema-driven regression coverage and synchronized upstream-delta blobs. Other locale and discovery-dialog translation coverage is not claimed.

## B34 — focused user feedback and additional read channel closure

Independent Q5 B32 field test in upstream #907/#918 verified short/long-term and last trip, 1,000 archived records across a restart, and close agreement with myAudi. This is not complete V2/V3 acceptance. Manufacturer identity #35 remains parked; no authentication or GraphQL experiment is introduced. A generated Auth0 account subject is no longer a display title; existing generated titles matching their unique ID are repaired without changing the account, device or entity identity or user-chosen titles. EU Data Act is an additional independently authorized read channel, not a fallback activated by CARIAD failure. Preserve existing family cadence, shared observation selection and command isolation. Distinguish missing subscription, no non-empty delivery, duplicate delivery and successful receipt in existing diagnostics; reject implausible future delivery timestamps before deduplication. Live Q8 portal login and dataset acceptance remain required.

All built-in native product names now use Home Assistant entity descriptions and translation keys, with the canonical English name as fallback. EN/DE/NL/FR resources cover the complete product entity contract and two range-role aliases; custom Workbench names remain owner-defined. Existing IDs and native metadata are unchanged. The registry no longer overwrites HA-managed translated labels; V2 rollback clears the V3 translation key and restores tracked original names. Other locales fall back to English; state values and Workbench dialogs are not part of this name-only change. Live localization and rollback remain acceptance gates.

The existing integration status sensor exposes the same bounded Data Act channel status as diagnostics. Mapped and selected counts compare only the same canonical observations, excluding derived capture timestamps. Optional channel status does not change native cloud health. No additional entity or poller.

### B34 simplification pass

The additional channel no longer maintains a separate mutable denied-VIN set or a second account-result state machine. Delivery status is the provider's authority; account status is derived from delivery outcomes, authorization, quota and scheduler timestamps. Only an unexpected processing failure remains a distinct scheduler fact. The product contract resolves label and translation identity together, including range roles; HA descriptions now use the existing category contract instead of repeated category assignments. Registry rollback combines its existing owned changes into one update per entity and evaluates stateful supersession once. No new module, scheduler, entity, command route, persistent store, provider request or source-selection policy. Tests preserve prior denial behavior, source counts, categories, translations, identity and rollback. The live Data Act and Q5 acceptance gates remain open.

The existing ownership policy now makes simplification, ownership, maintainability and user experience explicit review evidence. User guidance explains optional-channel results and the relevant action using the existing Integration status, without requiring Workbench or a second integration. No new enforcement workflow or runtime abstraction.
