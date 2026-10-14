"""#865: a command the car never confirmed must not be logged as a success.

The confirmation helper used to return nothing whether the car confirmed or the
wait ran out, so the account layer logged "Successfully started ..." straight
after the helper's own "not confirmed" warning. Corey saw both lines one
millisecond apart, then three more polls before the car really acted.

The helper now says which it was. The services pass that up, and the account
layer only claims success when it was not told otherwise: None (nothing to
confirm against, or a legacy path that confirmed itself) keeps the old line.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from custom_components.audiconnect import audi_services
from custom_components.audiconnect.audi_connect_account import AudiConnectAccount
from custom_components.audiconnect.audi_services import AudiService

VIN = "WAUZZZ00000000000"
REQ = "a769422d-cb80-45a0-94f7-a2c5ea2514a9"
SETTINGS = {
    "climatisation": {"climatisationSettings": {"value": {"targetTemperature_C": 18}}}
}


class _API:
    """Accepts every command with a requestID, then reports the given statuses."""

    def __init__(self, statuses: list[str], request_id: str | None = REQ) -> None:
        self.statuses = list(statuses)
        self.request_id = request_id
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
        if self.request_id is None:
            return {"data": {}}
        return {"data": {"requestID": self.request_id}}


def _service(statuses: list[str], request_id: str | None = REQ) -> AudiService:
    service = AudiService(_API(statuses, request_id), "DE", None, 1)
    service._bearer_token_json = {"access_token": "t"}
    return service


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    async def _sleep(_seconds):
        return None

    monkeypatch.setattr(audi_services.asyncio, "sleep", _sleep)


def _run(coro):
    return asyncio.run(coro)


# --- the helper and the services say whether the car confirmed -----------------


def test_the_helper_reports_a_confirmed_request():
    assert (
        _run(_service(["successful"])._confirm_vehicle_request(VIN, "start", REQ))
        is True
    )


def test_the_helper_reports_an_unconfirmed_request():
    """The must-fire case: attempts run out with the car still in progress."""
    service = _service(["in_progress"])
    assert _run(service._confirm_vehicle_request(VIN, "start", REQ)) is False


def test_a_rejection_still_raises_rather_than_reporting_unconfirmed():
    with pytest.raises(Exception, match="rejected by the vehicle"):
        _run(_service(["failed"])._confirm_vehicle_request(VIN, "start", REQ))


@pytest.mark.parametrize(
    ("statuses", "expected"), [(["successful"], True), (["in_progress"], False)]
)
def test_start_charging_passes_the_verdict_up(statuses, expected):
    service = _service(statuses)
    assert _run(service.set_battery_charger(VIN, True, False)) is expected


@pytest.mark.parametrize(
    ("statuses", "expected"), [(["successful"], True), (["in_progress"], False)]
)
def test_start_climatisation_passes_the_verdict_up(statuses, expected):
    service = _service(statuses)
    assert _run(service.start_climate_control(VIN, temp_c=20)) is expected


def test_no_request_id_means_nothing_to_confirm_not_unconfirmed():
    """None is not False: a gateway that returns no requestID gave us nothing to
    wait on, and calling that 'unconfirmed' would warn about every such car."""
    service = _service(["in_progress"], request_id=None)
    assert _run(service.set_battery_charger(VIN, True, False)) is None
    assert _run(service.start_climate_control(VIN, temp_c=20)) is None


def test_timer_mode_is_a_preference_with_nothing_to_confirm():
    assert _run(_service(["in_progress"]).set_battery_charger(VIN, True, True)) is None


# --- the account layer only claims success when it was not told otherwise ------


class _Service:
    def __init__(self, verdict):
        self.verdict = verdict

    async def set_battery_charger(self, vin, activate, timer):
        return self.verdict

    async def start_climate_control(self, *args, **kwargs):
        return self.verdict


def _account(verdict) -> AudiConnectAccount:
    account = object.__new__(AudiConnectAccount)
    account._loggedin = True
    account._observers = []
    account._audi_service = _Service(verdict)
    return account


def _debug_messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]


def _claims_success(messages: list[str]) -> bool:
    return any(m.startswith("Successfully") for m in messages)


@pytest.mark.parametrize("verdict", [True, None])
def test_charger_success_is_still_logged_when_confirmed_or_nothing_to_confirm(
    caplog, verdict
):
    with caplog.at_level(logging.DEBUG):
        assert _run(_account(verdict).set_battery_charger(VIN, True, False)) is True
    assert _claims_success(_debug_messages(caplog))


def test_charger_success_is_not_logged_when_the_car_did_not_confirm(caplog):
    with caplog.at_level(logging.DEBUG):
        assert _run(_account(False).set_battery_charger(VIN, True, False)) is True
    messages = _debug_messages(caplog)
    assert not _claims_success(messages)
    assert any("not confirmed" in m for m in messages)


@pytest.mark.parametrize("verdict", [True, None])
def test_climate_success_is_still_logged_when_confirmed_or_nothing_to_confirm(
    caplog, verdict
):
    with caplog.at_level(logging.DEBUG):
        assert _run(_account(verdict).start_climate_control(VIN, temp_c=20)) is True
    assert _claims_success(_debug_messages(caplog))


def test_climate_success_is_not_logged_when_the_car_did_not_confirm(caplog):
    with caplog.at_level(logging.DEBUG):
        assert _run(_account(False).start_climate_control(VIN, temp_c=20)) is True
    messages = _debug_messages(caplog)
    assert not _claims_success(messages)
    assert any("not confirmed" in m for m in messages)
