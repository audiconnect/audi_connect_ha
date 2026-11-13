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
