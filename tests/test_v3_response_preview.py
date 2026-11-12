"""V3 safe response preview rules."""
from __future__ import annotations

import json

from custom_components.audiconnect.v3.response_preview import safe_response_preview


def test_nested_climate_response_is_readable():
    observed = {
        "climatisation": {
            "climatisationStatus": {
                "value": {
                    "climatisationState": "off",
                    "carCapturedTimestamp": "2026-11-11T14:00:00Z",
                }
            }
        }
    }
    preview = safe_response_preview(observed)
    assert preview["climatisation"]["climatisationStatus"]["value"][
        "climatisationState"
    ] == "off"


def test_response_preview_never_exposes_vin_auth_or_coordinates():
    vin = "WAUZZZ4M0MD123456"
    value = {
        "vin": vin,
        "url": "https://example.org/vehicle/" + vin,
        "authorization": "Bearer TEST",
        "location": {"latitude": 50, "longitude": 4},
        "nested": {"refresh_token": "BAD", "state": "heating"},
    }
    report = json.dumps(safe_response_preview(value, vehicle_vin=vin))
    assert vin not in report
    assert "Bearer TEST" not in report
    assert '"latitude"' not in report
    assert '"refresh_token": "BAD"' not in report
    assert "heating" in report


def test_truncated_long_response_is_bounded():
    report = json.dumps(safe_response_preview({
        "list": [{"v": "x" * 800} for _ in range(100)]
    }))
    assert len(report) < 2800
    assert "more items omitted" in report

def test_engineering_json_keeps_actual_nested_values_and_template_placeholders():
    from custom_components.audiconnect.v3.response_preview import engineering_response
    vin = "WAUZZZ4M0MD123456"
    raw = {"vin": vin, "sPin": "1234", "authorization": "Bearer TEST",
           "requestId": "123456789", "position": {"latitude": 50.1},
           "climatisation": {"timers": [{"settings": {"targetTemperature_C": 15.5,
               "enabled": True, "remaining": -256, "status": "invalid"}}]},
           "message": "vehicle " + vin + " rejected configured-secret",
           "echo": "configured-secret"}
    detail = engineering_response(raw, vehicle_vin=vin, spin="1234", secrets=("configured-secret",))
    payload = detail["payload"]
    assert not detail["truncated"]
    assert payload["vin"] == "{VIN}" and payload["sPin"] == "{SPIN}"
    assert payload["authorization"] == "{SECRET}" and payload["position"] == "{LOCATION}"
    assert payload["requestId"] == "{ID}"
    assert payload["climatisation"] == raw["climatisation"]
    assert payload["echo"] == "{SECRET}" and "configured-secret" not in json.dumps(detail)
    assert vin not in json.dumps(detail) and "Bearer TEST" not in json.dumps(detail)


def test_engineering_response_keeps_large_batch_values_and_bounds_oversize():
    from custom_components.audiconnect.v3.response_preview import engineering_response, MAX_ENGINEERING_CHARS
    data = {f"job{i}": {"items": [{"value": j, "state": "off"} for j in range(30)]}
            for i in range(25)}
    result = engineering_response(data)
    assert not result["truncated"]
    assert result["payload"] == data
    oversized = engineering_response({"first": 15.5, "large": ["x"*1000]*1000})
    assert oversized["truncated"] and oversized["payload"]["first"] == 15.5
    assert len(json.dumps(oversized)) <= MAX_ENGINEERING_CHARS

def test_engineering_response_preserves_public_capability_and_timer_identifiers():
    from custom_components.audiconnect.v3.response_preview import engineering_response
    raw = {"userCapabilities": {"capabilities": [{"id": "charging", "status": "enabled"}]},
           "locationBasedCharging": {"timers": [{"id": 1, "enabled": True}]},
           "requestId": "12345"}
    detail = engineering_response(raw)["payload"]
    assert detail["userCapabilities"] == raw["userCapabilities"]
    assert detail["locationBasedCharging"] == raw["locationBasedCharging"]
    assert detail["requestId"] == "{ID}"
