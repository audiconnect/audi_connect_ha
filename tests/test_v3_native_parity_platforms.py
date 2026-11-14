"""V3 owns all nine native HA platforms; V2 classes are unchanged."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.audiconnect.v3.entities import (
    V3ChargeModeSelect,
    V3ChargeTargetNumber,
    V3ParkedTracker,
)
from custom_components.audiconnect.v3.parking import (
    parse_parked_position,
    keep_newest_position,
)
from custom_components.audiconnect.v3.vehicle import V3Vehicle


VIN = "WAUZZZ4M0MD123456"


def car():
    return V3Vehicle(
        vin=VIN, name="My Audi", model="Audi Q8", model_family="q8", country="BE"
    )


def coordinator(allow=False):
    return SimpleNamespace(
        engine=SimpleNamespace(
            control_enabled=lambda *args: allow,
        ),
        async_add_listener=lambda listener: None,
        last_update_success=True,
    )


def test_v3_platforms_reuse_exact_v2_unique_ids():
    vehicle = car()
    ctx = coordinator()
    number = V3ChargeTargetNumber(ctx, vehicle)
    select = V3ChargeModeSelect(ctx, vehicle)
    tracker = V3ParkedTracker(ctx, vehicle)
    assert number.unique_id == VIN.lower() + "_number_target_state_of_charge"
    assert select.unique_id == VIN.lower() + "_select_charge_mode"
    assert tracker.unique_id == VIN.lower() + "_device_tracker_position"
    assert number.native_min_value == 20
    assert number.native_max_value == 100
    assert number.native_step == 5
    assert select.options == []
    assert tracker.latitude is None and not tracker.available


def test_v3_parking_position_is_last_known_not_live_and_never_logs_location():
    now = datetime.now(UTC)
    previous = {"latitude": 50.0, "longitude": 4.0, "timestamp": now.isoformat()}
    payload = {
        "data": {
            "lat": 50.10,
            "lon": 4.55,
            "carCapturedTimestamp": (now - timedelta(minutes=10)).isoformat(),
        }
    }
    position = parse_parked_position(payload)
    assert position is not None
    assert not keep_newest_position(previous, position)
    assert keep_newest_position(None, position)
    vehicle = car()
    vehicle.position = position
    tracker = V3ParkedTracker(coordinator(), vehicle)
    assert tracker.available
    assert tracker.latitude == 50.10 and tracker.longitude == 4.55
    assert "last-known parked" in tracker.extra_state_attributes["position_source"]
    assert tracker.extra_state_attributes["position_age_minutes"] >= 10


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"data": {"lat": 100, "lon": 4}},
        {"data": {"lat": 50, "lon": -200}},
        {"data": {"lat": float("nan"), "lon": 4}},
        {"data": {"lat": True, "lon": 4}},
        {"data": {"lat": "invalid", "lon": 4}},
    ],
)
def test_parking_rejects_untrusted_or_invalid_coordinates(payload):
    assert parse_parked_position(payload) is None


def test_charge_targets_and_modes_read_normalized_v3_values():
    vehicle = car()
    captured = datetime.now(UTC).isoformat()
    vehicle.readings = {
        "targetstateOfCharge": {
            "value": 80,
            "captured": captured,
            "status": "verified",
        },
        "availableChargeModes": {
            "value": ["manual", "timer"],
            "captured": captured,
            "status": "verified",
        },
        "preferredChargeMode": {
            "value": "timer",
            "captured": captured,
            "status": "verified",
        },
    }
    ctx = coordinator(allow=True)
    target, mode = V3ChargeTargetNumber(ctx, vehicle), V3ChargeModeSelect(ctx, vehicle)
    assert target.available and target.native_value == 80.0
    assert mode.available and mode.current_option == "timer"
    assert mode.options == ["manual", "timer"]


def test_settings_fail_closed_without_verified_v3_command():
    vehicle = car()
    ctx = coordinator(allow=False)
    assert not V3ChargeTargetNumber(ctx, vehicle).available
    assert not V3ChargeModeSelect(ctx, vehicle).available


def test_all_nine_ha_platforms_have_independent_v3_code():
    import inspect
    from custom_components.audiconnect.v3 import ha_platforms

    code = inspect.getsource(ha_platforms)
    for kind in (
        "sensor",
        "binary_sensor",
        "button",
        "switch",
        "lock",
        "climate",
        "number",
        "select",
        "device_tracker",
    ):
        assert f'"{kind}"' in code
    assert "AudiAccount" not in code
    assert "AudiConnectVehicle" not in code


def test_parking_uses_shared_observations_without_inventing_motion_capture():
    from custom_components.audiconnect.v3.parking import observe_parking

    vehicle = car()
    profile = SimpleNamespace(registry=None)
    now = datetime.now(UTC)
    stamp = (now - timedelta(minutes=10)).isoformat()
    reply = SimpleNamespace(
        status=200,
        observed_at=now,
        data={"data": {"lat": 50.0, "lon": 4.0, "carCapturedTimestamp": stamp}},
    )
    operation = "cariad.mobility.status.parkingPosition"
    observe_parking(vehicle, profile, reply, operation)
    assert vehicle.readings["park_time"]["captured"] == stamp
    assert vehicle.readings["position_last_updated"]["status"] == "verified"
    assert vehicle.readings["is_moving"]["value"] is False
    assert vehicle.readings["is_moving"]["captured"] is None
    assert vehicle.readings["is_moving"]["status"] == "readable_but_stale"
    assert (
        vehicle.family_readings["park_time"]["cariad"] is vehicle.readings["park_time"]
    )
    position = vehicle.position
    reply.status = 204
    observe_parking(vehicle, profile, reply, operation)
    assert vehicle.position is position
    assert vehicle.readings["is_moving"]["value"] is True
    assert vehicle.readings["is_moving"]["captured"] is None
    reply.status = 200
    reply.data["data"]["carCapturedTimestamp"] = (now - timedelta(hours=2)).isoformat()
    observe_parking(vehicle, profile, reply, operation)
    assert vehicle.position is position
    assert vehicle.readings["park_time"]["captured"] == stamp
    assert vehicle.readings["is_moving"]["value"] is True


@pytest.mark.parametrize("invalid", ["2026-01-01T00:00:00", "2099-01-01T00:00:00Z"])
def test_parking_invalid_capture_cannot_poison_position_recovery(invalid):
    now = datetime.now(UTC)
    stamp = (now - timedelta(minutes=5)).isoformat()
    point = parse_parked_position(
        {"data": {"lat": 50, "lon": 4, "carCapturedTimestamp": invalid}}, now
    )
    assert point["timestamp"] is None
    good = parse_parked_position(
        {"data": {"lat": 51, "lon": 4, "carCapturedTimestamp": stamp}}, now
    )
    assert keep_newest_position({"timestamp": invalid}, good, now)
    assert not keep_newest_position(good, point, now)
