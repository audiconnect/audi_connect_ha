# Audi Connect — CARIAD engineering handover V2 (inclusief Homey/openHAB)

**Bijgewerkt 11 november 2026.** V2 bundelt de oorspronkelijke research van 10 november en de aanvullingen uit Homey/openHAB/FHEM/Node-RED.

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


---

# Audi Connect — aanvullend API-onderzoek in Homey, openHAB, FHEM en Node-RED

**Peildatum:** 11 november 2026 (Europe/Brussels)  
**Voor:** engineer op `audiconnect/audi_connect_ha`  
**Hoofdhandover:** `AUDI_CARIAD_ENG_HANDOVER_2026-11-10.md`  
**Doel:** API- en datacontracten terugvinden; geen parallel framework, geen implementatie zonder voertuigspecifieke evidentie.

## 1. Executive findings

1. **Actuele Homey myAudi is de interessantste operationele referentie.** Homey Store `com.audi.etron` vermeldt versie **1.1.5** bij raadpleging. Nieuwe releases bevatten praktische oplossingen rond command queue, startklimaat-payload, PHEV-SoC, tokenrefresh-concurrentie en adaptieve polling. Broncode van de nieuwe maintainer `andiwirz/com.audi.etron` is **momenteel publiek 404**; release-/communityclaims zijn geen geaudite code.
2. **Oude openHAB ConnectedCar Java-code is wél gevonden.** Branch `tknaller/openhab-addons`, `connectedcar_snapshot-3.4`, pad `bundles/org.openhab.binding.connectedcar/src/main/java/org/openhab/binding/connectedcar/internal/api/carnet/`. Beschrijft historische CarNet/MBB endpoints en parsers voor meerdere individuele ritten, geofence-alerts, snelheidsalerts, bestemmingen en laadstatus. Niet verwarren met moderne Audi Auth0-toegang.
3. **Waardevolle historische fixtures zijn publiek:** `tknaller/openhab-addons/connectedcar/sampleData/CarNet/tripDataShortTerm.json` (groot bestand, veel echte ritobjecten; voorzichtig met hergebruik/privacy) en `tripDataLongTerm.json` (twee voorbeelden). De legacy PHEV-consumption scale is x10; aparte normalizer vereist voor moderne CARIAD `/trips`-responsen.
4. **Oudere Homey core is geen tweede onafhankelijke endpoint-validatie:** `martijnpoppen/com.vag.core` embedt een kopie van `ioBroker.vw-connect` (`lib/@iobroker/iobroker.vw-connect/main.js`). Beschouw Homey 2022–2025 + ioBroker niet als onafhankelijk live bewijs.
5. **FHEM / Node-RED bieden geen aangetoonde extra directe Audi Auth0-triproute** in dit onderzoek. Een FHEM-gebruiker gebruikt een script rond EU Data Act; Node-RED-voorbeelden gebruiken onder andere TRONITY, een derde partij. Dit zijn ingestkanalen, geen nieuwe directe CARIAD API-bewijzen.

## 2. Homey myAudi (Andi W.) — functionele en operationele gap review

**Officiële Homey-app:** https://homey.app/en-nl/app/com.audi.etron/  
**Community:** https://community.homey.app/t/app-pro-myaudi-connect-your-audi-ev-or-phev/155543  
**Release-info:** https://homey.app/nl-be/app/com.audi.etron/myAudi/ en https://community.homey.app/t/app-pro-myaudi-connect-your-audi-ev-or-phev/155543/96

| Waarneming | Bewijssoort | Engineeringvraag voor Audi Connect |
|---|---|---|
| Homey v1.1.4: commando's naar één auto serieel, >=15 sec ertussen | App-releasebeschrijving; geen broncode | Heeft PR #915 command serialization per VIN en bescherming tegen gelijktijdige klimaatacties? Niet blind 15 sec overal instellen; eerst gedrag meten. |
| Homey v1.1.4: gewenste temperatuur samen met climate `start` in één call | App-releasebeschrijving; Q8 e-tron genoemd (BEV, niet Q8 TFSI e PHEV) | Bestaande `build_climatisation_start_body` toetsen op atomische temperatuur + start; afzonderlijke temperatuur-API mag 400 geven. |
| Homey v1.0.86: herstel van vastlopende 502, multiple concurrent tokenrefresh en verkeerde auth-foutclassificatie | Ontwikkelaarspost | Single-flight tokenrefresh, timeout en onderscheid 401/429/502/offline testen. |
| Homey v1.0.87: alternatieve PHEV SoC in `rangeStatus.secondaryEngine`/`fuelLevelStatus` | Ontwikkelaarspost | Q8 PHEV: primair verbrandingsmotor en secundair elektrisch expliciet testen; electric SoC mag niet uit benzineveld komen. |
| Homey v1.0.84: `Maximum`/`Reduced` als AC-laadstroominstelling voor PHEV | Ontwikkelaarspost; niet onafhankelijk Q8-gevalideerd | Voeg alleen writable select toe na GET+PUT+readback op eigen auto. Niet aannemen dat ampère-waarden juist zijn. |
| Adaptive polling tot 90 minuten bij slapend voertuig | Product/communitybeschrijving | Vergelijk met coördinator-/freshnessregels; onderscheid cloud-read vs expliciete vehicle-wakeup. |
| App heeft een API Helper en lokale debuglog | Product/communitybeschrijving | Privacy-veilige diagnostische schema keys en statuscodes beschikbaar maken zonder VIN, GPS, auth-headers, tokens of ruwe body in logs. |
| Homey versie 1.1.5 meldt correctie `Invalid Capability: ev_charge_type` voor hybrid | Store releasebeschrijving | Capability-gating per aandrijving testen; geen BEV-only feature op PHEV/ICE. |

**Let op:** Homey ontwikkelaar geeft WCAR (nieuwe voertuigen) en MBB_ODP (oudere Q7/Q8) als ondersteunde families, maar dit is géén bevestiging dat alle remote commands of tripdata onder Audi Connect 2026 Auth0 per Q8 werken. De Homey-app beschrijft geen recente individuele ritgeschiedenis als hoofdfeature. Gebruik de app voor command- en statusverbetering, niet als bewezen tripsolution.

**Source availability:** https://github.com/andiwirz/com.audi.etron is bij onderzoek 404. Een app-store link naar 'Source code' alleen is onvoldoende. Vraag desgewenst via community om toestemming tot inzage in de relevante clientmodules of een geschoonde endpoint-/responsebeschrijving; geen credentials uitwisselen.

## 3. openHAB ConnectedCar — daadwerkelijk geverifieerde Java-code

**Bronbranch:** https://github.com/tknaller/openhab-addons/tree/connectedcar_snapshot-3.4/bundles/org.openhab.binding.connectedcar  
**Java root:** `bundles/org.openhab.binding.connectedcar/src/main/java/org/openhab/binding/connectedcar/internal/api/carnet/`  
**Fixture root:** https://github.com/tknaller/openhab-addons/tree/master/connectedcar/sampleData/CarNet

### 3.1 Exacte historische endpoints in `CarNetApi.java`

Onderstaande routes gebruiken **CarNet/MBB home-region**, NIET de nieuwe Auth0 `https://emea.bff.cariad.digital` API. Ze zijn nuttig als featurespecificatie en historische schemareferentie, niet als werkende 2026-route.

| Java-methode | Historische route (zonder home-region) | Gebruik / model |
|---|---|---|
| `getTripData(type)` | `bs/tripstatistics/v1/{type}/{country}/vehicles/{VIN}/tripdata/{shortTerm\|longTerm}?type=list` | Volledige lijst met per-trip ID, datum, afstand, verbruik |
| `getTripStats(tripType)` | `bs/tripstatistics/v1/{type}/{country}/vehicles/{VIN}/tripdata/{tripType}?newest` | Afzonderlijke `newest`-variant — historisch en onbewezen onder Auth0 |
| `getGeoFenceAlerts()` | `bs/geofencing/v1/{type}/{country}/vehicles/{VIN}/geofencingAlerts` | Server-side geofence-events |
| `getGeoFenceConfig()` | `bs/geofencing/v1/{type}/{country}/vehicles/{VIN}/geofencingConfiguration` | Geofence-definities |
| `getSpeedAlerts()` | `bs/speedalert/v1/{type}/{country}/vehicles/{VIN}/speedAlerts` | Snelheidswaarschuwingen |
| `getSpeedAlertConfig()` | `bs/speedalert/v1/{type}/{country}/vehicles/{VIN}/speedAlertConfiguration` | Snelheidsdrempels |
| `getDestinations()` | `destinationfeedservice/mydestinations/v1/{type}/{country}/vehicles/{VIN}/destinations` | Bestemmingshistoriek; persoonlijke locatiegegevens |
| `getHistory()` | `bs/dwap/v1/{type}/{country}/vehicles/{VIN}/history` | Alarmsysteem-/eventhistorie, niet verwarren met ritten |

`{type}` is in de Java-route de voertuigspecifieke merk-/API-placeholder; niet te verwarren met triptype. **Beperking:** de openHAB-branch is historisch (ca. 2022–2023); geen actuele Auth0-authenticatie, geen aangetoond 2026 Audi succes. Tests van die routes zijn nu **lage prioriteit** ten opzichte van moderne CARIAD `/vehicle/v1/trips` en de Data Act-velden.

### 3.2 Concrete parser-/modellessen

- `CarNetServiceTripData.java` sorteert ritten aflopend op `timestamp` en maakt **meerdere individuele** short/long trip-channels (aantal geconfigureerd). Een nuttig ontwerp voor een latere triphistory, naast de huidige vier Audi Connect tripsensoren.
- Het bestand deelt historische `averageFuelConsumption` door 10 en schaalt `averageElectricEngineConsumption` eveneens. Die schaal is **schema-afhankelijk**. Niet toepassen op de moderne CARIAD-response waarin `averageFuelConsumption` bijvoorbeeld `8.1` kan zijn.
- `tripDataShortTerm.json` is circa 91 KB met veel oude ritrecords; gebruik geen historische echte ritgegevens rechtstreeks in een publieke testsuite zonder gegevenssanering. Bouw verkleinde **synthetische** fixtures voor v2.5.2 plus de moderne BFF-contracten.
- `CarNetServiceGeoFenceAlerts.java` en `CarNetServiceSpeedAlerts.java` modelleren alert-event, tijd en omschrijving. Niet hetzelfde als een lokaal afgeleide HA-zone of snelheid; pas beschikbaar maken na echte backendbevestiging.
- `CarNetServiceCharger.java` bevat historisch ook energieflow, plug lock, externe stroom en laadstatusfoutcodes. Controleer huidige BFF jobs op dezelfde **semantiek**, niet op dezelfde oude JSON-paden.
- Historische `BrandCarNetAudi.java` gebruikt `msg.audi.de/fs-car`, `openid mbb ...` en oude app/clientheaders. Deze login **niet herstellen** door de actuele Audi Auth0-flow terug te draaien.

### 3.3 Exacte bronlinks

- [CarNetApi.java](https://github.com/tknaller/openhab-addons/blob/connectedcar_snapshot-3.4/bundles/org.openhab.binding.connectedcar/src/main/java/org/openhab/binding/connectedcar/internal/api/carnet/CarNetApi.java)
- [CarNetServiceTripData.java](https://github.com/tknaller/openhab-addons/blob/connectedcar_snapshot-3.4/bundles/org.openhab.binding.connectedcar/src/main/java/org/openhab/binding/connectedcar/internal/api/carnet/CarNetServiceTripData.java)
- [CarNetServiceGeoFenceAlerts.java](https://github.com/tknaller/openhab-addons/blob/connectedcar_snapshot-3.4/bundles/org.openhab.binding.connectedcar/src/main/java/org/openhab/binding/connectedcar/internal/api/carnet/CarNetServiceGeoFenceAlerts.java)
- [CarNetServiceSpeedAlerts.java](https://github.com/tknaller/openhab-addons/blob/connectedcar_snapshot-3.4/bundles/org.openhab.binding.connectedcar/src/main/java/org/openhab/binding/connectedcar/internal/api/carnet/CarNetServiceSpeedAlerts.java)
- [Legacy trip short-term fixture](https://github.com/tknaller/openhab-addons/blob/master/connectedcar/sampleData/CarNet/tripDataShortTerm.json)
- [Legacy trip long-term fixture](https://github.com/tknaller/openhab-addons/blob/master/connectedcar/sampleData/CarNet/tripDataLongTerm.json)
- [Geofence-event fixture](https://github.com/tknaller/openhab-addons/blob/master/connectedcar/sampleData/CarNet/getGeoFenceAlerts.json)
- [Speed-alert fixture](https://github.com/tknaller/openhab-addons/blob/master/connectedcar/sampleData/CarNet/getSpeedAlerts.json)

**Licentie:** openHAB-code is onder het openHAB/EPL-licentieregime gepubliceerd. Onderzoek API-contracten en schrijf zelf MIT-compatibele implementaties; geen blind kopiëren van Java-code naar MIT Audi Connect.

## 4. Andere ecosystemen — stand van bewijs

| Platform / project | Wat gevonden? | Relevantie / beslissing |
|---|---|---|
| **Oude Homey core** [martijnpoppen/com.vag.core](https://github.com/martijnpoppen/com.vag.core) | Legacy Homey Audi EV/PHEV/ICE drivers, maar met ingebedde ioBroker VW Connect code | **Geen onafhankelijke verificatie** van een nieuw 2026 Audi endpoint. Wel oude semantische mapping. |
| **Homey Volkswagen door Bloemendaal** [discussie](https://community.homey.app/t/app-pro-volkswagen-your-car-your-smart-home-perfectly-connected/145155/93) | Developer traceerde `/auth/v1/android/challenge` en app attestation voor VW, stopte eind mei 2026 | **Niet** proberen Google Play Integrity of clientattestation te omzeilen. Deze flow is voor VW gedocumenteerd, geen bewezen vereiste van Audi's nieuwe Auth0-route. |
| **Homey/Volkswagen CARIAD B2B** [reactie Homey team](https://community.homey.app/t/app-pro-volkswagen-your-car-your-smart-home-perfectly-connected/145155/114) | Commerciële officiële API-toegang, prijsindicatie op basis van ontwikkelaarsgesprek | Bevestigt verschil open consument-API vs commerciële partner-API, niet bruikbaar als plug-and-play in MIT-integratie. |
| **FHEM Data Act** [CarConnectivity #155](https://github.com/tillsteinbach/CarConnectivity/issues/155) | FHEM-gebruiker leest EU Data Act via script/cron | **Geen nieuwe onafhankelijke Audi BFF-trip-API**. Wel aanvullende ingestmethode. |
| **Node-RED TRONITY** [flow](https://flows.nodered.org/flow/8cbe02c96bd96d095f8cd4a790716487) | OAuth en `/v1/vehicles/.../bulk` via TRONITY | Derde-partijdatastroom, geen Audi/CARIAD endpoint; geschikt als optionele vergelijkingsbron, niet als upstream clientfix. |
| **openHAB ConnectedCar** | Oude Java CarNet client; meerdere JSON-fixtures | **Hoge referentiewaarde voor schema's**, lage waarde voor huidige autorisatie. |
| **Homebridge** | In dit onderzoek geen overtuigend actuele rechtstreekse Audi/CARIAD client aangetroffen | Niet tellen als ontbrekende bevestiging; zoek alleen opnieuw met nieuwe naam/bronbewijs. |

## 5. Bijgewerkte ontwikkelvolgorde en testcriteria

**P0: tripdata herstellen — ongewijzigd.**

- Review upstream Audi PR #915; bedenk niet opnieuw command/freshness/diagnostic infrastructure.
- Test modern BFF `/vehicle/v1/trips/{vin}/shortterm/last`, `longterm/last`, `cyclic/last`, beperkt en read-only, tegen werkende **Audi** Auth0-session. Gebruik een apart gemaskeerd capability-resultaat en statuscodes. VW-werkzaamheid is geen Audi-bewijs.
- Houd de oude MBB `?type=list`- en de `?newest`-varianten apart, **nooit** met het Auth0-token tegen legacy `/fs-car` forceren.
- Behoud vier huidige Audi Connect tripentities en identifiers. Maak een expliciete `TripSource`, `TripKind`, `TripQuality` en aparte bronafhankelijke normalizer, niet vier willekeurige fallbackcalls in `sensor.py`.
- Indien CARIAD trips niet beschikbaar zijn, Data Act only **als dataset daadwerkelijk tripcluster bevat**, nooit een PHEV/BEV voorbeeld als echte Q8-data behandelen.

**P1: Auth0 remote actions en kwaliteit — overlap met PR #915 controleren.**

- Per-VIN serialisatie van remote commands en gecorreleerde request-ID/readback. Test twee parallelle flows; laat zien dat er geen verkeerde command success ontstaat.
- Climate start met temperatuur in dezelfde BFF-call; test wanneer afzonderlijke set-temperatuur 400 geeft.
- 502 timeouts, 401 vs 429, tokenrefresh single-flight en herstel zonder HA reload. Tussentijdse 404 mag capability niet permanent verwijderen.
- PHEV SoC/fuel/range: primary versus secondary engine per veld, geen blind assumed position; test specifiek Q8 PHEV.
- Lange slaap: cloudfreshness versus voertuigbevraging en ratebudget apart bewaken.

**P2: nieuwe functionele families — na bewijs.**

- Historische alert-events: geofence, speed alerts, stored destinations (privacy!). Eerst aantonen dat Audi huidige CARIAD backend die data biedt of expliciet `UNSUPPORTED`; geen willekeurige legacy oproepen per poll.
- Event history apart van trip history; DWA-alarmhistorie ≠ ritlogboek.
- Historische ritten (meerdere per dag) pas toevoegen na bevestigde `data[]` of stabiele Data Act-records; anders geen fake trip IDs/timestamps.

### Gerichte extra regressietests

1. `test_homey_like_per_vin_commands_are_serialized_not_parallel`
2. `test_climate_temperature_sent_atomically_with_start_when_supported`
3. `test_token_refresh_is_single_flight_after_concurrent_502`
4. `test_phev_soc_secondary_engine_and_fuel_primary_are_not_swapped`
5. `test_sleeping_car_poll_backoff_never_marks_cached_data_fresh`
6. `test_openhab_legacy_trip_list_fixture_parsed_with_legacy_scaling`
7. `test_openhab_legacy_trip_newest_is_not_assumed_modern_auth0`
8. `test_geofence_speedalert_destinations_not_probed_by_default`
9. `test_no_legacy_login_fallback_when_auth0_is_active`
10. `test_same_iobroker_source_via_homey_not_counted_as_independent_validation`

## 6. Directe engineerbeslissing

**Start niet met geofence/alerts.** De grootste winst uit dit vervolgonderzoek is (a) actueel Homey-command lifecycle/refresh-hardening, en (b) historische openHAB-code/fixtures voor ritmodel en ontbrekende functiefamilies. **Tripdata blijft eerste milestone**. De Q8 PHEV heeft een live, privacy-veilige Audi Auth0-test nodig voordat een route als werkend kan worden afgevinkt.

## 7. Bewijsgrens

- Geen Audi-credentials, VPN of voertuig live aangeraakt in dit onderzoek.
- Geen huidige Homey-maintainerbroncode beschikbaar; enkel publiek gepubliceerde changelog/forumcitaten.
- De openHAB-bron is historische CarNet/MBB-Java, **geen moderne Audi Auth0-implementatie**.
- Geen wijziging aan `audiconnect/audi_connect_ha` uitgevoerd.


---

# Audi Connect — Deep-dive openHAB, Homey, ioBroker en CARIAD (V3 addendum)

**Peildatum:** 11 november 2026 (Europe/Brussels)  
**Target:** upstream `audiconnect/audi_connect_ha` — base integratie; geen RHI-omweg  
**Lees eerst:** `AUDI_CARIAD_ENG_HANDOVER_V2_2026-11-11.md`  
**Nieuw in deze addendum:** gecontroleerde openHAB Java-contracten/fixtures, actuele Homey-diagnostiek, statische review van upstream PR #915, Tibber als onafhankelijke voertuigbron, en aangescherpte regressietests.

## 1. Executive findings — wat is *nieuw* tegenover V2

1. **Potentieel regressierisico in upstream PR #915**: `capability_jobs.select_jobs()` selecteert in opvolgpolls alleen jobs waarvan `job` letterlijk in `userCapabilities` staat. Binnen het VW Group/CARIAD-ecosysteem zijn **verschillende namen voor capability versus job** gevonden: capability `oilLevelStatus` versus `selectivestatus`-job `oilLevel`. OpenHAB's gedocumenteerde CARIAD JSON-response geeft een concreet voorbeeld. Dit kan `oilLevel` na eerste poll wegfilteren, ook wanneer de eerste poll gegevens teruggaf. **Statische code-reviewbevinding, nog niet live gereproduceerd.** Maak regressietest en mapping / behoud-van-succesvolle-job-strategie. De huidige PR-test `test_explicit_disabled_and_missing_jobs_are_skipped` verzekert juist naïeve exact-name filtering en dekt de afwijking niet.
2. **HTTP 207 wordt al geaccepteerd** in Audi Connect v2.5.2 `audi_api.py:125` (status `200, 202, 207`). Niet opnieuw aan de HTTP-laag sleutelen. Validatie moet op **jobniveau** gebeuren; 207 betekent juist mogelijk partiële successen en job-errors. OpenHAB bevat een echte gedeeltelijke CARIAD-response als referentie.
3. **Homey myAudi heeft concrete nieuwe diagnostiek**: versie 1.1.1 beschrijft warning-light triggers, plug-lock status, auxiliary heating status, inspection due en live S-PIN-check zonder reauth. Nieuwe tests kunnen aantonen of Audi Connect dezelfde bronnen al heeft en correct exposeert. Actuele broncode van de nieuwe Homey-maintainer is niet publiek bevestigd: app/releasebeschrijving is geen codebevestiging.
4. **openHAB ConnectedCar is historisch, maar de Java-bron en grote fixtures bestaan nog** in `tknaller/openhab-addons` branch `connectedcar_snapshot-3.4`. Moderne CARIAD/Auth0-beschikbaarheid is daarmee niet bewezen. Relevante details: `getTripData(...?type=list)`, alternatieve `getTripStats(...?newest)`, geofence/speed alerts, destinations, DWA history, charger errors en pending-action-guard.
5. **Tibber Data API via ioBroker is een extra onafhankelijke READ bron, geen directe Audi API**. `lib/tibber.js` consumeert vijf gegevensfamilies (SoC, target, range, plug, charging). Er is **geen ritgeschiedenisimplementatie** in die adapter; alleen gebruiken om statusfouten te vergelijken, niet als oplossing voor trip recovery.

## 2. Upstream PR #915 — gerichte static review

- PR: https://github.com/audiconnect/audi_connect_ha/pull/915
- Fork/ref: https://github.com/npinguin/audi_connect_ha/tree/contrib/upstream-audi-connect-fixes
- File: https://github.com/npinguin/audi_connect_ha/blob/contrib/upstream-audi-connect-fixes/custom_components/audiconnect/capability_jobs.py
- Test: https://github.com/npinguin/audi_connect_ha/blob/contrib/upstream-audi-connect-fixes/tests/test_q8_capability_poll_planner.py
- Gerelateerd catalogusbestand: `custom_components/audiconnect/capability_catalog.py`, dat `oilLevelStatus` expliciet als capability gebruikt, terwijl `capability_jobs.py` de job `oilLevel` vraagt.

**Effectief algoritme**:

```python
# Samenvatting van de geïnspecteerde PR-code, geen letterlijke volledige kopie
if not capabilities:
    return BASE_SELECTIVE_JOBS
return tuple(
    job for job in BASE_SELECTIVE_JOBS
    if job == 'userCapabilities' or (job in capabilities and job not in impaired)
)
```

**Reproductie op mock-level:**

```python
reported = frozenset({'access', 'oilLevelStatus', 'fuelStatus', 'vehicleHealthInspection'})
selected = select_jobs(reported, frozenset())
assert 'oilLevel' not in selected  # Huidige code; ongewenst als eerste poll data voor oilLevel had
```

**Voorgestelde oplossing:**

- Bouw een **beperkte** mapping van bekende capability-ID naar job-ID, bv. `oilLevelStatus -> oilLevel` (en alleen bewezen mappings). Geen universele aanname dat capability-ID exact de job-ID is.
- Houd per VIN bij welke jobs in de **eerste geldige selectivestatus-response** daadwerkelijk parseerbare data leverden; prune die niet op basis van naamverschil. Teken per job `valid`, `embedded_error`, `not_returned` en `captured_at` apart op.
- Een capability die als `reported_impaired` verschijnt, is niet automatisch een geldige HTTP-verbodscode. Hou `actual_endpoint_authorization` als afzonderlijk verdict.
- `parkingPosition` is een aparte `parkingposition`-route; `tripStatistics` en `b2bVDATrip` zijn capability-ID's en mogen **niet** zonder bewijs als `selectivestatus?jobs=tripStatistics` worden opgevoerd in productpolling.
- Voorkom de omgekeerde fout: niet alle ooit geziene jobs permanent op iedere poll blijven sturen zonder beleid. Gebruik last-success en conservatieve limieten; test tegen actieve capabilities en bekende failures.

**Regressietests toevoegen aan PR #915 voordat deze wordt gemerged:**

1. `test_oil_level_status_capability_keeps_oil_level_job_after_first_success`
2. `test_capability_job_ids_not_assumed_1_to_1`
3. `test_207_usable_job_and_embedded_error_job_are_handled_independently`
4. `test_reported_trip_statistics_does_not_enable_unknown_selectivestatus_job`
5. `test_job_removed_by_404_can_recover_after_backoff_without_reload`
6. `test_known_successful_job_survives_partial_capabilities_response`

**Al correct aanwezig:** `AudiAPI.request` ondersteunt HTTP 207 in upstream v2.5.2. Niet als ontbrekende feature registreren.

## 3. openHAB ConnectedCar — geverifieerde historische broncode

**Exact repo/ref:** https://github.com/tknaller/openhab-addons/tree/connectedcar_snapshot-3.4/bundles/org.openhab.binding.connectedcar

**Belangrijke Java-bestanden**:

| Bestandsnaam | Concrete technische waarde |
|---|---|
| `CarNetApi.java` | Oude endpoints `?type=list`, `?newest`, geofence, speedalert, destinations; pendingsystem en actieheaders |
| `CarNetServiceTripData.java` | Meerdere losse ritten, sortering op timestamp, legacy consumptie-schaal |
| `CarNetServiceGeoFenceAlerts.java` | Alert-eventtype, datum, definitienaam als afzonderlijke historische events |
| `CarNetServiceSpeedAlerts.java` | Overspeed eventtype, snelheid en tijd |
| `CarNetServiceDestinations.java` | Bestemmingshistoriek (persoons-/locatiegevoelig); laag prioriteit |
| `CarNetServiceCharger.java` | Legacy chargingStateErrorCode, `energyFlow`, remainingChargingTime en plug-/laadstatussemantiek |
| `BrandCarNetAudi.java` | Historische Audi `fs-car`-endpoints en OAuth/MBB headers, niet toepasbaar op nieuwe Auth0 |
| `ApiRequestQueue.java` / `CarNetPendingRequest.java` | Serververzoeken serieel opvolgen; niet hetzelfde als fysiek voertuig-readback |

**Historische API-routes:**

```text
bs/tripstatistics/v1/{brand}/{country}/vehicles/{VIN}/tripdata/shortTerm?type=list
bs/tripstatistics/v1/{brand}/{country}/vehicles/{VIN}/tripdata/longTerm?type=list
bs/tripstatistics/v1/{brand}/{country}/vehicles/{VIN}/tripdata/{tripType}?newest
bs/geofencing/v1/{brand}/{country}/vehicles/{VIN}/geofencingAlerts
bs/speedalert/v1/{brand}/{country}/vehicles/{VIN}/speedAlerts
destinationfeedservice/mydestinations/v1/{brand}/{country}/vehicles/{VIN}/destinations
bs/dwap/v1/{brand}/{country}/vehicles/{VIN}/history
```

**Alle bovenstaande routes zijn legacy CarNet/MBB, niet geverifieerd onder Audi Auth0 in november 2026.** Deze routes mogen nooit via een automatische 'probe all endpoints'-loop bij iedere statuspoll worden afgevuurd. De Java-code onder EPL-2.0 (openHAB-licentie); alleen protocolkennis/contract gebruiken in MIT-repo, geen blind codekopiëren.

**Werkelijke historische testfixtures:**

- Short-term lijst: https://github.com/tknaller/openhab-addons/blob/master/connectedcar/sampleData/CarNet/tripDataShortTerm.json (~92 KB)
- Long-term lijst: https://github.com/tknaller/openhab-addons/blob/master/connectedcar/sampleData/CarNet/tripDataLongTerm.json
- Geofence-alerts: https://github.com/tknaller/openhab-addons/blob/master/connectedcar/sampleData/CarNet/getGeoFenceAlerts.json
- Snelheidsalerts: https://github.com/tknaller/openhab-addons/blob/master/connectedcar/sampleData/CarNet/getSpeedAlerts.json
- Destinations: https://github.com/tknaller/openhab-addons/blob/master/connectedcar/sampleData/CarNet/getDestinations.json

`tripDataLongTerm.json` bevat concreet `averageElectricEngineConsumption: 138`, `averageFuelConsumption: 56`, `averageSpeed: 58`, `mileage: 6013`, `traveltime: 6226`, `reportReason: clamp15off`. Dit toont de **legacy x10 schaal**, niet dat moderne CARIAD dezelfde eenheid gebruikt. Fixtures bevatten mogelijke locatie-/ritmetadata; saneren vóór opname in Audi Connect-tests.

**Belangrijk openHAB-resultaat 2026:** de community beschreef in juli 2026 dat de ConnectedCar-binding feitelijk niet meer wordt onderhouden. De openbare bronbranch is dus een historisch referentiearchief, geen concurrerende actuele Audi API-client.

**Extra CARIAD-payloadreferentie:**
https://community.openhab.org/t/connectedcar-binding-myaudi-volkswagen-vw-id-skoda-enyaq-seat-ford-wecharge/92378?page=65
— oudere response met `HTTP 207`, `userCapabilities.id=oilLevelStatus` en job `oilLevel.oilLevelStatus.value`. Ook toont de response het verschil tussen `carCapturedTimestamp` en tijdstip van de API-call.

## 4. Homey myAudi 2026 — aanvullende referentie

Bronnen: https://homey.app/en-nl/app/com.audi.etron/ en https://community.homey.app/t/app-pro-myaudi-connect-your-audi-ev-or-phev/155543

| Waarneming | Aard bewijs | Engineeropdracht |
|---|---|---|
| Version 1.1.5: Hybrid `ev_charge_type` capability fout opgelost | Homey App Store | Geen BEV-only entity op PHEV/ICE, ook niet als API enkel een oud veld meestuurt |
| Version 1.1.4: serialisatie per auto, >=15 seconden tussen acties | Homey release notes | PR #915 controleren op per-VIN concurrentie en command queue; eerst meten, niet overal vaste timer kopiëren |
| Version 1.1.4: climate-start inclusief target temperatuur | Homey release notes; model Q8 e-tron BEV als voorbeeld | Atomic climate-start, later readback, geen twee onnodige mutaties |
| Version 1.1.1: waarschuwingslampjes en triggers | Homey release notes | `vehicleHealthWarnings` en `vehicleLights`: parser/capability/alerts gap bepalen |
| Version 1.1.1: plug locked + auxiliary heater + inspection due | Homey release notes | Bestaande Audi statusjobs vergelijken, ontbrekende bruikbare sensors toevoegen |
| Version 1.1.1: S-PIN wijziging wordt apart gevalideerd | Homey release notes | SPIN-setup onafhankelijk van gewone Auth0 reauth behandelen; alleen veilige, geautoriseerde check |
| Version 1.0.98: tokenrefresh max 30 sec, vermijdt permanente hang | Homey release notes | timeout + single-flight refresh regressies; PR #915 vergelijken |
| Version 1.0.87: PHEV SoC fallback onder secondaryEngine | Homey developer forum | Q8 PHEV engine/SoC/range mappings onder echt response schema testen |
| Adaptive sleep polling | Homey appbeschrijving | Scheiding cloud-cached state, forced vehicle wakeup en last actual capture |

**Homey toont bij onderzoek geen eigen actuele trip-history implementatie** als publieke feature. Niet ten onrechte kwalificeren als tweede onafhankelijke bevestiging van Audi Trip API. De vermeende open-source link voor nieuwe maintainer `https://github.com/andiwirz/com.audi.etron` gaf 404; oude `martijnpoppen/com.vag.core` embedt ioBroker-code en telt niet als volledig onafhankelijke API-bron.

## 5. Extra voertuigbron via ioBroker: Tibber Data API

- README: https://github.com/TA2k/ioBroker.vw-connect/blob/master/README.md
- Code: https://github.com/TA2k/ioBroker.vw-connect/blob/master/lib/tibber.js
- Publieke API-documentatie: https://data-api.tibber.com/docs/

De ioBroker-adapter gebruikt **niet** een Audi/CARIAD endpoint, maar Tibber als geconsenteerde derde partij. De code declareert deze concrete capabilities:

```text
storage.stateOfCharge          -> SoC
storage.targetStateOfCharge    -> target SoC
range.remaining               -> range (let op meter/mijl/km conversie)
connector.status              -> plugged/unplugged
charging.status               -> charging/idle
```

Tibber Data API beschrijft categorie `vehicles` en optionele historie 'where available', maar **geen aantoonbare Audi individuele ritrecords in ioBroker `lib/tibber.js`**. Ook is een apart Tibber-account, paired Audi en OAuth-consent nodig. Dit is hooguit een **optionele onafhankelijke observatie-/validatiebron** bij afwijkende SoC/charging state, niet de hoofdoplossing voor triprecovery en zeker geen tokenvervanging voor de base integratie.

**Bijkomende datakwaliteitles:** `range.remaining` kan m/km/mi rapporteren. Dit is geen reden om een standaardwaarde zonder unitblindheid te accepteren; test unit-conversies expliciet.

## 6. Functionele gaps en semantische scheiding

**Drie verschillende histories:**

1. `trip_history`: ritrecord met trip-ID/eindtimestamp/afstand, soms plus sinds-reset-statistiek.
2. `alert_history`: `geofence`, `speed`, `theft`; dit zijn evenementen, geen ritten. Privacy en autorisatie verschillen.
3. `charging_history`: laadtransacties, energie, betaal-/laadsessies; `WeCharge/getChargingSessions` valt onder andere auth en moet niet als voertuig-tripdata worden gemodelleerd.

Een HA sensor met de naam `ShortTerm Trip User Reset` mag **niet** worden gevuld met `shortterm/last` zonder een geldige semantische mapping. Oudere openHAB `?newest` en `?type=list` zijn evenmin automatisch equivalent aan nieuwe BFF `/trips/.../last`.

## 7. Exact engineering action list bovenop V2

**P0 — releaseblockers / direct starten**

1. Review PR #915 `capability_jobs.py`, voeg mapping + observed-valid-job retention toe. Bouw tests voor `oilLevelStatus -> oilLevel` en 207 met gemengde jobs. Bestaande API `200/202/207` behouden.
2. Implementeer/valideer expliciete Auth0 GET-trippath-probes (CARIAD `/vehicle/v1/trips/.../last`), strikt read-only met callbudget. PR #915 extended probe `selectivestatus?jobs=tripStatistics` is nog geen bewezen triproute.
3. Normaliseer los legacy `tripDataList.tripData` (x10) vs moderne `data` (eenheden in naam) vs Data Act (semantische aggregaten). Geen stille substitutie van User Reset door Last Trip.
4. Voeg synthetische fixtures toe voor oude openHAB-triplist en real-world gesaneerde *structuur* uit `/trips/.../last`, plus 'geen tripdata' case.

**P1 — naast PR #915 reviewen**

5. Homey runtime-lessen toetsen op concurrent remote commands, Auth0 refresh timeouts, 502 herstel, PHEV SoC en klimaat-temp-in-start.
6. Warning-light event / plug lock / auxiliary heater / inspection due capability-coverage, met duidelijke source+timestamp.
7. Optionele cross-check SoC/range/plug via Data Act of Tibber alleen bij expliciete setup; geen tweede actuator en geen duplicaat fysieke auto.

**P2 — alleen na bronbewijs**

8. Geofence- en speedalert-events en destinations via actieve moderne Audi API; legacy openHAB-schema dient als inventaris, geen bewijs van 2026 toegang.
9. Separate charging session history uit WeCharge/OEM/partnerbron, niet vermengen met ritten.

## 8. Verificatie- en overdrachtscriteria

- Classificeer iedere claim als `(A) geaudite code`, `(B) historische fixture`, `(C) app changelog/forum`, `(D) echte 2026 live Audi-call`, `(E) hypothese`.
- Een PR krijgt **geen 'Audi Q8 PHEV trip fixed' label** zonder `(D)` (daadwerkelijk geslaagde Q8 Auth0 call plus HA runtimebewijs).
- Test `200/207` met embedded errors, 204, 401, 403, 404, 429 en 5xx per bron; geen automatische requestloop op 404/429.
- Upload geen live VIN, routegeschiedenis, authenticatieheaders, tokens, S-PIN, GPS of raw triplogs in publieke issues/tests.
- Test bestaande vier trip entity IDs, command works/readback, modelidentiteit, SoC-engine en HA restart.
- PR #915 komt eerst; deze addendum verandert de **scope**, niet automatisch de implementatiestatus. Geen code in upstream gewijzigd tijdens dit onderzoek.


## 9. IP-Symcon PHP — PHEV-geval met modern tripboek (nieuw bewijs)

Bronnen:
- https://community.symcon.de/t/myaudi-klasse-fuer-fahrzeugdaten/134904
- https://community.symcon.de/t/myaudi-klasse-fuer-fahrzeugdaten/134904?page=2

**Ongewoon nuttige onafhankelijke bron:** auteur `Strichcode` meldt op **29 juli 2025** dat op zijn **Audi A3 8Y PHEV** het grootste deel van de data van één endpoint komt, maar het digitale rittenboek van een *ander* endpoint. In januari 2026 herwerkte hij de login na gewijzigde tokenhandling. Op **8 juni 2026** meldde hij dat een nieuwe client na API-wijzigingen opnieuw werkte; een tweede gebruiker bevestigde dit dezelfde dag. Dat is geen bewijs voor huidig november-2026 Auth0, maar wel voor 2026 CARIAD-tripimplementatie op een **echte Audi PHEV**, in tegenstelling tot de VW-Transporter uit de eerdere API-test.

De PHP-klasse toont o.a. de volgende routes (de exacte actuele respons en tokenondersteuning zijn **niet live gevalideerd**):

```text
GET https://emea.bff.cariad.digital/vehicle/v1/trips/{VIN}/shortterm
GET https://emea.bff.cariad.digital/vehicle/v1/trips/{VIN}/longterm/last
GET https://emea.bff.cariad.digital/navigation/v1/navigation/destinations
PUT https://emea.bff.cariad.digital/vehicle/v2/charging/{VIN}/timers
```

Bij korte ritten gebruikt de historische PHP-output `tripEndTimestamp`, `mileage_km`, `averageSpeed_kmph`, `averageElectricConsumption`, `averageFuelConsumption` en `travelTime`. De klasse telt ook verbruik en kosten op, maar haar huishoudtarief, assumpties en kostberekening zijn **applicatielogica, geen Audi API-velden**. Test PHEV `averageElectricConsumption` als nieuw alias naast legacy `averageElectricEngineConsumption`, zonder blind `/10` toe te passen.

**Veld met semantisch gevaar:** de auteur verving op 10 juni 2026 de verdwenen `vehicleParkingClock` door `shortTerm[0].tripEndTimestamp` om toch parkeertijd te kunnen tonen. Dit is een *afgeleide proxy*, geen echte door het voertuig gerapporteerde parkeerstart. Audi Connect moet `parked_since_reported` en `last_trip_ended_at` niet stilzwijgend gelijkstellen; indien als schatting toegevoegd, label `source=derived_last_trip_end` en `quality=estimated`.

**Aanvullende regressietests:**

- `test_audi_phev_modern_trip_average_electric_consumption_alias`
- `test_trip_end_timestamp_not_falsely_reported_as_vehicle_parking_clock`
- `test_navigation_destination_history_requires_explicit_consent_and_redaction`
- `test_modern_cariad_trip_route_does_not_use_legacy_mbb_bearer`

**Evidentiegrens:** PHP communitycode en juni 2026-gebruikersbevestiging, **geen geslaagde november 2026 Audi/Q8 Auth0 test**.