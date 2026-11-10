"""CARIAD-only fields from the standalone Audi connector become HA values."""
from __future__ import annotations

from types import SimpleNamespace as NS

from custom_components.audiconnect.audi_connect_account import AudiConnectVehicle
from custom_components.audiconnect.audi_models import VehicleDataResponse
from custom_components.audiconnect.sensor import SENSOR_DESCRIPTIONS


def parsed(data):
    return {x["name"]: x["value"] for x in VehicleDataResponse(data).states}


def test_modern_charging_settings_and_readiness():
    data = {
        "charging": {"chargingSettings": {"value": {
            "carCapturedTimestamp": "2026-11-10T15:00:00Z",
            "maxChargeCurrentAC_A": 12,
            "maxChargeCurrentAC": "reduced",
            "autoUnlockPlugWhenChargedAC": "on",
        }}},
        "readiness": {"readinessStatus": {"value": {
            "connectionState": {"isOnline": True, "isActive": False}
        }}},
    }
    s = parsed(data)
    assert s["chargingCurrentLimitA"] == 12
    assert s["chargingCurrentLimitMode"] == "reduced"
    assert s["chargingPlugAutoUnlock"] == "on"
    assert s["vehicleReportedOnline"] is True
    assert s["vehicleReportedActive"] is False
    car = AudiConnectVehicle(None, NS(vin="FAKEVIN", state=s, fields={}))
    # The wrapper initializes fresh state at construction, matching live setup.
    car._vehicle.state.update(s)
    assert car.charging_current_limit_a == 12
    assert car.charging_current_limit_mode == "reduced"
    assert car.charging_plug_auto_unlock == "enabled"
    assert car.vehicle_reported_online == "online"
    assert car.vehicle_reported_active == "inactive"
    keys = {d.key for d in SENSOR_DESCRIPTIONS}
    assert {
        "charging_current_limit_a", "charging_current_limit_mode",
        "charging_plug_auto_unlock", "vehicle_reported_online",
        "vehicle_reported_active",
    } <= keys


def test_unknown_values_are_not_assumed_false():
    s = parsed({"readiness": {"readinessStatus": {"value": {
        "connectionState": {"isOnline": None, "isActive": "unknown"}
    }}}})
    assert "vehicleReportedOnline" not in s
    assert "vehicleReportedActive" not in s
    car = AudiConnectVehicle(None, NS(vin="FAKEVIN", state={}, fields={}))
    assert car.vehicle_reported_online is None
    assert car.charging_plug_auto_unlock is None
    assert car.charging_current_limit_a is None
