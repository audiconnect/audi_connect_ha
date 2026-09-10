"""The charge mode select.

The trap this guards: the payload carries two chargeMode values, and the one
already parsed is the wrong one. `chargingStatus.value.chargeMode` is the mode
of the charge in progress; `chargeMode.value.preferredChargeMode` is the setting
that set_charge_mode writes. They read the same on a car sitting idle, so a
select bound to the existing field would have looked correct.
"""

from __future__ import annotations

import asyncio
import copy

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.audiconnect.audi_models import VehicleDataResponse
from custom_components.audiconnect.select import AudiChargeModeSelect, _options_for

from tests.fixture_q8_etron import PAYLOAD

VIN = "WAUZZZ00000000001"


def states_of(payload):
    return {s["name"]: s["value"] for s in VehicleDataResponse(payload).states}


class StubCoordinator:
    last_update_success = True

    def __init__(self, connection=None):
        self.account = type("A", (), {"connection": connection})()
        self.refreshed = 0

    async def async_request_refresh(self):
        self.refreshed += 1


class StubVehicle:
    def __init__(self, preferred=None, available=None):
        self.vin = VIN
        self.preferred_charge_mode = preferred
        self.available_charge_modes = available


class RecordingConnection:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    async def set_charge_mode(self, vin, mode):
        self.calls.append((vin, mode))
        return self.result


def build(preferred="manual", available=None, connection=None):
    coordinator = StubCoordinator(connection)
    return coordinator, AudiChargeModeSelect(
        coordinator, StubVehicle(preferred, available)
    )


# --- the two fields are not the same ----------------------------------------------


def test_the_payload_carries_both_and_they_are_parsed_separately():
    states = states_of(copy.deepcopy(PAYLOAD))
    assert states["preferredChargeMode"] == "manual"  # the setting
    assert states["chargeMode"] == "manual"  # the charge in progress
    assert "availableChargeModes" in states


def test_a_disagreement_between_them_is_visible():
    """Control for the test above: on this car both read manual, so force them
    apart and confirm the select follows the setting rather than the status."""
    payload = copy.deepcopy(PAYLOAD)
    payload["charging"]["chargeMode"]["value"]["preferredChargeMode"] = "timer"
    states = states_of(payload)
    assert states["preferredChargeMode"] == "timer"
    assert states["chargeMode"] == "manual"

    _, entity = build(preferred=states["preferredChargeMode"])
    assert entity.current_option == "timer"


# --- options ----------------------------------------------------------------------


def test_the_cars_own_list_wins_when_it_has_one():
    assert _options_for(StubVehicle("manual", ["manual", "timer", "hybrid"])) == [
        "manual",
        "timer",
        "hybrid",
    ]


@pytest.mark.parametrize("reported", [None, [], ["", None]])
def test_an_empty_list_falls_back_to_what_the_service_accepts(reported):
    """The live car reports availableChargeModes as [], so the fallback is the
    normal case rather than the edge case."""
    assert _options_for(StubVehicle("manual", reported)) == ["manual", "timer"]


def test_the_fixture_car_reports_an_empty_list():
    states = states_of(copy.deepcopy(PAYLOAD))
    assert states["availableChargeModes"] == []


# --- current option ---------------------------------------------------------------


def test_current_option_reflects_the_setting():
    _, entity = build(preferred="timer")
    assert entity.current_option == "timer"


@pytest.mark.parametrize("value", [None, "", 0])
def test_an_absent_setting_reads_as_no_selection(value):
    _, entity = build(preferred=value)
    assert entity.current_option is None


def test_a_mode_outside_the_option_list_is_added_to_the_options():
    """Home Assistant renders the entity as unknown when current_option is not
    in options, so an unexpected-but-real mode has to join the list rather than
    just be returned."""
    _, entity = build(preferred="somethingelse", available=["manual", "timer"])
    assert entity.current_option == "somethingelse"
    assert entity.current_option in entity.options


@pytest.mark.parametrize("reported", ["invalid", "unsupported", "unknown", "INVALID"])
def test_a_non_answer_reads_as_no_selection(reported):
    """The live car reports "invalid" while parked, which is a resting state
    rather than an error. It must not be offered as a selectable mode."""
    _, entity = build(preferred=reported)
    assert entity.current_option is None
    assert reported not in entity.options


def test_the_option_list_never_contains_a_non_answer():
    _, entity = build(preferred="manual", available=["manual", "invalid", "timer"])
    assert entity.options == ["manual", "timer"]


def test_current_option_is_always_in_options_or_none():
    """The invariant Home Assistant enforces, checked across every case above."""
    for preferred, available in (
        ("manual", None),
        ("timer", ["manual", "timer"]),
        ("hybrid", ["manual"]),
        ("invalid", []),
        (None, None),
        ("", ["manual"]),
    ):
        _, entity = build(preferred=preferred, available=available)
        assert entity.current_option is None or entity.current_option in entity.options


# --- writing ----------------------------------------------------------------------


def test_selecting_writes_the_mode_and_refreshes():
    connection = RecordingConnection()
    coordinator, entity = build(connection=connection)
    asyncio.run(entity.async_select_option("timer"))
    assert connection.calls == [(VIN, "timer")]
    assert coordinator.refreshed == 1


def test_a_rejected_write_raises_and_does_not_refresh():
    connection = RecordingConnection(result=False)
    coordinator, entity = build(connection=connection)
    with pytest.raises(HomeAssistantError):
        asyncio.run(entity.async_select_option("timer"))
    assert coordinator.refreshed == 0
