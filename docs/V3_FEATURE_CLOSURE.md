# V3 feature closure and release acceptance

This is the enduring acceptance contract, not a release-status page or a second backlog. [Stable gate #44](https://github.com/npinguin/audi_connect_ha/issues/44) owns the active decision and evidence; [published releases](https://github.com/npinguin/audi_connect_ha/releases) own version-specific changes and installation artifacts. [Upstream PR #918](https://github.com/audiconnect/audi_connect_ha/pull/918) owns upstream review. A passing suite or a single vehicle is not stable acceptance.

## Authoritative inventories

- [V2 parity baseline](V2_V3_PARITY_BASELINE.json): historical inventory, not a current generated inventory.
- [Product entity contract](../custom_components/audiconnect/v3/product_entities.json): native HA identities and declared extensions.
- [Capability catalog](../custom_components/audiconnect/v3/full_catalog.json): reviewed executable variants, not proof of physical support.
- [Ownership](../governance/OWNERSHIP.json): responsibility and architecture constraints.

Do not reproduce these inventories in a second editable catalog. See the [V3 guide](V3_REVIEW.md) for use and [architecture contract](V3_ARCHITECTURE_CLOSURE.md) for design rules.

## Acceptance criteria

- **Charging:** independently measure physical START/STOP and charging power. An accepted request, optimistic switch or later matching observation is not execution proof. Verify manual/timer modes, target SOC, profiles, ETA expiry and fail-closed unavailable routes; no automatic replay or guessed modes.
- **Climate and remote controls:** verify stored and parameterized start, independent settings, stop, window/auxiliary heating, access, flash, refresh/wake and engine actions only where eligible. Preserve explicit physical discovery and route-specific evidence.
- **Identity and coverage:** verify manufacturer model/year/image and powertrain provenance, representative ICE/PHEV/BEV, Auth0/legacy, markets, actual MBB reads and unavailable features. Missing metadata is not proof of unsupported vehicle.
- **Telemetry:** preserve capture times, last-known values, partial responses, zero versus missing and source semantics. Native and optional Data Act observations consolidate without making delayed data live or authorizing commands.
- **Trips:** preserve original entity semantics, current/reset/last distinctions and local archive; confirm normal cadence, reboot continuity and recovery after incomplete cycles without duplicate requests.
- **HA lifecycle:** all native platforms and historical services; preserve identities, user-disabled choices, recorder history, entry/device ownership, restart, reauth, upgrade, removal and V2/V3/V2 rollback.
- **Workbench:** reviewed definitions, sharing/import roundtrip, privacy, physical consent, route applicability and redacted evidence.
- **Operations:** validate native request accounting, actual rate-limit recovery, persisted cooldown, token expiry, multi-client behavior, optional Data Act connect/disconnect, stale delivery, restart/unload/cancellation and bounded traffic. No assumed OEM quota scope or refill rate.
- **Delivery:** exact-head Test/Validate, Workbench, pre-commit, HACS/hassfest, latest stable HA monthly release pinned to its latest stable patch, package integrity, immutable source pin and upstream review synchronization. Separate product-owner publication approval and maintainer stable acceptance.

## Open investigation and evidence

Use [#35 — vehicle identity](https://github.com/npinguin/audi_connect_ha/issues/35), [#36 — Data Act](https://github.com/npinguin/audi_connect_ha/issues/36), and [#44 — stable gate](https://github.com/npinguin/audi_connect_ha/issues/44) for the current disposition. Compare actual vehicle behavior before changing routes; the physical charging STOP root cause must not be inferred from HTTP acceptance or timer settings. The [upstream review discussion](https://github.com/audiconnect/audi_connect_ha/pull/918) contains the original Q5 charging reports, measurements, diagnostics and tester feedback.

For historical implementation decisions and prior CI/field evidence, see the [immutable previous closure record](https://github.com/npinguin/audi_connect_ha/blob/a6fbf6f3f835b77b69e414696d43686131aff652/docs/V3_FEATURE_CLOSURE.md) and [previous engineering review](https://github.com/npinguin/audi_connect_ha/blob/a6fbf6f3f835b77b69e414696d43686131aff652/docs/V3_REVIEW.md). These are archives, not active specifications.

During stabilisation, make evidence-backed corrections, security fixes and documentation improvements only. Do not expand feature scope or promote releases on CI alone.
