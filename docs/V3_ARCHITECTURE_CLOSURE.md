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

Every change must state its existing owner, what complexity is removed, remaining validation and regressions. No mock runtime values, speculative command routes, compatibility stubs or accepted debt. Maintainability is not a line-count target. The 80% declarative operation target is a design measure, not a release gate.

### Release authority

Develop against the current upstream review head; use short-lived review branches and derive HACS candidates from a pinned, validated runtime snapshot. No release promotion, version reuse for changed published code, or upstream merge based only on static tests. Keep upstream release ownership intact. Separate implementation, automated evidence and live acceptance in all status reporting.

See [V3 review](V3_REVIEW.md) and [V2 parity baseline](V2_V3_PARITY_BASELINE.json). These inventories are not proof of full functional or physical acceptance.

## Feature closure status

See [the feature closure review](V3_FEATURE_CLOSURE.md). It separates source inventory, implementation, automated evidence and real vehicle acceptance. Do not use an entity-count or a passing unit suite as a feature-completeness claim.
