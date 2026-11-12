"""Avoid duplicate climate buttons now that the native climate switch is available."""

from custom_components.audiconnect.button import BUTTON_DESCRIPTIONS
from types import SimpleNamespace

from custom_components.audiconnect.switch import AudiClimateQuickSwitch


def test_duplicate_climate_buttons_not_registered():
    keys = {description.key for description in BUTTON_DESCRIPTIONS}
    assert "start_climate_car_settings" not in keys
    assert "stop_climate" not in keys
    assert "flash_lights" in keys
    assert "refresh_vehicle_data" in keys


def test_native_climate_switch_keeps_stable_unique_id():
    coordinator = SimpleNamespace(last_update_success=True)
    vehicle = SimpleNamespace(vin="SYNTHETICVIN000001", climatisation_state="off")
    toggle = AudiClimateQuickSwitch(coordinator, vehicle)
    assert toggle.unique_id == "syntheticvin000001_switch_climate_quick_control"
