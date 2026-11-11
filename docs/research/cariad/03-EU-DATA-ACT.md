# 03 — VW Group EU Data Act: Consented, Read-Only, Delayed Vehicle Data

## Executive distinction

**EU Data Act portal ≠ CARIAD live BFF ≠ Audi remote-control API.**

The Volkswagen Group portal can expose **user-consented, read-only vehicle datasets** for eligible vehicles and markets (Audi, VW, Škoda, CUPRA, SEAT and others supported by the portal). It is a separate channel with its own enrolment, vehicle relationship and data request configuration. It does not provide Audi Connect lock, climate, charging start/stop or wake commands.

**Critical observed behavior:** on the user's Audi, data can stay **hours or even days old when the car is parked**. A recurring 15-minute delivery does not reset the observation timestamp or mean the car transmitted anything new.

## The data chain and the three clocks

```text
Vehicle measurements (often intermittent when parked)
    |
    |  variable vehicle -> OEM upload delay (can be hours/days)
    v
VW Group backend last-known observations
    |
    |  portal request processing / upstream provisioning / batching
    v
EU Data Act scheduled ZIP export (may be empty, e.g. *_no_content_found.zip)
    |
    |  downloader / extractor / field mapping
    v
Audi Connect source adapter -> HA entity + observed_at + delivered_at + fetched_at
```

Record at least:

1. **Vehicle observed_at / carCapturedTimestamp / source field timestamp**: when the car measured/reported the item, if supplied.
2. **Provider delivered_at / dataset timestamp**: when the portal generated the ZIP or report.
3. **Integration fetched_at**: when Home Assistant downloaded the file.
4. **Age of data** from observed_at, **not** from HA poll time.
5. **Uncertainty** when no vehicle timestamp is present. Never manufacture observed_at from ZIP generation.

## Portal workflow (documented in community implementations)

1. Sign in at [VW Group EU Data Act portal](https://eu-data-act.drivesomethinggreater.com/) with the brand identity; complete eligibility, vehicle relation and consent.
2. Under vehicle/data clusters, create an authorized **continuous/customized data request**, selecting appropriate clusters (usually All Data) and the available frequency, commonly 15 minutes.
3. Inspect whether the portal actually lists **non-empty datasets**. Empty `*_no_content_found.zip` is a first-class state, not a parsing exception.
4. Use the authorized list/download flow to retrieve only available datasets. Decode ZIP JSON preserving **source field names and timestamps**.
5. Avoid duplicating portal requests or generating unnecessary login attempts from Home Assistant; allow a user to manage consent in the official portal.

### Observed client route family (not a public API specification)

From [ioBroker `lib/euDataAct.js`](https://github.com/TA2k/ioBroker.vw-connect/blob/master/lib/euDataAct.js):

```text
BASE: https://eu-data-act.drivesomethinggreater.com
IDENTITY: https://identity.vwgroup.io/oidc/v1/authorize

/proxy_api/consent/me/vehicles
/proxy_api/vum/v2/users/me/relations/{VIN}
/proxy_api/euda-apim/datarequest/vehicles/{VIN}/metadata/partial
/proxy_api/euda-apim/datadelivery/vehicles/{VIN}/{identifier}/list
/proxy_api/euda-apim/datadelivery/vehicles/{VIN}/{identifier}/download
```

These are observed portal implementation routes. Session requirements may change. Do not treat them as stable externally supported OAuth APIs without vendor confirmation.

## What the Data Act can contribute

- **Fleet-normalized field discovery:** the [ioBroker EU Data Act dictionary](https://github.com/TA2k/ioBroker.vw-connect/blob/master/lib/euDataActDictionary.json) lists over a thousand possible fields, including short/long-term trip-statistic families.
- **Q8 PHEV candidate data:** `short_term_data_average_fuel_consumption`, `short_term_data_average_electr_engine_consumption`, `short_term_data_zero_emission_distance`, `short_term_data_average_recuperation`, corresponding long-term fields; when actually delivered and correctly unit-normalized.
- **Additional health/status:** 12V, battery temperatures, tyre pressure, maintenance and warning data in some vehicles.
- **Historical forensic evidence:** one-off exports may reveal what the Group backend holds, even if continuous exports fail.
- **Cross-checking:** compare Audi BFF values against Data Act measurements with **matching vehicle-observation timestamps**, not merely ZIP/fetch time.

The dictionary is a **possible field universe**, not evidence that the user's Audi Q8 emits every field. A PHEV fixture from another vehicle is not Q8 proof.

## Delayed and failed feeds: four distinct cases

| Scenario | Diagnosis | Integration behavior |
| --- | --- | --- |
| ZIP generated every 15 min, content shows old vehicle timestamps | **vehicle-observation staleness** | Retain last-known value; expose age; do not relabel as live |
| New `_no_content_found.zip` every 15 min | No data **in this delivery**; may be sleeping vehicle **or portal backend fault** | Track empty deliveries and last non-empty file separately; no zero fill |
| Auth/consent/vehicle relation rejected | Authorization or eligibility issue | Actionable diagnostic; no repetitive token storms |
| Non-empty ZIP contains only some selected fields | Vehicle/platform/cluster/data entitlement variation | Only create supported fields; mark gaps unknown, not zero |

**Do not assert that sleeping is the only explanation for empty ZIPs.** The Audi Q6 e-tron, S6, Q4 and A6 e-tron reports in [issue #1403](https://github.com/its-me-prash/vwgroup-connect-ha/issues/1403) describe prolonged entirely empty continuous feeds **even after driving or charging**, while the myAudi app shows fresh telemetry. An October 2026 community thread reports VW Group acknowledging a sporadic portal-side no-content fault. The data chain can fail **after** OEM ingestion.

## Read-only limitations and truth-in-data rules

- Delivery schedule **does not guarantee** fresh values.
- Data Act cannot issue vehicle-control commands.
- A Data Act aggregate is **not** an individual trip record; don't invent trip IDs, start/end times or routes.
- Do not infer charging power or active charging from an old ZIP.
- No historical `total_increasing` sensor should jump backwards after a partial import.
- Store source-specific timestamps and avoid converting absent values to 0.
- Do not retain unredacted ZIP archives with VIN, location, account or personally sensitive trip data in logs.
- Respect user consent and portal conditions; avoid background wake-ups to force a feed.

## Integration design

Introduce an optional **read-only** provider that maps known Data Act fields into a normalized observation model. It should never overwrite newer BFF observations for the same semantic field. The provider's scope is supplemental **historical/aggregate information**, fallback where explicitly valid, and debugging of missing coverage—not a replacement for myAudi command or live charging status.

Suggested source selection per measurement:

```text
1. Authorized current OEM/BFF measurement with valid car-observed timestamp
2. Authorized historical OEM trip endpoint (for *actual* trips)
3. Data Act field when present, with its own timestamp and labeled as delayed
4. Last-known cache (explicitly stale)
5. Unknown (no valid observation)
```

Avoid blindly preferring BFF if its measurement timestamp is older than the Data Act field; apply **field-by-field** provenance and semantic equivalence checks. See [04 — Freshness](04-FRESHNESS-AND-AVAILABILITY.md).

## Sources

- [VW Group EU Data Act portal](https://eu-data-act.drivesomethinggreater.com/)
- [VW Group Vehicle2MQTT](https://github.com/StephanHenke/vwgroup-vehicle2mqtt)
- [VW Group EU Data Act Home Assistant integration](https://github.com/TommiG1/HA_VAG-EU-Data-Act)
- [Audi continuous ZIP failure: issue #1403](https://github.com/its-me-prash/vwgroup-connect-ha/issues/1403)
- [Community October 2026 portal-status discussion](https://community.home-assistant.io/t/beta-vw-group-eu-data-act-vehicle-data-for-vw-audi-skoda-seat-cupra-bentley-official-portal/1013514?page=8)
- [ioBroker portal parser + dictionary](https://github.com/TA2k/ioBroker.vw-connect)
- [CarConnectivity VW EU Data Act](https://github.com/mikrohard/CarConnectivity-connector-vw-eu-data-act)
- [One-off versus continuous trip reconstruction](https://github.com/jmap42591/raval-trips)

Continue with [04 — Freshness and availability](04-FRESHNESS-AND-AVAILABILITY.md).