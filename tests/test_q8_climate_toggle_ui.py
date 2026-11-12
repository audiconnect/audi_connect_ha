"""One native Q8 climate toggle maps to both proven remote actions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.audiconnect.switch import AudiClimateQuickSwitch
from custom_components.audiconnect.button import BUTTON_DESCRIPTIONS
from custom_components.audiconnect.lock import AudiLock


class Connection:
    def __init__(self, outcome=True):
        self.outcome = outcome
        self.calls = []

    async def start_climate_control(self, vin: str):
        self.calls.append(("climate_start", vin))
        return self.outcome

    async def set_vehicle_climatisation(self, vin: str, active: bool):
        self.calls.append(("climate_stop", vin, active))
        return self.outcome


class Coordinator:
    last_update_success = True

    def __init__(self, connection):
        self.account = NS(connection=connection)
        self.refreshes = 0

    async def async_request_refresh(self):
        self.refreshes += 1


def vehicle(state="off"):
    return NS(
        vin="SYNTHETICVIN000001",
        title="Q8",
        model="Q8",
        model_year="2025",
        climatisation_state=state,
    )


def test_quick_switch_is_on_only_when_audi_reports_running():
    conn = Connection()
    car = vehicle("off")
    toggle = AudiClimateQuickSwitch(Coordinator(conn), car)
    assert toggle.is_on is False
    car.climatisation_state = "heating"
    assert toggle.is_on is True
    car.climatisation_state = "cooling"
    assert toggle.is_on is True
    car.climatisation_state = "error"
    assert toggle.is_on is None
    car.climatisation_state = None
    assert toggle.is_on is None
    assert toggle.unique_id.endswith("_switch_climate_quick_control")


def test_turn_on_uses_exact_proven_bodyless_start_without_duplicate_refresh():
    conn = Connection()
    coordinator = Coordinator(conn)
    switch = AudiClimateQuickSwitch(coordinator, vehicle("off"))
    asyncio.run(switch.async_turn_on())
    assert conn.calls == [("climate_start", "SYNTHETICVIN000001")]
    assert coordinator.refreshes == 0  # connection's notify already triggers refresh


def test_turn_off_uses_exact_proven_stop_without_duplicate_refresh():
    conn = Connection()
    coordinator = Coordinator(conn)
    switch = AudiClimateQuickSwitch(coordinator, vehicle("heating"))
    asyncio.run(switch.async_turn_off())
    assert conn.calls == [("climate_stop", "SYNTHETICVIN000001", False)]
    assert coordinator.refreshes == 0


def test_repeated_on_or_off_does_not_send_duplicate_commands():
    conn = Connection()
    toggle_on = AudiClimateQuickSwitch(Coordinator(conn), vehicle("heating"))
    toggle_off = AudiClimateQuickSwitch(Coordinator(conn), vehicle("off"))
    asyncio.run(toggle_on.async_turn_on())
    asyncio.run(toggle_off.async_turn_off())
    assert conn.calls == []


@pytest.mark.parametrize(
    "method,state", [("async_turn_on", "off"), ("async_turn_off", "heating")]
)
def test_failure_is_explicit_and_never_optimistic(method, state):
    conn = Connection(outcome=False)
    toggle = AudiClimateQuickSwitch(Coordinator(conn), vehicle(state))
    with pytest.raises(HomeAssistantError):
        asyncio.run(getattr(toggle, method)())
    assert toggle.is_on == (state == "heating")


def test_existing_buttons_and_native_lock_not_removed():
    buttons = {description.key for description in BUTTON_DESCRIPTIONS}
    assert {"flash_lights", "refresh_vehicle_data"} <= buttons
    assert {"start_climate_car_settings", "stop_climate"}.isdisjoint(buttons)
    assert hasattr(AudiLock, "async_lock") and hasattr(AudiLock, "async_unlock")
