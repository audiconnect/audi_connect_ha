"""Support for Audi Connect buttons."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, is_entity_supported
from .coordinator import AudiDataUpdateCoordinator
from .vehicle_controls import engine_start_stop_supported


# Retain the historical helper symbol for test compatibility.
_engine_controls_supported = engine_start_stop_supported


@dataclass(frozen=True, kw_only=True)
class AudiButtonEntityDescription(ButtonEntityDescription):
    """Describes an Audi button entity."""

    press_fn: Callable[[Any, str], Coroutine[Any, Any, None]]
    supported_fn: Callable[[Any], bool] = lambda vehicle: True
    experimental: bool = False


def _modern_capable(vehicle: Any, capability: str) -> bool:
    service = getattr(vehicle, "_audi_service", None)
    check = getattr(vehicle, "has_capability", None)
    impaired = getattr(vehicle, "impaired_capabilities", frozenset()) or frozenset()
    return (
        bool(getattr(service, "uses_auth0", False))
        and callable(check)
        and check(capability) is True
        and capability not in impaired
    )


def _wakeup_capable(vehicle: Any) -> bool:
    return _modern_capable(vehicle, "vehicleWakeUp") or _modern_capable(
        vehicle, "vehicleWakeUpTrigger"
    )


BUTTON_DESCRIPTIONS: tuple[AudiButtonEntityDescription, ...] = (
    AudiButtonEntityDescription(
        key="refresh_vehicle_data",
        name="Refresh vehicle data",
        icon="mdi:cloud-refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda account, vin: account.refresh_vehicle_data(vin),
    ),
    AudiButtonEntityDescription(
        key="flash_lights",
        name="Flash lights",
        icon="mdi:car-light-high",
        # Gated on the car's own capability, not on a field being present in
        # the current poll. The horn shares this capability and is deliberately
        # not exposed.
        supported_fn=lambda vehicle: is_entity_supported(
            vehicle, "position", "honkAndFlash"
        ),
        press_fn=lambda account, vin: account.connection.flash_lights(vin),
    ),
    AudiButtonEntityDescription(
        key="start_charging_modern",
        name="Start charging (experimental)",
        icon="mdi:ev-station",
        experimental=True,
        supported_fn=lambda v: _modern_capable(v, "charging"),
        press_fn=lambda account, vin: account.connection.set_battery_charger(
            vin, True, False
        ),
    ),
    AudiButtonEntityDescription(
        key="stop_charging_modern",
        name="Stop charging (experimental)",
        icon="mdi:ev-station",
        experimental=True,
        supported_fn=lambda v: _modern_capable(v, "charging"),
        press_fn=lambda account, vin: account.connection.set_battery_charger(
            vin, False, False
        ),
    ),
    AudiButtonEntityDescription(
        key="start_window_heating_modern",
        name="Start window heating (experimental)",
        icon="mdi:car-defrost-rear",
        experimental=True,
        supported_fn=lambda v: _modern_capable(v, "climatisation"),
        press_fn=lambda account, vin: account.connection.set_vehicle_window_heating(
            vin, True
        ),
    ),
    AudiButtonEntityDescription(
        key="stop_window_heating_modern",
        name="Stop window heating (experimental)",
        icon="mdi:car-defrost-rear",
        experimental=True,
        supported_fn=lambda v: _modern_capable(v, "climatisation"),
        press_fn=lambda account, vin: account.connection.set_vehicle_window_heating(
            vin, False
        ),
    ),
    AudiButtonEntityDescription(
        key="wake_vehicle_modern",
        name="Wake vehicle (experimental)",
        icon="mdi:car-connected",
        experimental=True,
        supported_fn=_wakeup_capable,
        press_fn=lambda account, vin: account.connection.trigger_vehicle_wakeup(vin),
    ),
    AudiButtonEntityDescription(
        key="start_engine",
        name="Start engine",
        icon="mdi:car-key",
        supported_fn=_engine_controls_supported,
        press_fn=lambda account, vin: account.start_engine(vin),
    ),
    AudiButtonEntityDescription(
        key="stop_engine",
        name="Stop engine",
        icon="mdi:car-off",
        supported_fn=_engine_controls_supported,
        press_fn=lambda account, vin: account.stop_engine(vin),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    from .v3.engine import V3Engine

    if isinstance(runtime_data.v3, V3Engine):
        from .v3.ha_platforms import setup as v3_setup

        v3_setup("button", config_entry, async_add_entities)
        return

    entities = [
        AudiButton(runtime_data.coordinator, description, vehicle)
        for config_vehicle in runtime_data.account.config_vehicles
        for description in BUTTON_DESCRIPTIONS
        if (not description.experimental)
        and description.supported_fn(vehicle := config_vehicle.vehicle)
    ]
    async_add_entities(entities)


class AudiButton(AudiEntity, ButtonEntity):
    """Representation of an Audi button."""

    entity_description: AudiButtonEntityDescription

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        description: AudiButtonEntityDescription,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self.entity_description = description
        self._attr_unique_id = f"{vehicle.vin.lower()}_button_{description.key}"

    async def async_press(self) -> None:
        result = await self.entity_description.press_fn(
            self.coordinator.account, self._vehicle.vin
        )
        if result is False:
            # Prevent UI from silently accepting a failed API action.
            raise HomeAssistantError(
                f"Audi {self.entity_description.name} request failed; "
                "check the Audi Connect integration logs"
            )


__all__ = ["AudiButton", "async_setup_entry"]
