"""The climatisation climate entity.

Each test here corresponds to something #751's climate entity gets wrong, so the
defects cannot come back in our own version: state read from an attribute that
does not exist, outdoor temperature presented as cabin temperature, a target
temperature that resets on restart, no support gating, and a start path through
the dead legacy action.
"""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.components.climate import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.exceptions import HomeAssistantError

from custom_components.audiconnect import climate as climate_mod
from custom_components.audiconnect.audi_connect_account import AudiConnectAccount
from custom_components.audiconnect.audi_entity import is_entity_supported
from custom_components.audiconnect.climate import AudiClimate

VIN = "WAUZZZ00000000001"


class RecordingConnection:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def __getattr__(self, name):
        if not hasattr(AudiConnectAccount, name):
            raise AttributeError(f"AudiConnectAccount has no method {name!r}")

        async def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.result

        return _call


class StubCoordinator:
    last_update_success = True

    def __init__(self, connection=None):
        self.account = type("Account", (), {"connection": connection})()
        self.refreshed = 0

    async def async_request_refresh(self):
        self.refreshed += 1


class StubVehicle:
    def __init__(self, state="off", **extra):
        self.vin = VIN
        self.climatisation_state = state
        for k, v in extra.items():
            setattr(self, k, v)


def build(state="off", connection=None, **extra):
    coordinator = StubCoordinator(connection)
    entity = AudiClimate(coordinator, StubVehicle(state, **extra))
    # Only the framework's state-write notification is stubbed; every property
    # and command path below is the entity's own code.
    entity.written = 0

    def _write():
        entity.written += 1

    entity.async_write_ha_state = _write
    return coordinator, entity


# --- state comes from the car -----------------------------------------------------


@pytest.mark.parametrize(
    ("state", "mode", "action"),
    [
        ("off", HVACMode.OFF, HVACAction.OFF),
        ("invalid", HVACMode.OFF, HVACAction.OFF),
        ("", HVACMode.OFF, HVACAction.OFF),
        ("heating", HVACMode.HEAT_COOL, HVACAction.HEATING),
        ("cooling", HVACMode.HEAT_COOL, HVACAction.COOLING),
        ("ventilation", HVACMode.HEAT_COOL, HVACAction.FAN),
    ],
)
def test_mode_and_action_track_the_reported_state(state, mode, action):
    _, entity = build(state)
    assert entity.hvac_mode is mode
    assert entity.hvac_action is action


def test_state_is_read_from_an_attribute_that_exists():
    """#751 read `climatisation_active`, which no vehicle defines, so its mode
    only ever reflected what HA last commanded."""
    assert climate_mod._ATTR_KEY == "climatisation_state"
    assert hasattr(AudiConnectAccount, "set_vehicle_climatisation")
    from custom_components.audiconnect import audi_connect_account as aca

    assert not hasattr(aca.AudiConnectVehicle, "climatisation_active")
    assert hasattr(aca.AudiConnectVehicle, "climatisation_state")


def test_an_unknown_running_mode_still_reads_as_running():
    _, entity = build("defrosting")
    assert entity.hvac_mode is HVACMode.HEAT_COOL
    assert entity.hvac_action is HVACAction.HEATING


def test_outdoor_temperature_is_not_presented_as_cabin_temperature():
    """#751 exposed current_temperature from a `temperature` attribute that does
    not exist; the car only reports the outside reading, which is not what a
    climate entity's current temperature means."""
    _, entity = build("off", outdoor_temperature=3.5)
    assert entity.current_temperature is None


def test_entity_is_gated_on_climatisation_support():
    class NoClimatisation:
        vin = VIN

    assert is_entity_supported(StubVehicle("off"), climate_mod._ATTR_KEY)
    assert not is_entity_supported(NoClimatisation(), climate_mod._ATTR_KEY)


# --- the target temperature -------------------------------------------------------


def test_target_temperature_survives_a_restart():
    """#751 hardcoded 21.0 on every construction, losing the user's setting on
    each restart."""
    _, entity = build()
    assert entity.target_temperature == 21.0  # the default, before restoring

    entity._restore_target_temperature(
        type("State", (), {"attributes": {ATTR_TEMPERATURE: 24.5}})
    )
    assert entity.target_temperature == 24.5


@pytest.mark.parametrize(
    "last_state",
    [
        None,
        type("State", (), {"attributes": {}}),
        type("State", (), {"attributes": {ATTR_TEMPERATURE: None}}),
        type("State", (), {"attributes": {ATTR_TEMPERATURE: "unknown"}}),
    ],
)
def test_an_unusable_recorded_state_leaves_the_default(last_state):
    _, entity = build()
    entity._restore_target_temperature(last_state)
    assert entity.target_temperature == 21.0


def test_added_to_hass_actually_calls_the_restore(monkeypatch):
    """Guard the call site, not just the helper: a correct restore behind
    unwired async_added_to_hass would pass every test above."""
    from homeassistant.helpers.restore_state import RestoreEntity
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    async def _noop(self):
        return None

    monkeypatch.setattr(CoordinatorEntity, "async_added_to_hass", _noop)
    monkeypatch.setattr(RestoreEntity, "async_added_to_hass", _noop)

    _, entity = build()

    async def _last_state():
        return type("State", (), {"attributes": {ATTR_TEMPERATURE: 17.0}})

    entity.async_get_last_state = _last_state
    asyncio.run(entity.async_added_to_hass())
    assert entity.target_temperature == 17.0


def test_setting_a_temperature_while_off_does_not_start_the_car():
    connection = RecordingConnection()
    coordinator, entity = build("off", connection)
    asyncio.run(entity.async_set_temperature(**{ATTR_TEMPERATURE: 19.5}))
    assert entity.target_temperature == 19.5
    assert connection.calls == []
    assert coordinator.refreshed == 0


def test_setting_a_temperature_while_running_re_sends_it():
    connection = RecordingConnection()
    _, entity = build("heating", connection)
    asyncio.run(entity.async_set_temperature(**{ATTR_TEMPERATURE: 19.5}))
    assert connection.calls == [("start_climate_control", (VIN,), {"temp_c": 19.5})]


# --- the write paths --------------------------------------------------------------


def test_turn_on_uses_the_live_start_path_and_sends_only_celsius():
    """set_vehicle_climatisation(vin, True) raises NotImplementedError upstream,
    and the service prefers temp_f when both are given, which would quantise the
    0.5 step through a Fahrenheit round trip."""
    connection = RecordingConnection()
    coordinator, entity = build("off", connection)
    asyncio.run(entity.async_set_hvac_mode(HVACMode.HEAT_COOL))
    assert connection.calls == [("start_climate_control", (VIN,), {"temp_c": 21.0})]
    assert coordinator.refreshed == 1


def test_turn_off_uses_the_stop_action_which_is_still_live():
    connection = RecordingConnection()
    _, entity = build("heating", connection)
    asyncio.run(entity.async_set_hvac_mode(HVACMode.OFF))
    assert connection.calls == [("set_vehicle_climatisation", (VIN, False), {})]


def test_the_legacy_start_really_is_dead():
    """Positive control: if upstream revives startClimatisation, this fails and
    the simpler call becomes available again."""
    import inspect

    from custom_components.audiconnect import audi_services

    source = inspect.getsource(audi_services.AudiService.set_climatisation)
    assert "raise NotImplementedError" in source


@pytest.mark.parametrize("mode", [HVACMode.HEAT_COOL, HVACMode.OFF])
def test_a_failed_command_raises_and_does_not_refresh(mode):
    connection = RecordingConnection(result=False)
    coordinator, entity = build(
        "off" if mode is HVACMode.HEAT_COOL else "heating", connection
    )
    with pytest.raises(HomeAssistantError):
        asyncio.run(entity.async_set_hvac_mode(mode))
    assert coordinator.refreshed == 0


def test_turn_on_and_off_are_advertised():
    _, entity = build()
    assert entity.supported_features & ClimateEntityFeature.TURN_ON
    assert entity.supported_features & ClimateEntityFeature.TURN_OFF
    assert entity.hvac_modes == [HVACMode.OFF, HVACMode.HEAT_COOL]
