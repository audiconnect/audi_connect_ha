# Engineering release policy

This is a maintainer policy, not user documentation or a release-status report. Track decisions, current acceptance and exact evidence in [#44](https://github.com/npinguin/audi_connect_ha/issues/44), focused issues and pull requests. Keep historical evidence in Git and issue history. Do not duplicate a current status report in the repository.

## Release authority

Use one active development line (`dev`) and one upstream delivery line in the fork. Keep one active compatible implementation batch/PR at a time; integrate completed work promptly, then reuse the development line. Backlog and field-evidence holds belong in issues, not active development branches. Reuse the existing branches and review history; do not create a new long-lived branch or a new upstream PR for every beta.

| Branch                       | Responsibility                                                                                                    |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `dev`                        | Canonical V3 development and integration; focused fix PRs target this branch.                                     |
| `feature/v3-upstream-review` | Curated delivery to upstream `dev` through existing PR #918; only reviewed, validated, upstream-relevant changes. |
| `master`                     | Unmodified upstream master mirror.                                                                                |
| `main`                       | Historical fork baseline; no parallel V3 development.                                                             |
| `release/hacs`               | Sole HACS packaging line; published candidate tags and their contents are immutable.                              |

Keep the delivery branch an ancestor of development wherever practical. Sync reviewed upstream changes back into `dev` before additional development. Promote a coherent, validated delta from `dev` to the existing upstream review branch; exclude fork-only release packaging, experimental evidence, private diagnostics and unrelated research. Do not force-push the active upstream review branch or replace its PR. Use a short-lived fix branch only when review or CI needs it; retire it after integration when no release or review depends on it.

Squash-merge the active development PR promptly once review and exact-head source CI pass for an authorized TEST batch; stable/upstream promotion requires applicable live acceptance. Do not accumulate green fixes in parallel branches or wait for an unrelated beta. Review open PRs and branch drift at each release checkpoint; record the owner and concrete blocker for any deferred merge. Promote small coherent upstream-ready deltas regularly, without bypassing upstream maintainers or live acceptance gates. Sync the accepted delivery head back to development before the next promotion.

Keep the offered upstream product code, tests and documentation at most one published HACS beta behind. Before publishing a new beta, verify that the preceding published beta's pinned product source is already included in the upstream review branch. Count published releases, not skipped version numbers. If this gate fails, stop publication and review a coherent delta for promotion; never push to upstream automatically or interrupt an agreed review freeze. Fork-only packaging, release notes and version metadata stay outside the upstream contribution.

Derive HACS candidates from a pinned, validated `dev` runtime snapshot. Keep fork versioning and publication out of the upstream contribution. No stable release promotion, version reuse for changed published code, or upstream merge based only on static tests. Keep upstream release ownership intact. Separate implementation, automated evidence and live acceptance in all status reporting.

## TEST versus stable acceptance

A HACS experimental TEST prerelease is the input to live acceptance, not its result. After source review, exact-head automated checks and safety/privacy review, merge the authorized TEST batch into fork `dev`. Publish its pinned integrated source through the existing workflow only after integrated automated checks and package integrity pass. Pending physical vehicle, provider and HA lifecycle acceptance is documented as the test objective, not a precondition for TEST publication. Keep experimental controls explicit, opt-in and fail-closed; known unsafe behavior, failing checks or an explicitly excluded feature still blocks inclusion. Stable promotion and upstream maintainer acceptance require the applicable live evidence below; TEST publication does not assert either. Do not conflate the two gates in issues or PRs.

## Acceptance criteria

- **Charging:** independently measure physical START/STOP and charging power. An accepted request, optimistic switch or later matching observation is not execution proof. Verify manual/timer modes, target SOC, profiles, ETA expiry and fail-closed unavailable routes; no automatic replay of pending or uncertain actions or guessed modes. The narrowly scoped, default-off, explicitly opted-in direct CARIAD STOP recovery may be qualified only after an exact terminal timeout and fresh native still-charging evidence; maximum one linked second STOP, unchanged context/route, no restart replay. Require independent physical evidence before acceptance.
- **Climate and remote controls:** verify stored and parameterized start, independent settings, stop, window/auxiliary heating, access, flash, refresh/wake and engine actions only where eligible. Preserve explicit physical discovery and route-specific evidence.
- **Identity and coverage:** verify manufacturer model/year/image and powertrain provenance, representative ICE/PHEV/BEV, Auth0/legacy, markets, actual MBB reads and unavailable features. Missing metadata is not proof of unsupported vehicle.
- **Telemetry:** preserve capture times, last-known values, partial responses, zero versus missing and source semantics. Native and optional Data Act observations consolidate without making delayed data live or authorizing commands.
- **Trips:** preserve original entity semantics, current/reset/last distinctions and local archive; confirm normal cadence, reboot continuity and recovery after incomplete cycles without duplicate requests.
- **HA lifecycle:** all native platforms and historical services; preserve identities, user-disabled choices, recorder history, entry/device ownership, restart, reauth, upgrade, removal and V2/V3/V2 rollback.
- **Workbench:** reviewed definitions, sharing/import roundtrip, privacy, physical consent, route applicability and redacted evidence.
- **Operations:** validate native request accounting, actual rate-limit recovery, persisted cooldown, token expiry, multi-client behavior, optional Data Act connect/disconnect, stale delivery, restart/unload/cancellation and bounded traffic. No assumed OEM quota scope or refill rate.
- **Delivery:** exact-head Test/Validate, Workbench, pre-commit, HACS/hassfest, latest stable HA monthly release pinned to its latest stable patch, package integrity, immutable source pin and upstream review synchronization. Separate product-owner publication approval and maintainer stable acceptance.

## Documentation boundary

Public documentation describes installation, behavior, limitations, safe use, contribution and architecture or research knowledge. It does not contain internal build status, release decisions, branch handovers, acceptance progress, CI counts or active development plans. User-facing release notes describe what changed, compatibility, known limitations and upgrade instructions. Internal validation, source pins and approval evidence belong to the existing release machinery, CI and issue history. Published release tags and assets remain immutable.
