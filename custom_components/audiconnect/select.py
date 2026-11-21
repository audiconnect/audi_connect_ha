"""Support for Audi Connect selects."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, entity_unique_id, should_create_entity
from .coordinator import AudiDataUpdateCoordinator

_ATTR_KEY = "preferred_charge_mode"
_CURRENT_ATTR_KEY = "active_charging_profile_max_charging_current"
_CURRENT_OPTIONS = ["max", "reduced"]

# What set_charge_mode accepts. The car also reports availableChargeModes, but
# it comes back empty on at least one vehicle, so this is the fallback rather
# than the source of truth.
_FALLBACK_MODES = ["manual", "timer"]

# What the car sends when it has no answer rather than a mode. A live vehicle
# reported "invalid" while parked, so this is the normal resting state, not an
# error.
_NOT_A_MODE = frozenset({"invalid", "unsupported", "unknown", ""})


def _current_mode(vehicle: Any) -> str | None:
    value = getattr(vehicle, "preferred_charge_mode", None)
    if not isinstance(value, str) or value.lower() in _NOT_A_MODE:
        return None
    return value


def _options_for(vehicle: Any) -> list[str]:
    reported = getattr(vehicle, "available_charge_modes", None)
    usable = [
        m for m in reported or [] if isinstance(m, str) and m.lower() not in _NOT_A_MODE
    ]
    options = usable or list(_FALLBACK_MODES)
    # Home Assistant renders the entity as unknown when current_option is not in
    # options, so a mode the car reports but does not list has to be added
    # rather than merely passed through.
    current = _current_mode(vehicle)
    if current is not None and current not in options:
        options = [*options, current]
    return options


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    vehicles = [cv.vehicle for cv in runtime_data.account.config_vehicles]
    entities: list[SelectEntity] = [
        AudiChargeModeSelect(runtime_data.coordinator, vehicle)
        for vehicle in vehicles
        if should_create_entity(hass, "select", "charge_mode", vehicle, _ATTR_KEY)
    ]
    entities.extend(
        AudiLocationChargingCurrentSelect(runtime_data.coordinator, vehicle)
        for vehicle in vehicles
        if should_create_entity(
            hass, "select", "location_charging_current", vehicle, _CURRENT_ATTR_KEY
        )
    )
    async_add_entities(entities)


class AudiChargeModeSelect(AudiEntity, SelectEntity):
    """The charge mode the car is set to.

    Reads preferredChargeMode, not the chargeMode of the charge in progress:
    set_charge_mode writes the former, and the two disagree whenever a charge is
    running under a different mode than the one configured.
    """

    _backing_attr = _ATTR_KEY

    _attr_name = "Charge mode"
    _attr_icon = "mdi:battery-clock"

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = entity_unique_id(vehicle, "select", "charge_mode")

    @property
    def options(self) -> list[str]:
        return _options_for(self._vehicle)

    @property
    def current_option(self) -> str | None:
        return _current_mode(self._vehicle)

    async def async_select_option(self, option: str) -> None:
        connection = self.coordinator.account.connection
        if not await connection.set_charge_mode(self._vehicle.vin, option):
            raise HomeAssistantError(
                f"Failed to set charge mode to {option}; see the log for details"
            )
        await self.coordinator.async_request_refresh()


class AudiLocationChargingCurrentSelect(AudiEntity, SelectEntity):
    """AC charging current of the charging location the car is parked at.

    The myAudi app's "Reduce AC charging current" switch under the location's
    advanced settings: "reduced" goes easy on the battery, "max" lets the car
    draw the most the charger offers. These are the values the app writes.
    """

    _backing_attr = _CURRENT_ATTR_KEY

    _attr_name = "Location AC charging current"
    _attr_icon = "mdi:current-ac"
    _attr_options = _CURRENT_OPTIONS

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = entity_unique_id(
            vehicle, "select", "location_charging_current"
        )

    @property
    def current_option(self) -> str | None:
        value = getattr(self._vehicle, _CURRENT_ATTR_KEY, None)
        return value if value in _CURRENT_OPTIONS else None

    async def async_select_option(self, option: str) -> None:
        connection = self.coordinator.account.connection
        if not await connection.set_location_max_charging_current(
            self._vehicle.vin, None, option
        ):
            raise HomeAssistantError(
                f"Failed to set the location AC charging current to {option}; "
                "see the log for details"
            )
        await self.coordinator.async_request_refresh()


__all__ = [
    "AudiChargeModeSelect",
    "AudiLocationChargingCurrentSelect",
    "async_setup_entry",
]
