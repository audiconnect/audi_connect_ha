# Audi Connect V3 — user guide

**Configure → Discover → Use.** V3 is experimental and opt-in within Audi Connect. V2 remains the default and fallback. Keep one account, one config entry and the existing HA devices and entity IDs.

Use a [published test release](https://github.com/npinguin/audi_connect_ha/releases) containing V3.

## User guide

### Installation and rollback

Follow the [main README](../readme.md) for installation and sign-in. Install a published HACS release containing V3. Back up Home Assistant before upgrading. In **Settings → Devices & services → Audi Connect → Configure**, select the experimental V3 runtime if available. Keep the normal scan interval (minimum 15 minutes). Leave the optional engineering Workbench and EU Data Act disabled unless needed. After switching from V2, save and reopen Configure once the V3 runtime is loaded. Vehicle setup & discovery is checked by default whenever V3 options are opened. Finish or uncheck it to save without testing. It is always available for guided discovery or one specific function, including retests, without enabling the Workbench. If EU Data Act or dealer details are also selected, their configuration completes first; discovery then opens using the currently loaded vehicle profile. No vehicle command is sent by saving options.

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

- Charging controls retain the reported vehicle state after HTTP acceptance; requested action and correlated backend status remain separate. Other existing comfort/access controls can show explicitly marked optimistic requested state for at most five minutes after a known HTTP acceptance. This is not physical confirmation. Newer capture boundaries, rejection or a superseding command end that overlay; expiry and restart fall back to the actual last-known value. Check `state_is_optimistic`, `state_source`, `last_reported_state`, capture and command outcome. Read-only telemetry never projects command intent. A staged local temperature is an edit, not an applied temperature.
- HTTP 2xx means backend acceptance, not physical execution. A matching later capture is recorded separately as `command_readback_observed_at`; it does not turn an accepted command into a verified command. A matching state can result from myAudi, a timer or manual operation. Correlated OEM failure takes precedence over earlier acceptance. Never automatically replay an uncertain command. Routine command history is not discovery evidence or an interlock: retain verified routes across temporary failures and restart, and allow a new explicit request after the existing bounded cooldown. Only an explicit discovery experiment awaits physical review; authorization and parameter/prerequisite checks remain in force.
- Climate has separate read target, stored-settings start, temperature-bearing start, independent settings update and stop operations. The configured temperature can be readable even when no temperature-write route works. Temperature adjustment requires an enabled applicable write route selected by the resolver. A reviewed catalog match is not the same as local physical verification; an alternative route must be verified before activation. Availability depends on your vehicle.

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

The same physical instructions appear in Guided. If undated charging-mode option lists conflict, they never become ordered vehicle measurements. Use Vehicle setup & discovery → Verify preferred charging mode to physically test Manual and Timer separately. A valid native options list is authoritative; temporarily missing, empty or invalid options may retain only individually verified modes on the active route revision. Explicit invalidation of route proof or capability impairment remains binding. A selectable option is not proof of the currently reported mode. A reviewed equivalent route may be tried after definitive rejection under the existing consent and quota rules; never auto-send a different semantic action.

### Report a problem safely

Include the exact integration/HA version, vehicle model/year/powertrain and market (if known), action, local timestamp with time zone, expected versus actual outcome, and myAudi/physical evidence if relevant. Compare historical and current builds only when the conditions and operation are known.

Download integration diagnostics from **Settings → Devices & services → Audi Connect → three-dot menu → Download diagnostics**. The integration's own data is designed to exclude credentials, tokens, VINs, coordinates, raw payloads and private trip values. The surrounding HA export can contain unrelated system or integration information: review it and share only the sanitized Audi Connect data section. Attach a ZIP if GitHub refuses the JSON. Do not share complete HA logs, raw responses, OAuth callback URLs or secrets.

Diagnostics are read-only and do not wake the vehicle. They distinguish transport requests, coordinator attempts, cloud reachability, vehicle captures, source coverage, registry projections and structural command evidence. They are not a full request timeline. Unknown quota is neither zero nor unlimited. The quota sensor shows the last server-reported allowance in the current runtime, not a running balance. Read and command counters are separate. A reported allowance is not a guarantee of permission; after restart the current allowance remains unknown until a fresh header arrives. Active server restrictions are respected. Trip history is retained and the normal trip refresh deadline survives restart.

For contribution instructions, see [Contributing](../CONTRIBUTING.md).
