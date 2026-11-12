"""V3 invalid and binary semantics match valid historical V2 behavior."""

from types import SimpleNamespace
from custom_components.audiconnect.v3.entities import V3ReadOnlyBinarySensor
from custom_components.audiconnect.v3.historical_catalog import INVENTORY
from custom_components.audiconnect.v3.vehicle import V3Vehicle


def binary_value(field, value):
    car = V3Vehicle(
        vin="WAUZZZ4M0MD123456", name="Audi", model="A4", model_family="", country="DE"
    )
    descriptor = {
        "id": field,
        "entity_key": "plug_state" if field == "plugState" else "plug_lock_state",
    }
    car.readings[field] = {"value": value}
    obj = V3ReadOnlyBinarySensor(
        SimpleNamespace(async_add_listener=lambda cb: None), car, descriptor
    )
    return obj.is_on


def test_plug_state_enum_not_confused_with_truthy_string():
    assert binary_value("plugState", "disconnected") is False
    assert binary_value("plugState", "connected") is True
    assert binary_value("plugState", "invalid") is None


def test_lock_state_and_unknown_do_not_falsely_claim_active():
    assert binary_value("plugLockState", "locked") is False
    assert binary_value("plugLockState", "unlocked") is True
    assert binary_value("plugLockState", "unknown") is None


def test_complete_platform_inventory_includes_v2_derived_access_and_switch():
    assert any(
        x["entity_key"] == "any_door_unlocked" and x["platform"] == "binary_sensor"
        for x in INVENTORY["attributes"]
    )
    assert any(x["id"] == "preheater_active" for x in INVENTORY["controls"])
