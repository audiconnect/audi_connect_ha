"""A 401 from the legacy preheater endpoint is "not available", not an error.

Upstream #862 (guidobbb): every poll logged a full traceback because the legacy
fs-car status endpoint answered 401 for that account, and there was no entity
to switch off to make it stop. 401 was falling through to the
generic error path, once per VIN, with the full VIN in the message. It now
joins the 403/502 branch: logged at debug, feature left on, because a 401 can
also be a temporary account ban (Kolbi on #864) and disabling until restart
would be the wrong answer to that.

The redaction half is the same defect in six messages, so it is fixed in all
six rather than in the one the issue happened to hit.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from aiohttp import ClientResponseError, RequestInfo
from multidict import CIMultiDictProxy, CIMultiDict
from yarl import URL

from custom_components.audiconnect.audi_connect_account import AudiConnectVehicle

VIN = "WAUZZZ4M1RD012345"


class FakeVehicle:
    vin = VIN
    csid = "csid"
    title = "Test"
    model = "A4"
    model_year = "2019"
    model_family = "A4"


class FailingService:
    """The legacy endpoints raise; the modern one is not consulted here."""

    def __init__(self, status: int):
        self._status = status
        self.calls = 0

    def _raise(self):
        self.calls += 1
        # str(ClientResponseError) reads request_info.real_url, so it needs one.
        info = RequestInfo(
            url=URL("https://fal-3a.prd.eu.dp.vwg-connect.com/fs-car/status"),
            method="GET",
            headers=CIMultiDictProxy(CIMultiDict()),
            real_url=URL("https://fal-3a.prd.eu.dp.vwg-connect.com/fs-car/status"),
        )
        raise ClientResponseError(
            request_info=info, history=(), status=self._status, message="Unauthorized"
        )

    async def get_preheater(self, vin):
        self._raise()

    async def get_charger(self, vin):
        self._raise()

    async def get_stored_vehicle_data(self, vin):
        self._raise()


def run(coro):
    return asyncio.run(coro)


# --- the 401 ----------------------------------------------------------------------


def test_a_401_is_quiet_and_keeps_the_feature_on(caplog):
    v = AudiConnectVehicle(FailingService(401), FakeVehicle())
    with caplog.at_level(logging.DEBUG):
        run(v.update_vehicle_preheater())
    assert v.support_preheater is True
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [
        r
        for r in caplog.records
        if r.levelno == logging.DEBUG and "401" in r.getMessage()
    ]


def test_a_401_is_retried_on_the_next_poll():
    svc = FailingService(401)
    v = AudiConnectVehicle(svc, FakeVehicle())
    run(v.update_vehicle_preheater())
    run(v.update_vehicle_preheater())
    assert svc.calls == 2


def test_a_404_is_not_retried():
    svc = FailingService(404)
    v = AudiConnectVehicle(svc, FakeVehicle())
    run(v.update_vehicle_preheater())
    run(v.update_vehicle_preheater())
    assert svc.calls == 1


def test_the_control_a_500_is_still_an_error_and_keeps_the_feature(caplog):
    """So the test above is not passing because nothing ever logs."""
    v = AudiConnectVehicle(FailingService(500), FakeVehicle())
    with caplog.at_level(logging.DEBUG):
        run(v.update_vehicle_preheater())
    assert v.support_preheater is True
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_404_still_disables_too(caplog):
    v = AudiConnectVehicle(FailingService(404), FakeVehicle())
    with caplog.at_level(logging.DEBUG):
        run(v.update_vehicle_preheater())
    assert v.support_preheater is False


# --- the VIN ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "method",
    [
        "update_vehicle_preheater",
        "update_vehicle_charger",
        "update_vehicle_statusreport",
    ],
)
def test_an_error_message_never_carries_the_full_vin(caplog, method):
    """The issue's own log shows the reporter redacting it by hand. The debug
    lines in these functions already use a redacted form; the error lines did
    not."""
    v = AudiConnectVehicle(FailingService(500), FakeVehicle())
    with caplog.at_level(logging.DEBUG):
        run(getattr(v, method)())
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "the control: a 500 must still log"
    for msg in errors:
        assert VIN not in msg, msg
        assert VIN[-4:] in msg, (
            "the last four should survive so a user can tell cars apart"
        )
