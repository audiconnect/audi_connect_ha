"""Protect V2 identity/device class while validating independent V3 presentation."""
from types import SimpleNamespace

from custom_components.audiconnect.binary_sensor import BINARY_SENSOR_DESCRIPTIONS
from custom_components.audiconnect.v3.attribute_contracts import binary_contracts
from custom_components.audiconnect.v3.entities import V3ReadOnlyBinarySensor
from custom_components.audiconnect.v3.vehicle import V3Vehicle


def test_binary_identity_and_device_class_parity_with_v3_product_presentation():
    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")
    coordinator = SimpleNamespace(async_add_listener=lambda callback: None)
    assert set(binary_contracts()) == {d.key for d in BINARY_SENSOR_DESCRIPTIONS}
    for description in BINARY_SENSOR_DESCRIPTIONS:
        entity = V3ReadOnlyBinarySensor(coordinator, car,
            {"id": description.key, "entity_key": description.key, "capability": "vehicle_status"})
        assert entity.unique_id == car.vin.lower() + "_binary_sensor_" + description.key
        contract = binary_contracts()[description.key]
        assert entity.name == contract["name"]
        assert entity.device_class == description.device_class
        assert entity.entity_category is None
        assert entity.icon == contract["icon"]

def test_vehicle_binary_properties_are_not_integration_diagnostics():
    contracts = binary_contracts()
    for side in ("left", "right"):
        for position in ("front", "rear"):
            for part in ("door", "window"):
                key = f"{side}_{position}_{part}_open"
                assert key in contracts
                assert contracts[key].get("category") is None
    for key in ("oil_level_binary", "parking_light", "is_moving"):
        assert contracts[key].get("category") is None
