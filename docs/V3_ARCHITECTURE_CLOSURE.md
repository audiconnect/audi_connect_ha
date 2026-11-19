# Audi Connect V3 — Architecture and ownership

## Mandatory engineering principle: simplify before adding

Preserve V2 as the default and independent fallback. V3 must remain opt-in until accepted. Use the existing architecture; do not introduce a second runtime, catalog, command path or framework to fix a defect. Prefer native Home Assistant mechanisms and declarative capabilities. Keep production behavior independent from optional engineering tools.

Preserve V2 behavior and stable entity semantics. Unsupported OEM functionality is not a verified product feature; missing evidence is not a reason to invent values or silently remove scope.

Preserve proven behavior as a first-class regression requirement. Each change must improve simplicity, ownership clarity, manageability, efficiency and reliability together; do not sacrifice working capabilities to simplify implementation. New or unproven operations remain explicit experiments using existing discovery contracts and must not damage previously verified behavior. Optimize for maximum useful functionality and vehicle-data freshness with minimum necessary requests, processing and storage. Adapt to observed delivery, activity, quota and recovery evidence; never confuse an arbitrary long cooldown with stability or intentionally exceed server limits.

### Review criteria for every improvement

| Criterion       | Required evidence                                                                         |
| --------------- | ----------------------------------------------------------------------------------------- |
| Simplification  | Remove duplicate state, paths or decisions; explain any unavoidable added complexity.     |
| Ownership       | One existing owner per responsibility and authoritative contract; no parallel writer.     |
| Maintainability | Declarative mappings, bounded state, native HA mechanisms, focused tests and rollback.    |
| Extendability   | Add reviewed variants through existing catalog and contracts; no parallel resolver or UI. |
| User experience | Ordinary use needs no Workbench, duplicate integration, API knowledge or entity rename.   |

Use the existing PR review, not an additional workflow or a second governance catalog. Show before/after runtime impact, user-visible outcome and remaining live acceptance. Provider problems must be actionable without exposing credentials or making another channel unavailable. The Workbench remains optional and administrator-only.

### Authoritative responsibilities

| Owner           | Responsibility                                                                 |
| --------------- | ------------------------------------------------------------------------------ |
| Shared HA entry | Account/device association, config and runtime selection                       |
| API             | Authentication, transport, family protocols and quota                          |
| Catalog         | Canonical capabilities, operations, attributes and reviewed discovery metadata |
| Status          | Read discovery, polling, normalization and freshness                           |
| Vehicle         | Canonical vehicle identity and observations                                    |
| Command         | Eligibility, execution, durable journal, verification                          |
| Profiles        | Bindings and persistent evidence                                               |
| HA              | Stable native entities, services and registry lifecycle                        |
| Workbench       | Optional administrator analysis, configuration and test UX                     |
| Diagnostics     | Read-only reporting and redaction                                              |
| Engine          | Composition and lifecycle orchestration                                        |

Read: API → status → vehicle → HA. Write: HA owning device → active runtime → command → API → shared status writer → vehicle/HA and verified native readback. Engineering: discover → configure → isolated test → explicit activation. A command must never be routed to an unrelated account by VIN. Ambiguous ownership fails closed.

Climate discovery is vehicle-specific: stored start, parameterized start and settings-only are independent; a temperature test does not qualify optional zones, window heating, external-power preferences or modes. The shared parameter contract offers observed native optional fields only, with fresh settings validation before mutation. Optional combinations use bounded, revision- and context-scoped physical evidence in the existing profile and command journal; a failed optional test does not invalidate a proven baseline route. No automatic combination search, guessed modes, or new writes based on read-only telemetry. Legacy MBB payloads remain separate and require their own vehicle qualification.

Discovery metadata belongs on the existing capability control. The catalog declares the reviewed actions, order, instructions and allowed parameter names; the shared parameter contract owns validation and the command owner owns dispatch, consent and physical evidence. Guided and selective use the same reviewed operation and parameter contracts. Guided offers one suggested route per action; selective allows each safe reviewed equivalent explicitly, with no automatic alternative dispatch in selective mode. Earlier failure is evidence, not a permanent discovery lockout. The native options wizard and the Workbench render the same candidate contract without their own capability policy. Native V3 options expose independent navigation choices; discovery opens only when explicitly selected; every physical operation requires separate consent. A catalog entry never authorizes a command by itself. New semantics require reviewed implementation and tests; no new state or framework for an existing operation.

The machine-readable owner inventory is [OWNERSHIP.json](../governance/OWNERSHIP.json). It describes runtime responsibility, not vehicle compatibility.

Every change must state its existing owner, what complexity is removed, remaining validation and regressions. A new provider is not a new framework: API owns optional compatible sessions and family transport; Catalog owns one read priority per family and sparse mappings; Status owns observation selection and freshness; Vehicle and HA own stable VIN-scoped data and entity contracts. Provider authorization and market context determine eligibility, never entity identity. For equivalent valid read observations, the newest known vehicle capture wins; family priority breaks timestamp ties. An older delivery must not regress a valid vehicle capture. Invalid observations from another family cannot erase a valid sample. Family priority does not select or authorize commands. Retain operation-specific command safety and explicit activation; a read fallback cannot authorize or verify a command. No mock runtime values, speculative command routes, compatibility stubs or accepted debt. Every PR must identify the existing owner, removed duplication or simplified control flow, and the reason for any remaining necessary complexity. Compare runtime state, executable paths, and ownership before and after; do not count translations, documentation, or tests as runtime complexity. A new persistent or mutable state owner requires explicit justification and a retirement condition. Maintainability is not a line-count target. The 80% declarative operation target is a design measure, not a release gate.

### Deterministic observation selection

Use the existing Status writer, not a second resolver. Keep one normalized in-memory sample per known family and semantic field, with at most one older usable scalar for last-known display; never persist this cache. A bounded in-memory diagnostic trace retains recent charging receipts (including repeated older captures); it is never a state source or persisted. Only actual field/envelope capture defines chronology. No sibling, job, receipt or delivery clock substitution. Valid observations use newest known vehicle capture, then family priority and a stable tie-break; unknown capture ranks below known capture. Older or undated samples never overwrite newer dated observations within the same family. Conflicting equal/unknown captures are uncertain until a strictly newer valid capture resolves them. Missing fields do not invalidate observations. Undated OEM request arrays are receipt-ordered diagnostic metadata, never vehicle state or physical proof. Only an exact own native request ID in the reviewed route's queue, with matching operation and unchanged dispatch context, may update backend outcome through the Command owner. No identifier alias guessing, restored-session correlation, inference from disappearance or extra poll. Explicit invalidation affects its own family. No separate priority matrix or change to command authorization. Selection does not move to an older equivalent valid observation merely because a higher-priority family returned it; freshness provenance remains visible. Native command evidence is selected separately from eligible native observations using the same Status selector. Command outcomes are correlated to their own ID. A matching capture is separate readback evidence, not execution proof; only explicit physical review activates discovery routes. No command-derived physical state or synthetic last-known observation. For cabin climate, an invalid current observation (including restored invalid history) means unknown effective HVAC mode; historical state remains available in attributes and explicit controls retain their independent eligibility. Durable observed/verified capability evidence is independent of the current write gate. Charging and climate timer counts and next single timer derive from the same selected normalized timer list; conflicting or incomplete lists invalidate derived values without deleting prior scalar history. An invalid timer observation does not publish a historical count as effective state.

### Passive discovery in the shared batch

Keep the fixed reviewed CARIAD job list in the existing selective-status request even when a job was previously reported unsupported. This does not increase the number of requests and lets the normal response correct old negative evidence. Explicit negatives still suppress separate targeted probes. Reuse an already fetched identical family/VIN/path response for targeted discovery. Preserve the bounded probe budget and explicit manual scan; do not treat missing data as permanent non-support. Verify the full batch continues to return usable responses on the live vehicle before release.

### Optional parking enrichment

The existing Status parking owner may resolve one approximate address from an already observed parked point, only with explicit V3 opt-in and an authorized configurable HTTPS reverse endpoint. No public Nominatim vehicle-tracking service, Audi credentials, location in diagnostics, persistent address cache, new Audi request or extra polling schedule. A bounded in-memory cache is keyed by rounded position and provider; the existing HA entry owns cancellation of one optional lookup at a time. A missing result does not affect native parking, zones or cloud health. HA projects a separate address sensor; the tracker and local-zone identity remain unchanged.

### Family polling ownership

Keep the existing HA coordinator and Status owner. Family cadence and source priority are independent. Native API accounting separates last server-reported VCF allowance, local requests by family and read/command class, and actual server restrictions. The remote scope is unknown; do not invent independent or additive OEM budgets. Ordinary reads do not debit or block on a presumed remaining allowance. A fresh same-family header may inform a conservative local preparation estimate for command sequences; its local validity window is not an OEM refill period. A server restriction defers reads for the affected family and prevents dispatch during the deadline. Only success in the matching family and request class can clear its streak; explicit new commands may recover after the deadline, never automatic replay.

Native and separately authorized Data Act sessions reuse the shared rate-limit mechanism with independent checkpoints in the existing private entry store. Restore restrictions, not a numeric current allowance. No extra coordinator, consent creation or implicit auth downgrade. Data Act maintains its independent delivery cadence and backoff; optional failure must not invalidate native success.

The Status owner uses the vehicle profile's persisted trip refresh deadline: three hours after a complete cycle, fifteen minutes after an incomplete cycle; context change invalidates the deadline. Do not repeat a completed trip refresh just because HA restarted. Normal native polling and optional read scheduling remain bounded. Ordinary Data Act delivery scheduling is runtime-local; persisted rate-limit recovery is separate. Broader adaptive scheduling requires measured evidence.

Independent read sessions may run concurrently within one coordinator. Keep the checks at API dispatch (auth, due time, restrictions) and normalized observation commit (semantic validity, capture time, family priority). No parallel entity writers, independent HA coordinators or read fallback that authorizes a command.

### Control-state continuity

Status owns canonical readings and their historical scalar representation.
The profile serializes eligible native historical scalar evidence and selected native conflict boundaries from the existing vehicle and family maps; conflict markers contain only capture, family and reason plus an eligible strictly older scalar if available. Undated conflicts remain uncertain across restart; no raw timer list or family cache is persisted. The same observation writer resolves a conflict only on a newer valid capture. The old climate-only cache is migrated and removed. Restored observations are historical, never fresh
readback or route authorization. No optional Data Act, location or raw response
is persisted here. Command owns intent, outcome and bounded expiry; HA derives
effective state from these existing owners, with no independent state cache.
Restart restores observations and outcomes but never reactivates intent.
One coordinator-local timer expires the overlay without a vehicle request.
Read-only telemetry never projects intent. Stateful controls may project accepted intent for at most five minutes from dispatch. A newer valid capture supersedes intent; after expiry or restart without such a capture the effective control state is unknown. Preserve the last reported observation separately. The HA assumed-state indicator and
explicit source/last-reported attributes distinguish estimated controls.
No replay of pending or uncertain actions, new store or polling owner. An explicitly enabled, default-off V3 option permits zero or one extra direct CARIAD charging STOP under the original explicit intent. Both attempts use the same configurable confirmation and bounded verification lifecycle. After the confirmation timeout, reuse existing exact request-ID evidence or perform one exact-ID status check. Only an exact terminal timeout and a new native still-charging capture after that timeout (at most 60 seconds old), unchanged same-session route and intent, and available quota authorize a second STOP. Reuse fresh observations before reading. The existing Status owner serializes up to ten single-job charging GETs per attempt with ordinary native polling, using the same canonical observation writer and coordinator publication. The existing command journal retains runtime-only recovery outcomes, never restored as authority. The HA entry task is cancelled on unload, never restored, never repeats a retry, and never wakes the vehicle. No additional periodic polling. Charging controls display native or clearly marked last-known state rather than optimistic intent; matching charging captures outside the five-minute correlation window remain telemetry only.

Routine execution outcomes never revoke or permanently block a discovered control. The Command owner retains the latest outcome and enforces bounded dispatch cooldowns; only an explicit discovery review can change physical route evidence, subject to context/revision and authorization checks. No replay, implicit rediscovery or mandatory historical-command review after restart.
