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

# The Cariad API rejects anything outside 20-100 and only accepts 5% steps.
_SOC_MIN = 20
_SOC_MAX = 100
_SOC_STEP = 5


@dataclass(frozen=True, kw_only=True)
class AudiNumberEntityDescription(NumberEntityDescription):
    """Describes an Audi number entity."""

    attr_key: str
    set_value_fn: Callable[[Any, str, int], Coroutine[Any, Any, bool]]


NUMBER_DESCRIPTIONS: tuple[AudiNumberEntityDescription, ...] = (
    AudiNumberEntityDescription(
        key="target_state_of_charge",
        attr_key="target_state_of_charge",
        name="Global charge target",
        icon="mdi:battery-charging-80",
        device_class=NumberDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=_SOC_MIN,
        native_max_value=_SOC_MAX,
        native_step=_SOC_STEP,
        mode=NumberMode.SLIDER,
        set_value_fn=lambda conn, vin, value: conn.set_target_state_of_charge(
            vin, value
        ),
    ),
    AudiNumberEntityDescription(
        key="active_charging_profile_target_soc",
        attr_key="active_charging_profile_target_soc",
        name="Current location charge target",
        icon="mdi:map-marker",
        device_class=NumberDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=_SOC_MIN,
        native_max_value=_SOC_MAX,
        native_step=_SOC_STEP,
        mode=NumberMode.SLIDER,
        # No profile id: the service resolves vehiclePositionedInProfileID, so
        # this follows the car between locations.
        set_value_fn=lambda conn, vin, value: conn.set_location_charge_target(
            vin, None, value
        ),
    ),
)


def _profiles(vehicle: Any) -> list[dict[str, Any]]:
    """Return the location charging profiles the car reports, if any."""
    profiles = getattr(vehicle, "charging_profiles", None)
    if not isinstance(profiles, list):
        return []
    return [p for p in profiles if isinstance(p, dict) and p.get("id") is not None]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities: list[NumberEntity] = [
        AudiNumber(runtime_data.coordinator, description, vehicle)
        for config_vehicle in runtime_data.account.config_vehicles
        for description in NUMBER_DESCRIPTIONS
        if is_entity_supported(
            (vehicle := config_vehicle.vehicle), description.attr_key
        )
    ]
    entities.extend(
        AudiProfileChargeTarget(
            runtime_data.coordinator, config_vehicle.vehicle, profile
        )
        for config_vehicle in runtime_data.account.config_vehicles
        for profile in _profiles(config_vehicle.vehicle)
    )
    async_add_entities(entities)


class AudiChargeTargetEntity(AudiEntity, NumberEntity):
    """Shared slider behaviour for the charge-target numbers."""

    _attr_device_class = NumberDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = _SOC_MIN
    _attr_native_max_value = _SOC_MAX
    _attr_native_step = _SOC_STEP
    _attr_mode = NumberMode.SLIDER

    async def _write(
        self,
        set_value_fn: Callable[[Any, str, int], Coroutine[Any, Any, bool]],
        value: float,
    ) -> None:
        connection = self.coordinator.account.connection
        if not await set_value_fn(connection, self._vehicle.vin, int(value)):
            raise HomeAssistantError(
                f"Failed to set {self.name}; see the log for details"
            )
        await self.coordinator.async_request_refresh()


class AudiNumber(AudiChargeTargetEntity):
    """A number backed by a single vehicle attribute."""

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
        await self._write(self.entity_description.set_value_fn, value)


class AudiProfileChargeTarget(AudiChargeTargetEntity):
    """The charge target of one location profile.

    Keyed on the profile id, never the name: names are editable in the car and
    the myAudi app, so a name-keyed unique_id would orphan the entity on a
    rename.
    """

    _attr_icon = "mdi:map-marker-radius"

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        vehicle: Any,
        profile: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, vehicle)
        self._profile_id = profile["id"]
        self._attr_name = f"{profile.get('name') or f'Profile {self._profile_id}'} charge target"
        self._attr_unique_id = (
            f"{vehicle.vin.lower()}_number_charge_profile_{self._profile_id}_target_soc"
        )

    @property
    def _profile(self) -> dict[str, Any] | None:
        return next(
            (p for p in _profiles(self._vehicle) if p["id"] == self._profile_id), None
        )

    @property
    def available(self) -> bool:
        # The profile can be deleted in the car; say so rather than showing a
        # stale target for a location that no longer exists.
        return super().available and self._profile is not None

    @property
    def native_value(self) -> float | None:
        profile = self._profile
        if profile is None:
            return None
        value = profile.get("targetSOC_pct")
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        await self._write(
            lambda conn, vin, soc: conn.set_location_charge_target(
                vin, self._profile_id, soc
            ),
            value,
        )


__all__ = ["AudiNumber", "AudiProfileChargeTarget", "async_setup_entry"]
