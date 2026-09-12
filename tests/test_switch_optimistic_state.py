"""A settings switch must not snap back while the car catches up.

Found on a live vehicle 2026-09-12: turning window heating on wrote to the car
and appeared in the myAudi app within a minute, while the Home Assistant switch
stayed off. The car acknowledges the settings write before it reports the new
value, so the refresh fired straight after the write re-reads the old one. With
the default 15 minute scan interval the switch then sits on the wrong value for
a quarter of an hour, which reads as the command having failed.

A CoordinatorEntity has should_poll False, and homeassistant/helpers/service.py
only calls async_update_ha_state after a service call when should_poll is True,
so the entity has to write its own state here.
"""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.audiconnect.switch import SWITCH_DESCRIPTIONS, AudiSwitch

VIN = "WAUZZZ00000000001"


class _Vehicle:
    vin = VIN

    def __init__(self, enabled: bool = False) -> None:
        self.climatisation_window_heating_enabled = enabled


class _Conn:
    def __init__(self, result: bool) -> None:
        self.result = result

    def __getattr__(self, name):
        async def _call(*a, **k):
            return self.result

        return _call


class _Coord:
    last_update_success = True

    def __init__(self, result: bool) -> None:
        self.account = type("A", (), {"connection": _Conn(result)})()
        self.refreshed = 0

    async def async_request_refresh(self) -> None:
        self.refreshed += 1


def _switch(result: bool, enabled: bool = False):
    description = next(
        d for d in SWITCH_DESCRIPTIONS if d.key == "climatisation_window_heating"
    )
    vehicle = _Vehicle(enabled)
    coord = _Coord(result)
    sw = AudiSwitch(coord, description, vehicle)
    # Built outside hass; the state machine is not what these tests are about.
    sw.async_write_ha_state = lambda: None
    return coord, sw, vehicle


def test_switch_shows_the_new_value_before_the_car_reports_it():
    """The must-fire case: fails if is_on reads straight off the vehicle."""
    _coord, sw, vehicle = _switch(True, enabled=False)
    asyncio.run(sw.async_turn_on())
    assert vehicle.climatisation_window_heating_enabled is False  # car not caught up
    assert sw.is_on is True


def test_the_assumption_clears_once_the_car_agrees():
    _coord, sw, vehicle = _switch(True, enabled=False)
    asyncio.run(sw.async_turn_on())
    vehicle.climatisation_window_heating_enabled = True
    sw._handle_coordinator_update()
    assert sw._assumed is None
    assert sw.is_on is True


def test_a_stale_poll_does_not_clear_the_assumption():
    _coord, sw, _vehicle = _switch(True, enabled=False)
    asyncio.run(sw.async_turn_on())
    sw._handle_coordinator_update()  # poll still reports the old value
    assert sw._assumed is True
    assert sw.is_on is True


def test_a_change_made_elsewhere_is_reflected_once_the_assumption_has_cleared():
    """The assumption bridges the car's reporting lag; it is not a lock. Once the
    car has caught up it is authoritative again, so a later change made in the
    myAudi app shows up."""
    _coord, sw, vehicle = _switch(True, enabled=False)
    asyncio.run(sw.async_turn_on())
    vehicle.climatisation_window_heating_enabled = True
    sw._handle_coordinator_update()
    assert sw._assumed is None
    vehicle.climatisation_window_heating_enabled = False  # disabled in the app
    sw._handle_coordinator_update()
    assert sw.is_on is False


def test_known_limit_a_car_that_never_reports_keeps_the_assumption():
    """Documents what this deliberately cannot do. A car still reporting the
    pre-write value is indistinguishable from one that has not caught up, so the
    assumption holds. Bounded by the write raising on failure, so a success means
    the car accepted it. If that proves wrong the fix is a timeout, not clearing
    on a value we cannot interpret."""
    _coord, sw, _vehicle = _switch(True, enabled=True)
    asyncio.run(sw.async_turn_off())
    for _ in range(5):
        sw._handle_coordinator_update()
    assert sw._assumed is False
    assert sw.is_on is False


def test_a_failed_write_assumes_nothing():
    _coord, sw, _vehicle = _switch(False, enabled=False)
    with pytest.raises(HomeAssistantError):
        asyncio.run(sw.async_turn_on())
    assert sw._assumed is None
    assert sw.is_on is False


def test_a_successful_write_still_requests_a_refresh():
    coord, sw, _vehicle = _switch(True, enabled=False)
    sw.coordinator = coord
    asyncio.run(sw.async_turn_on())
    assert coord.refreshed == 1
