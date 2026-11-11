"""Lock/unlock: rejected, accepted but unconfirmed, and readback-confirmed."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.audiconnect.lock import AudiLock


class Connection:
    def __init__(self, *, accepted=True):
        self.accepted = accepted
        self.calls = []

    async def set_vehicle_lock(self, vin: str, lock: bool, *, refresh: bool = True):
        assert refresh is False
        self.calls.append((vin, lock))
        return self.accepted


class Coordinator:
    last_update_success = True

    def __init__(self, car, *, accepted=True, refreshed_status=None, refresh_fails=False):
        self.car = car
        self.account = NS(connection=Connection(accepted=accepted))
        self.refreshed_status = refreshed_status
        self.refreshes = 0
        self.refresh_fails = refresh_fails

    def async_add_listener(self, *args, **kwargs):
        return lambda: None

    async def async_request_refresh(self):
        self.refreshes += 1
        if self.refresh_fails:
            raise RuntimeError("synthetic cloud failure")
        if self.refreshed_status is not None:
            self.car.door_lock_status = self.refreshed_status


@pytest.mark.parametrize(
    ("requested", "start", "after"),
    [(True, "unlocked", "unlocked"), (False, "locked", "locked")],
)
def test_delayed_state_is_accepted_unconfirmed(requested, start, after):
    car = NS(vin="NOT_A_REAL_VIN", door_lock_status=start, doors_trunk_status=None)
    coord = Coordinator(car, refreshed_status=after)
    entity = AudiLock(coord, car)
    asyncio.run(entity.async_lock() if requested else entity.async_unlock())
    assert coord.account.connection.calls == [("NOT_A_REAL_VIN", requested)]
    assert coord.refreshes == 1
    assert entity.extra_state_attributes["last_command_status"] == "accepted_unconfirmed"


@pytest.mark.parametrize(
    ("requested", "start", "after"),
    [(True, "unlocked", "locked"), (False, "locked", "unlocked")],
)
def test_both_directions_confirm_from_readback(requested, start, after):
    car = NS(vin="NOT_A_REAL_VIN", door_lock_status=start, doors_trunk_status=None)
    coord = Coordinator(car, refreshed_status=after)
    entity = AudiLock(coord, car)
    asyncio.run(entity.async_lock() if requested else entity.async_unlock())
    assert coord.refreshes == 1
    assert entity.extra_state_attributes["last_command_status"] == "confirmed_by_readback"


@pytest.mark.parametrize("requested", [True, False])
def test_rejected_command_does_not_refresh(requested):
    car = NS(vin="NOT_A_REAL_VIN", door_lock_status="unlocked", doors_trunk_status=None)
    coord = Coordinator(car, accepted=False)
    entity = AudiLock(coord, car)
    with pytest.raises(HomeAssistantError, match="rejected or could not be completed"):
        asyncio.run(entity.async_lock() if requested else entity.async_unlock())
    assert coord.refreshes == 0
    assert entity.extra_state_attributes["last_command_status"] == "request_failed"


def test_missing_vehicle_state_is_unconfirmed():
    car = NS(vin="NOT_A_REAL_VIN", door_lock_status=None, doors_trunk_status=None)
    entity = AudiLock(Coordinator(car), car)
    asyncio.run(entity.async_lock())
    assert entity.extra_state_attributes["last_command_status"] == "accepted_unconfirmed"


def test_refresh_failure_does_not_issue_duplicate_command():
    car = NS(vin="NOT_A_REAL_VIN", door_lock_status="unlocked", doors_trunk_status=None)
    coord = Coordinator(car, refresh_fails=True)
    entity = AudiLock(coord, car)
    asyncio.run(entity.async_lock())
    assert coord.refreshes == 1
    assert coord.account.connection.calls == [("NOT_A_REAL_VIN", True)]
    assert entity.extra_state_attributes["last_command_status"] == "accepted_unconfirmed"


def test_already_matching_state_is_not_claimed_as_new_confirmation():
    car = NS(vin="NOT_A_REAL_VIN", door_lock_status="locked", doors_trunk_status=None)
    entity = AudiLock(Coordinator(car, refreshed_status="locked"), car)
    asyncio.run(entity.async_lock())
    assert entity.extra_state_attributes["last_command_status"] == (
        "already_reported_in_requested_state"
    )
