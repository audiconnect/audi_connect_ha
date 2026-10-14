"""#865: a command the car never confirmed must not be logged as a success.

The confirmation helper used to return nothing whether the car confirmed or the
wait ran out, so the account layer logged "Successfully started ..." straight
after the helper's own "not confirmed" warning. The log in #865 shows both lines
in the same millisecond.

The helper now says which it was. The services pass that up, and the account
layer only claims success when it was not told otherwise: None (nothing to
confirm against, or a legacy path that settled it itself) keeps the old line.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import create_autospec

import pytest
from aiohttp import ClientResponseError, RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from custom_components.audiconnect import audi_services
from custom_components.audiconnect.audi_connect_account import AudiConnectAccount
from custom_components.audiconnect.audi_services import AudiService

VIN = "WAUZZZ00000000000"
REQ = "a769422d-cb80-45a0-94f7-a2c5ea2514a9"
OTHER = "0b1e5f3c-7a52-4c54-9a53-3f4b3c9d2e11"
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

    def pending(self) -> list[dict]:
        status = self.statuses[min(self.polls, len(self.statuses) - 1)]
        return [{"id": REQ, "status": status}]

    async def request(self, method, url, headers=None, data=None, **kwargs):
        if url.endswith("/pendingrequests"):
            entries = self.pending()
            self.polls += 1
            return {"data": entries}
        if self.request_id is None:
            return {"data": {}}
        return {"data": {"requestID": self.request_id}}


class _CrowdedAPI(_API):
    """A real gateway lists every request in flight, not just ours."""

    def __init__(self, ours: str, theirs: str) -> None:
        super().__init__([ours])
        self.theirs = theirs

    def pending(self) -> list[dict]:
        return [
            {"id": OTHER, "status": self.theirs},
            {"id": REQ, "status": self.statuses[0]},
        ]


class _NoContentAPI(_API):
    """The command POST answers 204, which the shared request helper raises on."""

    async def request(self, method, url, headers=None, data=None, **kwargs):
        if url.endswith("/pendingrequests"):
            return await super().request(method, url, headers, data, **kwargs)
        info = RequestInfo(URL(url), method, CIMultiDictProxy(CIMultiDict()), URL(url))
        raise ClientResponseError(info, (), status=204)


def _service(
    statuses: list[str] | None = None,
    request_id: str | None = REQ,
    api: _API | None = None,
    api_level: int = 1,
    country: str = "DE",
) -> tuple[AudiService, _API]:
    api = api or _API(statuses or ["successful"], request_id)
    service = AudiService(api, country, None, api_level)
    service._bearer_token_json = {"access_token": "t"}
    return service, api


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    async def _sleep(_seconds):
        return None

    monkeypatch.setattr(audi_services.asyncio, "sleep", _sleep)


def _run(coro):
    return asyncio.run(coro)


# --- the helper and the services say whether the car confirmed -----------------


def test_the_helper_reports_a_confirmed_request():
    service, _api = _service(["successful"])
    assert _run(service._confirm_vehicle_request(VIN, "start", REQ)) is True


def test_the_helper_reports_an_unconfirmed_request():
    """The must-fire case: attempts run out with the car still in progress."""
    service, _api = _service(["in_progress"])
    assert _run(service._confirm_vehicle_request(VIN, "start", REQ)) is False


def test_a_rejection_still_raises_rather_than_reporting_unconfirmed():
    service, _api = _service(["failed"])
    with pytest.raises(Exception, match="rejected by the vehicle"):
        _run(service._confirm_vehicle_request(VIN, "start", REQ))


def test_another_requests_success_does_not_confirm_ours():
    """The gateway lists every request in flight. Taking any entry as ours would
    report True for a command the car never acted on, which is the false
    success this change exists to stop."""
    service, _api = _service(api=_CrowdedAPI(ours="in_progress", theirs="successful"))
    assert _run(service._confirm_vehicle_request(VIN, "start", REQ)) is False


def test_another_requests_failure_does_not_reject_ours():
    service, _api = _service(api=_CrowdedAPI(ours="successful", theirs="failed"))
    assert _run(service._confirm_vehicle_request(VIN, "start", REQ)) is True


@pytest.mark.parametrize(
    ("statuses", "expected"), [(["successful"], True), (["in_progress"], False)]
)
def test_start_charging_passes_the_verdict_up(statuses, expected):
    service, _api = _service(statuses)
    assert _run(service.set_battery_charger(VIN, True, False)) is expected


@pytest.mark.parametrize(
    ("statuses", "expected"), [(["successful"], True), (["in_progress"], False)]
)
def test_start_climatisation_passes_the_verdict_up(statuses, expected):
    service, _api = _service(statuses)
    assert _run(service.start_climate_control(VIN, temp_c=20)) is expected


def test_charging_confirmed_on_a_later_poll_is_confirmed():
    service, api = _service(["in_progress", "successful"])
    assert _run(service.set_battery_charger(VIN, True, False)) is True
    assert api.polls == 2


def test_charging_gives_up_after_its_attempt_budget():
    service, api = _service(["in_progress"])
    assert _run(service.set_battery_charger(VIN, True, False)) is False
    assert api.polls == audi_services.CHARGING_CONFIRM_ATTEMPTS


def test_climatisation_gives_up_after_its_attempt_budget():
    service, api = _service(["in_progress"])
    assert _run(service.start_climate_control(VIN, temp_c=20)) is False
    assert api.polls == audi_services.CLIMATISATION_CONFIRM_ATTEMPTS


def test_no_request_id_means_nothing_to_confirm_not_unconfirmed():
    """None is not False: a gateway that returns no requestID gave us nothing to
    wait on, and calling that 'unconfirmed' would warn about every such car."""
    service, api = _service(["in_progress"], request_id=None)
    assert _run(service.set_battery_charger(VIN, True, False)) is None
    assert _run(service.start_climate_control(VIN, temp_c=20)) is None
    assert api.polls == 0


def test_a_204_is_an_acceptance_with_nothing_to_confirm():
    service, api = _service(api=_NoContentAPI(["in_progress"]))
    assert _run(service.set_battery_charger(VIN, True, False)) is None
    assert api.polls == 0


def test_timer_mode_is_a_preference_with_nothing_to_confirm():
    service, _api = _service(["in_progress"])
    assert _run(service.set_battery_charger(VIN, True, True)) is None


def test_the_legacy_climatisation_path_has_no_verdict_to_pass_up():
    """api_level 0 confirms through check_request_succeeded, which raises on a
    failure or a timeout, so what returns is None and the account keeps the
    success line. The poll must actually have run for that to mean anything."""
    api = _API(["in_progress"])

    async def _request(method, url, headers=None, data=None, **kwargs):
        return {"action": {"actionId": "a"}}

    api.request = _request
    service, _api_ = _service(api=api, api_level=0, country="US")
    service.vwToken = {"access_token": "t"}
    polled = []

    async def _poll(*args, **kwargs):
        polled.append(args)

    service.check_request_succeeded = _poll
    assert _run(service.start_climate_control(VIN, temp_c=20)) is None
    assert len(polled) == 1


# --- the account layer only claims success when it was not told otherwise ------


def _account(verdict=None, error: Exception | None = None) -> AudiConnectAccount:
    """The real account over a service that has the real signatures."""
    service = create_autospec(AudiService, instance=True)
    if error is not None:
        service.set_battery_charger.side_effect = error
        service.start_climate_control.side_effect = error
    else:
        service.set_battery_charger.return_value = verdict
        service.start_climate_control.return_value = verdict
    account = object.__new__(AudiConnectAccount)
    account._loggedin = True
    account._observers = []
    account._audi_service = service
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
    assert f"Successfully started charger for vehicle {VIN}" in _debug_messages(caplog)


@pytest.mark.parametrize(("activate", "word"), [(True, "start"), (False, "stop")])
def test_charger_success_is_not_logged_when_the_car_did_not_confirm(
    caplog, activate, word
):
    with caplog.at_level(logging.DEBUG):
        assert _run(_account(False).set_battery_charger(VIN, activate, False)) is True
    messages = _debug_messages(caplog)
    assert not _claims_success(messages)
    assert (
        f"Charger {word} command accepted for vehicle {VIN} but not confirmed by the car"
        in messages
    )


@pytest.mark.parametrize("verdict", [True, None])
def test_climate_success_is_still_logged_when_confirmed_or_nothing_to_confirm(
    caplog, verdict
):
    with caplog.at_level(logging.DEBUG):
        assert _run(_account(verdict).start_climate_control(VIN, temp_c=20)) is True
    assert f"Successfully started climate control of vehicle {VIN}" in _debug_messages(
        caplog
    )


def test_climate_success_is_not_logged_when_the_car_did_not_confirm(caplog):
    with caplog.at_level(logging.DEBUG):
        assert _run(_account(False).start_climate_control(VIN, temp_c=20)) is True
    messages = _debug_messages(caplog)
    assert not _claims_success(messages)
    assert (
        f"Climate control start accepted for vehicle {VIN} but not confirmed by the car"
        in messages
    )


def test_a_failing_service_logs_neither_success_nor_acceptance(caplog):
    """The except path: a rejected command must not read as accepted."""
    account = _account(error=Exception("rejected by the vehicle"))
    with caplog.at_level(logging.DEBUG):
        assert not _run(account.set_battery_charger(VIN, True, False))
        assert not _run(account.start_climate_control(VIN, temp_c=20))
    messages = _debug_messages(caplog)
    assert not _claims_success(messages)
    assert not any("accepted" in m for m in messages)
