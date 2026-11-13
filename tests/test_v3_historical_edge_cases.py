"""Historical access aggregation and account quota restore contracts."""

from datetime import UTC, datetime
from types import SimpleNamespace as NS

from custom_components.audiconnect.v3.attribute_runtime import observe_read_only
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3.entities import V3ApiQuotaSensor


def test_incomplete_or_duplicated_doors_do_not_prove_closed():
    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")
    profile = NS(attribute_routes={}, attribute_evidence={})
    now = datetime.now(UTC)
    data = {
        "access": {
            "accessStatus": {
                "value": {
                    "carCapturedTimestamp": now.isoformat(),
                    "doors": [
                        {"name": name, "status": ["closed", "locked"]}
                        for name in (
                            "frontLeft",
                            "frontRight",
                            "rearLeft",
                            "rearLeft",
                            "trunk",
                        )
                    ],
                    "windows": [
                        {"name": name, "status": ["closed"]}
                        for name in ("frontLeft", "frontRight", "rearLeft", "sunRoof")
                    ],
                }
            }
        }
    }
    observe_read_only(car, profile, data, now)
    for key in (
        "any_door_open",
        "any_door_unlocked",
        "doors_trunk_status",
        "any_window_open",
        "left_rear_door_open",
    ):
        assert car.readings[key]["value"] is None
        assert car.readings[key]["status"] == "invalid_value"


def test_restored_quota_is_display_only_and_live_quota_wins():
    transport = NS(remaining_calls=None, remaining_calls_observed_at=None)
    coordinator = NS(engine=NS(transport=transport))
    sensor = object.__new__(V3ApiQuotaSensor)
    sensor.coordinator = coordinator
    sensor._restored_native_value = 12
    sensor._restored_last_observed = "2026-09-01T00:00:00+00:00"
    assert sensor.native_value == 12
    assert sensor.extra_state_attributes["value_restored"] is True
    assert transport.remaining_calls is None
    transport.remaining_calls = 8
    assert sensor.native_value == 8
    assert sensor.extra_state_attributes["value_restored"] is False
