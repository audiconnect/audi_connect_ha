"""Support for Audi Connect selects."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, is_entity_supported
from .coordinator import AudiDataUpdateCoordinator

_ATTR_KEY = "preferred_charge_mode"

# What set_charge_mode accepts. The car also reports availableChargeModes, but
# it comes back empty on at least one vehicle, so this is the fallback rather
# than the source of truth.
_FALLBACK_MODES = ["manual", "timer"]


def _options_for(vehicle: Any) -> list[str]:
    reported = getattr(vehicle, "available_charge_modes", None)
    usable = [m for m in reported or [] if isinstance(m, str) and m]
    return usable or list(_FALLBACK_MODES)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    async_add_entities(
        AudiChargeModeSelect(runtime_data.coordinator, config_vehicle.vehicle)
        for config_vehicle in runtime_data.account.config_vehicles
        if is_entity_supported(config_vehicle.vehicle, _ATTR_KEY)
    )


class AudiChargeModeSelect(AudiEntity, SelectEntity):
    """The charge mode the car is set to.

    Reads preferredChargeMode, not the chargeMode of the charge in progress:
    set_charge_mode writes the former, and the two disagree whenever a charge is
    running under a different mode than the one configured.
    """

    _attr_name = "Charge mode"
    _attr_icon = "mdi:battery-clock"

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_select_charge_mode"

    @property
    def options(self) -> list[str]:
        return _options_for(self._vehicle)

    @property
    def current_option(self) -> str | None:
        value = getattr(self._vehicle, _ATTR_KEY, None)
        # A mode the car reports but does not list stays visible rather than
        # rendering the entity invalid.
        if isinstance(value, str) and value and value not in self.options:
            return value
        return value if isinstance(value, str) and value else None

    async def async_select_option(self, option: str) -> None:
        connection = self.coordinator.account.connection
        if not await connection.set_charge_mode(self._vehicle.vin, option):
            raise HomeAssistantError(
                f"Failed to set charge mode to {option}; see the log for details"
            )
        await self.coordinator.async_request_refresh()


__all__ = ["AudiChargeModeSelect", "async_setup_entry"]
