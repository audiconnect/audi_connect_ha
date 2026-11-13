"""Independent V3 implementation of the historical Home Assistant action contract.

The bootstrap resolves which runtime owns a VIN. This module contains V3's
complete action-name translation and fail-closed command execution. Nothing
imports or invokes V2 vehicle business code. Command route/payload resolution
belongs to V3Engine; this module does not build OEM HTTP requests.
"""

from __future__ import annotations

from typing import Any
from homeassistant.exceptions import HomeAssistantError

# Stable HA service action vocabulary, not a second API mapping layer.
# API method, URL and body remain owned by V3's declarative route catalog.
_V2_ACTIONS: dict[str, tuple[str, str]] = {
    "lock": ("access", "lock"),
    "unlock": ("access", "unlock"),
    "start_climatisation": ("climate", "start"),
    "stop_climatisation": ("climate", "stop"),
    "start_charger": ("charging", "start"),
    "stop_charger": ("charging", "stop"),
    "start_window_heating": ("climate", "window_heating_start"),
    "stop_window_heating": ("climate", "window_heating_stop"),
    "start_preheater": ("climate", "preheater_start"),
    "stop_preheater": ("climate", "preheater_stop"),
    "start_auxiliary_heating": ("climate", "preheater_start"),
    "refresh_vehicle_data": ("remote", "refresh"),
    "flash_lights": ("remote", "flash"),
    "start_engine": ("remote", "engine_start"),
    "stop_engine": ("remote", "engine_stop"),
    "set_target_soc": ("charging", "set_target_soc"),
    "set_charge_mode": ("charging", "set_charge_mode"),
    "set_location_charge_target": ("charging", "set_location_charge_target"),
    "start_timed_charger": ("charging", "set_charge_mode"),
}


async def execute(
    engine: Any,
    vin: str,
    action: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Execute one reviewed V3 command via the same external V2 service ID.

    Never discard unknown service parameters or fall back to V2 actions.
    """
    values = {
        k: v
        for k, v in (data or {}).items()
        if k not in ("device_id", "action") and v is not None
    }
    mapped = _V2_ACTIONS.get(action)
    if action == "start_climatisation" and values:
        mapped = ("climate", "start_with_settings")
    if action == "start_timed_charger":
        if values:
            raise HomeAssistantError("Timed charging does not accept parameters")
        values = {"value": "timer"}
    elif action == "set_charge_mode":
        if set(values) != {"charge_mode"}:
            raise HomeAssistantError("Supply only charge_mode")
        values = {"value": values["charge_mode"]}
    elif action in ("set_target_soc", "set_location_charge_target"):
        values["value"] = values.pop("target_soc", None)
    if mapped is None:
        raise HomeAssistantError(
            f"Audi action '{action}' is not yet V3-verified; "
            "switch to V2 to use the existing action safely"
        )
    capability, aspect = mapped
    try:
        if values:
            await engine.send_control(vin, aspect, capability, params=values)
        else:
            await engine.send_control(vin, aspect, capability)
    except (RuntimeError, ValueError) as exc:
        raise HomeAssistantError(f"Audi {action}: {exc}") from exc
