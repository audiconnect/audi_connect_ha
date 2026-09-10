"""The last_update_time scan must tolerate a state that carries no timestamp.

userCapabilities is a statement about the vehicle rather than a reading from
it, so it is the first state to be appended with measure_time None. That value
reaches the freshness scan in update_vehicle_statusreport.

Today the integration's own util.parse_datetime returns None for anything that
is not a datetime or a str, so the scan survives by accident. HA's
homeassistant.util.dt.parse_datetime raises TypeError on the same input, and
swapping to it is an ordinary-looking change. The scan sits above the loop that
assigns self._vehicle.state, inside a broad except Exception, so the failure
would be a silent stop: fields updated, no state updated, one logged error.

Raised by antoinevalentinHA in review of #854.
"""

from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime


from custom_components.audiconnect import audi_connect_account
from custom_components.audiconnect.audi_connect_account import AudiConnectVehicle
from custom_components.audiconnect.audi_models import VehicleDataResponse
from custom_components.audiconnect.util import parse_datetime as real_parse_datetime

from tests.fixture_q8_etron import PAYLOAD


class FakeVehicle:
    vin = "TESTVIN0000000000"
    csid = "csid"
    title = "Test"
    model = "Q8 e-tron"
    model_year = "2023"
    model_family = "e-tron"


class FakeService:
    def __init__(self, payload):
        self._payload = payload

    async def get_stored_vehicle_data(self, vin):
        return VehicleDataResponse(self._payload)


def run_report(payload):
    vehicle = AudiConnectVehicle(FakeService(payload), FakeVehicle())
    asyncio.run(vehicle.update_vehicle_statusreport())
    return vehicle._vehicle


def refuses_none(value):
    """The one property under test: a parse_datetime that will not take None.

    Not a full stand-in for HA's, which also refuses the datetime objects the
    data_fields carry. Modelling that would assert a promise this integration
    never made, and would fail for a reason the review was not about.
    """
    if value is None:
        raise TypeError("argument must be str")
    return real_parse_datetime(value)


def test_the_fixture_actually_produces_an_untimestamped_state():
    # Without this the rest of the file passes for the wrong reason.
    states = VehicleDataResponse(copy.deepcopy(PAYLOAD)).states
    untimed = [s["name"] for s in states if not s.get("measure_time")]
    assert "userCapabilities" in untimed


def test_states_are_assigned_when_a_state_carries_no_timestamp():
    state = run_report(copy.deepcopy(PAYLOAD)).state
    assert "userCapabilities" in state
    # The scan runs above the assignment loop, so a stop there shows up as
    # missing states rather than as an exception.
    assert "chargingState" in state


def test_scan_survives_a_strict_parse_datetime(monkeypatch):
    """The must-fire case: this fails if the loop hands None to parse_datetime."""
    monkeypatch.setattr(audi_connect_account, "parse_datetime", refuses_none)
    state = run_report(copy.deepcopy(PAYLOAD)).state
    assert "userCapabilities" in state
    assert "chargingState" in state


def test_an_untimestamped_state_does_not_move_last_update_time():
    payload = copy.deepcopy(PAYLOAD)
    with_caps = run_report(payload).state["last_update_time"]

    stripped = copy.deepcopy(PAYLOAD)
    stripped.pop("userCapabilities", None)
    without_caps = run_report(stripped).state["last_update_time"]

    assert with_caps == without_caps
    # Control: the scan is doing something, so equality above is not vacuous.
    assert with_caps > datetime(1970, 1, 1, tzinfo=UTC)
