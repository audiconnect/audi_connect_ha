# Audi Connect — CARIAD API research & engineer handover

**Peildatum:** 10 november 2026 (Europa/Brussel)  
**Doelrepo:** `audiconnect/audi_connect_ha` — basisintegratie verbeteren, **geen RHI Mobility-workaround**  
**Basis:** upstream stable **v2.5.2**, uitgebracht 10 november 2026  
**Topprioriteit:** terugkeer van tripgegevens op Audi EU/PHEV onder Auth0; daarna voertuigidentiteit, bereikbaarheid, diagnostiek en nieuwe datavelden.

## 0. Kernboodschap voor de engineer

1. **Niet opnieuw beginnen.** Upstream PR **#915** (`npinguin/audi_connect_ha`, `contrib/upstream-audi-connect-fixes`, head `1650d18a...`) staat open sinds 10 november. Deze omvangrijke patch werkt reeds aan Auth0-commando's, partial-poll recovery, freshness, diagnostics, capabilities en modelgegevens. **Review/rebase/integreer met dit werk, niet dupliceren.** PR: https://github.com/audiconnect/audi_connect_ha/pull/915 .
2. **Trip is momenteel bewust uitgeschakeld onder Auth0:** `AudiConnectVehicle.__init__` in `audi_connect_account.py` v2.5.2 zet `support_trip_data = not uses_auth0` (regels 807–812). De tripreader gebruikt een **legacy MBB**-endpoint en heeft onder Auth0 geen geschikt legacy-token. Een simpele boolean-wijziging is geen fix.
3. **De meest veelbelovende directe leesroute** voor individuele/laatste ritten is de modernere CARIAD-familie `/vehicle/v1/trips/{VIN}/{shortterm|longterm|cyclic}[/last]`. Deze routes bestaan in onafhankelijke open-source implementaties en gaven bij een **VW Transporter** op 18-08-2026 een echte HTTP 200 met tripdata; **Audi + huidig Auth0-token zijn nog niet live bevestigd**.
4. De alternatieve `/vehicle/v1/vehicles/{VIN}/tripstatistics?type=shortTerm` is **op sommige Audi's 404 ondanks actieve `tripStatistics` capability** (#1805). `selectivestatus?jobs=tripStatistics` staat alleen als **experimentele probe** in PR #915; niet verwarren met een bewezen geldige `selectivestatus`-job.
5. **EU Data Act is aanvullend, niet gegarandeerd.** Een onafhankelijke PHEV-fixture bevat `short_term_data_*` en `long_term_data_*`, maar Audi RS e-tron GT #1805 ontving géén Trip Statistics-cluster ondanks actieve RTT/RTS in myAudi. Data Act heeft eigen auth, batch-cadans en timestamps.
6. **De bestaande vier HA-trip-entities behouden** (unique IDs, namen, attributen). Nieuwe history-data als nieuwe surface toevoegen, niet bestaande sensorsemantiek geruisloos herdefiniëren. Onderscheid individuele rit, aggregaat sinds reset, en uit meetpunten gereconstrueerde rit.

## 1. Actuele upstream-context en overlap

| Item | Stand per 10-11-2026 | Relevantie |
|---|---|---|
| Stable v2.5.2 | Auth0/PKCE EU/CA en climate-temperature-fix | Basisbranch voor tests |
| PR #915 | Open; grote integratiepatch met veel tests | Eerst inhoudelijk beoordelen; voorkomt dubbel werk |
| Issue #914 | Auth0 werkt voor BFF-climate op legacy PHEV, terwijl oude `fs-car` 401 oplevert | Route en token zijn beslissend, niet alleen voertuigcapability |
| Issue #907 | Vier tripsensors unavailable; model `Unknown ()` op Q5 PHEV onder Auth0 | Reproduceerbaar probleem |
| Issue #888 | 1x 404 kan GPS-support permanent uitzetten tot reload | Geen permanent disable op tijdelijke backendfout |
| Issue #865 | Commandolog kan succes claimen voor fysieke bevestiging | Correcte readback / command status |
| Issue #1805 (VAG Connect) | Audi RS e-tron GT: `/tripstatistics` 404 ondanks actieve capability; Data Act geen tripcluster | Grootste bewijs dat capability ≠ beschikbaar endpoint |

PR #915 voegt **`api_probe.py`** toe met 8 basis-GET-probes + 5 extended-GET-probes, max 13, inclusief abort bij 401/429 en laag rate-budget. Extended bevat een `selectivestatus?jobs=tripStatistics`-kandidaat, **maar niet** de in ioBroker/Symcon gedocumenteerde `/vehicle/v1/trips/...`-familie. Overweeg een **aparte expliciete read-only tripdiagnose** die deze routes gericht test met een strikt requestbudget; voeg niet standaard 8–13 probes bovenop de normale polling toe. PR #915 bewaart enkel responseclassificaties, **niet de veldnamen of ruwe bytes**: voor een gevalideerde parser-fixture is een aparte bewust geactiveerde, privacy-veilige export/test nodig.

PR #915 stelt fysieke validatie op één Auth0-PHEV voor lock/unlock, flash en climate ON/OFF. **Niet extrapoleren naar elke Audi of specifiek de Q8 PHEV.** In upstream bestaat `tests/fixture_q8_etron.py`, maar die is van een **Q8 Sportback e-tron BEV**, niet Q8 TFSI e PHEV. Een echte/synthetische Q8-PHEV-fixture is nog nodig.

### Concreet te lezen bestanden in upstream v2.5.2

- [`audi_connect_account.py#L790-L815`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/audi_connect_account.py#L790-L815) — Auth0 capability-disables.
- [`audi_connect_account.py#L1328-L1413`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/audi_connect_account.py#L1328-L1413) — `update_vehicle_tripdata`, 404-uitschakeling, legacy mapping.
- [`audi_services.py#L491-L540`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/audi_services.py#L491-L540) — legacy GET, sortering, mutatie van tripdicts.
- [`audi_models.py#L730-L769`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/audi_models.py#L730-L769) — legacy `TripDataResponse`, schaalconversies.
- [`sensor.py#L50-L145`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/sensor.py#L50-L145) — vier trip timestamp-sensoren met attribuutvelden.
- [`audi_services.py#L1606-L1614`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/custom_components/audiconnect/audi_services.py#L1606-L1614) — Auth0-token wordt naar `_bearer_token_json`, `audiToken` en `vwToken` gealiasd; het bestaan van `vwToken` bewijst **niet** dat legacy MBB authorisatie bestaat.
- [`tests/fixture_q8_etron.py`](https://github.com/audiconnect/audi_connect_ha/blob/v2.5.2/tests/fixture_q8_etron.py) — BEV-sample, geen PHEV.

## 2. API-routecatalogus (alleen eigenaar-geautoriseerde read-only GETs)

**CARIAD EU basis:** `https://emea.bff.cariad.digital`. Gebruik de **bestaande** Audi Auth0-sessie (`_bearer_token_json`) en HTTP-client van de integratie; geen login-script of tweede credentialsstore. Andere markten vragen eigen base/authorization; geen hardcoded EU-route voor alle landen. De reeds geïntegreerde login gebruikt `https://group.identity.vwgroup.io/authorize`, `https://group.identity.vwgroup.io/oauth/token` met `audience=https://api.cariad.com` en `scope=openid profile offline_access` (zie `audi_services.py` v2.5.2). Reuse tokens only within their documented audience. No attempt to work around app attestation.

| ID | Kandidaat GET-pad | Payload volgens andere code | Bewijsklasse | Actie |
|---|---|---|---|---|
| T0 | Legacy MBB: `/api/bs/tripstatistics/v1/vehicles/{VIN}/tripdata/{shortTerm|longTerm}` op `home_region_setter` | `tripDataList.tripData[]`, o.a. `tripID`, `overallMileage`, `averageElectricEngineConsumption` | In Audi Connect geïmplementeerd; **niet Auth0-bruikbaar** | Alleen behouden voor werkelijk legacy-geautoriseerde sessies |
| T1 | `/vehicle/v1/trips/{VIN}/shortterm/last` | `data: {id, tripEndTimestamp, mileage_km, startMileage_km, overallMileage_km, travelTime, averageFuelConsumption, averageSpeed_kmph, ...}` | HTTP 200 met VW Transporter; niet bewezen voor Audi | **Eerste Audi Auth0-probe** |
| T2 | `/vehicle/v1/trips/{VIN}/longterm/last` | `data: {...}` | In VW-client en ioBroker, vergelijkbare data op VW gemeld | Tweede probe |
| T3 | `/vehicle/v1/trips/{VIN}/cyclic/last` | `data: {...}` | In code en VW-test, mogelijk sinds-refuel | Derde probe na budgetcheck |
| T4 | `/vehicle/v1/trips/{VIN}/shortterm?from={ISO}&to={ISO}` | `data: [ {id, tripEndTimestamp, mileage_km, ...}, ... ]` | ioBroker + PHP Symcon implementaties (historisch) | Alleen als T1 relevant en voldoende budget |
| T5 | `/vehicle/v1/trips/{VIN}/longterm?from={ISO}&to={ISO}` | `data: [...]` | ioBroker implementatie | Alleen indien gewenst en budget |
| T6 | `/vehicle/v1/vehicles/{VIN}/tripstatistics?type=shortTerm` (`longTerm`, `cyclic`) | `tripDataList.tripData[]` | VW Group Connect; Audi #1805 herhaalde 404 | Optionele kandidaat; **niet in loop bij 404** |
| T7 | `/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=tripStatistics` | onbekend | Alleen extended probe in PR #915 | Niet beschouwen als bewezen trip-API |

Voor T4/T5: `from`/`to` **URL-encoden**; begrens de historiek (bv. 24–72h als eerste test), geen onbeperkte scan vanaf 1970. Alle probes expliciet door engineer/gebruiker gestart; geen automatische trial-and-error op iedere pollingronde.

**Verwijzingen / onafhankelijke implementaties**:
- ioBroker: https://github.com/TA2k/ioBroker.vw-connect/blob/master/main.js (sectie `getIdStatus`, moderne tripfamilie). Let op: **Audi classic login is in ioBroker op 23-09-2026 uitgeschakeld**. Code ≠ bewezen actuele Audi-toegang.
- PHP IP-Symcon: https://community.symcon.de/t/myaudi-klasse-fuer-fahrzeugdaten/134904 (functie `getTripdata`: `/shortterm` en `/longterm/last`; onafhankelijke PHP-implementatie; live werking november 2026 niet aangetoond).
- Werkelijke 2026 VW HTTP 200 + veldnamen: https://github.com/robinostlund/homeassistant-volkswagencarnet/issues/1060 .
- Audi 404 + ontbrekende Data Act-tripvelden: https://github.com/its-me-prash/vwgroup-connect-ha/issues/1805 .
- Nieuwste upstream PR met beperkte probes: https://github.com/audiconnect/audi_connect_ha/pull/915 .

## 3. Drie JSON-contracten NIET door elkaar mengen

### A. Legacy MBB (`T0`)

```json
{
  "tripDataList": {"tripData": [{
    "tripID": "SYNTHETIC_ID", "timestamp": "2026-11-10T12:00:00Z",
    "mileage": 40, "startMileage": 65428, "overallMileage": 65468,
    "averageFuelConsumption": 81, "averageElectricEngineConsumption": 155,
    "traveltime": 73
  }]}
}
```

*Dit is een **synthetisch testschema** dat het huidige codecontract illustreert, geen ruwe live respons.* In legacy `TripDataResponse` worden fuel- en electric-consumption momenteel door 10 gedeeld. Alleen toepassen op **dit bewezen bronschema**; niet op nieuwe data.

### B. Moderne BFF `/trips/.../last` (`T1`)

```json
{
  "data": {
    "id": "REDACTED", "tripType": "shortTerm", "vehicleType": "fuel",
    "tripEndTimestamp": "2026-08-18T08:03:09Z", "mileage_km": 40,
    "startMileage_km": 65428, "overallMileage_km": 65469,
    "travelTime": 73, "averageFuelConsumption": 8.1,
    "averageSpeed_kmph": 33, "totalFuelConsumption_L": 3.24
  }
}
```

*Veldnamen en getallen gebaseerd op een gedeeld **VW Transporter**-voorbeeld in #1060; identificerende waarden/tijdrepresentatie geherformatteerd. **Geen Audi-200 bevestigd.** Let op: modern `averageFuelConsumption` is in dit voorbeeld al **8.1**, niet 81. Geen automatische `/10`!*

### C. EU Data Act (periodieke of historische dataset)

PHEV-voorbeeld heeft losse datapuntnamen zoals `short_term_data_average_electr_engine_consumption`, `long_term_data_average_fuel_consumption`, `short_term_data_mileage`, enz. Zie:
https://github.com/mikrohard/CarConnectivity-connector-vw-eu-data-act/blob/main/tests/phev_sample_dataset.json

Dit zijn **aggregaatmetingen**, geen automatische individuele ritrecords. Herkomst `source=eu_data_act`, `dataset_created_at`, **eigen carCapturedTimestamp waar aanwezig**, en `quality` bijhouden. Omrekening uit bron-unit specificeren (bijvoorbeeld `kWh/1000km` naar `kWh/100km` is `/10`) en testen op fixture. Niet afleiden uit veldnaam alleen.

**Contra-evidence:** Audi RS e-tron GT in #1805 had `portal_health=OK`, ~110 datapunten, maar geen Trip Statistics-cluster na een rit. Dus: een PHEV-fixture van een ander merk ondersteunt **geen** claim dat de Q8 zulke data levert.

## 4. Codefouten los van endpointblokkade

1. **Onterechte capability-gating:** `support_trip_data = not uses_auth0` koppelt alle trips aan de legacy auth-generatie; nieuwe CARIAD-reader moet per route en per voertuig status bijhouden.
2. **404 permanent-disable:** huidige `update_vehicle_tripdata` zet `support_trip_data=False` bij één 404. Introduceer endpoint-/vehicle-specifieke backoff en latere herontdekking; laat een bruikbare andere route doorgaan. Vergelijk GPS #888.
3. **Parser past niet bij modern payload:** verwacht `tripDataList.tripData`; nieuw antwoord heeft vaak `data: {...}` of `data: [...]` met `_km`, `_kmph` suffixen. Zorg voor aparte, pure parserfuncties.
4. **Onjuiste schaal bij direct mappen:** legacy electric/fuel `/10`; moderne payload kan al echte engineering units bevatten. Contract-level units en bron-specifieke conversie verplicht.
5. **Lege `tripData[]` crasht:** `td_sorted[0]` wordt gebruikt zonder lege-lijstcheck. Resultaat moet `NO_DATA` blijven, geen exception of fictieve nulrit.
6. **Mutatie van brondata:** `td_current = td_sorted[0]` en vervolgens `td_current['tripID']` / `startMileage` wijzigen in een loop; de bron- en resetsemantiek raken daardoor vermengd. Werk met immutable, expliciete snapshots.
7. **Semantiek van User Reset:** niet gelijkstellen aan `last`; als reset niet geleverd wordt, laat de bestaande reset-entity unavailable met reden `NOT_PROVIDED_BY_SOURCE`, in plaats van last-trip te dupliceren.
8. **HTTP 200/207 met embedded errors:** `selectivestatus` kan per job `error` rapporteren. Gebruik payload-level validatie en bewaar vorige geldige waarnemingen met duidelijk gedateerde freshness; geen false-green.
9. **PII in diagnostics:** trip-IDs, VIN, precieze GPS en routes kunnen herleidbaar zijn. De bestaande `get_tripdata` logt `td_current`/`td_reset_trip` bij DEBUG en de vehicle status-reader logt soms volledige payloads: audit van deze logs is verplicht. Geen response bodies of bearer tokens in standaarddiagnostics; synthetische fixtures voor publieke PR.

## 5. Minimale, geen-framework uitbreiding van de basisintegratie

Herbruik de bestaande `AudiService` en `AudiConnectVehicle`, plus de in PR #915 voorgestelde probe- en freshness-infrastructuur. Geen aparte Audi SDK voor de productruntime toevoegen.

**Nieuwe pure normalisatie aan een duidelijk kleine grens** (bestandsnaam vrij te kiezen, bijv. `audi_trip_models.py`):

```python
@dataclass(frozen=True)
class TripObservation:
    kind: str                    # shortterm | longterm | cyclic
    source: str                  # cariad_trips | cariad_tripstatistics | legacy_mbb
    record_type: str             # last_trip | history_item | aggregate_since_reset
    trip_id: str | None
    ended_at: datetime | None
    distance_km: float | None
    duration_min: float | None
    avg_speed_kmh: float | None
    avg_fuel_l_100km: float | None
    avg_electric_kwh_100km: float | None
    total_fuel_l: float | None
    zero_emission_distance_km: float | None
    observed_at: datetime | None
    retrieved_at: datetime
```

`None` betekent **niet beschikbaar**, niet 0. Waarde plus provenance is belangrijker dan het simpelweg vullen van alle velden. `record_type` en `kind` hebben afzonderlijke betekenis. Bovenstaande is ontwerpvoorstel, geen huidige upstream-class.

Voor de 4 oude sensors een **compatibility presenter** gebruiken. Geen verandering aan keys, unique_id of timestamp-semantieken. Nieuwe trip-history/history-export kan een eigen begrensde diagnostiek of separate entity/API krijgen, zodat de HA-state niet gigantisch wordt.

## 6. Eénmalige live-probe volgens afgesproken budget

1. Controleer: actuele Audi Connect v2.5.2, bestaande Auth0-sessie werkt, status/SoC komt via `/selectivestatus` binnen; inspecteer capability `tripStatistics`/`b2bVDATrip` als hint, **niet als bewijs**.
2. Leg **vooraf** een beperkt requestbudget vast en controleer `Vcf-Remaining-Calls` indien beschikbaar. Geen wakeup/POST/PUT en geen onbeperkte retry. Niet standaard bij integration startup.
3. Probeer **T1** `/shortterm/last`. Registreer alleen `HTTP status`, `schema class`, `field names` en eventuele foutcategorie. Geen ruwe payload in logs.
4. Bij parseerbaar 2xx: optioneel **T2** `/longterm/last`, daarna T3. Bij 404: één gecontroleerde alternatieve route T6, geen permanente voertuig-unsupported; bij 403: `AUTHORIZATION_DENIED`; bij 401/429 **stop direct**. Bij 5xx/timeout: `UPSTREAM_TRANSIENT` en bestaande data ongemoeid.
5. Indien T1 succes: test T4 met kleine periode en bepaal of history beschikbaar is. Maak redacted fixture van werkelijk Audi-responsformaat (zonder VIN/GPS/token/route).
6. Als alle CARIAD-routes falen: Data Act-export controleren op exacte `short_term_data_*` velden. Niet gokken op basis van algemene dictionary. Als niet aanwezig: expliciet `NOT_AVAILABLE_FROM_TESTED_SOURCES` rapporteren.
7. Geen officiële app-interceptie, private API-attestation-trucs of tokenextractie als productarchitectuur. Gebruik alleen door eigenaar toegankelijke en geautoriseerde routes.

**Statusinterpretatie**

| Uitkomst | Betekenis / actie |
|---|---|
| `200`, parseerbare `data` | Werkende kandidaat op specifiek getest voertuig; schrijf fixture/contracttest |
| `200`, leeg | Geen trip beschikbaar in antwoord; geen definitieve afwijzing |
| `207`, gemengde jobs | Valideer per job; gebruik alleen geldige subresponses |
| `204` | Geen actuele inhoud; niet gelijk aan voertuig ongeschikt of rit met afstand 0 |
| `401` | Sessie/token niet geautoriseerd; stop probes en markeer auth-probleem |
| `403` | Endpoint niet toegestaan voor sessie/voertuig; niet automatisch 'niet uitgerust' |
| `404` | Route niet gevonden/niet provisioned; probeer andere GET-kandidaat met backoff |
| `429` | Rate-limited; stop en respecteer teruggegeven retrytijd |
| `5xx`/timeout | Tijdelijke backend/transportfout; geen feature-disable of fake values |

## 7. Uitbreidingsbacklog ná tripfix

| Prioriteit | Feature | Bronnen / bewijs | Bepalende test |
|---|---|---|---|
| P0 | Trip current/longterm + User Reset compat | legacy fields, moderne `/trips` | Oude vier sensoren met echte data of expliciete unsupported reden |
| P0 | PHEV electric/fuel/zero-emission consumption | moderne BFF en Data Act veldfamilies | Bronunits, motorsoort, databron, timestamp correct |
| P1 | Vehicle model `Unknown` | Audi #907; VAG Connect AZS/vgql BFF fallback | Model/jaar zonder foutieve hardwarevariant |
| P1 | Position recovery na 404 | Audi #888 | `200→404→200` herstelt zonder reload |
| P1 | TPMS / 12V | andere CARIAD clients & Data Act | Alleen concrete gerapporteerde velden; availability per VIN |
| P1 | pending requests en charging confirm | #865 en PR #915 | API accepted ≠ fysieke success; readback/audit trail |
| P2 | Battery temperature/health, battery care, charging current | Data Act datasets | Brondata vs afgeleide schattingen duidelijk gescheiden |
| P2 | Push-notificaties | FCM-research VAG Connect | **Nog geen geverifieerde Audi-subscribe endpoint**: niet als klaar presenteren |

PR #915 kan de meeste P1-stukken al overlappen. Geen uitbreidings-PR openen vóór review van die gewijzigde bestanden en tests.

## 8. Offline testmatrix: minimaal vóór een PR

- `test_auth0_session_disables_only_legacy_reader_not_all_trip_readers`
- `test_cariad_last_trip_200_unit_suffixed_fields`
- `test_cariad_trip_history_200_list_sorted_by_end_timestamp`
- `test_legacy_mbb_trip_data_scaled_per_documented_legacy_schema`
- `test_modern_trip_consumption_must_not_be_divided_by_10_twice`
- `test_empty_trip_list_is_no_data_not_index_error`
- `test_trip_capability_active_and_endpoint_404_is_not_supported_false`
- `test_404_then_alternative_200_can_recover_without_integration_reload`
- `test_401_or_429_stops_manual_probe_burst`
- `test_207_embedded_job_error_not_counted_as_valid_trip_data`
- `test_cariad_last_trip_must_not_fill_user_reset_entity`
- `test_q8_phev_primary_combustion_secondary_electric_no_swap`
- `test_old_four_trip_entity_unique_ids_and_attributes_unchanged`
- `test_status_sensor_unavailable_with_last_good_observation_age`
- `test_trip_diagnostics_contains_no_vin_token_gps_or_raw_record_ids`
- `test_unreachable_data_act_trip_cluster_yields_unavailable_not_zero`
- `test_no_extra_wakeup_and_no_poll_storm_when_trip_endpoints_404`

Valideer niet enkel met mocked tests: **live Audi Auth0 + daadwerkelijk Q8 PHEV + consent/connected services + HA restart** is de pilotgate. Zonder deze evidence status **IMPLEMENTED, LIVE UNVERIFIED**, nooit 'fixed'.

## 9. Andere bronnen die expliciet de moeite waard zijn

- **Audi Connect upstream stable**: https://github.com/audiconnect/audi_connect_ha/releases/tag/v2.5.2
- **Open upstream PR #915**: https://github.com/audiconnect/audi_connect_ha/pull/915
- **Legacy / moderne Auth0 routeverschillen**: https://github.com/audiconnect/audi_connect_ha/issues/914
- **Actieve capability maar 404 / Audi Data Act gap**: https://github.com/its-me-prash/vwgroup-connect-ha/issues/1805
- **Werkelijke BFF trip-vorm (VW Transporter)**: https://github.com/robinostlund/homeassistant-volkswagencarnet/issues/1060
- **ioBroker moderne trip endpoints + releasebeperkingen**: https://github.com/TA2k/ioBroker.vw-connect
- **Onafhankelijke PHP-route / schema**: https://community.symcon.de/t/myaudi-klasse-fuer-fahrzeugdaten/134904
- **CarConnectivity PHEV Data Act fixture**: https://github.com/mikrohard/CarConnectivity-connector-vw-eu-data-act/blob/main/tests/phev_sample_dataset.json
- **CarConnectivity PHEV documentatie**: https://github.com/mikrohard/CarConnectivity-connector-vw-eu-data-act
- **Audi Data Act fixture + MQTT bridge**: https://github.com/StephanHenke/vwgroup-vehicle2mqtt
- **Audi RTS officiële privacybeschrijving**: https://www.audi.de/de/rechtliches/datenschutz/audi-connect-datenschutz/
- **Audi BE gegevenscategorieën**: https://www.audi.be/nl/myaudi/legal-ag/data-categories/
- **VW Group Data Hub aankondiging**: https://www.drivesomethinggreater.com/newsroom/short-news/2026-4-02-Transition
- **High Mobility VW Group OEM data**: https://docs.high-mobility.com/oem-guides/volkswagen-group

## 10. First assignment — exacte vervolgstappen

**A.** Review PR #915 tegen v2.5.2 en noteer overlap (probe/diagnostics/commands/freshness); neem zijn tests waar geschikt over.  
**B.** Maak afzonderlijke `TripEndpointProbe` die **T1–T3 en beperkt T6** read-only, rate-limited en handmatig onderzoekt; resultaten bevatten alleen status, schema keys en reden.  
**C.** Schrijf pure normalizers met synthetische fixture voor modern BFF en legacy MBB; unitversies niet mengen.  
**D.** Pas `AudiConnectVehicle` aan zodat Auth0 alleen het oude endpoint blokkeert en de nieuwe tripprovider onafhankelijk kan slagen.  
**E.** Verifieer op Q8 PHEV of Audi daadwerkelijk een van de moderne triproutes serveert; leg dan de redacted **exacte response shape** vast.  
**F.** Herstel de vier bestaande tripentities zonder changing IDs; aparte history-optie enkel wanneer echte records beschikbaar zijn.  
**G.** Test exception flows + API-budget + privacy + HA runtime; publiceer pas daarna een nieuwe versioned PR/release.

**Do not**: fake trip values, zero voor missing data, een BEV Q8 fixture als PHEV test gebruiken, alle `404`s permanent uitschakelen, oude MBB-tokenidentiteit met Auth0 verwarren, Data Act-aggregaten als individuele ritten verkopen, of automatische retries op rate-limited GETs introduceren.