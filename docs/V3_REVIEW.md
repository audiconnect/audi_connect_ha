# Audi Connect V3 — user, engineer and maintainer review

**Configure → Discover automatically → Use.** V3 is an opt-in runtime within Audi Connect. V2 remains the default and fallback; one account, one config entry and stable native HA entity contracts are design requirements.

## User: installation and everyday use

Follow the [Audi Connect installation instructions](../readme.md) for your installed version. Back up Home Assistant. Only select V3 in the integration runtime options if your build includes the experimental runtime. Keep the existing config entry, devices and entities; do not delete the registry when switching back to V2.

- Select the normal scan interval in the integration options. V3 always enumerates vehicles during setup; the V2-only startup update preference remains stored for rollback. Vehicle data comes from Audi's cloud: a successful HTTP refresh does not necessarily mean the vehicle has sent new measurements. Look at vehicle capture time and availability, not only the latest cloud poll. The tracker represents the last parked position, not live GPS; movement without a reliable vehicle capture remains unknown.
- Read discovery and native controls depend on the vehicle and supported API. A missing or unavailable control is not permission to try another command. Never repeat an uncertain remote command; HTTP acceptance is not physical completion.
- Optional EU Data Act is read-only and off by default. Obtain an authorized continuous request in Audi's official portal, then use Manage EU Data Act in V3 options. Enter portal credentials locally when required. The wizard and EU Data Act diagnostic show the connection and last successful delivery separately from native Audi health; Keep current connection does not reauthenticate. Connected means a delivered or acknowledged unchanged dataset, not fresh vehicle data. Awaiting data means no confirmed delivery; subscription unavailable or access denied means check the portal request; authorization required means check credentials; rate limited means allow automatic recovery. Disconnect removes local optional credentials and observations without changing native Audi login or the portal request. Data Act never authorizes or confirms commands. The Workbench exposes source mappings and timestamps; no second integration is needed.
- Latest vehicle data age reports the newest usable measurement, not the oldest; the attributes and Workbench expose the oldest and per-job ages. Check the specific entity capture and freshness for automations. An accepted command may display a bounded optimistic comfort state or locking/unlocking transition; neither changes the vehicle capture clock. Check command status, requested state and last reported state. New valid telemetry, including command-response data, supersedes that display. A mismatch is not proof of a failed physical action.
- V3 Engineering Workbench is administrator-only and optional. Ordinary use does not require it. Use the existing V2 runtime option to revert if necessary.

For issue reports, share the model/year/powertrain, market, HA and integration versions, expected/actual behavior and sanitized integration-specific diagnostics data only. Do not upload the complete Home Assistant diagnostics wrapper, unrelated integration inventory, credentials, VIN, coordinates, private trips or raw HTTP responses.

## Engineer: investigate and validate

Use the existing [architecture and ownership contract](V3_ARCHITECTURE_CLOSURE.md) and [feature closure register](V3_FEATURE_CLOSURE.md). V3 provides reviewed automatic read discovery, semantic data normalization, capability-aware native entities, guarded commands, trip snapshots and bounded local trip history. The optional Workbench supports missing-data investigation and individually authorized control tests; discovery never automatically sends physical commands.

Compare exact installed versions and runtime contexts. Diagnostics distinguish current transport request count, coordinator attempts, native cloud reachability, vehicle capture and the latest structural record per operation (which can include restored evidence). The operation list is not a complete request timeline; unknown quota is not zero or unlimited quota. Capture-less parking indications are not live motion telemetry. Preserve source timestamps and registry IDs. Reuse existing owners and tests; never add a poller, auth workaround or speculative command to compensate for absent evidence.

## Maintainer: release and upstream review

Prior upstream contributions are retained. The candidate adds the independent V3 runtime, native HA projection, optional Workbench, regression coverage and source inventory. The existing upstream release metadata and pipeline remain authoritative; no stable promotion or default-runtime change is requested. Review exact-head Test/Validate, the existing packaging checks and the relevant real-vehicle acceptance separately. The upstream review branch is not a published HACS release. Use the existing upstream PR and fork candidate workflow; see the [release authority](V3_ARCHITECTURE_CLOSURE.md#release-authority).

Source inventories, normalized attribute counts, entity counts and ownership contracts are implementation evidence, not physical vehicle certification. Vehicle metadata has worked earlier but can be absent from OEM responses; backend or authorization context may be involved, with no confirmed root cause. Charging controls, model/market compatibility, V2 parity, HA lifecycle and rollback, quota and optional Data Act live acceptance remain explicit release gates. The legacy upstream read-only probe service remains available in V2; in V3 use independent read discovery and Workbench instead.

## B37 engineering closure — multi-source acceptance candidate

B36 is the measured runtime baseline: first authorized Data Act delivery, 84 bounded structural fields, 19 mapped/normalized, 2 selected; 64/101 canonical attributes normalized, none fresh. 125 registered entities, 98 offered, 394 complete odometer-interval trip records. One poll is not a soak test. No raw owner diagnostics retained in the repository.

B37 corrects the existing owners rather than adding a new runtime, source scheduler, entity contract or dashboard:

- Registry-driven source selector and consolidated coverage; existing schema and observation evidence supply source mapping, capture, receipt, delivery and selection. Parking hints do not count as movement.
- Dedicated portal connect/reconnect/disconnect options; validate credentials before replacing working settings. Existing native authentication stays separate. The optional source's actionable status is visible in the existing integration status attributes and Workbench, not a native account reauthentication trigger.
- Record privacy-safe portal identity schema and outcome; never use nickname or VIN inference. On terminal authorization loss or explicit disconnect, remove optional identity and observations, retaining native measurements and trips. Missing dataset subscription removes dataset readings, not independently authorized identity.
- Invalidate both selected and competing readings when a mapping changes or is disabled. Ignore late disabled-route responses. Re-activation requires a new normal read. Derive ETA from the currently selected duration, not an independent cache. Coalesce registry reconciliation and preserve historical entity IDs and user choices.
- Share one bounded response-body reader across native and optional transport. Mark profile and registry storage private; no raw datasets are persisted.
- Add exact UUID/name mappings for minute-based charging/climate durations and explicit hood status; invalid/sentinel values do not become telemetry. Source: [community Data Act dictionary](https://github.com/TA2k/ioBroker.vw-connect/blob/master/lib/euDataActDictionary.json). These are candidates pending real vehicle evidence, not guaranteed extra live fields.

### Acceptance gates

The experimental HACS candidate requires exact-head Test/Validate, the existing release-only delta and pinned merged source, both HA compatibility targets, archive verification and the preceding beta's upstream review source. No stable release is implied.

Live acceptance remains necessary: upgrade/restart and V2 rollback; source authentication and revocation; native and optional freshness after a ride and active charging; model identity from actual OEM fields; physical control evidence; registry/trip preservation; independent ICE/PHEV/BEV and regional coverage. Unknown charging enums, maintenance signs, tyre units, ambiguous door states, oil validity and BEM semantics stay unmapped until evidence exists. This is not a reason to create a second model or to fabricate support.

Existing issue #44 remains the stable release gate. Do not equate passed synthetic tests, HTTP acceptance, or assessed schema coverage with vehicle support. B37 is an engineering correction and acceptance candidate, not a claim of zero remaining product or upstream debt.

## B38 field-test closure and source contract

Q5 field evidence in upstream #918 confirms 1,000 trips survive B32 to B35 and physical charging start/stop, independent power-meter confirmation, mostly German entity names and numeric quota. Model identity remains unavailable in both Q5 and Q8; browser Auth0 and the OEM GraphQL partial response are not proof of an unsupported vehicle. HACS master-versus-beta behavior is an upstream merge/packaging concern. V2 default is intentional; new Auth0 entries already use the readable title Audi Connect.

B38 addresses actual source observation visibility, the blank optional-authentication menu, and all 84 structurally observed Data Act fields. Every exact UUID/name pair has a declared destination: existing canonical attributes or bounded informational details. This is mapping inventory coverage, not 84 valid measurements. Unknown units, invalid values and unproven enum semantics are not physical evidence. The field inventory fixture contains no personal values.

### Extending source and authentication coverage

Keep the existing owners: account/session authentication, reviewed family executor and relative operation paths, registry mappings, shared observation and identity consolidation, native HA projection. Authentication context is not a family name: GraphQL and CARIAD may share an account while requiring different token audiences. Optional Data Act has an isolated portal session; its failure must not invalidate the native account. Workbench shows coarse token role/availability and delivery status without credentials or unverified claims as authorization.

For a possible myAudi web identity source, first obtain sanitized evidence of an authorized inventory operation and its response fields. Prefer the central Audi ID and regional endpoint resolution inside the reviewed transport owner. Market-specific hosts and locale belong in that adapter, not the core or canonical model. Do not allow arbitrary URLs, import browser tokens, bypass OAuth client limitations, or automatically replay unreviewed requests. Add an independent auth context only if the documented/observed operation actually requires it; reuse existing HA options/reauth, request budget, bounded response reading and source discovery. A valid same-VIN manufacturer model/year and drivetrain remain live acceptance blockers. Never promote a display nickname or infer a manufacturer model from a VIN.

The B38 release is a test candidate, not an accepted stable release. After field acceptance, consolidate and remove redundant discovery/projection code, validate source failure/renewal, preserve entity contracts and trip history, and rerun the existing compatibility and upstream gates. No new runtime framework is justified.

## B39 consolidation — B38 live diagnostics and engineering audit

B38 Q8 baseline (HA 2026.11.1): one successful native poll, optional dataset
received, 84 observed dataset fields mapped, 30 normalized canonical source
observations and 28 normalized read-only details. Four Data Act observations
selected; 64/101 canonical attributes overall, zero fresh. Registry: 126
entries, 98 enabled runtime offers, no category drift; 394 archived trips.
Mapping coverage is not value coverage. No private diagnostic payload is
committed.

The existing Capabilities view now compares declared source mappings, actual
normalized observations, invalid states, capture time and selected source
with family priority. Source columns are registry-driven; technical details
are folded. Additional read-only source details appear in their relevant
capability without new HA entities. Transport and source-level discovery
remain in API Log; the guided physical verification path is retained. Ordinary
users continue to use native HA entities.

Status records timestamped rejected/conflicting Data Act samples through the
existing observation writer, preserves valid independent native fallback and
does not treat missing/null fields or undated rejections as invalidation.
Declared detail metadata, rather than attribute naming, excludes informational
details from operational freshness. Optional delivery status is vehicle-scoped
in vehicle health and Workbench; account scheduling remains shared. The
catalog rejects malformed observation mapping contracts at construction.
Workbench refresh computes a local command binding snapshot without writing
to profiles. No added polling, scheduler, persistent cache, command route,
HA entity or required setup step.

### Remaining acceptance and audit scope

Identity remains open (#35); no invented metadata or unapproved authentication
workaround. Source engineering detail labels and units do not imply physical
semantics or support. Confirm B39 on a normal drive, active charging, optional
disconnect/reconnect, multi-vehicle isolation, HA restart and V2 rollback.
The existing guided validation UI remains a separate view for this candidate;
consolidating it into four governance views and real-browser acceptance,
config flow simplification, remaining freshness primitive duplication and
broader extensibility audit remain tracked in #44. Stable release is NO GO.
An experimental candidate must pass all existing release and upstream gates.

## B40 operational UX — B39 field feedback

Expose the existing Data Act delivery state in both HA options steps and a
vehicle-scoped diagnostic entity. A configured login is not a confirmed
delivery; an acknowledged unchanged file is not a disconnected source. The
account wizard uses the existing account projection; an available connection
can be kept without reauthenticating. No extra request or persistent cache.
Optional source failures remain independent of native Audi health.

Manufacturer identity and GraphQL inventory metadata findings remain in
engineering evidence with informational severity if the native poll succeeds
and the vehicle is present. Other failures continue to drive operational
health. The ordinary HA last-error entity shows only an actionable active
operational error. Rename discovery coverage to assessment without changing
entity identity or its meaning. Position explicitly overrides the HA tracker
base-class diagnostic category; the existing reversible registry reconciliation
preserves the device, entity ID and history.

Keep optimistic comfort/charging projections and expose requested command
state and whether the displayed value is optimistic through the existing
shared command metadata. Security controls remain conservative: stale lock
status is unknown, a command acceptance is a bounded locking/unlocking
transition, and only vehicle readback can confirm the physical state.
No extra command requests or automatic retry. Real HA restart, device-page,
wizard and lock/comfort action acceptance remain required.

### B40 follow-up — measurement age and redundant readiness

The existing vehicle age entity measures the latest usable scalar vehicle
capture; preserve its ID, units and semantics. Name it Latest vehicle data age.
Keep oldest observed age and individual job ages in existing attributes and
show both ages in Engineering. No new freshness sensor or polling.

Remove the redundant V3-only Charging ready binary sensor, its special
projection and traceability alias. Retire the exact registry identity through
the existing pilot retirement mechanism, preserving history and user-owned
settings. The OEM chargingState remains normalized and visible; readiness is
not a separate permission or actionable control. V2 remains unchanged.

Workbench list age now uses the same global capture summary as native HA,
not climate capture age. Shared diagnostics include bounded per-source capture
evidence for SoC, charging, plug, lock and climate, without scalar values or
source paths. This supports comparison against actual charging/locking events
without claiming the existing data gaps have been resolved.

B39 field evidence (2026-11-14): 48 fresh canonical attributes, latest capture
16:37 local, last cloud poll 17:06. Lock readback mismatch after accepted unlock
must remain visible; no assertion of physical failure from HTTP or mismatch.
Use the existing bounded command projection window for lock transitions too,
independently of command cooldown; never optimistically claim locked/unlocked.
A newer explicit non-charging observation suppresses a superseded derived ETA,
while preserving its underlying duration for engineering evidence.

Command responses now use the same normalized observation and capture
projection as native polling, with the actual operation as provenance.
Only valid per-envelope vehicle captures newer than the command start are
eligible; HTTP acceptance, request echoes and undated values never advance
freshness or confirm physical state. The existing last-update entity updates
immediately, independent of the cloud poll clock. Regression covers a combined
access/charging response, stale and missing captures, and request-only echo.

Source projections explicitly label derived ETA and global last update and
retain the source operation in the matrix; direct dataset counts remain
separate from normalized projections. Invalid climate state cannot produce a
valid climate age. Source operation identifiers are filtered in exported
capture evidence to the built-in registry.

### B40 final field acceptance before stable promotion

Use the pinned HACS candidate and restart without deleting the integration.
Record the installed version, sanitized integration diagnostics and actual
vehicle outcomes. Acceptance is not a requirement to make every OEM field
available: unsupported or unproven controls must stay unavailable.

| Check                   | Acceptance                                                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Upgrade and rollback    | IDs, user settings and trip archive retained; V2 still works                                                        |
| Setup and Data Act      | Wizard and diagnostic agree; keep/disconnect/reconnect do not affect native auth                                    |
| Normal driving/charging | Individual captures and global latest/oldest age agree; no old ETA treated as active                                |
| Lock/unlock             | Actual vehicle outcome compared to accepted, pending, verified or mismatch; no fabricated state                     |
| Climate and charging    | Native controls, optimistic feedback and real readback agree; unavailable OEM values explicitly marked              |
| Workbench               | Source priority, derived values, operation and capture/receipt evidence consistent; no extra requests               |
| Health and registry     | Identity warning stays in engineering; native failures remain actionable; Position ordinary, Charging ready retired |
| Regression and release  | Exact-head tests, both HA targets, immutable candidate, upstream review and #44 acceptance                          |

Keep V3 experimental if any gate is unresolved. After acceptance, freeze feature
scope and perform maintenance only (security, regressions, OEM breaking changes).
The upstream maintainer remains the authority for the upstream default/stable
release. Do not claim stable certification from CI or one Q8 runtime alone.
