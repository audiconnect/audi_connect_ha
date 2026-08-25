"""The position sensor reports a location, but not how old it is.

parkingposition carries its own carCapturedTimestamp and only moves when the car
reports a new position, so device_tracker can show a confident `home` that is
hours stale, and nothing in Home Assistant distinguishes that from a live fix.
These pin the accessor that exposes the capture time, including the case where
the vehicle omits the timestamp entirely (update_vehicle_position stores None
for it rather than failing).

    python3 -m pytest phase-audi-charging/tests -q

Exercises the REAL AudiConnectVehicle property, with its state dict populated
the way update_vehicle_position populates it. The service is never touched by
this code path, so no HTTP boundary is mocked and the test fails if the property
is absent or wrong.
"""

from __future__ import annotations

import datetime

import pytest


from custom_components.audiconnect.audi_connect_account import AudiConnectVehicle


class _Stub:
    """AudiConnectVehicle only reads `vin` from the vehicle at construction and
    never touches the service for this property, so the real class can be built
    directly rather than reimplemented in the test."""

    vin = "WAUZZZ00000000000"


def _accessor(position):
    """The REAL AudiConnectVehicle, with its state dict populated the way
    update_vehicle_position populates it."""
    v = AudiConnectVehicle(audi_service=None, vehicle=_Stub())
    if position is not None:
        v._vehicle.state["position"] = position
    return v


CAPTURED = datetime.datetime(2026, 8, 21, 17, 57, 41, tzinfo=datetime.UTC)


def test_reports_the_capture_time():
    a = _accessor({"latitude": 50.86, "longitude": -0.15, "timestamp": CAPTURED})
    assert a.position_last_updated_supported is True
    assert a.position_last_updated == CAPTURED


def test_absent_timestamp_is_unsupported_not_an_error():
    """update_vehicle_position stores timestamp None when the car omits
    carCapturedTimestamp, so the entity must simply not be offered."""
    a = _accessor({"latitude": 50.86, "longitude": -0.15, "timestamp": None})
    assert a.position_last_updated_supported is False
    assert a.position_last_updated is None


def test_no_position_at_all_is_unsupported():
    """Cars without position support never write the key."""
    a = _accessor(None)
    assert a.position_last_updated_supported is False
    assert a.position_last_updated is None


def test_position_present_but_missing_timestamp_key():
    a = _accessor({"latitude": 50.86, "longitude": -0.15})
    assert a.position_last_updated_supported is False
    assert a.position_last_updated is None


def test_a_stale_capture_is_still_reported():
    """The point of the sensor: an old timestamp is a VALUE, not a failure. The
    caller decides what is too old; the integration must not silently hide it."""
    stale = datetime.datetime(2026, 8, 14, 6, 0, tzinfo=datetime.UTC)
    a = _accessor({"latitude": 50.86, "longitude": -0.15, "timestamp": stale})
    assert a.position_last_updated == stale
    assert (CAPTURED - a.position_last_updated).days == 7


def test_timestamp_is_timezone_aware():
    """SensorDeviceClass.TIMESTAMP rejects a naive datetime, so a tz-naive value
    would break the entity at runtime rather than at parse time."""
    a = _accessor({"latitude": 50.86, "longitude": -0.15, "timestamp": CAPTURED})
    value = a.position_last_updated
    assert value.tzinfo is not None
    assert value.utcoffset() is not None


@pytest.mark.parametrize("falsy", [{}, None])
def test_empty_position_shapes_do_not_raise(falsy):
    assert _accessor(falsy).position_last_updated is None
