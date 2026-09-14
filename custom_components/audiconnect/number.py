"""Support for Audi Connect numbers."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, is_entity_supported
from .coordinator import AudiDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class AudiNumberEntityDescription(NumberEntityDescription):
    """Describes an Audi number entity."""

    attr_key: str
    set_value_fn: Callable[[Any, str, int], Coroutine[Any, Any, bool]]


NUMBER_DESCRIPTIONS: tuple[AudiNumberEntityDescription, ...] = (
    AudiNumberEntityDescription(
        key="target_state_of_charge",
        attr_key="target_state_of_charge",
        name="Target state of charge",
        icon="mdi:battery-charging-80",
        device_class=NumberDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        # The Cariad API rejects anything outside 20-100 and only accepts
        # 5% increments.
        native_min_value=20,
        native_max_value=100,
        native_step=5,
        mode=NumberMode.SLIDER,
        set_value_fn=lambda conn, vin, value: conn.set_target_state_of_charge(
            vin, value
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities = [
        AudiNumber(runtime_data.coordinator, description, vehicle)
        for config_vehicle in runtime_data.account.config_vehicles
        for description in NUMBER_DESCRIPTIONS
        if is_entity_supported(
            (vehicle := config_vehicle.vehicle), description.attr_key
        )
    ]
    async_add_entities(entities)


class AudiNumber(AudiEntity, NumberEntity):
    """Representation of an Audi number."""

    entity_description: AudiNumberEntityDescription

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        description: AudiNumberEntityDescription,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self.entity_description = description
        self._attr_unique_id = f"{vehicle.vin.lower()}_number_{description.key}"

    @property
    def native_value(self) -> float | None:
        value = getattr(self._vehicle, self.entity_description.attr_key, None)
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        connection = self.coordinator.account.connection
        if not await self.entity_description.set_value_fn(
            connection, self._vehicle.vin, int(value)
        ):
            raise HomeAssistantError(
                f"Failed to set {self.name}; see the log for details"
            )
        await self.coordinator.async_request_refresh()


__all__ = ["AudiNumber", "async_setup_entry"]
