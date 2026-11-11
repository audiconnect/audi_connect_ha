# Audi Connect / VW Group API Research

**Canonical research index** | Updated 2026-11-11 | Research only | Target: [Audi Connect for Home Assistant](https://github.com/audiconnect/audi_connect_ha)

## Mission

Restore and expand the **base Audi Connect integration**, not an RHI Mobility workaround, by understanding the entire Volkswagen Group connected-vehicle API landscape. The first practical target is genuine **Audi Q8 PHEV trip data**: trips, fuel and electric consumption, distance, time and relevant charging data. This research also identifies ways to recover vehicle metadata, images, diagnostics and reliable remote controls.

An API found in VW, Škoda, CUPRA, SEAT, Homey, openHAB, Porsche or another integration is a **clue**, not proof that the endpoint works with an Audi account, token or specific car.

## Vision and principles

- Keep one Audi Connect integration for Home Assistant; design small source-specific adapters rather than a competing framework.
- Plan for likely long-term VW Group platform and cost-driven convergence **without claiming that the manufacturer has announced full API unification**. Preserve old and new APIs, vehicles, authentication variants and models through evidence-driven discovery.
- Move toward automatic detection: supported authorization(s) → compatible API services → vehicle/platform → feature capabilities → stable entities. Multiple independent authorized providers may coexist for one car.
- Release isolated, safe experimental features earlier behind opt-in flags, backed by test fixtures, diagnostics and community validation; retain stronger safeguards for remote commands.
- Separate **vehicle telemetry**, **trip history**, **charging history**, **remote control** and **user-consented EU Data Act exports**.
- Build on the existing entity registry and config entries: never delete/recreate the four historical trip entities to introduce a new backend.
- Make **data provenance and freshness** first-class. For a parked Audi, a cloud observation can be **hours or days old**; polling or 15-minute EU Data Act ZIP delivery does not make it live.
- Use OEM-reported capabilities as evidence, not as conclusive authorization or proof an endpoint works; favor conservative tri-state capability detection.
- Distinguish request accepted, command executed and vehicle state confirmed.
- Treat privacy, account safety, rate limits, vehicle sleep, licensing and vendor-side changes as engineering constraints.
- Prioritize reproducible redacted fixtures and tests. Avoid invasive reverse engineering, unauthorized scope use and speculative production probes.

## Reading order

| Order | Document | Questions it answers |
| --- | --- | --- |
| 1 | [Architecture, vision and API evolution](01-ARCHITECTURE-EVOLUTION.md) | How do VW Group APIs fit together and how did the platform change? |
| 2 | [Cross-brand endpoint and data-contract atlas](02-CROSS-BRAND-API-ATLAS.md) | Which API families actually overlap, and where are the gaps for Audi? |
| 3 | [EU Data Act: read-only, delayed data](03-EU-DATA-ACT.md) | What do the portal and ZIP exports provide—and what do they not? |
| 4 | [Parked-car latency and freshness](04-FRESHNESS-AND-AVAILABILITY.md) | How should hours/days of stale readings be represented without lying? |
| 5 | [Authentication, capabilities, resilience](05-AUTH-CAPABILITIES-RELIABILITY.md) | Which token works where? Why is a capability not an authorization? |
| 6 | [Engineering work packages and release gates](06-ENGINEERING-PLAYBOOK.md) | Exactly where should the engineer work, test and stop? |
| 7 | [Sources and evidence ledger](07-SOURCES-AND-EVIDENCE.md) | Which findings have code, official docs, reports, or only a hypothesis behind them? |
| 8 | [Adaptive target architecture and experimental delivery](08-TARGET-ARCHITECTURE-AND-EXPERIMENTAL-DELIVERY.md) | How do multiple auth/API generations, vehicle/capability discovery, NFRs and early community releases fit together? |

## Evidence labels

- **OFFICIAL:** official documentation proves the stated service semantics; does not establish third-party token access.
- **CODE:** public client implementation, fixtures or tests show a route/schema; not necessarily a current successful Audi request.
- **REPORT:** observed field/error on a specific vehicle, market, token, date or firmware.
- **HYPOTHESIS:** derived from cross-brand API patterns; explicitly not a working Audi endpoint.
- **Q8 UNVERIFIED:** no authenticated successful Audi Q8 PHEV observation in this research.

## Repository and upstream relationship

- Upstream [README](https://github.com/audiconnect/audi_connect_ha/blob/dev/readme.md) documents setup and user controls; [CONTRIBUTING](https://github.com/audiconnect/audi_connect_ha/blob/dev/CONTRIBUTING.md) documents contributions. As of this review, upstream has **no equivalent API architecture knowledge base**.
- [PR #915](https://github.com/audiconnect/audi_connect_ha/pull/915) already addresses Auth0 controls, cloud resilience and diagnostics. Review overlap before implementation.
- This **research-only** branch is based on the fork's `master`. It changes no runtime code and should not be used as a release branch.
- Earlier source notes were imported in prior commits; Dutch drafts have been **consolidated into this English research set** and removed from the branch tip. They remain available in Git history rather than as competing entry points.

## One-page current status

| Subject | Outcome |
| --- | --- |
| Core Audi trip data on Auth0 | **Broken by design gate:** `support_trip_data = not uses_auth0` in v2.5.2, while the reader still calls legacy MBB |
| Modern VW EU trip service | CARIAD BFF `/vehicle/v1/trips/{vin}/{type}/last` documented by multiple clients and a VW HTTP 200 report; **Audi Auth0 unverified** |
| Separate `tripstatistics` API | Exists in code; widely reported HTTP 404 after provider changes; do not hammer |
| CUPRA trip family | OLA `/driving-data/SHORT` + `/driving-data/CYCLIC`, not the earlier incorrect OLA `/trips` guess |
| Škoda trip family | `/api/v1/trip-statistics/{vin}` and `/single-trips`; own gateway/authorization |
| Charging history | Shared `prod.emea.mobile.charging.cariad.digital` among Škoda and CUPRA; Audi access unknown |
| VW/Audi media | Separate VW CARIAD `/media/v2/vehicle-images/{vin}` is a candidate for Audi images; **unverified** |
| Data Act | Consented, read-only and delayed; continuous 15-minute delivery can contain zero new measurements for **hours/days**, or remain empty due to upstream faults |
| Vehicle parked | An Audi's last OEM observation may be **hours or days old**, independently of how often HA polls |

**Start coding only after reading [08 — Target Architecture](08-TARGET-ARCHITECTURE-AND-EXPERIMENTAL-DELIVERY.md) and [06 — Engineering Playbook](06-ENGINEERING-PLAYBOOK.md).**