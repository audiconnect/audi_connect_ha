"""Active clean-runtime replacements for retired pilot architecture checks."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from custom_components.audiconnect.v3.entities import V3ClimateEntity
from custom_components.audiconnect.v3.runtime import V3_DEFAULT, V3_ENABLED
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3.coordinator_clean import V3CleanCoordinator
from custom_components.audiconnect.coordinator import AudiDataUpdateCoordinator

VIN = "WAUZZZ4M0MD123456"


def test_clean_runtime_preserves_option_and_identity():
    assert V3_DEFAULT == "v2" and V3_ENABLED == "v3_climate"
    assert not issubclass(V3CleanCoordinator, AudiDataUpdateCoordinator)
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    coordinator = NS(engine=NS(control_enabled=lambda *args: False))
    entity = V3ClimateEntity(coordinator, car)
    assert entity.unique_id == VIN.lower() + "_climate_climatisation"
    assert entity.hvac_mode is None


def test_stale_climate_readback_is_never_reported_as_current():
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    coordinator = NS(engine=NS(control_enabled=lambda *args: False))
    entity = V3ClimateEntity(coordinator, car)
    now = datetime.now(UTC)
    car.set_climate(
        "off",
        (now - timedelta(hours=2)).isoformat(),
        route="test",
        observed_at=now,
        http_status=200,
    )
    assert entity.hvac_mode.value == "off"
    assert entity.hvac_action is None
    car.set_climate(
        "heating", now.isoformat(), route="test", observed_at=now, http_status=200
    )
    assert entity.hvac_mode is not None
    assert entity.hvac_mode.value == "heat_cool"


def test_trusted_manufacturer_context_not_nickname():
    car = V3Vehicle.from_graphql(
        {
            "vin": VIN,
            "nickname": "Audi Q8",
            "vehicle": {"media": {"longName": "Audi A4"}},
        },
        "DE",
    )
    assert car.model_family == "a4"
    assert car.model_family != "q8"
    car = V3Vehicle.from_graphql(
        {
            "vin": VIN,
            "nickname": "other",
            "vehicle": {"media": {"longName": "Audi Q8"}},
        },
        "DE",
    )
    assert car.model_family == "q8"


def test_native_climate_actions_are_independent_of_stale_state_and_no_duplicate_buttons():
    import asyncio
    from custom_components.audiconnect.v3.ha_platforms import setup
    from homeassistant.components.climate import ClimateEntityFeature, HVACMode

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    now = datetime.now(UTC)
    car.set_climate(
        "off",
        (now - timedelta(hours=2)).isoformat(),
        route="test",
        observed_at=now,
        http_status=200,
    )
    enabled = {"start", "stop", "start_with_settings"}
    calls, offered, listeners = [], [], []

    from custom_components.audiconnect.v3.command_journal import CommandRecord
    from custom_components.audiconnect.v3.command_readback import configure_readback

    journal = []

    async def send(vin, action, capability, **kwargs):
        calls.append((vin, action, capability, kwargs))
        row = CommandRecord.begin(
            capability, action, "test", datetime.now(UTC).timestamp()
        )
        configure_readback(row, kwargs.get("params"))
        row.observe_http(200)
        journal.append(row)

    engine = NS(
        vehicles={VIN.lower(): car},
        profiles={VIN.lower(): NS(command_journal=journal)},
        control_enabled=lambda vin, action, capability="climate": (
            capability == "climate" and action in enabled
        ),
        send_control=send,
    )
    coordinator = NS(
        engine=engine,
        last_update_success=True,
        async_add_listener=lambda cb: listeners.append(cb),
    )
    entry = NS(
        entry_id="entry",
        runtime_data=NS(v3=engine, coordinator=coordinator),
        async_on_unload=lambda cb: None,
    )
    setup("climate", entry, offered.extend)
    setup("button", entry, offered.extend)
    climates = [entity for entity in offered if isinstance(entity, V3ClimateEntity)]
    assert len(climates) == 1
    assert not any(
        entity.unique_id.endswith(
            ("_button_start_climate_car_settings", "_button_stop_climate")
        )
        for entity in offered
    )
    entity = climates[0]
    entity.async_write_ha_state = lambda: None
    assert entity.unique_id == VIN.lower() + "_climate_climatisation"
    assert entity.available and entity.hvac_mode == HVACMode.OFF
    assert entity.supported_features & ClimateEntityFeature.TURN_ON
    assert entity.supported_features & ClimateEntityFeature.TURN_OFF
    asyncio.run(entity.async_set_hvac_mode(HVACMode.HEAT_COOL))
    assert calls[-1] == (VIN, "start", "climate", {})
    asyncio.run(entity.async_set_hvac_mode(HVACMode.OFF))
    assert calls[-1] == (VIN, "stop", "climate", {})
    asyncio.run(entity.async_set_temperature(temperature=19.5))
    assert len(calls) == 2 and entity.target_temperature == 19.5
    asyncio.run(entity.async_turn_on())
    assert calls[-1] == (
        VIN,
        "start_with_settings",
        "climate",
        {"params": {"temp_c": 19.5}},
    )
    assert entity.hvac_mode == HVACMode.HEAT_COOL
    assert entity.target_temperature == 19.5
    assert entity.extra_state_attributes["pending_dispatched_temperature"] == 19.5
    journal[-1].observe_backend("rejected", datetime.now(UTC).timestamp())
    assert entity.extra_state_attributes["pending_dispatched_temperature"] is None
    car.readings["climatisationTargetTemperatureC"] = {
        "value": 20,
        "captured": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
    }
    assert entity.target_temperature == 20
    enabled.remove("start")
    assert entity.supported_features & ClimateEntityFeature.TURN_ON
    assert entity.supported_features & ClimateEntityFeature.TURN_OFF


def test_old_capture_does_not_claim_command_confirmation():
    from custom_components.audiconnect.v3.command_journal import CommandRecord
    from homeassistant.components.climate import HVACMode

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    now = datetime.now(UTC)
    car.set_climate(
        "off",
        (now - timedelta(minutes=2)).isoformat(),
        route="test",
        observed_at=now,
        http_status=200,
    )
    command = CommandRecord.begin(
        "climate", "start", "route", (now - timedelta(minutes=1)).timestamp()
    )
    command.state = "accepted_unconfirmed"
    from custom_components.audiconnect.v3.command_readback import configure_readback

    configure_readback(command, {})
    coordinator = NS(
        engine=NS(
            control_enabled=lambda *args: True,
            profiles={VIN.lower(): NS(command_journal=[command])},
        )
    )
    entity = V3ClimateEntity(coordinator, car)
    assert entity.hvac_mode == HVACMode.OFF
    assert entity.hvac_action.value == "off"
    assert entity.extra_state_attributes["state_source"] == "vehicle"
    assert entity.extra_state_attributes["command_status"] == "accepted_unconfirmed"
    car.set_climate(
        "heating", now.isoformat(), route="test", observed_at=now, http_status=200
    )
    assert entity.hvac_mode == HVACMode.HEAT_COOL


def test_rejected_setpoint_preserves_reported_target():
    import asyncio
    import pytest
    from unittest.mock import AsyncMock
    from homeassistant.exceptions import HomeAssistantError

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    now = datetime.now(UTC)
    car.set_climate(
        "heating", now.isoformat(), route="test", observed_at=now, http_status=200
    )
    car.readings["climatisationTargetTemperatureC"] = {
        "value": 17,
        "captured": now.isoformat(),
    }
    engine = NS(
        control_enabled=lambda *args: True,
        profiles={},
        send_control=AsyncMock(side_effect=RuntimeError("rejected")),
    )
    entity = V3ClimateEntity(NS(engine=engine, last_update_success=True), car)
    entity.async_write_ha_state = lambda: None
    with pytest.raises(HomeAssistantError):
        asyncio.run(entity.async_set_temperature(temperature=24))
    assert entity.target_temperature == 17
    assert entity.hvac_action.value == "heating"


def test_staged_target_does_not_block_stored_start_when_settings_disabled():
    import asyncio
    from unittest.mock import AsyncMock

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    enabled = {"start", "stop", "start_with_settings"}
    engine = NS(
        control_enabled=lambda vin, action, capability: action in enabled,
        profiles={},
        send_control=AsyncMock(),
    )
    entity = V3ClimateEntity(NS(engine=engine, last_update_success=True), car)
    entity.async_write_ha_state = lambda: None
    asyncio.run(entity.async_set_temperature(temperature=24))
    enabled.remove("start_with_settings")
    asyncio.run(entity.async_turn_on())
    engine.send_control.assert_awaited_once_with(VIN, "start", "climate")


def test_native_q8_setpoint_does_not_start_climate_or_claim_unread_temperature():
    import asyncio
    from unittest.mock import AsyncMock

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    car.readings["climatisationTargetTemperatureC"] = {"value": 20}
    engine = NS(
        control_enabled=lambda vin, action, capability: action == "set_settings",
        profiles={},
        send_control=AsyncMock(),
    )
    entity = V3ClimateEntity(NS(engine=engine, last_update_success=True), car)
    entity.async_write_ha_state = lambda: None
    asyncio.run(entity.async_set_temperature(temperature=22))
    engine.send_control.assert_awaited_once_with(
        VIN, "set_settings", "climate", params={"temp_c": 22}
    )
    assert entity.target_temperature == 20
    assert entity.hvac_mode is None


def test_climate_discovery_selects_temperature_route_per_vehicle():
    import asyncio
    from unittest.mock import AsyncMock

    from homeassistant.components.climate import ClimateEntityFeature

    from custom_components.audiconnect.v3.control_resolution import control_decision
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    from custom_components.audiconnect.v3.registry import CapabilityRegistry
    from custom_components.audiconnect.v3.runtime import catalog_path

    catalog = CapabilityRegistry.from_json_file(catalog_path())
    auth = NS(uses_auth0=True, service=NS(_spin=""))
    stored = "cariad.climate.start.stored"
    temperature = "cariad.climate.start.vehicle_settings"

    def discovered(vin, temperature_works):
        # Same advertised capability, no manufacturer model needed.
        car = V3Vehicle(vin, "Audi", "", "", "DE", auth_family="auth0")
        car.advertised_capabilities.add("climatisation")
        car.readings["climatisationTargetTemperatureC"] = {"value": 21}
        profile = DevelopmentProfile(catalog, car.context, cooldown_seconds=0)
        assert temperature in {
            row["operation"]
            for row in profile.discovery.candidates("climate", "start_with_settings")
        }
        for index, (action, route, worked) in enumerate(
            (
                ("start", stored, not temperature_works),
                ("start_with_settings", temperature, temperature_works),
                ("set_settings", "cariad.climate.settings", False),
            )
        ):
            stamp = 100 + index * 10
            attempt = profile.begin_test("climate", action, route, now=stamp)
            profile.observe_http(attempt.sequence, 200)
            profile.confirm(
                attempt.sequence, worked=worked, inspected_vehicle=True, now=stamp + 1
            )
            if worked:
                profile.choose_working("climate", action, route)

        def resolve(vin, action, capability):
            return control_decision(car, profile, auth, capability, action)["operation"]

        engine = NS(
            profiles={vin.lower(): profile},
            control_enabled=lambda *args: resolve(*args) is not None,
            send_control=AsyncMock(),
        )
        entity = V3ClimateEntity(NS(engine=engine), car)
        entity.async_write_ha_state = lambda: None
        return entity, engine, resolve

    stored_entity, stored_engine, stored_route = discovered(VIN, False)
    other_vin = "WAUZZZ4M0MD123457"
    temp_entity, temp_engine, temp_route = discovered(other_vin, True)

    assert stored_route(VIN, "start", "climate") == stored
    assert stored_route(VIN, "start_with_settings", "climate") is None
    assert (
        not stored_entity.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
    )
    # Reading a stored setpoint does not authorize a temperature-bearing start.
    assert stored_entity.reported_target_temperature == 21
    assert stored_entity.target_temperature == 21
    assert stored_entity.extra_state_attributes["reported_target_temperature"] == 21
    asyncio.run(stored_entity.async_turn_on())
    stored_engine.send_control.assert_awaited_once_with(VIN, "start", "climate")

    assert temp_route(other_vin, "start", "climate") is None
    assert temp_route(other_vin, "start_with_settings", "climate") == temperature
    assert temp_entity.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
    assert temp_entity.reported_target_temperature == 21
    assert temp_entity.target_temperature == 21
    asyncio.run(temp_entity.async_turn_on())
    temp_engine.send_control.assert_awaited_once_with(
        other_vin, "start_with_settings", "climate", params={"temp_c": 21}
    )
