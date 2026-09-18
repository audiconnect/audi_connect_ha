"""The lock reads the car's own lock verdict, and says nothing rather than
"unlocked" when it has no data.

Upstream #861 (EPICENTER24): on a two-door A5 the lock entity read unlocked
while the car was locked. Two defects stacked. doors_trunk_status requires all
four door fields, a coupé has no rear ones, so it returned None and
is_locked compared None == "Locked". And lock_supported was a method without
@property, so the support check saw a bound method, always truthy, and created
the lock whether or not it could ever know the state.

The car has said the answer all along: access.accessStatus.value.doorLockStatus
is "locked" or "unlocked" for the vehicle as a whole. It was fetched on every
poll and never parsed.
"""

from __future__ import annotations

import copy
import datetime

from custom_components.audiconnect.audi_connect_account import AudiConnectVehicle
from custom_components.audiconnect.audi_models import VehicleDataResponse
from custom_components.audiconnect.lock import AudiLock

from tests.fixture_q8_etron import PAYLOAD

CAPTURED = datetime.datetime(2026, 8, 18, 21, 9, 17, tzinfo=datetime.UTC)


def states_of(payload):
    return {s["name"]: s["value"] for s in VehicleDataResponse(payload).states}


def two_door(payload, lock_status="locked"):
    """A coupé: no rear doors in the access block."""
    p = copy.deepcopy(payload)
    access = p["access"]["accessStatus"]["value"]
    access["doors"] = [d for d in access["doors"] if not d["name"].startswith("rear")]
    access["doorLockStatus"] = lock_status
    return p


class _Service:
    def __init__(self, spin):
        self._spin = spin


class _Stub:
    vin = "WAUZZZ00000000000"


def vehicle(state: dict, spin="1234"):
    """Legacy per-door values (LOCK_STATE_*, OPEN_STATE_*) live in `fields`;
    the modern car-wide verdict lives in `state`. That split is the real one."""
    v = AudiConnectVehicle(audi_service=_Service(spin), vehicle=_Stub())
    for k, val in state.items():
        (v._vehicle.fields if "_STATE_" in k else v._vehicle.state)[k] = val
    return v


class _Coordinator:
    last_update_success = True

    def async_add_listener(self, *a, **k):
        return lambda: None


# --- parsing --------------------------------------------------------------------


def test_the_car_wide_lock_status_is_parsed():
    states = states_of(copy.deepcopy(PAYLOAD))
    assert states["doorLockStatus"] == "locked"


def test_it_carries_the_access_block_timestamp():
    ts = {s["name"]: s["measure_time"] for s in VehicleDataResponse(PAYLOAD).states}
    assert ts["doorLockStatus"] == CAPTURED


def test_a_two_door_car_still_reports_it():
    """The per-door path collapses on a coupé; this one does not."""
    states = states_of(two_door(PAYLOAD))
    assert states["doorLockStatus"] == "locked"
    assert "LOCK_STATE_LEFT_REAR_DOOR" not in states


# --- the vehicle's view -----------------------------------------------------------


def test_doors_trunk_status_is_none_on_a_two_door_car():
    """Documents the shape #861 hit, rather than fixing it here: the sensor
    that reads this is a separate decision. The lock no longer depends on it."""
    v = vehicle(
        {
            "LOCK_STATE_LEFT_FRONT_DOOR": "2",
            "LOCK_STATE_RIGHT_FRONT_DOOR": "2",
            "LOCK_STATE_TRUNK_LID": "2",
            "OPEN_STATE_LEFT_FRONT_DOOR": "3",
            "OPEN_STATE_RIGHT_FRONT_DOOR": "3",
            "OPEN_STATE_TRUNK_LID": "3",
        }
    )
    assert v.doors_trunk_status is None


def test_door_lock_status_reads_the_car_wide_verdict():
    assert vehicle({"doorLockStatus": "locked"}).door_lock_status == "locked"
    assert vehicle({"doorLockStatus": "unlocked"}).door_lock_status == "unlocked"


def test_door_lock_status_is_unsupported_when_absent_or_unsupported():
    assert vehicle({}).door_lock_status_supported is False
    assert (
        vehicle({"doorLockStatus": "unsupported"}).door_lock_status_supported is False
    )


def test_lock_supported_is_a_property_and_reads_false_without_a_spin():
    """#861's second finding. A bound method is truthy, so the old check created
    the lock on every car. Now it is a value, and it says no without an S-PIN."""
    assert isinstance(AudiConnectVehicle.lock_supported, property)
    assert vehicle({"doorLockStatus": "locked"}, spin=None).lock_supported is False
    assert vehicle({"doorLockStatus": "locked"}, spin="1234").lock_supported is True


def test_lock_supported_needs_some_source_of_truth():
    """An S-PIN alone is not enough: with neither the car-wide status nor all
    four doors, there is nothing to report."""
    assert vehicle({}, spin="1234").lock_supported is False


# --- the entity --------------------------------------------------------------------


def lock_for(state, spin="1234"):
    return AudiLock(_Coordinator(), vehicle(state, spin))


def test_the_regression_a_locked_two_door_car_reads_locked():
    """The must-fire case from #861: doors_trunk_status is None here, and the
    old is_locked would have said unlocked."""
    v = vehicle(
        {
            "doorLockStatus": "locked",
            "LOCK_STATE_LEFT_FRONT_DOOR": "2",
            "LOCK_STATE_RIGHT_FRONT_DOOR": "2",
            "LOCK_STATE_TRUNK_LID": "2",
        }
    )
    assert v.doors_trunk_status is None
    assert AudiLock(_Coordinator(), v).is_locked is True


def test_an_unlocked_car_reads_unlocked():
    """The control, so the test above is not passing on a constant."""
    assert lock_for({"doorLockStatus": "unlocked"}).is_locked is False


def test_the_car_wide_status_wins_over_the_per_door_derivation():
    """They should agree; when they do not, the car's own verdict is the one the
    app shows, so it is the one the lock shows."""
    v = vehicle(
        {
            "doorLockStatus": "unlocked",
            "LOCK_STATE_LEFT_FRONT_DOOR": "2",
            "LOCK_STATE_RIGHT_FRONT_DOOR": "2",
            "LOCK_STATE_LEFT_REAR_DOOR": "2",
            "LOCK_STATE_RIGHT_REAR_DOOR": "2",
            "LOCK_STATE_TRUNK_LID": "2",
            "OPEN_STATE_LEFT_FRONT_DOOR": "3",
            "OPEN_STATE_RIGHT_FRONT_DOOR": "3",
            "OPEN_STATE_LEFT_REAR_DOOR": "3",
            "OPEN_STATE_RIGHT_REAR_DOOR": "3",
            "OPEN_STATE_TRUNK_LID": "3",
        }
    )
    assert v.doors_trunk_status == "Locked"
    assert AudiLock(_Coordinator(), v).is_locked is False


def test_the_per_door_derivation_still_serves_a_car_without_the_car_wide_field():
    v = vehicle(
        {
            "LOCK_STATE_LEFT_FRONT_DOOR": "2",
            "LOCK_STATE_RIGHT_FRONT_DOOR": "2",
            "LOCK_STATE_LEFT_REAR_DOOR": "2",
            "LOCK_STATE_RIGHT_REAR_DOOR": "2",
            "LOCK_STATE_TRUNK_LID": "2",
            "OPEN_STATE_LEFT_FRONT_DOOR": "3",
            "OPEN_STATE_RIGHT_FRONT_DOOR": "3",
            "OPEN_STATE_LEFT_REAR_DOOR": "3",
            "OPEN_STATE_RIGHT_REAR_DOOR": "3",
            "OPEN_STATE_TRUNK_LID": "3",
        }
    )
    assert AudiLock(_Coordinator(), v).is_locked is True


def test_no_data_is_unknown_not_unlocked():
    """#861's third point, and the whole reason the bug was dangerous: a missing
    value must never be shown as an open door."""
    lock = lock_for({})
    assert lock.is_locked is None
    assert lock.available is False


def test_with_data_the_lock_is_available():
    assert lock_for({"doorLockStatus": "locked"}).available is True
