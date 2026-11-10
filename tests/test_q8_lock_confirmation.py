"""Physical lock confirmation must not be fabricated from HTTP 200."""

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
        assert refresh is False  # Exactly one refresh belongs to AudiLock.
        self.calls.append((vin, lock))
        return self.accepted


class Coordinator:
    last_update_success = True

    def __init__(self, car, *, accepted=True, refreshed_status=None):
        self.car = car
        self.account = NS(connection=Connection(accepted=accepted))
        self.refreshed_status = refreshed_status
        self.refreshes = 0

    def async_add_listener(self, *args, **kwargs):
        return lambda: None

    async def async_request_refresh(self):
        self.refreshes += 1
        if self.refreshed_status is not None:
            self.car.door_lock_status = self.refreshed_status


def test_lock_action_reports_unconfirmed_when_cloud_ack_did_not_lock_car():
    car = NS(vin="NOT_A_REAL_VIN", door_lock_status="unlocked", doors_trunk_status=None)
    coord = Coordinator(car, refreshed_status="unlocked")
    entity = AudiLock(coord, car)
    with pytest.raises(HomeAssistantError, match="not confirmed"):
        asyncio.run(entity.async_lock())
    assert coord.account.connection.calls == [("NOT_A_REAL_VIN", True)]
    assert coord.refreshes == 1  # no added polling loop or blind retry


def test_lock_action_succeeds_when_refreshed_car_confirms_locked():
    car = NS(vin="NOT_A_REAL_VIN", door_lock_status="unlocked", doors_trunk_status=None)
    coord = Coordinator(car, refreshed_status="locked")
    asyncio.run(AudiLock(coord, car).async_lock())
    assert coord.account.connection.calls == [("NOT_A_REAL_VIN", True)]
    assert coord.refreshes == 1


def test_lock_action_reports_no_state_as_unconfirmed():
    car = NS(vin="NOT_A_REAL_VIN", door_lock_status=None, doors_trunk_status=None)
    coord = Coordinator(car)
    with pytest.raises(HomeAssistantError, match="not confirmed"):
        asyncio.run(AudiLock(coord, car).async_lock())
    assert coord.refreshes == 1


def test_lock_api_failure_does_not_refresh_or_report_success():
    car = NS(vin="NOT_A_REAL_VIN", door_lock_status="unlocked", doors_trunk_status=None)
    coord = Coordinator(car, accepted=False)
    with pytest.raises(HomeAssistantError, match="Failed to lock"):
        asyncio.run(AudiLock(coord, car).async_lock())
    assert coord.refreshes == 0


def test_unlock_success_path_unchanged():
    car = NS(vin="NOT_A_REAL_VIN", door_lock_status="locked", doors_trunk_status=None)
    coord = Coordinator(car, refreshed_status="unlocked")
    asyncio.run(AudiLock(coord, car).async_unlock())
    assert coord.account.connection.calls == [("NOT_A_REAL_VIN", False)]
    assert coord.refreshes == 1
