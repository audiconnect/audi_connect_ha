"""Support for Audi Connect locks."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, entity_unique_id, should_create_entity
from .coordinator import AudiDataUpdateCoordinator

# Lock uses attr_key="lock" which maps to the lock_supported property on the
# vehicle.  State is derived from doors_trunk_status (matching the legacy
# Lock instrument exactly).
_LOCK_ATTR_KEY = "lock"


def _spin_configured(vehicle: Any) -> bool:
    """lock_supported also requires an S-PIN, which the user sets.

    Removing it must remove the lock, so that half of the gate cannot be
    overridden by the entity having existed before. Same reasoning that
    keeps the engine buttons out of the rescue.
    """
    service = getattr(vehicle, "_audi_service", None)
    return getattr(service, "_spin", None) is not None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities = [
        AudiLock(runtime_data.coordinator, config_vehicle.vehicle)
        for config_vehicle in runtime_data.account.config_vehicles
        if should_create_entity(
            hass,
            "lock",
            _LOCK_ATTR_KEY,
            vehicle := config_vehicle.vehicle,
            _LOCK_ATTR_KEY,
            configured=_spin_configured(vehicle),
        )
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
        self._attr_unique_id = entity_unique_id(vehicle, "lock", _LOCK_ATTR_KEY)

    @property
    def is_locked(self) -> bool | None:
        """The car's own verdict first. The per-door derivation is the fallback,
        and None when neither is there: a missing value shown as "unlocked" is
        what #861 reported, and it is worse than showing nothing."""
        status = self._vehicle.door_lock_status
        if status is not None:
            return status == "locked"
        derived = self._vehicle.doors_trunk_status
        if derived is not None:
            return derived == "Locked"
        return None

    @property
    def available(self) -> bool:
        return super().available and self.is_locked is not None

    async def async_lock(self, **kwargs: Any) -> None:
        connection = self.coordinator.account.connection
        if not await connection.set_vehicle_lock(self._vehicle.vin, True):
            raise HomeAssistantError(
                "Failed to lock the vehicle; see the log for details"
            )
        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs: Any) -> None:
        connection = self.coordinator.account.connection
        if not await connection.set_vehicle_lock(self._vehicle.vin, False):
            raise HomeAssistantError(
                "Failed to unlock the vehicle; see the log for details"
            )
        await self.coordinator.async_request_refresh()


__all__ = ["AudiLock", "async_setup_entry"]
