"""Entity creation gated on what the car can do, not on what this poll carried.

The bug: is_entity_supported asks whether a value is present right now. A
rate-limited poll on a live vehicle removed sixteen entities, among them a
parking-position sensor for a car whose capability list plainly includes
parkingPosition. They came back only after a reload.

userCapabilities answers the right question and is stable across polls. It was
commented out of JOBS2QUERY on 2024-03-02 and never used.
"""

from __future__ import annotations

import copy

import pytest

from custom_components.audiconnect.audi_entity import is_entity_supported
from custom_components.audiconnect.audi_models import VehicleDataResponse

from tests.fixture_q8_etron import PAYLOAD


def states_of(payload):
    return {s["name"]: s["value"] for s in VehicleDataResponse(payload).states}


class Vehicle:
    """Stands in for AudiConnectVehicle: the three-valued has_capability plus
    whatever attributes the poll happened to carry."""

    def __init__(self, caps=None, **attrs):
        self._caps = caps
        for k, v in attrs.items():
            setattr(self, k, v)

    def has_capability(self, capability):
        # Mirrors AudiConnectVehicle.has_capability, including empty meaning
        # "said nothing". test_the_real_has_capability_matches_this_stub pins
        # that, so the stub cannot drift from the thing it stands in for.
        if not self._caps:
            return None
        return capability in self._caps


# --- parsing ----------------------------------------------------------------------


def test_the_capability_list_is_parsed():
    states = states_of(copy.deepcopy(PAYLOAD))
    caps = states["userCapabilities"]
    assert "parkingPosition" in caps
    assert "charging" in caps
    assert "honkAndFlash" in caps
    assert caps == sorted(caps)


def test_capabilities_reporting_an_error_are_recorded_separately():
    """Listed is not the same as working: two entries carry status codes."""
    states = states_of(copy.deepcopy(PAYLOAD))
    assert states["userCapabilitiesImpaired"] == ["onlineLogBook", "rewardChallenges"]
    # control: those ids are in the main list too
    assert "onlineLogBook" in states["userCapabilities"]


def test_the_job_is_actually_requested():
    """It was commented out of JOBS2QUERY, so parsing it would have been dead
    code. This is the call-site half."""
    import inspect

    from custom_components.audiconnect import audi_services

    source = inspect.getsource(audi_services.AudiService.get_stored_vehicle_data)
    assert '"userCapabilities",' in source
    assert '# "userCapabilities"' not in source


def test_a_payload_without_the_block_yields_nothing():
    payload = copy.deepcopy(PAYLOAD)
    del payload["userCapabilities"]
    states = states_of(payload)
    assert "userCapabilities" not in states
    # control: the rest still parses
    assert states["climatisationState"] == "off"


@pytest.mark.parametrize(
    "value", [None, [], "notalist", [{"noid": 1}], [{"id": ""}], [{"id": 5}]]
)
def test_junk_in_the_block_is_ignored(value):
    payload = copy.deepcopy(PAYLOAD)
    payload["userCapabilities"]["capabilitiesStatus"]["value"] = value
    assert "userCapabilities" not in states_of(payload)


# --- the gate ---------------------------------------------------------------------


def test_a_capable_car_keeps_the_entity_when_the_value_is_missing():
    """The whole point: the poll carried no position, the car does parking
    position, so the entity is created and goes unavailable rather than away."""
    vehicle = Vehicle(caps={"parkingPosition"})  # no position attribute at all
    assert is_entity_supported(vehicle, "position", "parkingPosition") is True


def test_an_incapable_car_does_not_get_the_entity():
    vehicle = Vehicle(caps={"charging"}, position="somewhere")
    assert is_entity_supported(vehicle, "position", "parkingPosition") is False


def test_a_car_that_reports_no_list_falls_back_to_the_old_behaviour():
    """The important half. Treating "did not say" as "not capable" would strip
    every entity from vehicles that never report the list."""
    silent_with_data = Vehicle(caps=None, position="somewhere")
    silent_without = Vehicle(caps=None)
    assert is_entity_supported(silent_with_data, "position", "parkingPosition") is True
    assert is_entity_supported(silent_without, "position", "parkingPosition") is False


def test_an_empty_list_counts_as_no_list():
    """A car reporting zero capabilities is saying nothing useful, not saying
    it can do nothing."""
    vehicle = Vehicle(caps=set(), position="somewhere")
    assert is_entity_supported(vehicle, "position", "parkingPosition") is True


def test_no_capability_named_means_unchanged_behaviour():
    """Every description that names no capability must behave exactly as before,
    which is what keeps this change small."""
    with_data = Vehicle(caps={"parkingPosition"}, position="somewhere")
    without = Vehicle(caps={"parkingPosition"})
    assert is_entity_supported(with_data, "position") is True
    assert is_entity_supported(without, "position") is False


def test_a_supported_property_still_wins_when_no_capability_is_named():
    vehicle = Vehicle(caps=None, position="somewhere", position_supported=False)
    assert is_entity_supported(vehicle, "position") is False


def test_an_object_without_has_capability_falls_back():
    """Older or stubbed vehicle objects must not crash the gate."""

    class Bare:
        position = "somewhere"

    assert is_entity_supported(Bare(), "position", "parkingPosition") is True


def test_the_real_has_capability_matches_this_stub():
    """Guard against the stub drifting from the implementation: the first
    version of this stub treated an empty list as "not capable" while the real
    property treats it as "said nothing", and the test that mattered failed
    for that reason alone."""
    from custom_components.audiconnect.audi_connect_account import AudiConnectVehicle

    real = object.__new__(AudiConnectVehicle)
    real._vehicle = type("V", (), {"state": {}})()

    for caps, expected in (
        (None, None),
        ([], None),
        (["parkingPosition"], True),
        (["charging"], False),
    ):
        real._vehicle.state = {} if caps is None else {"userCapabilities": caps}
        assert real.has_capability("parkingPosition") is expected, caps
        assert Vehicle(caps=caps).has_capability("parkingPosition") is expected, caps
