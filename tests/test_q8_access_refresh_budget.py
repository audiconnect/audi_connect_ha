"""No double polling when the HA lock entity already owns the readback."""

import asyncio

from custom_components.audiconnect.audi_connect_account import AudiConnectAccount
from custom_components.audiconnect.diagnostic_events import (
    classify_route,
    build_http_event,
)


class Service:
    def __init__(self):
        self.calls = []

    async def set_vehicle_lock(self, vin, lock):
        self.calls.append((vin, lock))


def test_connection_suppresses_inner_notify_when_platform_will_refresh_once():
    account = object.__new__(AudiConnectAccount)
    account._loggedin = True
    service = Service()
    account._audi_service = service
    notices = []

    async def fake_notify(vin, action):
        notices.append(action)

    account.notify = fake_notify

    result = asyncio.run(account.set_vehicle_lock("EXAMPLEVIN", True, refresh=False))
    assert result is True
    assert notices == []
    assert service.calls == [("EXAMPLEVIN", True)]
    result = asyncio.run(account.set_vehicle_lock("EXAMPLEVIN", False))
    assert result is True
    assert len(notices) == 1
    assert service.calls[-1] == ("EXAMPLEVIN", False)


def test_diagnostics_separate_lock_vs_unlock_without_personal_data():
    lock = "https://emea.bff.cariad.digital/vehicle/v1/vehicles/PRIVATEVIN/access/lock"
    unlock = lock[:-4] + "unlock"
    assert classify_route(lock) == "modern_access_lock"
    assert classify_route(unlock) == "modern_access_unlock"
    event = build_http_event("POST", lock + "?access_token=SECRET", 429)
    assert event["route"] == "modern_access_lock"
    assert event["http_status"] == 429
    assert "PRIVATEVIN" not in repr(event)
    assert "SECRET" not in repr(event)
