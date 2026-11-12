# Audi Connect V3 — capability-driven integration (review candidate)

**Configure → Discover automatically → Use.** V3 is an opt-in runtime within Audi Connect. V2 remains the default and fallback; one account, one config entry and stable native HA entity contracts are design requirements.

V3 provides reviewed automatic read discovery, semantic data normalization, capability-aware native entities, guarded commands, trip snapshots and bounded local trip history. The optional administrator Engineering Workbench supports investigating missing data and individually authorized control tests. Discovery never automatically sends physical commands.

## Testing

Back up Home Assistant. Use V3 only in an experimental test environment, select V3 under the integration runtime options, and verify available functions against myAudi and the vehicle. Revert to V2 in runtime options if necessary. Do not delete the registry to switch runtimes. The upstream review branch is not a published HACS release.

For issue reports, share the model/year/powertrain, market, HA and integration versions, expected/actual behavior and sanitized integration-specific diagnostics data only. Do not upload the complete Home Assistant diagnostics wrapper, unrelated integration inventory, credentials, VIN, coordinates, private trips or raw HTTP responses. Never repeat uncertain remote commands.

## Known limitations

Vehicle metadata has worked in earlier testing but can be absent in OEM responses; backend or authorization context may be involved, with no confirmed root cause. Preserve valid identity evidence and never invent missing data. HTTP acceptance is not physical completion. Model and market compatibility, V2 parity, HA lifecycle and rollback remain acceptance work. The legacy upstream read-only probe service remains available in V2; in V3 use the independent read discovery and Workbench instead.

## Review scope

Prior upstream contributions are retained. This candidate adds the V3 runtime, native HA projection, optional Workbench, regression coverage, and source inventory. The existing upstream release metadata and release pipeline remain authoritative; no stable promotion or default-runtime change is requested. Source inventories and ownership contracts are tests of implementation coverage, not physical vehicle certification.
