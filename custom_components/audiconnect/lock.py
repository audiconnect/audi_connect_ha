"""Support for Audi Connect locks."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, is_entity_supported
from .coordinator import AudiDataUpdateCoordinator

# Lock uses attr_key="lock" which maps to the lock_supported property on the
# vehicle.  State is derived from doors_trunk_status (matching the legacy
# Lock instrument exactly).
_LOCK_ATTR_KEY = "lock"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities = [
        AudiLock(runtime_data.coordinator, config_vehicle.vehicle)
        for config_vehicle in runtime_data.account.config_vehicles
        if is_entity_supported(config_vehicle.vehicle, _LOCK_ATTR_KEY)
    ]
    async_add_entities(entities)


class AudiLock(AudiEntity, LockEntity):
    """Representation of an Audi lock."""

    _attr_name = "Door lock"

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_lock_{_LOCK_ATTR_KEY}"

    @property
    def is_locked(self) -> bool:
        return self._vehicle.doors_trunk_status == "Locked"

    async def async_lock(self, **kwargs: Any) -> None:
        connection = self.coordinator.account.connection
        await connection.set_vehicle_lock(self._vehicle.vin, True)
        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs: Any) -> None:
        connection = self.coordinator.account.connection
        await connection.set_vehicle_lock(self._vehicle.vin, False)
        await self.coordinator.async_request_refresh()


__all__ = ["AudiLock", "async_setup_entry"]
