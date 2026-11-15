# Audi Connect V3 — user and engineering guide

**Configure → Discover → Use.** V3 is experimental and opt-in within Audi Connect. V2 remains the default and fallback. Keep one account, one config entry and the existing HA devices and entity IDs.

This guide describes the published B42 experimental baseline and the approved B43 development scope. Neither is a stable V3 release. For exact release evidence and open gates, see [feature closure](V3_FEATURE_CLOSURE.md).

## User guide

### Installation and rollback

Follow the [main README](../readme.md) for installation and sign-in. Use a published, pinned HACS candidate containing V3; a GitHub review branch is not a published release. Back up Home Assistant before upgrading. In **Settings → Devices & services → Audi Connect → Configure**, select the experimental V3 runtime if available. Keep the normal scan interval (minimum 15 minutes). Leave the optional engineering Workbench and EU Data Act disabled unless needed. After switching from V2, save and reopen Configure once the V3 runtime is loaded. Vehicle setup & discovery is checked by default whenever V3 options are opened. Finish or uncheck it to save without testing. It is always available for guided discovery or one specific function, including retests, without enabling the Workbench. If EU Data Act or dealer details are also selected, their configuration completes first; discovery then opens using the currently loaded vehicle profile. No vehicle command is sent by saving options.

V3 enumerates vehicles during setup; the V2-only startup update preference is retained for rollback. To revert, select V2 in the same entry and reload. Do not delete the integration or the registry to resolve a temporary data problem. Retain device IDs, entity IDs, user preferences and trip history. Verify automations after any runtime change.

### Data and freshness

Audi's cloud can be reachable while a parked vehicle has not sent new data. A cloud refresh is not proof of a new vehicle capture. No automatic wake on every poll.

| State          | Meaning                                                                                                                                 |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Fresh          | Valid measurement with a sufficiently recent vehicle capture.                                                                           |
| Last known     | Historical observation; check its capture time. Not confirmation of current state.                                                      |
| Unknown        | No reliable current value. A historical value may still be available in attributes.                                                     |
| Unavailable    | The entity or source cannot currently provide a usable value. Check the reason.                                                         |
| Not applicable | The underlying condition does not apply, e.g. charging ETA when explicitly not charging. Never interpret a missing ETA as zero minutes. |

Latest vehicle data age refers to the newest usable vehicle measurement, not the cloud receipt or oldest measurement. Oldest observed age and per-job ages remain available in attributes and the Workbench. Check the specific entity's capture time for automations. Data Act delivery may be fresh while the underlying capture is old. The tracker shows last parked position, not live GPS; movement without reliable vehicle capture stays unknown.

Previously registered, mapped read-only sensors and reviewed native control identities are offered again on reload even if their current OEM value or write route is absent. Registration is not authorization. The same entity recovers when valid evidence returns. Its identity does not establish current availability or new vehicle support. Explicitly retired identities such as the redundant V3 Charging ready sensor remain retired; no registry deletion is required.

### Native controls

Use the HA vehicle device page for ordinary actions. Routes and features depend on the vehicle, auth context and verified capabilities. Missing controls are not permission to try a different API.

- B43 charging controls retain the reported vehicle state after HTTP acceptance; requested action and correlated backend status remain separate. B42 and other existing comfort/access controls can show explicitly marked optimistic requested state for at most five minutes after a known HTTP acceptance. This is not physical confirmation. Newer capture boundaries, rejection or a superseding command end that overlay; expiry and restart fall back to the actual last-known value. Check `state_is_optimistic`, `state_source`, `last_reported_state`, capture and command outcome. Read-only telemetry never projects command intent. A staged local temperature is an edit, not an applied temperature.
- HTTP 2xx means backend acceptance, not physical execution. A matching later capture is recorded separately as `command_readback_observed_at`; it does not turn an accepted command into a verified command. A matching state can result from myAudi, a timer or manual operation. Correlated OEM failure takes precedence over earlier acceptance. Never automatically replay an uncertain command. Routine command history is not discovery evidence or an interlock: retain verified routes across temporary failures and restart, and allow a new explicit request after the existing bounded cooldown. Only an explicit discovery experiment awaits physical review; authorization and parameter/prerequisite checks remain in force.
- Climate has separate read target, stored-settings start, temperature-bearing start, independent settings update and stop operations. The configured temperature can be readable even when no temperature-write route works. Temperature adjustment requires an enabled applicable write route selected by the resolver. A reviewed catalog match is not the same as local physical verification; an alternative route must be verified before activation. There is no model-specific assumption that Q5 or Q8 supports a particular route.

### Optional EU Data Act

Obtain an authorized continuous request in Audi's official portal. In V3 options, select Manage EU Data Act; enter portal credentials locally when required. The wizard and vehicle diagnostic show delivery status independently from native Audi health. Keep current connection does not reauthenticate.

Connected means a delivered or acknowledged unchanged dataset, not fresh vehicle data. Awaiting data means no confirmed delivery; subscription unavailable or access denied means check the portal request; authorization required means check credentials; rate limited means allow automatic recovery. Disconnect removes local optional credentials and observations without changing native Audi login or the portal request. Data Act is read-only; it never authorizes or confirms commands.

## Engineering Workbench

Enable the optional V3 Development Workbench in integration options as an HA administrator. Open **Audi Engineering Dashboard**, select the account and vehicle. Ordinary HA use does not require the Workbench.

- **Overview**: current findings, health and vehicle capture.
- **Capabilities**: compare source mappings, actual observations, supported actions and their HA entities.
- **Configure & test**: inspect an individual API route, its parameters and evidence; explicitly test or activate reviewed mappings.
- **API Log**: inspect bounded local request/response evidence and read-only scans.
- **End-user validation**: Guided walks eligible unverified actions; Expert selective lets you choose a capability or one action, including retesting eligible verified actions. Both use the same reviewed definitions, parameters and physical confirmation.

### Test a specific climate function

For ordinary users: Configure → Vehicle setup & discovery → select a specific function (or Guided). Both native setup and the Workbench use the same typed inputs and physical consent. The optional Workbench offers deeper evidence:

1. Safely park the vehicle, select it in the Workbench and open **End-user validation → Expert selective**. Filter by Climate.
2. To test stored settings, start with climate off; select Start cabin climate and confirm whether it really starts.
3. Stop climate, then select Start climate with temperature. Enter a different target temperature in °C. Verify both actual start and the requested target.
4. To test Change climate target temperature independently, start with climate off; choose a different target and verify it changes without starting climate.
5. Confirm Worked on vehicle or Did not work on vehicle for the actual outcome. If unsure, keep the test pending and inspect the car; do not replay it. Restore the vehicle to a safe state before the next test.
6. Check the native HA climate entity after validation. Only explicit physical confirmation activates a tested control route. A successfully verified route is stored for that vehicle; failure on another vehicle does not authorize or disable this one.

The same physical instructions appear in Guided. If undated charging-mode option lists conflict, they never become ordered vehicle measurements. Use Vehicle setup & discovery → Verify preferred charging mode to physically test Manual and Timer separately. In B43, a valid native options list is authoritative; temporarily missing, empty or invalid options may retain only individually verified modes on the active route revision. Explicit invalidation of route proof or capability impairment remains binding. A selectable option is not proof of the currently reported mode. A reviewed equivalent route may be tried after definitive rejection under the existing consent and quota rules; never auto-send a different semantic action.

### Report a problem safely

Include the exact integration/HA version, vehicle model/year/powertrain and market (if known), action, local timestamp with time zone, expected versus actual outcome, and myAudi/physical evidence if relevant. Compare historical and current builds only when the conditions and operation are known.

Download integration diagnostics from **Settings → Devices & services → Audi Connect → three-dot menu → Download diagnostics**. The integration's own data is designed to exclude credentials, tokens, VINs, coordinates, raw payloads and private trip values. The surrounding HA export can contain unrelated system or integration information: review it and share only the sanitized Audi Connect data section. Attach a ZIP if GitHub refuses the JSON. Do not share complete HA logs, raw responses, OAuth callback URLs or secrets.

Diagnostics are read-only and do not wake the vehicle. They distinguish transport requests, coordinator attempts, cloud reachability, vehicle captures, source coverage, registry projections and structural command evidence. They are not a full request timeline. Unknown quota is neither zero nor unlimited.

## Engineer and maintainer

Use the [architecture and ownership contract](V3_ARCHITECTURE_CLOSURE.md), [feature closure](V3_FEATURE_CLOSURE.md) and the existing catalog. The capability control in `full_catalog.json` owns reviewed discovery metadata: order, label, physical instructions and allowed parameter names. The shared `parameter_schema` supplies types and limits; the resolver and command lifecycle enforce vehicle applicability, consent and verification. Frontend and backend consume the same candidates. Extend a reviewed existing operation through catalog metadata plus regression tests; new semantics still require reviewed execution and verification support. Do not add a second catalog, poller, auth owner, entity store or command framework.

Native command-response observations with their own valid vehicle capture use the same status writer as polling. Older captures cannot regress the selected sample, and equal-time conflicts are uncertain. No field borrows another field’s or the response root’s timestamp. HTTP acceptance, echoes and undated fields never advance freshness. Readback evidence requires a post-dispatch capture and receipt; it is not command execution proof. Read fallback, including Data Act, cannot confirm or authorize a native command. Charging request feedback is exposed alongside charging state and in the admin API Log using the existing climate/access parser. It is informational, has no vehicle capture of its own, and cannot confirm, reject or replay a command without independent correlation. Preserve last-known evidence, source timestamps and stable registry IDs.

Review exact-head Test and Validate, both supported HA targets, archive/packaging gates, upstream review and live acceptance separately. [Release authority](V3_ARCHITECTURE_CLOSURE.md#release-authority) governs promotion. Issue [#44](https://github.com/npinguin/audi_connect_ha/issues/44) remains the stable gate; [#35](https://github.com/npinguin/audi_connect_ha/issues/35) tracks missing manufacturer identity. The upstream maintainer owns the upstream default and stable release.

The [historical B37–B40 review](https://github.com/npinguin/audi_connect_ha/blob/b245cd62b51b08398166932dcb4f95987b87a4e9/docs/V3_REVIEW.md) remains available at the pinned B40 source. Its historical behavior and field counts are not current B43 instructions. See the feature closure for remaining acceptance.

## B43 — Reliability & Intelligence (approved fixes; release HOLD)

**Implementation GO for sufficiently evidenced fixes only.** B42 remains the published community-test baseline; no HACS publication, stable promotion or upstream delivery is authorized. Unproven vehicle operations remain explicit experiments. Use the existing ownership contract and issue #44. All acceptance items below are open unless supported by exact candidate evidence.

### Work packages, in implementation order

| ID  | Priority | Existing owner                    | Task for the engineer                                                                                                                                                                                                                            | Acceptance evidence                                                                                                                                                                       |
| --- | -------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1  | P0       | Command / API / Catalog           | Reproduce Q5 STOP regression B35 to B40/B42. Compare exact routes, payload, request lifecycle, status and physical measurements; investigate OEM timeout E.PA.VCF.18. No speculative alternate mutation or model hardcode.                       | Independently measured charging power and actual vehicle behavior; distinguish integration regression from OEM failure.                                                                   |
| C2  | P0       | Command / HA                      | Separate request acceptance, backend result, post-dispatch state observation and causally correlated execution. A later manual stop must not verify the earlier remote command. Do not show unconfirmed charging OFF as actual OFF.              | Regression for HTTP 200 + continuing power + later manual stop; timeout, rejection, delayed/ambiguous readback, restart and superseding intents. No automatic replay.                     |
| C3  | P1       | Catalog / Command / Profiles / HA | Validate charging START/STOP routes and manual/timer mode capabilities through explicit discovery. Preserve verified options when an advertised list is temporarily empty; do not invent supported modes.                                        | Q8 and Q5 route evidence, empty mode list, restart, invalid context and explicit rediscovery cases.                                                                                       |
| D1  | P1       | Status / Vehicle / Profiles / HA  | Fix source selection of the newest semantically valid observation, including retained last-known samples when the newer native response is invalid and Data Act is older.                                                                        | B42 SOC scenario, timestamps, equal-time conflict, invalid/sentinel, source withdrawal, restart and stale labeling. Historical values do not become live or satisfy command verification. |
| D2  | P1       | Command / Profiles                | Retain durable physical route proof independently of bounded execution history. Investigate lost climate START test detail after routine operations.                                                                                             | Journal rotation, restart and unrelated commands preserve discovery proof; explicit re-evaluation, authorization and operation revision still apply.                                      |
| A1  | P1       | API / Status / Profiles           | Use integrated #59 rather than duplicate it. Validate the integrated Data Act delivery cadence, Retry-After, 15-minute exponential fallback, persisted cooldown and session reuse; consider jitter only where evidence shows synchronized calls. | No request during cooldown or restart; repeated 429, session expiry, empty/old datasets, optional failure, recovery and independent native budget.                                        |
| A2  | P1       | API / Status                      | Treat multiple clients as normal; use reported remaining allowance conservatively, reserve native commands, suppress optional work when budget is low, and avoid synchronized polls.                                                             | Simulated external quota depletion and reset, absent headers, two clients, read recovery and unaffected native control reserve. No assumption of exact account/VIN/IP quota scope.        |
| A3  | P1       | API / Diagnostics / HA            | Record bounded redacted request evidence by family and endpoint category: identity/auth, metadata, listing, download, native status, command; HTTP status, Retry-After, attempts, last success, next eligible time.                              | Rate-limit attribution without credentials, raw payloads, VIN or a second logging system; truthful optional health and freshness.                                                         |
| E1  | P2       | Catalog / Command / HA            | Validate climate temperature settings and start-with-parameters via guided discovery; keep proven start/stop routes.                                                                                                                             | Physical Q8/Q5 checks where supported; no invented parameter capability.                                                                                                                  |
| E2  | P2       | API / Vehicle                     | Investigate manufacturer identity recovery (#35); use exact identity field evidence only.                                                                                                                                                        | Model/year/image provenance; no nickname inference; bounded requests.                                                                                                                     |
| E3  | P2       | HA / Workbench / Docs             | Review onboarding #52 and consolidate accepted changes with current contracts; update stale B41 release references.                                                                                                                              | Simple Configure → Discover → Use, existing entity IDs, no duplicate setup or obsolete instructions.                                                                                      |

### API policy and remaining evidence

- The official business Data Act API specification is not the consumer portal contract. Exact quota scope, reset period, and limits are unconfirmed. Do not hardcode a presumed manufacturer limit or bypass throttling.
- PR #59 retains the B42 normal 30-minute cadence, backs off idle delivery to 60 minutes, starts 429 fallback at 15 minutes and honors longer server deadlines. Native read deferral preserves the last real poll result without spending command reserve; prepared CARIAD settings reads retain allowance for the associated write. Validate actual recovery and multi-client effects before release; exact OEM quota scope is unconfirmed.
- Keep Data Act independently authorized and read-only. Native allowance remains conservatively shared where applicable. No automatic wake, retry of a vehicle mutation, implicit discovery, extra scheduler, new database or parallel state owner.
- Confirm whether both owner clients use the Data Act portal; compare sanitized HTTP evidence and request cadence. Do not request credentials. Further Q5 B42 feedback is pending.

### Acceptance and release gate

- [x] Product-owner implementation GO for sufficiently evidenced fixes only; release remains on HOLD.
- [ ] P0 command fixes and independent physical evidence or documented blocking uncertainty; do not label an OEM failure resolved without evidence.
- [ ] Source continuity, command evidence and all B42 discovery/registry/history regression tests.
- [ ] Data Act throttling, multi-client quota simulation, native isolation, restart/unload/cancellation, privacy and bounded request volume.
- [ ] V2 default/fallback and stable HA identifiers; Q8/Q5 field evidence and supported/unsupported/unverified distinctions.
- [ ] Simplification/ownership audit; no duplicate state or scheduler; updated documentation and governance delta ledger.
- [ ] Exact-head full Test/Validate, Workbench, HACS/hassfest, latest stable HA monthly release, package integrity and upstream review procedure.
- [ ] Separate product-owner release GO; immutable HACS beta and upstream review synchronization only via existing gates. Stable issue #44 remains open until separately accepted.

References: merged B42 product PR #58; merged Data Act PR #59 and issues #35/#36/#44; merged onboarding PR #52; [Q5 STOP evidence](https://github.com/audiconnect/audi_connect_ha/pull/918#issuecomment-6881591226), [manual STOP and mode evidence](https://github.com/audiconnect/audi_connect_ha/pull/918#issuecomment-6881920047), [B42 tester handoff](https://github.com/audiconnect/audi_connect_ha/pull/918#issuecomment-6883962709).

Focused, sufficiently evidenced fixes may be implemented and merged into dev after exact-head checks. Do not publish B43, change upstream delivery or announce a release until separately authorized.
