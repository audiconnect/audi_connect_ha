"""Support for Audi Connect switches."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, is_entity_supported
from .coordinator import AudiDataUpdateCoordinator


def _is_charging(value: Any) -> bool:
    """Only an in-progress charge counts as on; the plug states do not."""
    return isinstance(value, str) and value.lower() == "charging"


@dataclass(frozen=True, kw_only=True)
class AudiSwitchEntityDescription(SwitchEntityDescription):
    """Describes an Audi switch entity."""

    attr_key: str
    turn_on_fn: Callable[[Any, str], Coroutine[Any, Any, None]]
    turn_off_fn: Callable[[Any, str], Coroutine[Any, Any, None]]
    value_fn: Callable[[Any], bool] = bool


SWITCH_DESCRIPTIONS: tuple[AudiSwitchEntityDescription, ...] = (
    AudiSwitchEntityDescription(
        key="preheater_active",
        attr_key="preheater_active",
        name="Preheater",
        icon="mdi:radiator",
        turn_on_fn=lambda conn, vin: conn.set_vehicle_pre_heater(vin, True),
        turn_off_fn=lambda conn, vin: conn.set_vehicle_pre_heater(vin, False),
    ),
    AudiSwitchEntityDescription(
        key="charger",
        attr_key="charging_state",
        name="Charger",
        icon="mdi:ev-station",
        value_fn=_is_charging,
        turn_on_fn=lambda conn, vin: conn.set_battery_charger(vin, True, False),
        turn_off_fn=lambda conn, vin: conn.set_battery_charger(vin, False, False),
    ),
    AudiSwitchEntityDescription(
        key="window_heating",
        attr_key="glass_surface_heating",
        name="Window heating",
        icon="mdi:car-defrost-front",
        device_class=SwitchDeviceClass.SWITCH,
        turn_on_fn=lambda conn, vin: conn.set_vehicle_window_heating(vin, True),
        turn_off_fn=lambda conn, vin: conn.set_vehicle_window_heating(vin, False),
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
        value = getattr(self._vehicle, self.entity_description.attr_key, None)
        return self.entity_description.value_fn(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        connection = self.coordinator.account.connection
        await self.entity_description.turn_on_fn(connection, self._vehicle.vin)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        connection = self.coordinator.account.connection
        await self.entity_description.turn_off_fn(connection, self._vehicle.vin)
        await self.coordinator.async_request_refresh()


__all__ = ["AudiSwitch", "async_setup_entry"]
