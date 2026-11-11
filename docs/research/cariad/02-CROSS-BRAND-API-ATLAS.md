# 02 — Cross-Brand API Atlas: Hosts, Endpoints, Patterns and Gaps

**Legend:** **CODE** = public implementation/fixture; **REPORT** = a known example request/response; **HYPOTHESIS** = pattern-based candidate only. No entry means proven Q8 PHEV access unless explicitly stated.

## 1. High-value endpoint matrix

| Domain | Brand + host family | Method + route | Evidence | Audi Connect relevance |
| --- | --- | --- | --- | --- |
| Status | Audi/VW EU CARIAD BFF | `GET /vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=charging,measurements,...` | CODE in Audi Connect | Existing core status; HTTP 207 is normal partial success |
| Position | Audi/VW EU BFF | `GET /vehicle/v1/vehicles/{VIN}/parkingposition` | CODE | Position may return 204 despite parked state |
| Individual/latest trips | VW EU BFF | `GET /vehicle/v1/trips/{VIN}/{shortterm\|longterm\|cyclic}/last` | CODE + VW HTTP 200 REPORT | **Top Audi Auth0 GET candidate, not verified** |
| Historical trip list | VW EU BFF | `GET /vehicle/v1/trips/{VIN}/{shortterm\|longterm\|cyclic}?from=...&to=...` | CODE in ioBroker | Check only after proof of authorization/last-trip |
| Alternative trip statistics | VW/Audi BFF | `GET /vehicle/v1/vehicles/{VIN}/tripstatistics?type=shortTerm` | CODE; multiple 404 REPORTS | Low priority; cooldown on 404 |
| Legacy trip statistics | Audi Connect MBB | `GET /api/bs/tripstatistics/v1/vehicles/{VIN}/tripdata/{shortTerm\|longTerm}` | CODE | Already implemented but disabled under Auth0 |
| Audi media | VW EU CARIAD | `GET /media/v2/vehicle-images/{VIN}?resolution=2x` | CODE in WeConnect-python (VW) | **Audi media HYPOTHESIS**; may avoid blocked GraphQL exchange |
| Audi GraphQL | Audi app API | `POST /vgql/v1/graphql` | CODE | Vehicle model/render fields restricted for Auth0 in one EU test |
| Audi AZS token exchange | CARIAD BFF | `POST /login/v1/audi/token` | CODE | May work for IDK; Auth0 exchange denied in reported test |
| Oil/TPMS | Audi/VW EU BFF | `GET /vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=oilLevel,tyrePressure` | CODE candidates / known jobs | Check supported fields and unit semantics |
| Škoda period trips | MyŠkoda `mysmob` | `GET /api/v1/trip-statistics/{VIN}?offsetType=week&offset=0&timezone=...` | CODE | Data-shape reference, **not Audi host substitution** |
| Škoda individual trips | MyŠkoda | `GET /api/v1/trip-statistics/{VIN}/single-trips?timezone=...` | CODE + community REPORT | Detailed start/end SoC, miles, duration, waypoints; privacy sensitive |
| CUPRA/SEAT driving data | OLA | `GET /v1/vehicles/{VIN}/driving-data/SHORT?from=...&to=...` | CODE corrected after failed /trips guesses | Shared domain model but **OLA token required** |
| CUPRA/SEAT refuel/charge | OLA | `GET /v1/vehicles/{VIN}/driving-data/CYCLIC?from=...&to=...` | CODE | Refuel cycle semantics |
| Škoda charging history | MyŠkoda | `GET /api/v1/charging/{VIN}/history` | CODE, backend regression reported | No longer sufficient as sole charging-history source |
| Shared charging statistics | central CARIAD charging host | `POST /charging_statistics` with VIN/date JSON filter (Škoda) | CODE + PR #586 | **Audi HYPOTHESIS**; verify method and token, no blind POST |
| Shared charging statistics | central CARIAD charging host | `GET /charging_statistics` (CUPRA) | CODE | Similar functionality but request contract differs |
| Charging power curve | central CARIAD charging host | `GET /charging_statistics/{VIN}/power-curve` (CUPRA) | CODE | Potential historical charging profile |
| CUPRA warning lamps | OLA | `GET /v3/vehicles/{VIN}/warninglights` | CODE | Normalize warning-state fields |
| Škoda warning lamps | MyŠkoda | `GET /api/v1/vehicle-health-report/warning-lights/{VIN}` | CODE | Brand-specific data-shape reference |
| CUPRA extra reads | OLA | `GET /v1/vehicles/{VIN}/{mileage\|ranges\|maintenance\|remote-availability}` | CODE | Useful service decomposition/legacy fallbacks |
| Škoda vehicle info | MyŠkoda | `GET /api/v1/vehicle-information/{VIN}/renders` | CODE | Images/composites; brand-specific |
| CUPRA vehicle renders | OLA | `GET /v2/vehicles/{VIN}/renders` | CODE | Image data model |
| Porsche trip family | Porsche `api.ppa` | `GET /app/connect/v1/vehicles/{VIN}?mf=TRIP_STATISTICS_SHORT_TERM&...` | CODE | Measurement-key approach is **not** CARIAD BFF routing |
| EU Data Act datasets | VW Group portal | `GET /proxy_api/euda-apim/datadelivery/vehicles/{VIN}/{identifier}/list` then `.../download` | CODE in ioBroker | Read-only, consent-based, **delayed**; no control |

**Host prefixes:** `https://emea.bff.cariad.digital`; `https://mysmob.api.connect.skoda-auto.cz`; `https://ola.prod.code.seat.cloud.vwgroup.com`; `https://prod.emea.mobile.charging.cariad.digital`; `https://api.ppa.porsche.com`; `https://eu-data-act.drivesomethinggreater.com`. Use only the corresponding approved authorization flow.

## 2. Three different trip response contracts (do not apply one parser to all)

### Legacy Audi MBB (CODE + historical fixtures)

```json
{
  "tripDataList": {"tripData": [{
    "tripID": 778996476,
    "averageElectricEngineConsumption": 284,
    "averageFuelConsumption": 0,
    "mileage": 12,
    "traveltime": 14,
    "timestamp": "2020-08-28T13:12:54Z",
    "overallMileage": 4534
  }]}
}
```

Legacy consumption integers are **tenths**: e.g., 284 -> **28.4 kWh/100 km**. Fixtures: [openHAB short-term JSON](https://github.com/tknaller/openhab-addons/blob/master/connectedcar/sampleData/CarNet/tripDataShortTerm.json).

### CARIAD BFF latest trip (VW REPORT, not Audi proof)

```json
{
  "data": {
    "tripType": "shortTerm",
    "mileage_km": 40,
    "startMileage_km": 65428,
    "overallMileage_km": 65469,
    "travelTime": 73,
    "averageFuelConsumption": 8.1,
    "averageSpeed_kmph": 33
  }
}
```

This is an excerpt from a VW Transporter HTTP 200 report in [issue #1060](https://github.com/robinostlund/homeassistant-volkswagencarnet/issues/1060), **not a Q8 sample**. Do **not** divide `8.1` by ten again. Preserve raw + normalization tests.

### EU Data Act and MyŠkoda

EU Data Act may contain fields such as `short_term_data_average_fuel_consumption`, `short_term_data_average_electr_engine_consumption`, `short_term_data_mileage`, `long_term_data_...` with **field-specific timestamps**. These are **aggregates/observations**—not automatically a list of genuine individual trips.

MyŠkoda `SingleTrips` has distinct per-trip fields including `startMileageInKm`, `endMileageInKm`, `startBatteryStateOfChargeInPercent`, `endBatteryStateOfChargeInPercent`, durations and waypoints. These are useful design clues but are not an Audi payload.

## 3. Cross-brand naming patterns worth exploiting

| Pattern | Examples | Research implication |
| --- | --- | --- |
| Domain-first BFF | `/vehicle/v1/`, `/media/v2/`, `/login/v1/` | Search for separate **service roots**, not only `/vehicle/v1/vehicles/{vin}/...` |
| Resource-first OLA | `/v1/vehicles/{vin}/charging/status`, `/driving-data/SHORT` | Do not project BFF `trips` path onto OLA |
| Brand gateway | `/api/v1/trip-statistics/{vin}/single-trips` | The same domain may be wrapped by a different gateway |
| Porsche field-key API | `?mf=TRIP_STATISTICS_...` | One generic measurement endpoint instead of many REST resources |
| Capability vocab | BFF `honkAndFlash`; OLA `honk-and-flash`; Škoda `HONK_AND_FLASH` | Normalize **capability IDs**, not just API values |
| Separate charging host | `charging_statistics` for Škoda/CUPRA | Investigate audience, scopes and headers by brand before a probe |
| Version changes are local | OLA `v1` status vs `v5` mycar; Škoda `v3` maintenance | Highest version is not necessarily the current route for all features |
| GET/POST can both read | Škoda `POST /charging_statistics` is a filter/query | Validate semantics from code; don't assume POST means command, but don't auto-probe it either |

## 4. Audi-specific gaps and new candidates

| Priority | Candidate | Classification | Required proof |
| --- | --- | --- | --- |
| P0 | CARIAD BFF `trips/{VIN}/shortterm/last`, longterm, cyclic | **Q8 UNVERIFIED** | Audi Auth0 HTTP status, authorized response fields, meaningful timestamps |
| P0 | PHEV electric + fuel consumption | CODE mapping / UNVERIFIED feed | Separate units, trip-cycle semantics and missing values |
| P1 | Central CARIAD charging statistics | **HYPOTHESIS for Audi** | Audi identity/token audience, requested body/headers, response/permission |
| P1 | CARIAD media image route | **HYPOTHESIS for Audi** | Authorized Audi HTTP 200; image URL licensing and metadata |
| P1 | Tyre pressure / 12V / health diagnostics | CODE job/capability universe; Q8 field delivery unverified | Redacted selectivestatus or Data Act fixture with capture timestamps |
| P2 | Engine start / auxiliary heaters / mobile digital keys | Model- and market-restricted | Explicit Audi capabilities + user authorization + safety and physical tests |

## 5. Source overlap map

- **Audi Connect** source code: [`audi_services.py`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/audi_services.py), [`audi_connect_account.py`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/audi_connect_account.py), [`audi_models.py`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/audi_models.py).
- **VW BFF trip and media routes:** [WeConnect-python](https://github.com/tillsteinbach/WeConnect-python/blob/master/weconnect/elements/vehicle.py) and [ioBroker VW Connect](https://github.com/TA2k/ioBroker.vw-connect).
- **Škoda endpoints and typed models:** [MyŠkoda API list](https://github.com/skodaconnect/myskoda/blob/main/docs/api_endpoints.md), [trip models](https://github.com/skodaconnect/myskoda/blob/main/myskoda/models/trip_statistics.py), [charging models](https://github.com/skodaconnect/myskoda/blob/main/myskoda/models/charging_history.py).
- **CUPRA route corrections and central charging host:** [seat_cupra.py](https://github.com/its-me-prash/vwgroup-connect-ha/blob/main/custom_components/vag_connect/cariad/api/seat_cupra.py) (**AGPL source; behavior reference only**).
- **Porsche measurement keys:** [Porsche API const](https://github.com/CJNE/pyporscheconnectapi/blob/main/pyporscheconnectapi/const.py).

Next: [EU Data Act](03-EU-DATA-ACT.md), then [freshness](04-FRESHNESS-AND-AVAILABILITY.md).