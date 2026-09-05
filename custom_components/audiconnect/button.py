"""Support for Audi Connect buttons."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, is_entity_supported
from .coordinator import AudiDataUpdateCoordinator


def _spin_available(vehicle: Any) -> bool:
    """Engine start/stop needs the S-PIN, the same gate the lock entity uses."""
    service = getattr(vehicle, "_audi_service", None)
    return getattr(service, "_spin", None) is not None


@dataclass(frozen=True, kw_only=True)
class AudiButtonEntityDescription(ButtonEntityDescription):
    """Describes an Audi button entity."""

    press_fn: Callable[[Any, str], Coroutine[Any, Any, None]]
    supported_fn: Callable[[Any], bool] = lambda vehicle: True


BUTTON_DESCRIPTIONS: tuple[AudiButtonEntityDescription, ...] = (
    AudiButtonEntityDescription(
        key="refresh_vehicle_data",
        name="Refresh vehicle data",
        icon="mdi:cloud-refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda account, vin: account.refresh_vehicle_data(vin),
    ),
    AudiButtonEntityDescription(
        key="start_timed_charging",
        name="Start timed charging",
        icon="mdi:timer-play-outline",
        supported_fn=lambda vehicle: is_entity_supported(vehicle, "charging_state"),
        press_fn=lambda account, vin: account.connection.set_battery_charger(
            vin, True, True
        ),
    ),
    AudiButtonEntityDescription(
        key="start_engine",
        name="Start engine",
        icon="mdi:car-key",
        supported_fn=_spin_available,
        press_fn=lambda account, vin: account.start_engine(vin),
    ),
    AudiButtonEntityDescription(
        key="stop_engine",
        name="Stop engine",
        icon="mdi:car-off",
        supported_fn=_spin_available,
        press_fn=lambda account, vin: account.stop_engine(vin),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities = [
        AudiButton(runtime_data.coordinator, description, vehicle)
        for config_vehicle in runtime_data.account.config_vehicles
        for description in BUTTON_DESCRIPTIONS
        if description.supported_fn(vehicle := config_vehicle.vehicle)
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
        await self.entity_description.press_fn(
            self.coordinator.account, self._vehicle.vin
        )


__all__ = ["AudiButton", "async_setup_entry"]
