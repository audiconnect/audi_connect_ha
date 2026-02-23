"""Support for Audi Connect locks."""

from __future__ import annotations

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities = [
        AudiLock(runtime_data.coordinator, lock)
        for config_vehicle in runtime_data.account.config_vehicles
        for lock in config_vehicle.locks
    ]
    async_add_entities(entities)


class AudiLock(AudiEntity, LockEntity):
    @property
    def is_locked(self):
        return self._instrument.is_locked

    async def async_lock(self, **kwargs):
        await self._instrument.lock()
        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs):
        await self._instrument.unlock()
        await self.coordinator.async_request_refresh()
