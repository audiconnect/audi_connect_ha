"""Do not report charging or climate as completed on transport acknowledgement.

Regression for upstream #865 and former PR #897; preserves public service
return values while making the internal confirmation verdict explicit.
"""

from __future__ import annotations

import logging

import pytest

from custom_components.audiconnect import audi_services
from custom_components.audiconnect.audi_connect_account import AudiConnectAccount
from custom_components.audiconnect.audi_services import AudiService


VIN = "SYNTHETICVIN000001"
REQUEST_ID = "synthetic-request"


class _API:
    def __init__(self, states):
        self.states = states
        self.polls = 0

    def use_token(self, _token):
        pass

    async def request(self, method, url, headers=None, data=None, **_kwargs):
        if url.endswith("/pendingrequests"):
            state = self.states[min(self.polls, len(self.states) - 1)]
            self.polls += 1
            return {"data": [{"id": REQUEST_ID, "status": state}]}
        return {"data": {"requestID": REQUEST_ID}}


def _service(states):
    api = _API(states)
    service = AudiService(api, "DE", None, 1)
    service._bearer_token_json = {"access_token": "synthetic"}
    return service, api


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        (["successful"], True),
        (["in_progress"], False),
        (["in_progress", "successful"], True),
    ],
)
@pytest.mark.asyncio
async def test_pending_request_status_is_returned_not_discarded(states, expected):
    service, api = _service(states)
    verdict = await service._confirm_vehicle_request(
        VIN, "start", REQUEST_ID, attempts=2, sleep=0
    )
    assert verdict is expected
    assert api.polls == (1 if states == ["successful"] else 2)


@pytest.mark.asyncio
async def test_explicit_vehicle_rejection_still_raises():
    service, _api = _service(["failed"])
    with pytest.raises(RuntimeError, match="rejected by the vehicle"):
        await service._confirm_vehicle_request(
            VIN, "start", REQUEST_ID, attempts=1, sleep=0
        )


@pytest.mark.asyncio
async def test_charge_service_propagates_confirmation_without_extra_polls(monkeypatch):
    monkeypatch.setattr(audi_services, "CHARGING_CONFIRM_SLEEP", 0)
    monkeypatch.setattr(audi_services, "CHARGING_CONFIRM_ATTEMPTS", 2)
    service, api = _service(["in_progress"])
    assert await service.set_battery_charger(VIN, True, False) is False
    assert api.polls == 2


@pytest.mark.asyncio
async def test_climate_service_propagates_confirmation_without_extra_polls(monkeypatch):
    monkeypatch.setattr(audi_services, "CLIMATISATION_CONFIRM_SLEEP", 0)
    monkeypatch.setattr(audi_services, "CLIMATISATION_CONFIRM_ATTEMPTS", 2)
    service, api = _service(["in_progress"])
    assert await service.start_climate_control(VIN) is False
    assert api.polls == 2


class _AccountService:
    def __init__(self, verdict):
        self.verdict = verdict

    async def set_battery_charger(self, *_args):
        return self.verdict

    async def start_climate_control(self, *_args):
        return self.verdict


def _account(verdict):
    account = object.__new__(AudiConnectAccount)
    account._loggedin = True
    account._audi_service = _AccountService(verdict)

    async def _notify(_vin, _action):
        return None

    account.notify = _notify
    return account


@pytest.mark.parametrize("verdict", [True, False, None])
@pytest.mark.parametrize("action", ["charge", "climate"])
@pytest.mark.asyncio
async def test_account_does_not_claim_unconfirmed_vehicle_success(
    caplog, verdict, action
):
    account = _account(verdict)
    with caplog.at_level(logging.DEBUG):
        if action == "charge":
            accepted = await account.set_battery_charger(VIN, True, False)
        else:
            accepted = await account.start_climate_control(VIN)
    assert accepted is True  # Historical API: request accepted, not car state.
    messages = "\n".join(r.getMessage() for r in caplog.records)
    if verdict is True:
        assert "Successfully started" in messages
    else:
        assert "Successfully started" not in messages
        expected = "not confirmed" if verdict is False else "confirmation unavailable"
        assert expected in messages
