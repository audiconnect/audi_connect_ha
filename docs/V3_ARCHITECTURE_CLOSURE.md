# Audi Connect V3 — Architecture and maintainability closure

## Mandatory engineering principle: simplify before adding

Preserve V2 as the default and independent fallback. V3 must remain opt-in until accepted. Use the existing architecture; do not introduce a second runtime, catalog, command path or framework to fix a defect. Prefer native Home Assistant mechanisms and declarative capabilities. Keep production behavior independent from optional engineering tools.

The release objective is 100% agreed functional scope and V2 parity, zero known defects and zero known technical debt. This is a release gate, not a claim about current completeness. Unsupported OEM functionality is not a verified product feature; missing OEM evidence remains explicit and is not a reason to invent values or silently remove scope.

### Authoritative responsibilities

| Owner           | Responsibility                                             |
| --------------- | ---------------------------------------------------------- |
| Shared HA entry | Account/device association, config and runtime selection   |
| API             | Authentication, transport, family protocols and quota      |
| Catalog         | Canonical capability, operation and attribute definitions  |
| Status          | Read discovery, polling, normalization and freshness       |
| Vehicle         | Canonical vehicle identity and observations                |
| Command         | Eligibility, execution, durable journal, verification      |
| Profiles        | Bindings and persistent evidence                           |
| HA              | Stable native entities, services and registry lifecycle    |
| Workbench       | Optional administrator analysis, configuration and test UX |
| Diagnostics     | Read-only reporting and redaction                          |
| Engine          | Composition and lifecycle orchestration                    |

Read: API → status → vehicle → HA. Write: HA owning device → active runtime → command → API → verified readback. Engineering: discover → configure → isolated test → explicit activation. A command must never be routed to an unrelated account by VIN. Ambiguous ownership fails closed.

The machine-readable owner inventory is [OWNERSHIP.json](../governance/OWNERSHIP.json). Its current path coverage is not evidence that all functional boundaries are closed.

### Closure sequence

1. Inventory all V2/V3 features, operations, attributes, native entities, services and supported contexts against the pinned source and upstream issues.
2. Close HA routing, account ownership, lifecycle, auth and token ownership.
3. Rationalize duplicate catalog definitions and mappings; preserve stable IDs and all working behavior.
4. Consolidate status, vehicle state, command lifecycle and HA projections into their existing owners.
5. Simplify Workbench using backend templates; preserve security, opt-in tests and explicit activation. Close agreed community export/import scope.
6. Close storage, migrations, diagnostics, tests and documentation drift.
7. Verify exact-head CI, feature parity, representative ICE/PHEV/BEV and supported market/API contexts, restart/rollback, quota, privacy and physical acceptance.

Every change must state its existing owner, what complexity is removed, remaining validation and regressions. A new provider is not a new framework: API owns optional compatible sessions and family transport; Catalog owns one read priority per family and sparse mappings; Status owns observation selection and freshness; Vehicle and HA own stable VIN-scoped data and entity contracts. Provider authorization and market context determine eligibility, never entity identity. A fresh preferred read family cannot be displaced by a lower-priority equivalent observation; stale fallback must not regress a valid vehicle capture. Invalid observations from another family cannot erase a valid sample. Family priority does not select or authorize commands. Retain operation-specific command safety and explicit activation; a read fallback cannot authorize or verify a command. No mock runtime values, speculative command routes, compatibility stubs or accepted debt. Maintainability is not a line-count target. The 80% declarative operation target is a design measure, not a release gate.

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

Use the existing Status writer, not a second resolver. Keep one normalized in-memory sample per known family and semantic field; never persist this cache. Valid fresh observations use family priority, then capture time and a stable tie-break. If no fresh observation exists, use the newest valid captured sample, then family priority; unknown capture ranks below known capture. Older samples never overwrite a newer sample within the same family. Explicit invalidation affects its own family. No separate priority matrix or change to command authorization. The selected projection may legitimately move to a slightly older but still fresh higher-priority family; freshness provenance remains visible.
