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
    from custom_components.audiconnect.v3.entities import V3ReadOnlyBinarySensor
    from custom_components.audiconnect.v3.historical_catalog import ATTRIBUTES

    vehicle = car()
    profile = SimpleNamespace(registry=None, attribute_evidence={}, job_discovery={})
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
    moving = V3ReadOnlyBinarySensor(coordinator(), vehicle, ATTRIBUTES["is_moving"])
    assert moving.is_on is None
    assert not moving.available
    from custom_components.audiconnect.v3.capability_status import attribute_status

    assert (
        attribute_status(vehicle, profile, ATTRIBUTES["is_moving"], now)[0]
        == "not_observed"
    )
    assert (
        vehicle.family_readings["park_time"]["cariad"] is vehicle.readings["park_time"]
    )
    position = vehicle.position
    reply.status = 204
    observe_parking(vehicle, profile, reply, operation)
    assert vehicle.position is position
    assert vehicle.readings["is_moving"]["value"] is None
    assert vehicle.readings["is_moving"]["captured"] is None
    assert moving.is_on is None
    assert not moving.available
    reply.status = 200
    reply.data["data"]["carCapturedTimestamp"] = (now - timedelta(hours=2)).isoformat()
    observe_parking(vehicle, profile, reply, operation)
    assert vehicle.position is position
    assert vehicle.readings["park_time"]["captured"] == stamp
    assert vehicle.readings["is_moving"]["value"] is None


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


def test_registered_read_entities_survive_missing_values_on_reload(monkeypatch):
    from custom_components.audiconnect.v3 import ha_platforms

    vehicle = car()
    vin = VIN.lower()
    keys = (
        "charging_plug_auto_unlock",
        "next_climatisation_timer_local",
        "charging_current_limit_a",
        "charging_current_limit_mode",
        "remaining_climatisation_time",
    )
    registered = [
        SimpleNamespace(
            unique_id=f"{vin}_sensor_{key}",
            domain="sensor",
            platform="audiconnect",
        )
        for key in keys
    ]
    # An unrelated VIN must not create a capability on this vehicle.
    registered.append(
        SimpleNamespace(
            unique_id="other_vin_sensor_oil_level",
            domain="sensor",
            platform="audiconnect",
        )
    )
    monkeypatch.setattr(ha_platforms.er, "async_get", lambda _: object())
    monkeypatch.setattr(
        ha_platforms.er, "async_entries_for_config_entry", lambda *_: registered
    )
    ctx = coordinator()
    ctx.hass = object()
    ctx.engine.vehicles = {vin: vehicle}
    ctx.engine.profiles = {}
    entry = SimpleNamespace(
        entry_id="entry",
        runtime_data=SimpleNamespace(v3=ctx.engine, coordinator=ctx),
        async_on_unload=lambda _: None,
    )
    offered = []
    ha_platforms.setup("sensor", entry, offered.extend)
    by_id = {entity.unique_id: entity for entity in offered}
    for key in keys:
        entity = by_id[f"{vin}_sensor_{key}"]
        assert not entity.available
        assert entity.native_value is None
    assert f"{vin}_sensor_oil_level" not in by_id
    assert len(by_id) == len(offered)
    # When data returns, the same entity object becomes available.
    now = datetime.now(UTC).isoformat()
    vehicle.readings["chargingCurrentLimitA"] = {
        "value": 16,
        "status": "verified",
        "captured": now,
        "observed": now,
    }
    entity = by_id[f"{vin}_sensor_charging_current_limit_a"]
    assert entity.available
    assert entity.native_value == 16


def test_registered_conditionals_survive_reload_without_write_permission(monkeypatch):
    from custom_components.audiconnect.v3 import ha_platforms

    vehicle = car()
    vin = VIN.lower()
    keys = {
        "select": "charge_mode",
        "number": "target_state_of_charge",
        "climate": "climatisation",
        "lock": "lock",
        "switch": "charging",
    }
    registry = [
        SimpleNamespace(
            unique_id=f"{vin}_{platform}_{key}", domain=platform, platform="audiconnect"
        )
        for platform, key in keys.items()
    ]
    monkeypatch.setattr(ha_platforms.er, "async_get", lambda _: object())
    monkeypatch.setattr(
        ha_platforms.er, "async_entries_for_config_entry", lambda *_: registry
    )
    ctx = coordinator()
    ctx.hass = object()
    ctx.engine.vehicles = {vin: vehicle}
    ctx.engine.profiles = {}
    ctx.engine.auth = SimpleNamespace()
    entry = SimpleNamespace(
        entry_id="entry",
        runtime_data=SimpleNamespace(v3=ctx.engine, coordinator=ctx),
        async_on_unload=lambda _: None,
    )
    for platform, key in keys.items():
        offered = []
        ha_platforms.setup(platform, entry, offered.extend)
        entity = next(e for e in offered if e.unique_id == f"{vin}_{platform}_{key}")
        assert not entity.available
    # A fresh, valid option can return on the very same select object.
    offered = []
    ha_platforms.setup("select", entry, offered.extend)
    select = offered[0]
    ctx.engine.control_enabled = lambda *args: True
    vehicle.readings["availableChargeModes"] = {"value": ["manual"], "family": "cariad"}
    assert select.available
    assert select.options == ["manual"]
    assert select.current_option is None
