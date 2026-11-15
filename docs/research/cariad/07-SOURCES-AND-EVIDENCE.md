# 07 — Evidence Ledger, Primary Sources and Outstanding Questions

**Snapshot date:** 2026-11-11. Public repositories, issues and vendor claims change. Re-check source date, commit/version, market and license before implementing.

## 1. Primary repositories — inspected implementations

| Source                                                                                                                                        | Role                                                     | Useful code or data                                                                                      | Reliability / license                                                  |
| --------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| [audiconnect/audi_connect_ha](https://github.com/audiconnect/audi_connect_ha)                                                                 | Target upstream                                          | `audi_services.py`, `audi_connect_account.py`, `audi_models.py`, `sensor.py`; v2.5.2                     | Code; MIT                                                              |
| [Audi upstream PR #915](https://github.com/audiconnect/audi_connect_ha/pull/915)                                                              | Overlapping Auth0 controls/resilience/diagnostics        | `capability_jobs.py`, probes, command routes                                                             | Open PR on review date; not all claims live-tested                     |
| [TA2k/ioBroker.vw-connect](https://github.com/TA2k/ioBroker.vw-connect)                                                                       | Multi-brand API and Data Act                             | `main.js` CARIAD trips, `lib/euDataAct.js` portal auth/list/download, `lib/euDataActDictionary.json`     | Source code; MIT; not proof Audi Auth0 is accepted                     |
| [tillsteinbach/WeConnect-python](https://github.com/tillsteinbach/WeConnect-python)                                                           | Independent VW EU CARIAD BFF                             | `weconnect/elements/vehicle.py`: `/vehicle/v1/trips/{vin}/{type}/last`, `/media/v2/vehicle-images/{vin}` | Historical/active independent client; MIT                              |
| [trocotronic/weconnect](https://github.com/trocotronic/weconnect)                                                                             | Independent BFF app proxy                                | `NativeAPI.py`: trips, parking, wake, warning lights                                                     | Historical implementation; check current availability                  |
| [skodaconnect/myskoda](https://github.com/skodaconnect/myskoda)                                                                               | Škoda brand gateway                                      | `docs/api_endpoints.md`, `rest_api.py`, `trip_statistics.py`, `charging_history.py`                      | Active; endpoint shape CODE; license check before copying              |
| [mobility-lab-vsb/skoda-public-api](https://github.com/mobility-lab-vsb/skoda-public-api)                                                     | Official Škoda public API client                         | `api_layer/rest_api.py`, vehicle/charging models                                                         | Distinct API-key protocol; MIT                                         |
| [tillsteinbach/CarConnectivity-connector-seatcupra](https://github.com/tillsteinbach/CarConnectivity-connector-seatcupra)                     | CUPRA/SEAT OLA                                           | Separate OLA v1/v2/v5 status/charging, capabilities, actions                                             | Active/legacy variants; MIT                                            |
| [its-me-prash/vwgroup-connect-ha](https://github.com/its-me-prash/vwgroup-connect-ha)                                                         | Cross-brand feature matrix and hypothesis inventory      | `cariad/api/{vw_eu,audi,skoda,seat_cupra,porsche}.py`, `api/_v3_probes.py`, `_capabilities.py`           | Rich CODE/REPORT evidence; **AGPL-3.0**, clean implementation required |
| [CJNE/pyporscheconnectapi](https://github.com/CJNE/pyporscheconnectapi)                                                                       | Porsche comparison                                       | `const.py` `TRIP_STATISTICS_*`, `vehicle.py` `mf=` query, `remote_services.py`                           | MIT; Porsche OAuth isn't Audi OAuth                                    |
| [tknaller/openhab-addons](https://github.com/tknaller/openhab-addons/tree/connectedcar_snapshot-3.4/bundles/org.openhab.binding.connectedcar) | Historic openHAB ConnectedCar                            | `CarNetApi.java`, `CarNetServiceTripData.java`, `CarNetServiceGeoFenceAlerts.java`                       | Historical legacy MBB reference, not current Auth0                     |
| [openHAB historic test JSON](https://github.com/tknaller/openhab-addons/tree/master/connectedcar/sampleData/CarNet)                           | Historical schema fixtures                               | short/long trip JSON, alerts, destinations, charger                                                      | CODE fixtures; redact if reused                                        |
| [martijnpoppen/com.vag.core](https://github.com/martijnpoppen/com.vag.core)                                                                   | Historic Homey VAG core                                  | Historical VW Group device/auth mappings                                                                 | Not current Auth0 proof                                                |
| [Homey myAudi](https://homey.app/en-nl/app/com.audi.etron/)                                                                                   | User-level functionality comparison                      | Command serialization, climate, warning lamps, battery, 12V/SoC reports                                  | App/release notes; current source reportedly unavailable               |
| [StephanHenke/vwgroup-vehicle2mqtt](https://github.com/StephanHenke/vwgroup-vehicle2mqtt)                                                     | Data Act ZIP→MQTT, field timestamps                      | Anonymized Audi fixture and portal dataset handling                                                      | CODE, not guaranteed any field for Q8                                  |
| [TommiG1/HA_VAG-EU-Data-Act](https://github.com/TommiG1/HA_VAG-EU-Data-Act)                                                                   | Dedicated official-portal HA data reader                 | Read-only ZIP, cadence, no-content handling                                                              | Community implementation                                               |
| [mikrohard/CarConnectivity-connector-vw-eu-data-act](https://github.com/mikrohard/CarConnectivity-connector-vw-eu-data-act)                   | Data Act schema / PHEV fixtures                          | `tests/phev_sample_dataset.json`, notes on unused trip fields                                            | PHEV fixture not Q8                                                    |
| [jmap42591/raval-trips](https://github.com/jmap42591/raval-trips)                                                                             | Reconstructed trips from snapshots                       | Odometer/time inference                                                                                  | Approximation, not OEM trip records                                    |
| [evcc-io/evcc](https://github.com/evcc-io/evcc)                                                                                               | Energy charging integrations and alternate Data Act auth | Vehicle adapters, portal access; rate-aware design                                                       | Source code; MIT                                                       |

## 2. High-signal issue / PR evidence

- [Audi Connect #903](https://github.com/audiconnect/audi_connect_ha/issues/903): Audi authentication migration to Auth0/PKCE.
- [Audi Connect #914](https://github.com/audiconnect/audi_connect_ha/issues/914): Auth0 climate controls using BFF on an older Audi.
- [Audi Connect PR #915](https://github.com/audiconnect/audi_connect_ha/pull/915): earlier upstream work for commands, recovery and diagnostics; historical source evidence.
- [VW CarNet #1060](https://github.com/robinostlund/homeassistant-volkswagencarnet/issues/1060): HTTP 200 `/vehicle/v1/trips/.../shortterm/last` payload; trip entities can still be broken by mapping.
- [VAG Connect #392](https://github.com/its-me-prash/vwgroup-connect-ha/issues/392): CUPRA Formentor PHEV missing trip data; corrected OLA `driving-data` route in client.
- [VAG Connect #1310](https://github.com/its-me-prash/vwgroup-connect-ha/issues/1310): Škoda individual trip telemetry available in MyŠkoda, not CARIAD BFF.
- [MyŠkoda PR #586](https://github.com/skodaconnect/myskoda/pull/586): charging statistics moved to central CARIAD charging endpoint with VIN/date filter; reports HTTP 200 after fix.
- [VAG Connect #1403](https://github.com/its-me-prash/vwgroup-connect-ha/issues/1403): Audi continuous 15-minute Data Act deliveries empty for days, including **after driving**, sometimes while myAudi has live data. Critical against the assumption that empty = sleeping.
- [HA Community VW Group EU Data Act](https://community.home-assistant.io/t/beta-vw-group-eu-data-act-vehicle-data-for-vw-audi-skoda-seat-cupra-bentley-official-portal/1013514?page=8): October 2026 VW Group portal no-content incident and login-flow change.

## 3. Vendor / official references

- [VW Group EU Data Act portal](https://eu-data-act.drivesomethinggreater.com) — consent/authorized read-only vehicle dataset delivery.
- [VW Group Info Services, April 2026 transition](https://www.drivesomethinggreater.com/newsroom/short-news/2026-4-02-Transition) — separate official B2B vehicle-data access.
- [High Mobility VW Group OEM guide](https://docs.high-mobility.com/oem-guides/volkswagen-group) — brand/OEM Trip, Consumption, Charging, Vehicle Health data contracts.
- [MyŠkoda Public API](https://public.api.connect.skoda-auto.cz/docs) — public brand API reference (not an Audi API).
- [Audi Connect privacy disclosure](https://www.audi.de/de/rechtliches/datenschutz/audi-connect-datenschutz/) — Remote Trip Statistic as an Audi connected service, not a third-party permission grant.

## 4. Research questions requiring explicit proof

- Which additional trip cycles, reset semantics and retention are supported across Audi generations?
- Which Audi authorizations legitimately expose charging history and media?
- Which fields in the status and Data Act sources provide valid tyre pressure, 12 V, HV temperature, warnings or charge power?
- What is the measured native quota scope and recovery behavior across sessions, and what causes delayed or empty Data Act deliveries?
- What is required for authorized official public/business API access?

## 5. Traceability / review checklist

For every new claim record: source permalink, source revision/date, endpoint type, HTTP method, brand, market, platform, auth audience, sanitized status/payload keys, units, car capture time, confidence, and compatibility with Audi/MIT licensing.

Avoid "all Volkswagen Group endpoints should work on Audi" narratives. The real shared asset is **domain knowledge**, while access is gated by **brand, identity, platform, consent, market and service contract**.

## 6. Strategic architecture evidence versus inference

**Implementation evidence:** consult the [current product architecture](../../V3_ARCHITECTURE_CLOSURE.md), [user guide](../../V3_REVIEW.md) The research source ledger records historical comparisons; it does not define today's implementation.

**Strategic hypothesis, NOT vendor commitment:** VW Group may increasingly standardize API models, shared identity infrastructure, services and costs across brands. Shared CARIAD BFF conventions and a Škoda/CUPRA charging-statistics host are supporting clues; parallel proprietary OLA/MyŠkoda/Porsche/Audi identity and API systems are counterevidence to any claim of complete uniformity. No date, sequence or guarantee of unification is asserted.

**Target design proposals:** see [08 — Target Architecture and Experimental Delivery](08-TARGET-ARCHITECTURE-AND-EXPERIMENTAL-DELIVERY.md). The current architecture and capability catalog take precedence over proposed contracts or feature flags.

**Validation still needed:** see the research questions above and the current acceptance gate. Cross-brand source evidence is not universal Audi support.
