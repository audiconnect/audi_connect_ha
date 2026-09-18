"""A climatisation start that the car never acts on must not report success.

Measured on a live vehicle 2026-09-13: POST climatisation/start with no settings
body returned 200 with a requestID, sat at "in_progress" through +10s and +20s,
and only reached "timeout" at about +60s. A control in the same session with a
settings body reached "successful" and the car was cooling within 15s. So the
200 is the gateway accepting the request, not the car acting on it, and the real
verdict is only in pendingrequests, which api_level 1 was not reading.

Same class of defect as #847's switch, which reported success on a rejected
command.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from custom_components.audiconnect import audi_services
from custom_components.audiconnect.audi_services import AudiService

VIN = "WAUZZZ00000000000"
REQ = "a769422d-cb80-45a0-94f7-a2c5ea2514a9"

SETTINGS = {
    "climatisation": {
        "climatisationSettings": {
            "value": {
                "targetTemperature_C": 18,
                "windowHeatingEnabled": True,
                "zoneFrontLeftEnabled": True,
            }
        }
    }
}


class _API:
    """Returns a requestID from the start, then the given pendingrequests states."""

    def __init__(self, statuses: list[str]) -> None:
        self.statuses = list(statuses)
        self.polls = 0

    def use_token(self, token) -> None:
        pass

    async def get(self, url, **kwargs):
        return SETTINGS

    async def request(self, method, url, headers=None, data=None, **kwargs):
        if url.endswith("/pendingrequests"):
            status = self.statuses[min(self.polls, len(self.statuses) - 1)]
            self.polls += 1
            return {"data": [{"id": REQ, "status": status}]}
        return {"data": {"requestID": REQ}}


def _service(statuses: list[str]) -> tuple[AudiService, _API]:
    api = _API(statuses)
    service = AudiService(api, "DE", None, 1)
    service._bearer_token_json = {"access_token": "t"}
    return service, api


def _start(service: AudiService, **kwargs) -> None:
    asyncio.run(service.start_climate_control(VIN, **kwargs))


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    """The real budget is 8 polls 10s apart; the point here is the verdict."""
    monkeypatch.setattr(audi_services, "CLIMATISATION_CONFIRM_SLEEP", 0)

    async def _sleep(_seconds):
        return None

    monkeypatch.setattr(audi_services.asyncio, "sleep", _sleep)


def test_a_start_the_car_times_out_on_raises():
    """The must-fire case: this is the live failure, which used to look like success."""
    service, api = _service(["in_progress", "in_progress", "timeout"])
    with pytest.raises(Exception, match="rejected by the vehicle"):
        _start(service, temp_c=20)
    assert api.polls >= 3


def test_a_start_the_car_accepts_returns_normally():
    service, api = _service(["in_progress", "successful"])
    _start(service, temp_c=20)  # must not raise
    assert api.polls >= 2


def test_a_failed_status_raises_too():
    service, _api = _service(["failed"])
    with pytest.raises(Exception, match="rejected by the vehicle"):
        _start(service, temp_c=20)


def test_still_in_progress_at_the_end_is_not_reported_as_failure():
    """Running out of attempts means unconfirmed, not broken: a command that did
    work must never be announced as having failed."""
    service, _api = _service(["in_progress"])
    _start(service, temp_c=20)  # must not raise


def test_the_confirmation_names_climatisation_not_charging():
    service, _api = _service(["timeout"])
    with pytest.raises(Exception, match="Climatisation start"):
        _start(service, temp_c=20)


def test_the_settings_body_still_goes_out_unharmed():
    """The confirmation must not disturb the read-modify-write body."""
    calls = []

    class _Recording(_API):
        async def request(self, method, url, headers=None, data=None, **kwargs):
            if not url.endswith("/pendingrequests"):
                calls.append(data)
            return await super().request(method, url, headers, data, **kwargs)

    api = _Recording(["successful"])
    service = AudiService(api, "DE", None, 1)
    service._bearer_token_json = {"access_token": "t"}
    _start(service, temp_c=20)
    body = json.loads(calls[0])
    assert body["targetTemperature"] == 20
    assert body["windowHeatingEnabled"] is True
