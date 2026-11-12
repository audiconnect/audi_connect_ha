"""Global V2 capability inventory is source-based, vehicle filtering is separate."""
from __future__ import annotations
from datetime import UTC, datetime

from custom_components.audiconnect.v3.historical_catalog import (
    INVENTORY, V2_JOBS, ATTRIBUTES, CONTROLS, extract_attributes, advertised_capabilities,
)


def test_historical_scope_is_broader_than_climate_and_includes_controls():
    assert len(V2_JOBS) >= 23
    assert len(ATTRIBUTES) >= 45
    assert len(CONTROLS) >= 15
    assert {x["capability"] for x in INVENTORY["attributes"]} >= {
        "climate", "charging", "vehicle_status", "access", "service", "mobility"
    }
    assert "stateOfCharge" in ATTRIBUTES and "chargingState" in ATTRIBUTES
    assert "start_engine" in CONTROLS and "lock" in CONTROLS


def test_different_vehicle_payloads_preserve_false_and_zero_without_inventing_values():
    sample = {"charging": {"batteryStatus": {"value": {
        "currentSOC_pct": 0, "carCapturedTimestamp": "2026-11-11T10:00:00Z"
    }}, "chargingStatus": {"value": {
        "chargingState": "off", "carCapturedTimestamp": "2026-11-11T10:00:00Z"
    }}}}
    values = {r["id"]:r for r in extract_attributes(sample)}
    assert values["stateOfCharge"]["value"] == 0
    assert values["stateOfCharge"]["captured"] == "2026-11-11T10:00:00Z"
    assert values["chargingState"]["value"] == "off"
    assert "climatisationState" not in values


def test_advertised_is_not_necessarily_usable_or_command_verified():
    status = {"userCapabilities":{"capabilitiesStatus":{"value":[
        {"id":"charging","status":None},{"id":"onlineLogBook","status":"impaired"}
    ]}}}
    reported, impaired = advertised_capabilities(status)
    assert reported == {"charging","onlineLogBook"}
    assert impaired == {"onlineLogBook"}
    assert CONTROLS["start_charging"]["verification"] == "required"


def test_location_inventory_is_preserved_but_no_location_response_is_collected():
    assert any(x["capability"] == "mobility" for x in INVENTORY["attributes"])
    sample={"parkingPosition":{"data":{"lat":50.0,"lon":4.0}}}
    assert extract_attributes(sample) == []
