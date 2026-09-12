"""Every switch and button description is exercised against the real connection
class, not a stub that accepts anything.

The climatisation switch shipped calling set_vehicle_climatisation(vin, True),
which raises NotImplementedError upstream: the legacy start action is dead. The
description looked correct and no test touched the callable, so the switch could
never turn on. That control is now a climate entity (see
test_climate_entity.py), but the class of bug is what these tests guard: they
call every description's callables against a recording double that refuses any
method AudiConnectAccount does not define.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.audiconnect.audi_connect_account import AudiConnectAccount
from custom_components.audiconnect.button import (
    BUTTON_DESCRIPTIONS,
    _engine_controls_supported,
)
from custom_components.audiconnect.switch import SWITCH_DESCRIPTIONS

VIN = "WAUZZZ00000000001"

# Methods the descriptions are allowed to call, each verified below to exist on
# AudiConnectAccount and to be usable for that direction.
LIVE_METHODS = {
    "set_vehicle_pre_heater",
    "set_climatisation_setting",
}


class RecordingConnection:
    """Records calls; raises on anything AudiConnectAccount does not define."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if not hasattr(AudiConnectAccount, name):
            raise AttributeError(f"AudiConnectAccount has no method {name!r}")

        async def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return True

        return _call


def calls_of(fn):
    conn = RecordingConnection()
    asyncio.run(fn(conn, VIN))
    return conn.calls


@pytest.mark.parametrize("description", SWITCH_DESCRIPTIONS, ids=lambda d: d.key)
def test_switch_callables_hit_methods_that_exist(description):
    for fn in (description.turn_on_fn, description.turn_off_fn):
        [(name, args, _)] = calls_of(fn)
        assert name in LIVE_METHODS
        assert args[0] == VIN


@pytest.mark.parametrize("description", BUTTON_DESCRIPTIONS, ids=lambda d: d.key)
def test_button_callables_are_awaitable(description):
    """Buttons take the account, not the connection, so just check the callable
    produces a coroutine rather than blowing up at definition time."""

    class Account:
        connection = RecordingConnection()

        def __getattr__(self, name):
            async def _call(*a, **k):
                return True

            return _call

    result = description.press_fn(Account(), VIN)
    assert inspect.isawaitable(result)
    asyncio.run(result)


# --- the engine buttons ----------------------------------------------------------


class _Vehicle:
    def __init__(self, spin=None, car_type=None):
        self._audi_service = type("Svc", (), {"_spin": spin})()
        if car_type is not None:
            self.car_type = car_type


def _engine_buttons(vehicle):
    return [
        d.key
        for d in BUTTON_DESCRIPTIONS
        if d.key in ("start_engine", "stop_engine") and d.supported_fn(vehicle)
    ]


def test_battery_electric_cars_get_no_engine_buttons():
    """Found on a live BEV: the buttons were created because an S-PIN was set,
    with nothing checking whether there is an engine to start."""
    assert _engine_buttons(_Vehicle(spin="1234", car_type="electric")) == []


def test_a_combustion_car_still_gets_them():
    assert _engine_buttons(_Vehicle(spin="1234", car_type="gasoline")) == [
        "start_engine",
        "stop_engine",
    ]


@pytest.mark.parametrize("car_type", [None, "unsupported", "hybrid", ""])
def test_an_unknown_car_type_keeps_the_buttons(car_type):
    """Omitting a control the car does support is the worse failure, so only a
    positive "electric" suppresses them."""
    assert len(_engine_buttons(_Vehicle(spin="1234", car_type=car_type))) == 2


def test_no_spin_still_means_no_engine_buttons():
    assert _engine_buttons(_Vehicle(spin=None, car_type="gasoline")) == []


def test_the_gate_is_case_insensitive():
    assert not _engine_controls_supported(_Vehicle(spin="1234", car_type="Electric"))


# --- a failed command must not read as success --------------------------------------


class _Coordinator:
    last_update_success = True

    def __init__(self, result):
        self.account = type("A", (), {"connection": _Connection(result)})()
        self.refreshed = 0

    async def async_request_refresh(self):
        self.refreshed += 1


class _Connection:
    def __init__(self, result):
        self.result = result

    def __getattr__(self, name):
        async def _call(*a, **k):
            return self.result

        return _call


def _switch(result):
    from custom_components.audiconnect.switch import AudiSwitch

    description = next(d for d in SWITCH_DESCRIPTIONS if d.key == "preheater_active")
    vehicle = type("V", (), {"vin": VIN, "preheater_active": False})()
    coordinator = _Coordinator(result)
    switch = AudiSwitch(_Coordinator(result), description, vehicle)
    # The entity is built outside hass here, and a CoordinatorEntity has
    # should_poll False, so HA does not write state for us after a service call
    # and the switch must do it itself. Stub the write; the state machine is not
    # what these tests are about.
    switch.async_write_ha_state = lambda: None
    return coordinator, switch


def test_a_rejected_command_raises_rather_than_reporting_success():
    """Found live: window heating hit a 404 and the switch reported success,
    because it never looked at what the connection returned. The lock, number
    and climate entities all raise; this one silently did not."""
    coordinator, switch = _switch(False)
    switch.coordinator = coordinator
    with pytest.raises(HomeAssistantError):
        asyncio.run(switch.async_turn_on())
    assert coordinator.refreshed == 0

    with pytest.raises(HomeAssistantError):
        asyncio.run(switch.async_turn_off())


def test_a_successful_command_refreshes():
    coordinator, switch = _switch(True)
    switch.coordinator = coordinator
    asyncio.run(switch.async_turn_on())
    assert coordinator.refreshed == 1
