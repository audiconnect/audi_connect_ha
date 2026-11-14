# Audi Connect V3 — Architecture and maintainability closure

## Mandatory engineering principle: simplify before adding

Preserve V2 as the default and independent fallback. V3 must remain opt-in until accepted. Use the existing architecture; do not introduce a second runtime, catalog, command path or framework to fix a defect. Prefer native Home Assistant mechanisms and declarative capabilities. Keep production behavior independent from optional engineering tools.

The release objective is 100% agreed functional scope and V2 parity, zero known defects and zero known technical debt. This is a release gate, not a claim about current completeness. Unsupported OEM functionality is not a verified product feature; missing OEM evidence remains explicit and is not a reason to invent values or silently remove scope.

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

Discovery metadata belongs on the existing capability control. The catalog declares the reviewed actions, order, instructions and allowed parameter names; the shared parameter contract owns validation and the command owner owns dispatch, consent and physical evidence. Guided and selective use identical candidates. The native options wizard and the Workbench render the same candidate contract without their own capability policy. Native V3 options open discovery by default after optional configuration steps; every physical operation requires separate consent. A catalog entry never authorizes a command by itself. New semantics require reviewed implementation and tests; no new state or framework for an existing operation.

The machine-readable owner inventory is [OWNERSHIP.json](../governance/OWNERSHIP.json). Its current path coverage is not evidence that all functional boundaries are closed.

### Closure sequence

1. Inventory all V2/V3 features, operations, attributes, native entities, services and supported contexts against the pinned source and upstream issues.
2. Close HA routing, account ownership, lifecycle, auth and token ownership.
3. Rationalize duplicate catalog definitions and mappings; preserve stable IDs and all working behavior.
4. Consolidate status, vehicle state, command lifecycle and HA projections into their existing owners.
5. Simplify Workbench using backend templates; preserve security, opt-in tests and explicit activation. Close agreed community export/import scope.
6. Close storage, migrations, diagnostics, tests and documentation drift.
7. Verify exact-head CI, feature parity, representative ICE/PHEV/BEV and supported market/API contexts, restart/rollback, quota, privacy and physical acceptance.

Every change must state its existing owner, what complexity is removed, remaining validation and regressions. A new provider is not a new framework: API owns optional compatible sessions and family transport; Catalog owns one read priority per family and sparse mappings; Status owns observation selection and freshness; Vehicle and HA own stable VIN-scoped data and entity contracts. Provider authorization and market context determine eligibility, never entity identity. For equivalent valid read observations, the newest known vehicle capture wins; family priority breaks timestamp ties. An older delivery must not regress a valid vehicle capture. Invalid observations from another family cannot erase a valid sample. Family priority does not select or authorize commands. Retain operation-specific command safety and explicit activation; a read fallback cannot authorize or verify a command. No mock runtime values, speculative command routes, compatibility stubs or accepted debt. Every PR must identify the existing owner, removed duplication or simplified control flow, and the reason for any remaining necessary complexity. Compare runtime state, executable paths, and ownership before and after; do not count translations, documentation, or tests as runtime complexity. A new persistent or mutable state owner requires explicit justification and a retirement condition. Maintainability is not a line-count target. The 80% declarative operation target is a design measure, not a release gate.

### Release authority

Use one active development line and one upstream delivery line in the fork. Reuse the existing branches and review history; do not create a new long-lived branch or a new upstream PR for every beta.

| Branch                       | Responsibility                                                                                                    |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `dev`                        | Canonical V3 development and integration; focused fix PRs target this branch.                                     |
| `feature/v3-upstream-review` | Curated delivery to upstream `dev` through existing PR #918; only reviewed, validated, upstream-relevant changes. |
| `master`                     | Unmodified upstream master mirror.                                                                                |
| `main`                       | Historical fork baseline; no parallel V3 development.                                                             |
| `release/*`                  | Pinned HACS test candidates; published tags and their contents are immutable.                                     |

Keep the delivery branch an ancestor of development wherever practical. Sync reviewed upstream changes back into `dev` before additional development. Promote a coherent, validated delta from `dev` to the existing upstream review branch; exclude fork-only release packaging, experimental evidence, private diagnostics and unrelated research. Do not force-push the active upstream review branch or replace its PR. Use a short-lived fix branch only when review or CI needs it; retire it after integration when no release or review depends on it.

Merge focused PRs promptly once review, exact-head CI and relevant acceptance gates pass. Do not accumulate green fixes in parallel branches or wait for an unrelated beta. Review open PRs and branch drift at each release checkpoint; record the owner and concrete blocker for any deferred merge. Promote small coherent upstream-ready deltas regularly, without bypassing upstream maintainers or live acceptance gates. Sync the accepted delivery head back to development before the next promotion.

Keep the offered upstream product code, tests and documentation at most one published HACS beta behind. Before publishing a new beta, verify that the preceding published beta's pinned product source is already included in the upstream review branch. Count published releases, not skipped version numbers. If this gate fails, stop publication and review a coherent delta for promotion; never push to upstream automatically or interrupt an agreed review freeze. Fork-only packaging, release notes and version metadata stay outside the upstream contribution.

Derive HACS candidates from a pinned, validated `dev` runtime snapshot. Keep fork versioning and publication out of the upstream contribution. No release promotion, version reuse for changed published code, or upstream merge based only on static tests. Keep upstream release ownership intact. Separate implementation, automated evidence and live acceptance in all status reporting.

See [V3 review](V3_REVIEW.md) and [V2 parity baseline](V2_V3_PARITY_BASELINE.json). These inventories are not proof of full functional or physical acceptance.

## Feature closure status

See [the feature closure review](V3_FEATURE_CLOSURE.md). It separates source inventory, implementation, automated evidence and real vehicle acceptance. Do not use an entity-count or a passing unit suite as a feature-completeness claim.

### Deterministic observation selection

Use the existing Status writer, not a second resolver. Keep one normalized in-memory sample per known family and semantic field, with at most one older usable scalar for last-known display; never persist this cache. Only actual field/envelope capture defines chronology. No sibling, job, receipt or delivery clock substitution. Valid observations use newest known vehicle capture, then family priority and a stable tie-break; unknown capture ranks below known capture. Older or undated samples never overwrite newer dated observations within the same family. Conflicting equal/unknown captures are uncertain until a strictly newer valid capture resolves them. Missing fields do not invalidate observations. Undated OEM request arrays are receipt-ordered diagnostic metadata only; never vehicle state or command proof. Explicit invalidation affects its own family. No separate priority matrix or change to command authorization. Selection does not move to an older equivalent valid observation merely because a higher-priority family returned it; freshness provenance remains visible. Native command evidence is selected separately from eligible native observations using the same Status selector. Command outcomes are correlated to their own ID. A matching capture is separate readback evidence, not execution proof; only explicit physical review activates discovery routes. No command-derived physical state or synthetic last-known observation. Durable observed/verified capability evidence is independent of the current write gate.

### Passive discovery in the shared batch

Keep the fixed reviewed CARIAD job list in the existing selective-status request even when a job was previously reported unsupported. This does not increase the number of requests and lets the normal response correct old negative evidence. Explicit negatives still suppress separate targeted probes. Reuse an already fetched identical family/VIN/path response for targeted discovery. Preserve the bounded probe budget and explicit manual scan; do not treat missing data as permanent non-support. Verify the full batch continues to return usable responses on the live vehicle before release.

### Family polling ownership

Keep the existing HA coordinator and Status owner. Family cadence and source priority are independent. Poll only compatible authorized families when due, respecting the family restrictions AND any shared authentication/account quota. Do not split the native VCF budget into artificial independent counters: its scope is conservatively shared until proven otherwise. Data Act uses an isolated authorized portal session and its own existing QuotaBudget implementation, never the native command reserve. Optional absence, no new delivery, or a family failure must not invalidate another family's successful poll. No extra coordinator, consent creation or implicit auth downgrade.

Independent read sessions may run concurrently within one coordinator. Keep the checks at the two existing boundaries: API dispatch (auth, due time, quota, backoff) and normalized observation commit (semantic validity, capture time, family priority). Do not suppress an eligible read merely because another family provides a value. Shared native sessions and quota remain protected by the existing transport lock; no parallel entity writers or independent HA coordinators. Optional Data Act fetch results are merged at the same observation writer before the consolidated snapshot is published.

Before committing, run the existing pinned pre-commit hooks on changed files and focused tests where the development environment supports them. Batch related fixes; use the complete hook report rather than committing individual formatting corrections. Preserve the exact-head full PR and release validation gates. No new lint workflow or relaxed check.

### Control-state continuity (B41)

Status owns canonical readings and their historical scalar representation.
The profile serializes the same vehicle map; the old climate-only cache is
migrated and removed. Restored observations are historical, never fresh
readback or route authorization. No optional Data Act, location or raw response
is persisted here. Command owns intent, outcome and bounded expiry; HA derives
effective state from these existing owners, with no independent state cache.
Restart restores observations and outcomes but never reactivates intent.
One coordinator-local timer expires the overlay without a vehicle request.
Read-only telemetry never projects intent. The HA assumed-state indicator and
explicit source/last-reported attributes distinguish estimated controls.
No automatic replay, new store or polling owner.

Routine execution outcomes never revoke or permanently block a discovered control. The Command owner retains the latest outcome and enforces bounded dispatch cooldowns; only an explicit discovery review can change physical route evidence, subject to context/revision and authorization checks. No replay, implicit rediscovery or mandatory historical-command review after restart.
