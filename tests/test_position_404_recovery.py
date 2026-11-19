"""A transient position 404 must not strand a parking tracker until reload.

Regression for upstream #888, with bounded retries on scheduled polls only.
"""

from __future__ import annotations

import asyncio
import time

from aiohttp import ClientResponseError, RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from custom_components.audiconnect.audi_connect_account import (
    AudiConnectVehicle,
    POSITION_404_MAX_BACKOFF_SECONDS,
)


VIN = "SYNTHETICVIN000001"
POSITION = {
    "data": {
        "lat": 50.85,
        "lon": 4.35,
        "carCapturedTimestamp": "2026-11-10T18:00:00.000Z",
    }
}


def _not_found():
    url = URL("https://example.invalid/parking-position")
    info = RequestInfo(
        url=url,
        method="GET",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=url,
    )
    return ClientResponseError(info, (), status=404, message="Not Found")


class _Vehicle:
    vin = VIN


class _Service:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def get_stored_position(self, _vin):
        self.calls += 1
        result = self.outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _run(coro):
    return asyncio.run(coro)


def test_single_404_does_not_permanently_disable_position():
    service = _Service([_not_found(), POSITION])
    vehicle = AudiConnectVehicle(service, _Vehicle())
    _run(vehicle.update_vehicle_position())
    assert vehicle.support_position is True
    assert vehicle._position_404_count == 1
    assert vehicle._position_retry_after > time.monotonic()

    _run(vehicle.update_vehicle_position())
    assert service.calls == 1  # Cooldown prevents excess Audi requests.

    vehicle._position_retry_after = 0.0  # Simulate next scheduled eligible poll.
    _run(vehicle.update_vehicle_position())
    assert service.calls == 2
    assert vehicle._position_404_count == 0
    assert vehicle._position_retry_after == 0.0
    assert vehicle._vehicle.state["position"]["latitude"] == 50.85


def test_repeated_404_retries_are_bounded_and_never_create_extra_calls():
    service = _Service([_not_found() for _ in range(9)])
    vehicle = AudiConnectVehicle(service, _Vehicle())
    previous_count = 0
    for attempt in range(9):
        vehicle._position_retry_after = 0.0
        _run(vehicle.update_vehicle_position())
        assert service.calls == attempt + 1
        assert vehicle._position_404_count >= previous_count
        previous_count = vehicle._position_404_count
        remaining = vehicle._position_retry_after - time.monotonic()
        assert 0 < remaining <= POSITION_404_MAX_BACKOFF_SECONDS
        assert vehicle.support_position is True

    _run(vehicle.update_vehicle_position())
    assert service.calls == 9


def test_success_after_404_restores_position_without_reload():
    vehicle = AudiConnectVehicle(_Service([_not_found(), POSITION]), _Vehicle())
    _run(vehicle.update_vehicle_position())
    vehicle._position_retry_after = 0.0
    _run(vehicle.update_vehicle_position())
    assert vehicle.position_last_updated is not None
    assert vehicle.support_position is True
