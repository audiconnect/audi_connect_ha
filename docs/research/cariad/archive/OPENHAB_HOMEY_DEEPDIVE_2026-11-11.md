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