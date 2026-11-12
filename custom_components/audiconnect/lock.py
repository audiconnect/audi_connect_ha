"""Support for Audi Connect locks."""

from __future__ import annotations

import logging
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
_LOGGER = logging.getLogger(__name__)


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

    async def _async_set_door_lock(self, target_locked: bool) -> None:
        """Apply identical lock/unlock outcome handling with no blind retry.

        A gateway acknowledgement is not confirmation of the physical door
        state. Audi's state reports may lag an accepted command.
        """
        action = "lock" if target_locked else "unlock"
        initial_state = self.is_locked
        connection = self.coordinator.account.connection
        if not await connection.set_vehicle_lock(
            self._vehicle.vin, target_locked, refresh=False
        ):
            self._attr_extra_state_attributes = {
                "last_command": action,
                "last_command_status": "request_failed",
            }
            raise HomeAssistantError(
                f"Audi {action} request was rejected or could not be completed; "
                "see the integration log for details."
            )

        try:
            # Exactly one vehicle refresh and no automatic duplicate command.
            await self.coordinator.async_request_refresh()
        except Exception:
            # Refresh can fail after Audi has already accepted the action.
            # Cancellation propagates (CancelledError is BaseException).
            outcome = "accepted_unconfirmed"
        else:
            reported = self.is_locked
            if (
                getattr(self.coordinator, "last_update_success", False)
                and reported is target_locked
                and initial_state is not target_locked
            ):
                outcome = "confirmed_by_readback"
            elif reported is target_locked and initial_state is target_locked:
                outcome = "already_reported_in_requested_state"
            else:
                outcome = "accepted_unconfirmed"

        self._attr_extra_state_attributes = {
            "last_command": action,
            "last_command_status": outcome,
        }
        if outcome == "accepted_unconfirmed":
            _LOGGER.warning(
                "Audi %s request accepted but vehicle state not yet confirmed; "
                "verify at the vehicle or in myAudi before sending another command.",
                action,
            )
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()

    async def async_lock(self, **kwargs: Any) -> None:
        await self._async_set_door_lock(True)

    async def async_unlock(self, **kwargs: Any) -> None:
        await self._async_set_door_lock(False)


__all__ = ["AudiLock", "async_setup_entry"]
