"""Historical metadata and access normalization without V2 runtime calls."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from custom_components.audiconnect.v3.attribute_contracts import contract_for
from custom_components.audiconnect.v3.attribute_runtime import observe_read_only
from custom_components.audiconnect.v3.vehicle import V3Vehicle

def test_recorder_repairs_restore_exact_fix_branch_metadata():
    for key in ("service_inspection_time", "oil_change_distance",
                "primary_engine_range", "secondary_engine_range", "tank_level",
                "state_of_charge", "hybrid_range", "secondary_engine_range_percent",
                "service_inspection_distance", "oil_change_time",
                "remaining_climatisation_time", "primary_engine_range_percent", "range"):
        assert contract_for(key)["state_class"] == "measurement"
    assert contract_for("mileage")["state_class"] == "total_increasing"

def test_access_explicit_status_and_unknown_values():
    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")
    profile = NS(attribute_routes={}, attribute_evidence={})
    now = datetime.now(UTC)
    payload = {"access": {"accessStatus": {"value": {
        "carCapturedTimestamp": now.isoformat(),
        "doors": [{"name": "frontLeft", "status": ["closed", "locked"]},
                  {"name": "frontRight", "status": ["open", "unlocked"]},
                  {"name": "rearLeft", "status": ["unknown"]}],
        "windows": [{"name": "frontLeft", "status": ["closed"]},
                    {"name": "rearRight", "status": ["unsupported"]}],
    }}}}
    observe_read_only(car, profile, payload, now)
    assert car.readings["left_front_door_open"]["value"] is False
    assert car.readings["right_front_door_open"]["value"] is True
    assert car.readings["any_door_open"]["value"] is True
    assert car.readings["left_rear_door_open"]["value"] is None
    assert car.readings["left_rear_door_open"]["status"] == "invalid_value"
    assert car.readings["right_rear_window_open"]["value"] is None
    assert car.readings["right_rear_window_open"]["status"] == "invalid_value"
    assert car.readings["left_front_window_open"]["value"] is False

def test_older_climate_capture_does_not_override_newer_state():
    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")
    now = datetime.now(UTC)
    assert car.set_climate("off", now.isoformat(), route="new", observed_at=now, http_status=200)
    assert not car.set_climate("heating", (now-timedelta(hours=1)).isoformat(),
                               route="cached", observed_at=now, http_status=207)
    assert car.climate_state == "off"
