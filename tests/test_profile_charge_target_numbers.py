"""Per-location charge target numbers.

Profiles are enumerated from the real Q8 payload rather than an invented list,
so the entities are built from the shape the car actually reports (two profiles,
"Home" at 60% and "Work" at 100%, the car parked in profile 1).
"""

from __future__ import annotations

import asyncio
import copy

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.audiconnect.audi_models import VehicleDataResponse
from custom_components.audiconnect.number import (
    NUMBER_DESCRIPTIONS,
    AudiProfileChargeTarget,
    _profiles,
)

from tests.fixture_q8_etron import PAYLOAD


class StubCoordinator:
    """Stands in for the update coordinator; only availability is read here."""

    last_update_success = True

    def __init__(self, connection=None):
        self.account = type("Account", (), {"connection": connection})()
        self.refreshed = 0

    async def async_request_refresh(self):
        self.refreshed += 1


class StubVehicle:
    def __init__(self, states):
        self.vin = "WAUZZZ00000000001"
        self._states = states

    @property
    def charging_profiles(self):
        return self._states.get("chargingProfiles")


@pytest.fixture
def vehicle():
    resp = VehicleDataResponse(copy.deepcopy(PAYLOAD))
    return StubVehicle({s["name"]: s["value"] for s in resp.states})


def build(vehicle, connection=None):
    coordinator = StubCoordinator(connection)
    entities = [
        AudiProfileChargeTarget(coordinator, vehicle, p) for p in _profiles(vehicle)
    ]
    return coordinator, entities


# --- enumeration ------------------------------------------------------------------


def test_one_entity_per_profile_in_the_payload(vehicle):
    _, entities = build(vehicle)
    assert [e.name for e in entities] == ["Home charge target", "Work charge target"]
    assert [e.native_value for e in entities] == [60.0, 100.0]


def test_unique_id_is_keyed_on_profile_id_not_name(vehicle):
    _, entities = build(vehicle)
    assert [e.unique_id for e in entities] == [
        "wauzzz00000000001_number_charge_profile_1_target_soc",
        "wauzzz00000000001_number_charge_profile_2_target_soc",
    ]


def test_renaming_a_profile_in_the_car_keeps_the_same_entity(vehicle):
    """Names are editable in the myAudi app, so a rename must not orphan the
    entity. The control: the id is unchanged, so the unique_id is too."""
    _, before = build(vehicle)
    vehicle.charging_profiles[0]["name"] = "Nanna's"
    _, after = build(vehicle)
    assert after[0].unique_id == before[0].unique_id
    assert after[0].name == "Nanna's charge target"


def test_profile_without_a_name_falls_back_to_its_id(vehicle):
    vehicle.charging_profiles[0]["name"] = None
    _, entities = build(vehicle)
    assert entities[0].name == "Profile 1 charge target"


def test_entries_without_an_id_are_skipped(vehicle):
    vehicle.charging_profiles.append({"name": "junk", "targetSOC_pct": 50})
    assert [p["id"] for p in _profiles(vehicle)] == [1, 2]


def test_no_profiles_reported_means_no_entities():
    _, entities = build(StubVehicle({}))
    assert entities == []


# --- tracking the payload ---------------------------------------------------------


def test_value_follows_the_profile_rather_than_a_snapshot(vehicle):
    _, entities = build(vehicle)
    vehicle.charging_profiles[0]["targetSOC_pct"] = 85
    assert entities[0].native_value == 85.0


def test_deleting_a_profile_makes_its_entity_unavailable(vehicle):
    _, entities = build(vehicle)
    assert entities[0].available is True  # positive control
    del vehicle.charging_profiles[0]
    assert entities[0].available is False
    assert entities[0].native_value is None


def test_unavailable_when_the_coordinator_is_failing(vehicle):
    coordinator, entities = build(vehicle)
    coordinator.last_update_success = False
    assert entities[0].available is False


# --- writes -----------------------------------------------------------------------


class RecordingConnection:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    async def set_location_charge_target(self, vin, profile_id, target_soc):
        self.calls.append((vin, profile_id, target_soc))
        return self.result


def test_write_targets_that_profile_by_id(vehicle):
    connection = RecordingConnection()
    coordinator, entities = build(vehicle, connection)
    asyncio.run(entities[1].async_set_native_value(80))
    assert connection.calls == [("WAUZZZ00000000001", 2, 80)]
    assert coordinator.refreshed == 1


def test_failed_write_raises_and_does_not_refresh(vehicle):
    connection = RecordingConnection(result=False)
    coordinator, entities = build(vehicle, connection)
    with pytest.raises(HomeAssistantError):
        asyncio.run(entities[0].async_set_native_value(80))
    assert coordinator.refreshed == 0


# --- the two non-profile targets --------------------------------------------------


def test_current_location_number_sends_no_profile_id(vehicle):
    """Omitting the id is what makes it follow the car: the service resolves
    vehiclePositionedInProfileID itself."""
    description = next(
        d for d in NUMBER_DESCRIPTIONS if d.key == "active_charging_profile_target_soc"
    )
    connection = RecordingConnection()
    asyncio.run(description.set_value_fn(connection, "WAUZZZ00000000001", 75))
    assert connection.calls == [("WAUZZZ00000000001", None, 75)]


def test_global_number_is_a_distinct_target(vehicle):
    """The global setting does not govern at a location (#722), so it keeps its
    own entity and its own writer rather than aliasing a profile."""
    keys = {d.key for d in NUMBER_DESCRIPTIONS}
    assert keys == {"target_state_of_charge", "active_charging_profile_target_soc"}
