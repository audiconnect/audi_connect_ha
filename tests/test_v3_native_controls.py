"""V3 controls use historical HA entity identifiers and are never enabled pre-proof."""

from pathlib import Path
from types import SimpleNamespace
from custom_components.audiconnect.v3.entities import (
    CONTROL_BUTTONS,
    V3ClimateQuickSwitch,
    V3LockEntity,
)
from custom_components.audiconnect.v3.vehicle import V3Vehicle

ROOT = Path(__file__).resolve().parents[1] / "custom_components/audiconnect"


def test_control_button_keys_retain_historical_ids():
    ids = {item[0] for item in CONTROL_BUTTONS}
    assert ids >= {
        "wake_vehicle_modern",
        "start_charging_modern",
        "stop_charging_modern",
        "start_window_heating_modern",
        "stop_window_heating_modern",
    }
    platforms = (ROOT / "v3" / "ha_platforms.py").read_text()
    assert "V3ControlButton" in platforms
    assert "V3LockEntity" in platforms
    assert "V3ClimateQuickSwitch" in platforms


def test_lock_and_switch_entity_unique_ids_match_v2():
    car = V3Vehicle(
        vin="WAUZZZ4M0MD123456",
        name="Audi",
        model="Audi Q8",
        model_family="q8",
        country="DE",
    )
    dummy = SimpleNamespace(async_add_listener=lambda cb: None)
    lock = V3LockEntity(dummy, car)
    switch = V3ClimateQuickSwitch(dummy, car)
    assert lock.unique_id == car.vin.lower() + "_lock_lock"
    assert switch.unique_id == car.vin.lower() + "_switch_climate_quick_control"
    assert lock.is_locked is None
    assert switch.is_on is None
