"""Regression tests for the clean V3 engine, independent of V2 polling.

Only synthetic Audi API responses are used. Never contact a real vehicle.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.audiconnect.coordinator import AudiDataUpdateCoordinator
from custom_components.audiconnect.v3.coordinator_clean import V3CleanCoordinator
from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
from custom_components.audiconnect.v3.engine import V3Engine
from custom_components.audiconnect.v3.registry import CapabilityRegistry, VehicleContext
from custom_components.audiconnect.v3.transport import V3Response
from custom_components.audiconnect.v3.profile_store import restore_profile
from custom_components.audiconnect.v3.vehicle import V3Vehicle

CATALOG = Path(__file__).resolve().parents[1] / "tests/fixtures/v3_climate_catalog.json"
VIN = "WAUZZZ4M0MD123456"


class FakeAuth:
    country = "DE"
    uses_auth0 = True


class FakeTransport:
    def __init__(self, response_list):
        self._responses = list(response_list)
        self.calls = []
        self.request_count = 0
        self.remaining_calls = 100

    async def discover_vehicles(self):
        self.calls.append(("inventory",))
        return [
            {
                "vin": VIN,
                "nickname": "Test Audi",
                "vehicle": {
                    "media": {"longName": "Audi Q8 TFSI e"},
                    "classification": {"driveTrain": "PHEV"},
                },
            }
        ]

    async def request(self, family, method, path, **kwargs):
        self.calls.append((family, method, path, kwargs))
        self.request_count += 1
        return self._responses.pop(0)


class FakeStore:
    def __init__(self):
        self.writes = []
        self.loads = 0
        self.records = {}

    async def async_load(self, catalog, contexts):
        self.loads += 1
        return {
            vin: (
                restore_profile(catalog, context, self.records[vin], cooldown_seconds=0)
                if vin in self.records
                else DevelopmentProfile(catalog, context, cooldown_seconds=0)
            )
            for vin, context in contexts.items()
        }

    async def async_save(self, profiles):
        snapshot = {key: val.snapshot() for key, val in profiles.items()}
        self.writes.append(snapshot)
        self.records.update(snapshot)


def engine_for(*response_list):
    registry = CapabilityRegistry(json.loads(CATALOG.read_text()))
    transport = FakeTransport(response_list)
    storage = FakeStore()
    engine = V3Engine(
        SimpleNamespace(),
        SimpleNamespace(entry_id="example"),
        registry,
        auth=FakeAuth(),
        transport=transport,
        storage=storage,
    )
    return engine, transport, storage


def status(*, http=200, value="off", captured=True):
    payload = {
        "climatisation": {
            "climatisationStatus": {"value": {"climatisationState": value}}
        }
    }
    if captured:
        payload["climatisation"]["climatisationStatus"]["value"][
            "carCapturedTimestamp"
        ] = datetime.now(UTC).isoformat()
    return V3Response(http, payload, datetime.now(UTC), 100)


def test_no_v2_coordinator_inheritance():
    assert not issubclass(V3CleanCoordinator, AudiDataUpdateCoordinator)


@pytest.mark.asyncio
async def test_first_v3_poll_discovers_one_car_and_learns_climate_get():
    engine, transport, store = engine_for(status())
    cars = await engine.poll()
    assert len(cars) == 1
    assert cars[0].vin == VIN
    assert cars[0].model_family == "q8"
    assert cars[0].climate_state == "off"
    assert store.loads == 1
    assert len(store.writes) >= 1
    assert transport.calls[0] == ("inventory",)
    assert len([c for c in transport.calls if len(c) > 1]) == 1
    assert all(c[1] == "GET" for c in transport.calls if len(c) > 1)
    assert engine.profiles[VIN.lower()].active["climate.status"] == (
        "cariad.climate.status.batch"
    )
    assert "AudiAccount" not in type(engine).__name__


@pytest.mark.asyncio
async def test_stale_status_is_readable_but_not_proven_fresh():
    engine, _, _ = engine_for(status(captured=False))
    await engine.poll()
    profile = engine.profiles[VIN.lower()]
    assert profile.read_results["cariad.climate.status.batch"]["outcome"] == (
        "readable_but_stale"
    )
    assert "climate.status" not in profile.active


@pytest.mark.asyncio
async def test_rate_limit_is_inconclusive_and_no_auto_retry_post():
    engine, transport, _ = engine_for(status(http=429, value="invalid"))
    await engine.poll()
    assert transport.request_count == 1
    assert (
        engine.profiles[VIN.lower()].read_results["cariad.climate.status.batch"][
            "outcome"
        ]
        == "inconclusive"
    )
    assert all(c[1] == "GET" for c in transport.calls if len(c) > 1)


@pytest.mark.asyncio
async def test_start_test_requires_human_result_before_normal_control():
    engine, transport, store = engine_for(
        status(),
        V3Response(202, {"data": {"requestID": "synthetic"}}, datetime.now(UTC)),
    )
    await engine.poll()
    assert not engine.control_enabled(VIN, "start")
    attempt = await engine.test_action(VIN, "start", "cariad.climate.start.stored")
    assert attempt["transport"] == "accepted_unconfirmed"
    assert not engine.control_enabled(VIN, "start")
    assert transport.request_count == 2
    assert transport.calls[-1][1] == "POST"
    assert transport.calls[-1][3]["explicit_action"] is True
    await engine.review_action(VIN, attempt["sequence"], "worked")
    assert engine.control_enabled(VIN, "start")
    assert len(store.writes) >= 3


@pytest.mark.asyncio
async def test_unreviewed_vehicle_settings_control_never_substitutes_bodyless():
    engine, transport, _ = engine_for(status())
    await engine.poll()
    with pytest.raises(ValueError, match="not implemented"):
        await engine.test_action(VIN, "start", "cariad.climate.start.vehicle_settings")
    assert transport.request_count == 1
    assert engine.profiles[VIN.lower()].discovery._active is None


@pytest.mark.asyncio
async def test_import_diagnostics_isolated_and_contains_no_vehicle_identity():
    engine, _, _ = engine_for(status())
    await engine.poll()
    exported = json.dumps(engine.diagnostics())
    assert VIN not in exported
    assert "Bearer" not in exported
    assert "requestID" not in exported


def test_nickname_cannot_spoof_manufacturer_q8_context():
    car = V3Vehicle.from_graphql(
        {
            "vin": VIN,
            "nickname": "Q8",
            "vehicle": {"media": {"longName": "Audi A5"}},
        },
        "DE",
    )
    assert car.model_family == "a5"
    assert car.model_family != "q8"
    assert car.climate_supported is None


@pytest.mark.asyncio
async def test_later_vehicle_restores_saved_candidate():
    engine, transport, store = engine_for(status())
    await engine.poll()
    late = "WAUZZZ4M0MD123457"
    old = DevelopmentProfile(
        engine.registry,
        VehicleContext(
            auth="auth0",
            region="DE",
            vehicle_type="phev",
            model_family="q8",
        ),
        cooldown_seconds=0,
    )
    old.save_candidate("climate", "start", "cariad.climate.start.stored")
    store.records[late.lower()] = old.snapshot()

    async def later():
        return [
            {
                "vin": late,
                "vehicle": {
                    "media": {"longName": "Audi Q8 TFSI e"},
                    "classification": {"driveTrain": "PHEV"},
                },
            }
        ]

    transport.discover_vehicles = later
    await engine.discover()
    assert engine.profiles[late.lower()].draft_selected["climate.start"] == (
        "cariad.climate.start.stored"
    )


@pytest.mark.asyncio
async def test_missing_capture_does_not_schedule_manual_climate_candidates():
    engine, transport, _ = engine_for(status(captured=False))
    await engine.poll()
    assert len([c for c in transport.calls if len(c) > 1]) == 1
    assert "climate.status" not in engine.profiles[VIN.lower()].active


@pytest.mark.asyncio
async def test_historical_sensors_recovered_and_targeted_selection_affects_real_poll():
    """One source response -> two attributes; selected alternate GET -> real poll."""
    stamp = datetime.now(UTC).isoformat()

    def snapshot(*, climate=True, charging=True):
        payload = {}
        if climate:
            payload["climatisation"] = {
                "climatisationStatus": {
                    "value": {
                        "climatisationState": "off",
                        "carCapturedTimestamp": stamp,
                    }
                }
            }
        if charging:
            payload["charging"] = {
                "batteryStatus": {
                    "value": {"currentSOC_pct": 61, "carCapturedTimestamp": stamp}
                },
                "chargingStatus": {
                    "value": {
                        "chargingState": "charging",
                        "carCapturedTimestamp": stamp,
                    }
                },
            }
        return V3Response(200, payload, datetime.now(UTC), 99)

    engine, transport, store = engine_for(
        snapshot(),  # first shared V3 batch
        snapshot(climate=False),  # explicitly requested targeted charging test
        snapshot(charging=False),  # subsequent normal batch (climate only)
        snapshot(climate=False),  # selected targeted charging GET
    )
    await engine.poll()
    car = engine.require_vehicle(VIN)
    profile = engine.profiles[VIN.lower()]
    assert car.readings["stateOfCharge"]["value"] == 61
    assert car.readings["chargingState"]["value"] == "charging"
    assert profile.attribute_routes["stateOfCharge"] == "cariad.selectivestatus.batch"
    assert len([call for call in transport.calls if len(call) > 1]) == 1
    result = await engine.test_attribute_route(
        VIN, "stateOfCharge", "cariad.selectivestatus.targeted"
    )
    assert result["result"] == "verified"
    assert profile.attribute_routes["stateOfCharge"] == "cariad.selectivestatus.batch"
    await engine.save_attribute_candidate(
        VIN, "stateOfCharge", "cariad.selectivestatus.targeted"
    )
    await engine.activate_attribute_route(
        VIN, "stateOfCharge", "cariad.selectivestatus.targeted"
    )
    assert (
        profile.attribute_routes["stateOfCharge"] == "cariad.selectivestatus.targeted"
    )
    await engine.poll()
    requests = [call for call in transport.calls if len(call) > 1]
    assert len(requests) == 4
    assert requests[-1][2].endswith("selectivestatus?jobs=charging")
    assert requests[-1][1] == "GET"
    assert all(call[1] == "GET" for call in requests)
    restored = await store.async_load(engine.registry, {VIN.lower(): car.context})
    assert restored[VIN.lower()].attribute_routes["stateOfCharge"] == (
        "cariad.selectivestatus.targeted"
    )


@pytest.mark.asyncio
async def test_manual_batch_probe_includes_requested_job_even_if_unobserved():
    engine, transport, _ = engine_for(status())
    await engine.poll()
    car = engine.require_vehicle(VIN)
    profile = engine.profiles[VIN.lower()]
    profile.attribute_routes.pop("stateOfCharge", None)
    profile.attribute_evidence.pop("stateOfCharge", None)
    family, path, mappings = engine.status.attribute_request(
        car, profile, "stateOfCharge", "cariad.selectivestatus.batch"
    )
    assert family == "cariad"
    assert "charging" in path.split("jobs=")[-1].split(",")
    assert any("currentSOC_pct" in name for name in mappings)


@pytest.mark.asyncio
async def test_failed_http_probe_does_not_mutate_attribute_state_or_ability():
    engine, transport, _ = engine_for(
        status(),
        V3Response(
            403,
            {
                "charging": {
                    "batteryStatus": {
                        "value": {
                            "currentSOC_pct": 88,
                            "carCapturedTimestamp": datetime.now(UTC).isoformat(),
                        }
                    }
                }
            },
            datetime.now(UTC),
        ),
    )
    await engine.poll()
    result = await engine.test_attribute_route(
        VIN, "stateOfCharge", "cariad.selectivestatus.targeted"
    )
    assert result["result"] == "api_error"
    assert "stateOfCharge" not in engine.require_vehicle(VIN).readings
    with pytest.raises(ValueError, match="verify fresh"):
        await engine.activate_attribute_route(
            VIN, "stateOfCharge", "cariad.selectivestatus.targeted"
        )


@pytest.mark.asyncio
async def test_local_response_detail_isolated_from_storage_diagnostics_and_vehicle_scope():
    engine, transport, store = engine_for()
    await engine.discover()
    profile = engine.profiles[VIN.lower()]
    payload = {
        "status": "accepted",
        "securityToken": "secret-value",
        "settings": {"targetTemperature_C": 15.5},
        "vin": VIN,
    }
    response = V3Response(202, payload, datetime.now(UTC))
    engine._api_record(profile, "test.command", "cariad", "POST", response, VIN)
    detail = engine.engineering_response_for(VIN, "test.command")
    assert detail["available"] and detail["payload"]["status"] == "accepted"
    assert detail["payload"]["securityToken"] == "{SECRET}"
    assert detail["payload"]["settings"]["targetTemperature_C"] == 15.5
    assert detail["payload"]["vin"] == "{VIN}"
    assert "engineering_responses" not in profile.snapshot()

    def contains_private_number(value):
        if isinstance(value, dict):
            return any(contains_private_number(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_private_number(item) for item in value)
        return type(value) in (int, float) and value == 15.5

    for evidence in (profile.snapshot(), engine.api_results_for(VIN)):
        assert "targetTemperature_C" not in json.dumps(evidence)
        assert not contains_private_number(evidence)
    assert (
        profile.api_observations["test.command"]["preview"]
        == "[control response withheld: security]"
    )
    with pytest.raises(ValueError):
        engine.engineering_response_for("WAUZZZ4M0MD999999", "test.command")
    assert len(transport.calls) == 1
    engine._api_record(profile, "test.command", "cariad", "POST", None, VIN)
    assert not engine.engineering_response_for(VIN, "test.command")["available"]


@pytest.mark.asyncio
async def test_engineering_and_restricted_evidence_mask_echoed_configured_secret():
    engine, _, _ = engine_for()
    engine.entry.data = {"password": "private-password-value"}
    await engine.discover()
    profile = engine.profiles[VIN.lower()]
    engine._api_record(
        profile,
        "test.read",
        "cariad",
        "GET",
        V3Response(
            200,
            {"message": "error private-password-value", "capability": "charging"},
            datetime.now(UTC),
        ),
        VIN,
    )
    assert (
        engine.engineering_response_for(VIN, "test.read")["payload"]["message"]
        == "error {SECRET}"
    )
    assert "private-password-value" not in json.dumps(profile.snapshot())
    assert "private-password-value" not in json.dumps(engine.api_results_for(VIN))
    assert "charging" in json.dumps(engine.api_results_for(VIN))


@pytest.mark.asyncio
async def test_engineering_execution_history_pairs_actual_request_and_response():
    engine, _, _ = engine_for()
    await engine.discover()
    profile = engine.profiles[VIN.lower()]
    from datetime import timedelta

    now = datetime.now(UTC)
    for i in range(2):
        engine._api_record(
            profile,
            "test.command",
            "cariad",
            "POST",
            V3Response(
                202,
                {"value": i},
                now + timedelta(seconds=i),
                request={
                    "method": "POST",
                    "url": "/vehicles/" + VIN,
                    "body": {"spin": "1234", "target": i},
                },
            ),
            VIN,
        )
    rows = engine.engineering_history_for(VIN)
    assert [row["payload"]["value"] for row in rows] == [1, 0]
    assert rows[0]["request"]["payload"]["body"] == {"spin": "{SPIN}", "target": 1}
    assert VIN not in json.dumps(rows)
    assert "engineering_history" not in profile.snapshot()


@pytest.mark.asyncio
async def test_diagnostics_cover_all_product_capabilities_without_private_route_names():
    engine, _, _ = engine_for(status())
    await engine.poll()
    profile = engine.profiles[VIN.lower()]
    from custom_components.audiconnect.v3.api_observations import (
        record_for,
        save_record,
    )

    for operation in (
        "cariad.discovery.full",
        "cariad.discovery.batterySupport",
        "private_custom_route",
    ):
        save_record(
            profile,
            operation,
            record_for(
                family="cariad", method="GET", http_status=207, payload={}, vin=VIN
            ),
        )
    snapshot = engine.diagnostics()["vehicles"][0]
    evidence = snapshot["capability_evidence"]
    assert {row["capability"] for row in evidence["capabilities"]} >= set(
        engine.registry.capabilities
    )
    from custom_components.audiconnect.v3.transport import IDENTITY_OPERATIONS

    assert all(
        row["operation"] in engine.registry.operations
        or row["operation"] in IDENTITY_OPERATIONS
        for row in evidence["operations"]
    )
    names = {row["operation"] for row in snapshot["climate"]["last_api_results"]}
    assert {
        "cariad.discovery.full",
        "cariad.discovery.batterySupport",
        "custom_or_discovery_route",
    } <= names
    encoded = json.dumps(snapshot)
    assert "private_custom_route" not in encoded and VIN not in encoded
    assert "engineering_history" not in encoded
    assert all(
        "preview" not in row and "fields" not in row
        for row in snapshot["climate"]["last_api_results"]
    )
    from custom_components.audiconnect.v3.historical_catalog import CANONICAL_ATTRIBUTES

    assert set(evidence["attributes"]) == set(CANONICAL_ATTRIBUTES)
    for job, historical in snapshot["historical_schema_evidence"][
        "fields_by_job"
    ].items():
        current = snapshot["job_schema_evidence"].get(job, {}).get("fields", [])
        assert not any(row in current for row in historical)


@pytest.mark.asyncio
async def test_inventory_evidence_is_per_vehicle_and_not_a_physical_command():
    from custom_components.audiconnect.v3.transport import INVENTORY_OPERATION
    from custom_components.audiconnect.v3.capability_status import build_status_report

    engine, transport, _ = engine_for()
    other = "WAUZZZ4M0MD123457"

    async def inventory():
        transport.last_inventory_metadata = V3Response(
            200,
            None,
            datetime.now(UTC),
            request={
                "method": "POST",
                "url": "https://example.invalid/vgql/v1/graphql",
                "body": {"query": "query vehicleList { userVehicles { vin } }"},
            },
        )
        return [
            {
                "vin": VIN,
                "nickname": "private nickname",
                "vehicle": {"media": {"shortName": "Q8"}},
            },
            {
                "vin": other,
                "nickname": "other private nickname",
                "vehicle": {"media": {"shortName": "A6"}},
            },
        ]

    transport.discover_vehicles = inventory
    await engine.discover()
    detail = engine.engineering_response_for(VIN, INVENTORY_OPERATION)
    assert detail["payload"]["data"]["userVehicles"] == [
        {
            "vin": "{VIN}",
            "nickname": "{PERSONAL}",
            "vehicle": {"media": {"shortName": "Q8"}},
        }
    ]
    assert other not in json.dumps(detail) and "A6" not in json.dumps(detail)
    assert detail["request"]["payload"]["method"] == "POST"
    profile = engine.profiles[VIN.lower()]
    assert "private nickname" not in json.dumps(profile.snapshot())
    report = build_status_report(engine.vehicles[VIN.lower()], profile)
    row = next(x for x in report["operations"] if x["operation"] == INVENTORY_OPERATION)
    assert row["read_only"] and row["physical"] == "not_applicable"
    assert "accepted_not_physically_verified" not in row["attention"]


@pytest.mark.asyncio
async def test_accepted_climate_start_and_immediate_stop_use_real_command_owner():
    from homeassistant.components.climate import HVACMode
    from custom_components.audiconnect.v3.entities import V3ClimateEntity

    engine, transport, store = engine_for(
        status(),
        V3Response(200, {}, datetime.now(UTC)),
        V3Response(200, {}, datetime.now(UTC)),
    )
    await engine.poll()
    profile = engine.profiles[VIN.lower()]
    for action, route in (
        ("start", "cariad.climate.start.stored"),
        ("stop", "cariad.climate.stop"),
    ):
        profile.control_results[route] = "worked"
        profile.choose_working("climate", action, route)
    car = engine.vehicles[VIN.lower()]
    climate = V3ClimateEntity(
        SimpleNamespace(engine=engine, last_update_success=True), car
    )
    climate.async_write_ha_state = lambda: None
    assert climate.hvac_mode == HVACMode.OFF
    await climate.async_turn_on()
    assert climate.hvac_mode == HVACMode.HEAT_COOL
    assert climate.extra_state_attributes["state_source"] == "command_pending"
    assert car.climate_state == "off"
    assert profile.last_command.state == "accepted_unconfirmed"
    await climate.async_turn_off()
    assert climate.hvac_mode == HVACMode.OFF
    assert climate.extra_state_attributes["state_source"] == "command_pending"
    assert [call[1] for call in transport.calls if len(call) > 1] == [
        "GET",
        "POST",
        "POST",
    ]
    assert (
        len([r for r in profile.command_journal if r.origin == "home_assistant"]) == 2
    )
    with pytest.raises(RuntimeError, match="cooldown"):
        await engine.send_control(VIN, "start")
    assert transport.request_count == 3


@pytest.mark.asyncio
async def test_direct_command_response_uses_actual_vehicle_status():
    from datetime import timedelta
    from homeassistant.components.climate import HVACMode
    from custom_components.audiconnect.v3.entities import V3ClimateEntity

    engine, transport, _ = engine_for(status())
    await engine.poll()
    profile = engine.profiles[VIN.lower()]
    route = "cariad.climate.start.stored"
    profile.control_results[route] = "worked"
    profile.choose_working("climate", "start", route)
    future = datetime.now(UTC) + timedelta(seconds=1)
    transport._responses.append(
        V3Response(
            200,
            {
                "climatisation": {
                    "climatisationStatus": {
                        "value": {
                            "climatisationState": "cooling",
                            "carCapturedTimestamp": future.isoformat(),
                        }
                    }
                }
            },
            future,
        )
    )
    await engine.send_control(VIN, "start")
    car = engine.vehicles[VIN.lower()]
    entity = V3ClimateEntity(
        SimpleNamespace(engine=engine, last_update_success=True), car
    )
    assert entity.hvac_mode == HVACMode.HEAT_COOL
    assert entity.hvac_action.value == "cooling"
    assert entity.extra_state_attributes["state_source"] == "vehicle"
    assert profile.last_command.state == "verified"


@pytest.mark.asyncio
async def test_standalone_schema_evidence_and_discovery_export_without_trip_values():
    registry = CapabilityRegistry.from_json_file(
        CATALOG.parents[2] / "custom_components/audiconnect/v3/full_catalog.json"
    )
    engine = V3Engine(
        SimpleNamespace(),
        SimpleNamespace(entry_id="example"),
        registry,
        auth=FakeAuth(),
        transport=FakeTransport([]),
        storage=FakeStore(),
    )
    await engine.discover()
    profile = engine.profiles[VIN.lower()]
    operation = "cariad.mobility.status.lastTrip"
    engine._api_record(
        profile,
        operation,
        "cariad",
        "GET",
        V3Response(
            200,
            {
                "data": {
                    "tripEndTimestamp": "2026-01-01T00:00:00Z",
                    "mileage_km": 123.456,
                    "tripID": "private-trip",
                }
            },
            datetime.now(UTC),
        ),
        VIN,
    )
    snapshot = engine.diagnostics()["vehicles"][0]
    schema = snapshot["job_schema_evidence"][operation]
    assert any(row["path"] == "data.mileage_km" for row in schema["fields"])
    assert (
        snapshot["discovery_progress"]["standalone_schema"][operation]["field_count"]
        > 0
    )
    assert snapshot["discovery_progress"]["control_evidence_scope"].startswith(
        "stored_vehicle_context"
    )
    assert "123.456" not in json.dumps(snapshot)
    assert "private-trip" not in json.dumps(snapshot)


@pytest.mark.asyncio
async def test_optional_vehicle_render_failure_does_not_break_identity_and_retries_follow_fresh_inventory():
    engine, transport, _ = engine_for()
    from unittest.mock import AsyncMock

    transport.discover_vehicle_images = AsyncMock(side_effect=RuntimeError("denied"))
    await engine.discover()
    car = engine.vehicles[VIN.lower()]
    assert car.model_family == "q8"
    assert car.image_status == "inconclusive"
    await engine.discover()
    await engine.discover()
    await engine.discover()
    assert transport.discover_vehicle_images.await_count == 4
    assert car.model_family == "q8"


@pytest.mark.asyncio
async def test_optional_vehicle_render_url_is_not_exported_in_diagnostics():
    engine, transport, _ = engine_for()
    from unittest.mock import AsyncMock

    url = "https://mediaservice.audi.com/render/example.png"
    transport.discover_vehicle_images = AsyncMock(return_value={VIN.lower(): url})
    await engine.discover()
    car = engine.vehicles[VIN.lower()]
    assert car.image_url == url
    assert car.image_status == "observed"
    assert url not in json.dumps(engine.diagnostics())


@pytest.mark.asyncio
async def test_model_context_refinement_preserves_vin_trip_snapshots():
    from custom_components.audiconnect.v3.trips import observe_cariad_trip
    from unittest.mock import AsyncMock

    engine, transport, _ = engine_for()
    transport.discover_vehicles = AsyncMock(
        side_effect=[
            [{"vin": VIN}],
            [
                {
                    "vin": VIN,
                    "vehicle": {
                        "media": {"longName": "Audi Q8 TFSI e"},
                        "classification": {"driveTrain": "PHEV"},
                    },
                }
            ],
        ]
    )
    await engine.discover()
    car = engine.vehicles[VIN.lower()]
    assert car.model_family == ""
    observe_cariad_trip(
        car,
        "cariad.mobility.status.lastTrip",
        {"data": {"tripEndTimestamp": "2026-01-01T00:00:00Z", "mileage_km": 42}},
    )
    engine.status._trip_poll_at[VIN.lower()] = 123
    await engine.discover()
    assert car is engine.vehicles[VIN.lower()]
    assert car.model_family == "q8"
    assert car.trips["last_trip"]["mileage"] == 42
    assert VIN.lower() not in engine.status._trip_poll_at


@pytest.mark.asyncio
async def test_missing_identity_does_not_automatically_run_research_queries():
    from custom_components.audiconnect.v3.transport import (
        GARAGE_OPERATION,
        INVENTORY_OPERATION,
    )
    from unittest.mock import AsyncMock

    engine, transport, _ = engine_for()
    other = "WAUZZZ4M0MD123457"

    async def discover():
        transport.last_inventory_metadata = V3Response(200, None, datetime.now(UTC))
        return [
            {
                "vin": VIN,
                "vehicle": {"core": None, "media": None, "classification": None},
            }
        ]

    transport.discover_vehicles = discover
    transport.test_identity_query = AsyncMock(
        return_value=V3Response(
            200,
            {
                "data": [
                    {"vin": VIN, "model": "Audi Q8", "modelYear": 2022},
                    {"vin": other, "model": "Other"},
                ]
            },
            datetime.now(UTC),
        )
    )
    await engine.discover()
    car = engine.require_vehicle(VIN)
    assert not car.model
    transport.test_identity_query.assert_not_awaited()
    profile = engine.profiles[VIN.lower()]
    assert INVENTORY_OPERATION in profile.api_observations
    result = await engine.test_identity_operation(VIN, GARAGE_OPERATION)
    assert result["model_present"] and result["year_present"]
    assert not car.model and not car.model_year
    assert GARAGE_OPERATION in profile.api_observations
    assert list(engine.vehicles) == [VIN.lower()]
    assert other not in json.dumps(engine.diagnostics())
    transport.test_identity_query.assert_awaited_once_with(GARAGE_OPERATION)


@pytest.mark.asyncio
async def test_older_targeted_read_keeps_current_attribute_and_evidence_aligned():
    from datetime import timedelta

    engine, transport, store = engine_for()
    await engine.discover()
    car = engine.require_vehicle(VIN)
    profile = engine.profiles[VIN.lower()]
    now = datetime.now(UTC)
    path = "charging.batteryStatus.value.currentSOC_pct"
    fresh_payload = {
        "charging": {
            "batteryStatus": {
                "value": {"currentSOC_pct": 70, "carCapturedTimestamp": now.isoformat()}
            }
        }
    }
    stale_payload = {
        "charging": {
            "batteryStatus": {
                "value": {
                    "currentSOC_pct": 49,
                    "carCapturedTimestamp": (now - timedelta(hours=3)).isoformat(),
                }
            }
        }
    }
    from custom_components.audiconnect.v3.attribute_runtime import observe_read_only

    observe_read_only(car, profile, fresh_payload, now)
    original = dict(profile.attribute_evidence["stateOfCharge"])
    response = V3Response(200, stale_payload, now, 50)
    result = engine.status.record_attribute_response(
        car,
        profile,
        "stateOfCharge",
        "cariad.selectivestatus.targeted",
        [path],
        response,
    )
    assert result["result"] == "readable_but_stale"
    assert car.readings["stateOfCharge"]["value"] == 70
    assert profile.attribute_evidence["stateOfCharge"] == original
    assert (
        profile.attribute_route_evidence["stateOfCharge"][
            "cariad.selectivestatus.targeted"
        ]["outcome"]
        == "readable_but_stale"
    )


@pytest.mark.asyncio
async def test_targeted_external_power_uses_same_meaningful_unavailable_state_as_batch():
    engine, transport, store = engine_for()
    await engine.discover()
    car = engine.require_vehicle(VIN)
    profile = engine.profiles[VIN.lower()]
    from custom_components.audiconnect.v3.historical_catalog import ATTRIBUTES

    path = ATTRIBUTES["externalPower"]["paths"][0]
    # Build a matching envelope from the canonical path, not a separate fixture mapping.
    now = datetime.now(UTC)
    payload = {}
    node = payload
    for name in path.split(".")[:-1]:
        node[name] = {}
        node = node[name]
    node[path.split(".")[-1]] = "unavailable"
    node["carCapturedTimestamp"] = now.isoformat()
    result = engine.status.record_attribute_response(
        car,
        profile,
        "externalPower",
        "cariad.selectivestatus.targeted",
        [path],
        V3Response(200, payload, now),
    )
    assert result["result"] == "verified"
    assert car.readings["externalPower"]["value"] == "unavailable"


@pytest.mark.asyncio
async def test_selected_climate_mapping_is_the_single_native_state_source():
    engine, _, _ = engine_for(
        status(value="off"),
        status(value="heating"),
        status(value="off"),
        status(value="heating"),
    )
    await engine.poll()
    car = engine.require_vehicle(VIN)
    assert car.climate_state == car.readings["climatisationState"]["value"] == "off"
    route = "cariad.selectivestatus.targeted"
    result = await engine.test_attribute_route(VIN, "climatisationState", route)
    assert result["value"] == "heating" and car.climate_state == "off"
    await engine.activate_attribute_route(VIN, "climatisationState", route)
    await engine.poll()
    assert car.climate_state == car.readings["climatisationState"]["value"] == "heating"
    assert car.climate_source == "cariad.status.climatisation"


@pytest.mark.asyncio
async def test_targeted_jobs_do_not_overwrite_each_others_api_evidence():
    stamp = datetime.now(UTC).isoformat()
    charging = V3Response(
        200,
        {
            "charging": {
                "batteryStatus": {
                    "value": {"currentSOC_pct": 61, "carCapturedTimestamp": stamp}
                }
            }
        },
        datetime.now(UTC),
    )
    engine, _, _ = engine_for(status(), charging, status(value="heating"))
    await engine.poll()
    route = "cariad.selectivestatus.targeted"
    first = await engine.test_attribute_route(VIN, "stateOfCharge", route)
    second = await engine.test_attribute_route(VIN, "climatisationState", route)
    assert first["operation"] == "cariad.status.charging"
    assert second["operation"] == "cariad.status.climatisation"
    profile = engine.profiles[VIN.lower()]
    assert (
        first["operation"] in profile.api_observations
        and second["operation"] in profile.api_observations
    )
    assert route not in profile.api_observations


@pytest.mark.asyncio
async def test_engineering_review_waits_for_in_flight_dispatch():
    import asyncio

    engine, transport, _ = engine_for(
        status(),
        V3Response(202, {"data": {"requestID": "synthetic"}}, datetime.now(UTC)),
    )
    await engine.poll()
    entered, release = asyncio.Event(), asyncio.Event()
    original_request = transport.request

    async def delayed_request(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original_request(*args, **kwargs)

    transport.request = delayed_request
    dispatch = asyncio.create_task(
        engine.test_action(VIN, "start", "cariad.climate.start.stored")
    )
    await asyncio.wait_for(entered.wait(), 2)
    profile = engine.profiles[VIN.lower()]
    review = asyncio.create_task(
        engine.review_action(VIN, profile.discovery._active.sequence, "worked")
    )
    try:
        await asyncio.sleep(0)
        assert not review.done()
        assert profile.discovery._active is not None
    finally:
        release.set()
        await asyncio.gather(dispatch, review)
    assert profile.discovery._active is None
    assert engine.control_enabled(VIN, "start")
    assert transport.request_count == 2


@pytest.mark.asyncio
async def test_queued_engineering_command_rechecks_vehicle_after_lock():
    import asyncio

    engine, transport, _ = engine_for(status())
    await engine.poll()
    profile = engine.profiles[VIN.lower()]

    def unavailable(vin):
        raise ValueError("Vehicle no longer available")

    async with engine.commands.exclusive():
        task = asyncio.create_task(
            engine.test_action(VIN, "start", "cariad.climate.start.stored")
        )
        await asyncio.sleep(0)
        engine.commands.require_vehicle = unavailable
    with pytest.raises(ValueError, match="Vehicle no longer available"):
        await task
    assert transport.request_count == 1
    assert profile.discovery._active is None


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["home_assistant", "workbench"])
async def test_pre_dispatch_storage_failure_rolls_back_without_mutation(origin):
    engine, transport, store = engine_for(
        status(), V3Response(200, {}, datetime.now(UTC))
    )
    await engine.poll()
    profile = engine.profiles[VIN.lower()]
    route = "cariad.climate.start.stored"
    profile.control_results[route] = "worked"
    profile.choose_working("climate", "start", route)
    before = profile.snapshot()
    save = store.async_save

    async def fail_save(profiles):
        raise OSError("Storage unavailable")

    async def dispatch():
        if origin == "workbench":
            return await engine.test_action(VIN, "start", route)
        return await engine.send_control(VIN, "start")

    store.async_save = fail_save
    with pytest.raises(OSError, match="Storage unavailable"):
        await dispatch()
    assert profile.snapshot() == before
    assert transport.request_count == 1
    store.async_save = save
    await dispatch()
    assert transport.request_count == 2


@pytest.mark.asyncio
async def test_schema_evidence_excludes_echoed_spin_in_field_names():
    from custom_components.audiconnect.const import CONF_SPIN
    from custom_components.audiconnect.v3.transport import INVENTORY_OPERATION

    engine, _, _ = engine_for()
    engine.entry.data = {CONF_SPIN: "9387"}
    await engine.discover()
    profile = engine.profiles[VIN.lower()]
    payload = {
        "data": {"userVehicles": [{"vehicle": {"field9387": 1, "modelYear": 2020}}]}
    }
    engine._api_record(
        profile,
        INVENTORY_OPERATION,
        "graphql",
        "POST",
        V3Response(200, payload, datetime.now(UTC)),
        VIN,
    )
    schema = profile.job_schema["inventory"]["fields"]
    assert any("modelYear" in row["path"] for row in schema)
    assert all("9387" not in row["path"] for row in schema)


@pytest.mark.asyncio
async def test_execution_review_is_private_persistent_and_non_authorizing():
    engine, transport, store = engine_for()
    engine.entry.data = {"password": "private-password-value"}
    await engine.discover()
    profile = engine.profiles[VIN.lower()]
    now = datetime.now(UTC)
    engine._api_record(
        profile, "test.read", "cariad", "GET", V3Response(200, {"value": 7}, now), VIN
    )
    at = profile.api_observations["test.read"]["at"]
    before = dict(profile.active)
    await engine.review_execution(
        VIN, "test.read", at, "worked", "checked private-password-value"
    )
    assert profile.active == before and profile.control_results == {}
    assert len(transport.calls) == 1
    assert profile.execution_reviews[0]["comment"] == "checked {SECRET}"
    restored = restore_profile(
        engine.registry, profile.discovery.context, profile.snapshot()
    )
    assert restored.execution_reviews == profile.execution_reviews
    assert "private-password-value" not in json.dumps(profile.snapshot())
    with pytest.raises(ValueError, match="no longer retained"):
        await engine.review_execution(VIN, "unknown", at, "worked", "not evidence")


@pytest.mark.asyncio
async def test_discard_unused_read_draft_preserves_tested_definitions():
    engine, transport, _ = engine_for(status())
    await engine.poll()
    profile = engine.profiles[VIN.lower()]
    route = {
        "id": "user.read.soc",
        "attribute": "stateOfCharge",
        "family": "cariad",
        "method": "GET",
        "path": "/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=charging",
        "response_path": "charging.batteryStatus.value.currentSOC_pct",
    }
    await engine.add_attribute_route(VIN, route)
    await engine.save_attribute_candidate(VIN, "stateOfCharge", route["id"])
    await engine.discard_unused_route(VIN, route["id"])
    assert route["id"] not in profile.attribute_custom
    assert "stateOfCharge" not in profile.attribute_drafts
    await engine.add_attribute_route(VIN, route)
    profile.attribute_route_evidence["stateOfCharge"] = {
        route["id"]: {"outcome": "failed"}
    }
    with pytest.raises(ValueError, match="Tested or active"):
        await engine.discard_unused_route(VIN, route["id"])
    assert route["id"] in profile.attribute_custom
    assert transport.request_count == 1


@pytest.mark.asyncio
async def test_reviewed_identity_activation_uses_matching_fresh_oem_metadata():
    from unittest.mock import AsyncMock
    from custom_components.audiconnect.v3.transport import GARAGE_OPERATION

    engine, transport, store = engine_for()

    async def incomplete():
        return [{"vin": VIN, "vehicle": {"core": None, "media": None}}]

    transport.discover_vehicles = incomplete
    transport.test_identity_query = AsyncMock(
        return_value=V3Response(
            200,
            {"data": [{"vin": VIN, "model": "Audi Q8", "modelYear": 2022}]},
            datetime.now(UTC),
        )
    )
    await engine.discover()
    car = engine.require_vehicle(VIN)
    profile = engine.profiles[VIN.lower()]
    car.trips["last_trip"] = {"mileage": 42}
    candidate = await engine.test_identity_operation(VIN, GARAGE_OPERATION)
    assert candidate["can_activate"] and not car.model
    result = await engine.test_identity_operation(VIN, GARAGE_OPERATION, activate=True)
    assert result["activated"] and car.model == "Audi Q8" and car.model_year == "2022"
    assert car.identity_operation == GARAGE_OPERATION and not car.identity_restored
    assert car.trips["last_trip"]["mileage"] == 42
    assert profile.manufacturer_identity["operation"] == GARAGE_OPERATION
    assert GARAGE_OPERATION in profile.api_observations
    assert GARAGE_OPERATION in profile.engineering_responses
    assert store.records[VIN.lower()]["manufacturer_identity"]["model"] == "Audi Q8"
    assert profile.discovery.context == car.context
    transport.test_identity_query.return_value = V3Response(
        200,
        {"data": [{"vin": "WAUZZZ4M0MD123457", "model": "Other Audi"}]},
        datetime.now(UTC),
    )
    with pytest.raises(ValueError, match="No current matching"):
        await engine.test_identity_operation(VIN, GARAGE_OPERATION, activate=True)
    assert car.model == "Audi Q8"


@pytest.mark.asyncio
async def test_adopted_identity_is_retained_without_repeating_experimental_query():
    from unittest.mock import AsyncMock
    from custom_components.audiconnect.v3.transport import GARAGE_OPERATION

    engine, transport, store = engine_for()

    async def incomplete():
        return [{"vin": VIN, "vehicle": {"media": None, "core": None}}]

    transport.discover_vehicles = incomplete
    transport.test_identity_query = AsyncMock(
        return_value=V3Response(
            200,
            {"data": [{"vin": VIN, "model": "Audi Q8", "modelYear": 2022}]},
            datetime.now(UTC),
        )
    )
    await engine.discover()
    transport.test_identity_query.assert_not_awaited()
    await engine.test_identity_operation(VIN, GARAGE_OPERATION, activate=True)
    transport.test_identity_query.reset_mock()
    await engine.discover()
    car = engine.require_vehicle(VIN)
    assert car.model == "Audi Q8" and car.identity_restored
    assert car.identity_operation == GARAGE_OPERATION
    transport.test_identity_query.assert_not_awaited()
    assert GARAGE_OPERATION in engine.profiles[VIN.lower()].api_observations


@pytest.mark.asyncio
async def test_guided_command_automatically_confirms_only_fresh_changed_readback():
    from types import SimpleNamespace as NS
    from custom_components.audiconnect.v3.runtime import catalog_path
    from datetime import timedelta

    engine, transport, store = engine_for()
    engine.registry = CapabilityRegistry.from_json_file(catalog_path())
    engine.auth.service = NS(_spin=None)
    await engine.discover()
    car = engine.require_vehicle(VIN)
    profile = engine.profiles[VIN.lower()]
    car.readings["climatisationState"] = {
        "value": "off",
        "captured": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    }
    stamp = datetime.now(UTC) + timedelta(seconds=1)
    transport._responses.append(
        V3Response(
            202,
            {
                "climatisation": {
                    "climatisationStatus": {
                        "value": {
                            "climatisationState": "heating",
                            "carCapturedTimestamp": stamp.isoformat(),
                        }
                    }
                }
            },
            stamp,
        )
    )
    result = await engine.approved_control_discovery(
        VIN, "start", "cariad.climate.start.stored", approval="non_spin", guided=True
    )
    assert result["physical_result"] == "verified"
    assert profile.discovery._active is None
    assert profile.control_results["cariad.climate.start.stored"] == "worked"
    assert profile.active["climate.start"] == "cariad.climate.start.stored"
    assert profile.command_journal[-1].state == "verified"
    assert transport.request_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first_status,first_payload,expected_calls",
    [
        (405, {"error": {"code": "notSupported"}}, 2),
        (410, {"error": {"code": "unsupported"}}, 2),
        (405, {}, 1),
        (502, {}, 1),
        (202, {"data": {"requestID": "test"}}, 1),
    ],
)
async def test_guided_charging_alternative_only_after_definite_rejection(
    first_status, first_payload, expected_calls
):
    from types import SimpleNamespace as NS
    from custom_components.audiconnect.v3.runtime import catalog_path

    engine, transport, store = engine_for()
    engine.registry = CapabilityRegistry.from_json_file(catalog_path())
    engine.auth.service = NS(_spin=None)
    await engine.discover()
    car = engine.require_vehicle(VIN)
    car.advertised_capabilities.add("charging")
    profile = engine.profiles[VIN.lower()]
    transport._responses.extend(
        [
            V3Response(first_status, first_payload, datetime.now(UTC)),
            V3Response(202, {"data": {"requestID": "second"}}, datetime.now(UTC)),
        ]
    )
    result = await engine.approved_control_discovery(
        VIN,
        "start",
        "cariad.charging.start",
        capability="charging",
        approval="non_spin",
        guided=True,
    )
    assert transport.request_count == expected_calls
    assert profile.discovery._active is not None
    if expected_calls == 2:
        assert result["operation"] == "cariad.charging.start.combined"
        assert profile.discovery.history[0].result == "rejected"
        assert profile.command_journal[0].state == "rejected"
        assert result["previous_attempt"]["status"] == first_status
        assert not engine.control_enabled(VIN, "start", "charging")
        restored = restore_profile(
            engine.registry, car.context, store.records[VIN.lower()], cooldown_seconds=0
        )
        assert restored.discovery.history[0].result == "rejected"
    else:
        assert result["operation"] == "cariad.charging.start"
        assert "previous_attempt" not in result


@pytest.mark.asyncio
async def test_golden_configure_discover_use_restart_without_workbench():
    """Full reviewed catalog with synthetic OEM transport; no real vehicle contact."""
    from unittest.mock import Mock
    from types import SimpleNamespace as NS
    from datetime import timedelta
    from custom_components.audiconnect.v3.runtime import catalog_path
    from custom_components.audiconnect.v3.ha_platforms import setup

    registry = CapabilityRegistry.from_json_file(catalog_path())
    store = FakeStore()
    auth = FakeAuth()
    auth.service = NS(_spin=None)

    class Transport(FakeTransport):
        charging = False

        async def request(self, family, method, path, **kwargs):
            self.calls.append((family, method, path, kwargs))
            self.request_count += 1
            stamp = datetime.now(UTC) + timedelta(milliseconds=10)
            if method == "POST":
                assert path.endswith("/charging/start")
                assert store.records[VIN.lower()]["last_command"]["state"] == "pending"
                self.charging = True
            else:
                assert method == "GET"
            value = "charging" if self.charging else "readyForCharging"
            return V3Response(
                200,
                {
                    "charging": {
                        "chargingStatus": {
                            "value": {
                                "chargingState": value,
                                "carCapturedTimestamp": stamp.isoformat(),
                            }
                        },
                        "batteryStatus": {
                            "value": {
                                "currentSOC_pct": 65,
                                "carCapturedTimestamp": stamp.isoformat(),
                            }
                        },
                    },
                    "climatisation": {
                        "climatisationStatus": {
                            "value": {
                                "climatisationState": "off",
                                "carCapturedTimestamp": stamp.isoformat(),
                            }
                        }
                    },
                },
                stamp,
            )

    transport = Transport([])
    engine = V3Engine(
        NS(),
        NS(entry_id="golden"),
        registry,
        auth=auth,
        transport=transport,
        storage=store,
    )
    await engine.poll()
    assert all(call[1] == "GET" for call in transport.calls if len(call) > 1)
    car = engine.require_vehicle(VIN)
    assert car.model == "Audi Q8 TFSI e"
    assert engine.control_enabled(VIN, "start", "charging")
    assert not engine.profiles[VIN.lower()].control_results

    def entities_for(engine):
        result = []
        coordinator = NS(
            engine=engine, async_add_listener=lambda cb: None, last_update_success=True
        )
        entry = NS(
            entry_id="golden",
            runtime_data=NS(v3=engine, coordinator=coordinator),
            async_on_unload=lambda cb: None,
        )
        for platform in (
            "sensor",
            "switch",
            "climate",
            "binary_sensor",
            "button",
            "lock",
            "number",
            "select",
            "device_tracker",
        ):
            setup(platform, entry, result.extend)
        return {entity.unique_id: entity for entity in result}

    entities = entities_for(engine)
    model_key, switch_key = (
        VIN.lower() + "_sensor_model",
        VIN.lower() + "_switch_charging",
    )
    assert entities[model_key].native_value == "Audi Q8 TFSI e"
    switch = entities[switch_key]
    assert switch.available and switch.is_on is False
    switch.async_write_ha_state = Mock()
    await switch.async_turn_on()
    assert switch.is_on is True
    assert engine.profiles[VIN.lower()].last_command.state == "verified"
    assert sum(call[1] == "POST" for call in transport.calls if len(call) > 1) == 1

    restarted = V3Engine(
        NS(),
        NS(entry_id="golden"),
        registry,
        auth=auth,
        transport=transport,
        storage=store,
    )
    await restarted.poll()
    restored_entities = entities_for(restarted)
    assert restored_entities[model_key].native_value == "Audi Q8 TFSI e"
    assert restored_entities[switch_key].is_on is True
    assert sum(call[1] == "POST" for call in transport.calls if len(call) > 1) == 1
    assert restarted.profiles[VIN.lower()].last_command.state == "verified"


def test_identity_refresh_is_periodic_and_quota_aware():
    from custom_components.audiconnect.v3.status_engine import identity_refresh_due

    car = V3Vehicle(VIN, "Audi", "", "", "DE")
    cars = {VIN.lower(): car}
    assert not identity_refresh_due(cars, 3599, 100)
    assert identity_refresh_due(cars, 3600, 100)
    assert not identity_refresh_due(cars, 3600, 12)
    car.model, car.model_family, car.model_year, car.car_type = (
        "Audi Q8",
        "q8",
        "2022",
        "phev",
    )
    car.image_url = "https://mediaservice.audi.com/render/example.png"
    assert not identity_refresh_due(cars, 86399, 100)
    assert identity_refresh_due(cars, 86400, 100)
    car.identity_restored = True
    assert identity_refresh_due(cars, 3600, 100)


@pytest.mark.asyncio
async def test_identity_image_waits_for_real_model_then_caches_across_restart():
    from unittest.mock import AsyncMock
    from custom_components.audiconnect.v3.identity_cache import apply_cached_identity

    engine, transport, store = engine_for()
    original = transport.discover_vehicles

    async def incomplete():
        return [{"vin": VIN, "vehicle": {"media": None, "core": None}}]

    url = "https://mediaservice.audi.com/render/example.png"
    transport.discover_vehicle_images = AsyncMock(return_value={VIN.lower(): url})
    transport.discover_vehicles = incomplete
    await engine.discover()
    transport.discover_vehicle_images.assert_not_awaited()
    transport.discover_vehicles = original
    await engine.discover()
    car = engine.require_vehicle(VIN)
    assert car.model and car.image_url == url
    transport.discover_vehicle_images.assert_awaited_once()
    cached = store.records[VIN.lower()]["manufacturer_identity"]
    assert cached["image_url"] == url
    restored = V3Vehicle(VIN, "Audi vehicle", "", "", "DE")
    apply_cached_identity(restored, cached)
    assert restored.identity_restored and restored.image_url == url
    transport.discover_vehicles = incomplete
    await engine.discover()
    assert car.model and car.image_url == url
    transport.discover_vehicle_images.assert_awaited_once()
    assert url not in json.dumps(engine.diagnostics())

    async def load_identity(key, country):
        return store.records[key]["manufacturer_identity"]

    store.async_identity = load_identity
    restarted = V3Engine(
        SimpleNamespace(),
        SimpleNamespace(entry_id="example"),
        engine.registry,
        auth=engine.auth,
        transport=transport,
        storage=store,
    )
    await restarted.discover()
    restored_car = restarted.require_vehicle(VIN)
    assert restored_car.identity_restored
    assert restored_car.model == car.model and restored_car.image_url == url
    transport.discover_vehicle_images.assert_awaited_once()


@pytest.mark.asyncio
async def test_diagnostics_distinguish_poll_attempts_quota_and_operation_evidence():
    engine, transport, _ = engine_for(status())
    transport.remaining_calls = None
    await engine.poll()
    snapshot = engine.diagnostics()
    assert snapshot["poll_attempt_count"] == 1
    assert snapshot["requests"] == transport.request_count
    assert snapshot["requests_scope"] == "current_transport_runtime"
    assert snapshot["last_poll_scope"] == "native_cloud_reachability"
    assert snapshot["api_evidence_scope"] == (
        "latest_per_operation_including_restored_evidence"
    )
    assert snapshot["quota_remaining"] is None
    assert snapshot["quota_scope"] == "unknown_no_header"
    transport.remaining_calls = 40
    assert (
        engine.diagnostics()["quota_scope"] == "conservative_estimate_since_last_header"
    )
