# Audi Connect / VW Group API Research

**Canonical research index** | Updated 2026-11-11 | Research only | Target: [Audi Connect for Home Assistant](https://github.com/audiconnect/audi_connect_ha)

## Mission

Restore and expand the **Audi Connect integration** by understanding the entire Volkswagen Group connected-vehicle API landscape. The first practical target is genuine **Audi Q8 PHEV trip data**: trips, fuel and electric consumption, distance, time and relevant charging data. This research also identifies ways to recover vehicle metadata, images, diagnostics and reliable remote controls.

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

| Order | Document                                                                                                      | Questions it answers                                                                                                |
| ----- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| 1     | [Architecture, vision and API evolution](01-ARCHITECTURE-EVOLUTION.md)                                        | How do VW Group APIs fit together and how did the platform change?                                                  |
| 2     | [Cross-brand endpoint and data-contract atlas](02-CROSS-BRAND-API-ATLAS.md)                                   | Which API families actually overlap, and where are the gaps for Audi?                                               |
| 3     | [EU Data Act: read-only, delayed data](03-EU-DATA-ACT.md)                                                     | What do the portal and ZIP exports provide—and what do they not?                                                    |
| 4     | [Parked-car latency and freshness](04-FRESHNESS-AND-AVAILABILITY.md)                                          | How should hours/days of stale readings be represented without lying?                                               |
| 5     | [Authentication, capabilities, resilience](05-AUTH-CAPABILITIES-RELIABILITY.md)                               | Which token works where? Why is a capability not an authorization?                                                  |
| 6     | [Engineering validation methods](06-ENGINEERING-PLAYBOOK.md)                                     | How can API hypotheses be validated safely?                                                              |
| 7     | [Sources and evidence ledger](07-SOURCES-AND-EVIDENCE.md)                                                     | Which findings have code, official docs, reports, or only a hypothesis behind them?                                 |
| 8     | [Adaptive target architecture and experimental delivery](08-TARGET-ARCHITECTURE-AND-EXPERIMENTAL-DELIVERY.md) | How do multiple auth/API generations, vehicle/capability discovery, NFRs and early community releases fit together? |

## Evidence labels

- **OFFICIAL:** official documentation proves the stated service semantics; does not establish third-party token access.
- **CODE:** public client implementation, fixtures or tests show a route/schema; not necessarily a current successful Audi request.
- **REPORT:** observed field/error on a specific vehicle, market, token, date or firmware.
- **HYPOTHESIS:** derived from cross-brand API patterns; explicitly not a working Audi endpoint.
- **Q8 UNVERIFIED:** no authenticated successful Audi Q8 PHEV observation in this research.

## Repository and upstream relationship

The [architecture guide](../../V3_ARCHITECTURE_CLOSURE.md) documents product design. Research chapters provide source comparisons and hypotheses, not competing active specifications.

## Research directions

- Modern CARIAD current/last trips have been observed on Audi; reset/cyclic semantics, retention and broader vehicle coverage require separate evidence.
- CUPRA OLA, MyŠkoda and shared charging-statistics hosts supply comparison patterns, not Audi permissions.
- Investigate authorized media, charging history, tyre pressure, 12 V and health observations through reviewed read-only discovery.
- Data Act is consented, delayed and read-only. Delivery and vehicle capture are separate clocks; see the [V3 guide](../../V3_REVIEW.md#optional-eu-data-act) for usage.
- Official public/business API access is a separate research path; do not confuse business registration or approval with the consumer Data Act portal.

**For technical background, read [08 — Target Architecture](08-TARGET-ARCHITECTURE-AND-EXPERIMENTAL-DELIVERY.md) and [06 — Engineering Playbook](06-ENGINEERING-PLAYBOOK.md).**
