"""Support for Audi Connect switches."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, is_entity_supported
from .coordinator import AudiDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class AudiSwitchEntityDescription(SwitchEntityDescription):
    """Describes an Audi switch entity."""

    attr_key: str
    turn_on_fn: Callable[[Any, str], Coroutine[Any, Any, None]]
    turn_off_fn: Callable[[Any, str], Coroutine[Any, Any, None]]


SWITCH_DESCRIPTIONS: tuple[AudiSwitchEntityDescription, ...] = (
    AudiSwitchEntityDescription(
        key="preheater_active",
        attr_key="preheater_active",
        name="Preheater",
        icon="mdi:radiator",
        turn_on_fn=lambda conn, vin: conn.set_vehicle_pre_heater(vin, True),
        turn_off_fn=lambda conn, vin: conn.set_vehicle_pre_heater(vin, False),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities = [
        AudiSwitch(runtime_data.coordinator, description, vehicle)
        for config_vehicle in runtime_data.account.config_vehicles
        for description in SWITCH_DESCRIPTIONS
        if is_entity_supported(
            (vehicle := config_vehicle.vehicle), description.attr_key
        )
    ]
    async_add_entities(entities)


class AudiSwitch(AudiEntity, SwitchEntity):
    """Representation of an Audi switch."""

    entity_description: AudiSwitchEntityDescription

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        description: AudiSwitchEntityDescription,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self.entity_description = description
        self._attr_unique_id = f"{vehicle.vin.lower()}_switch_{description.key}"

    @property
    def is_on(self) -> bool:
        return getattr(self._vehicle, self.entity_description.attr_key, False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        connection = self.coordinator.account.connection
        await self.entity_description.turn_on_fn(connection, self._vehicle.vin)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        connection = self.coordinator.account.connection
        await self.entity_description.turn_off_fn(connection, self._vehicle.vin)
        await self.coordinator.async_request_refresh()


__all__ = ["AudiSwitch", "async_setup_entry"]
