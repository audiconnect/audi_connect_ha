# 01 — Architecture, Vision and Evolution of VW Group Vehicle APIs

## 1. A service landscape, not one universal endpoint

Volkswagen Group brands reuse underlying **identity, connectivity, domain services and data models**, but front them through different gateways and applications. The core mistake is to equate a similar JSON field name with a shared token audience or to replace the host while keeping the URL unchanged.

\`\`\`text
                            Vehicle ECUs / telematics (TCU)
                                         |
                        OEM ingestion + asynchronous cloud updates
                                         |
                +------------------------+-----------------------+
                |                        |                       |
     CARIAD BFF / service APIs     Brand application APIs   EU Data Act delivery
      (Audi, VW EU in part)        (Škoda, SEAT/CUPRA,      (consent, scheduled ZIP,
         vehicle/v1/...                 Porsche)              read-only, delayed)
                |                        |                       |
       CARIAD IDK / Audi Auth0    brand OAuth / API keys   VW Group identity +
       tokens and service scopes   / brand-specific rules  portal-specific consent
                +------------------------+-----------------------+
                                         |
                       Source-specific Audi Connect adapters
                                         |
                     Normalized OEM data + provenance + timestamps
                                         |
                     Existing Home Assistant entities and services
\`\`\`

The diagram is conceptual, not a claim of one internal implementation across all brands.

## 2. Historical evolution

| Period | Technical phase | Evidence and implications |
| --- | --- | --- |
| ~2020–2023 | **MBB / CarNet / fs-car**: market-scoped hosts and endpoints, separate \`vwToken\`, app headers, \`X-Client-ID\`, legacy S-PIN procedures | Historic [openHAB ConnectedCar](https://github.com/tknaller/openhab-addons/tree/connectedcar_snapshot-3.4/bundles/org.openhab.binding.connectedcar) fixtures; base Audi Connect \`get_tripdata\` uses \`/api/bs/tripstatistics/v1/vehicles/{VIN}/tripdata/{kind}\`. |
| 2023–2025 | **CARIAD BFF** and selectively retrieved status/jobs: \`emea.bff.cariad.digital\`, \`selectivestatus\`, dedicated trip, media, parking and command services | [WeConnect-python](https://github.com/tillsteinbach/WeConnect-python) and [ioBroker.vw-connect](https://github.com/TA2k/ioBroker.vw-connect) implementations. |
| 2025–2026 | **Brand gateway divergence**: Škoda \`mysmob\`, SEAT/CUPRA \`OLA\`, Porsche \`api.ppa\`; similar functionality, different routes and capability IDs | [MyŠkoda](https://github.com/skodaconnect/myskoda), [CarConnectivity SEAT/CUPRA](https://github.com/tillsteinbach/CarConnectivity-connector-seatcupra), [Porsche API client](https://github.com/CJNE/pyporscheconnectapi). |
| 2026 | **Auth and device attestation enforcement** disrupts older Audi MBB paths; Audi Connect restores interactive Auth0/PKCE but some old trip and control paths remain incompatible | [Audi Connect issue #903](https://github.com/audiconnect/audi_connect_ha/issues/903), [PR #915](https://github.com/audiconnect/audi_connect_ha/pull/915), tagged base code. |
| 2026 | **VW Group EU Data Act portal and B2B vehicle data channels** provide distinct, authorized mechanisms for data access; these are not the myAudi remote-control API | [VW Group data portal](https://eu-data-act.drivesomethinggreater.com), [VW Group Info Services announcement](https://www.drivesomethinggreater.com/newsroom/short-news/2026-4-02-Transition), [High Mobility OEM guide](https://docs.high-mobility.com/oem-guides/volkswagen-group). |
| 2026–next | **Desired integration**: service-aware readers, explicit authentication routing, stable entities, provenance/freshness, verified capability tests and optional delayed data-channel enrichment | Engineering direction, **not** a promised vendor roadmap. |

The user-facing app can show recent values even when the EU Data Act continuous export is empty; conversely, a portal ZIP can arrive on schedule while the underlying vehicle observation is days old.

## 3. API gateway families and shared patterns

| Family | Host | API style | Primary brands / caveat |
| --- | --- | --- | --- |
| CARIAD EU BFF | \`emea.bff.cariad.digital\` | \`/{domain}/v{n}/{resource}/...\` | VW EU, Audi in observed code; token permissions vary |
| Legacy MBB | \`mal-3a.prd.eu.dp.vwg-connect.com\` and regional endpoints | \`/fs-car/bs/{service}/v1/...\`, \`/api/bs/...\` | Historic VW/Audi/other VAG; Auth0 often incompatible |
| Audi GraphQL | \`app-api.live-my.audi.com\` | \`/vgql/v1/graphql\` | Audi IDK→AZS exchange required for restricted fields; Auth0 often denied |
| MyŠkoda | \`mysmob.api.connect.skoda-auto.cz\` | \`/api/v1|v2|v3/{domain}/{vin}/...\` | Škoda app-specific auth, separate from Audi BFF |
| Škoda official | \`public.api.connect.skoda-auto.cz\` | \`/api/v1/vehicles/{vin}\` and commands | Official private-user API-key model; **not an Audi key** |
| CUPRA/SEAT OLA | \`ola.prod.code.seat.cloud.vwgroup.com\` | \`/v1|v2|v5/vehicles/{vin}/...\` | Own brand headers/device-attestation restrictions |
| CARIAD charging service | \`prod.emea.mobile.charging.cariad.digital\` | \`/charging_statistics\` and associated resources | Shared in Škoda and CUPRA code; Audi token access unknown |
| Porsche | \`api.ppa.porsche.com\` | \`/app/connect/v1/vehicles/{vin}?mf=...\` | Own authorization/audience and measurement/command-key models |
| VW Group EU Data Act | \`eu-data-act.drivesomethinggreater.com\` | portal consent + metadata/list/download ZIP | Audi, VW, Škoda, SEAT, CUPRA, Bentley; separate **read-only** flow |

### Architectural distinction

Shared domain: **charging history**. Shared host is seen across Škoda/CUPRA. That makes it an excellent candidate for an Audi token-compatibility investigation, but **does not imply the Audi token can authorize it**. Similarly, shared trip semantics do not imply a shared route.

## 4. What an Audi Connect implementation should look like

\`\`\`text
AudiConnectVehicle
 ├── AudiAuthProvider (Auth0/PKCE, refresh handling; no token leakage)
 ├── CariadStatusProvider (selectivestatus, parking, relevant reads)
 ├── AudiTripsProvider
 │    ├── CariadBffTripsAdapter       [subject to authenticated verification]
 │    ├── LegacyMbbTripAdapter        [only when compatible auth is available]
 │    └── DataActTripAggregateAdapter [optional, read-only, delayed; no fake trip IDs]
 ├── AudiChargingHistoryProvider      [candidate; no deployed endpoint assumed]
 ├── AudiMediaProvider                [GraphQL currently restricted; BFF media candidate]
 ├── AudiActionProvider               [separate, explicit user permission + readback]
 └── ObservationRegistry              [timestamps, provenance, capability, freshness]
             |
    Existing HA device/entities/unique IDs
\`\`\`

This is a **proposed responsibility split**, not a demand to introduce these exact class names.

## 5. Non-goals

- Do not reuse Škoda/CUPRA/Porsche tokens across brands or bypass app attestation.
- Do not assume the Data Act is a 15-minute live API.
- Do not invent trip history by summing sporadic odometer snapshots.
- Do not migrate remote controls to a read-only portal.
- Do not create a second generic vehicle-management framework beneath Audi Connect.
- Do not copy AGPL-3.0 implementation code into the MIT upstream project without a license review. Extract externally supported behavior and implement independently.

Continue with the [Cross-Brand Atlas](02-CROSS-BRAND-API-ATLAS.md).