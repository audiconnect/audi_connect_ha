"""Support for Audi Connect binary sensors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, is_entity_supported
from .coordinator import AudiDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class AudiBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes an Audi binary sensor entity."""

    attr_key: str


BINARY_SENSOR_DESCRIPTIONS: tuple[AudiBinarySensorEntityDescription, ...] = (
    AudiBinarySensorEntityDescription(
        key="plug_state",
        attr_key="plug_state",
        name="Plug state",
        icon="mdi:ev-plug-type1",
        device_class=BinarySensorDeviceClass.PLUG,
    ),
    AudiBinarySensorEntityDescription(
        key="plug_lock_state",
        attr_key="plug_lock_state",
        name="Plug Lock state",
        icon="mdi:ev-plug-type1",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    AudiBinarySensorEntityDescription(
        key="glass_surface_heating",
        attr_key="glass_surface_heating",
        name="Glass Surface Heating",
        icon="mdi:car-defrost-front",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    AudiBinarySensorEntityDescription(
        key="sun_roof",
        attr_key="sun_roof",
        name="Sun roof",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    AudiBinarySensorEntityDescription(
        key="roof_cover",
        attr_key="roof_cover",
        name="Roof Cover",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    AudiBinarySensorEntityDescription(
        key="parking_light",
        attr_key="parking_light",
        name="Parking light",
        device_class=BinarySensorDeviceClass.SAFETY,
        icon="mdi:lightbulb",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiBinarySensorEntityDescription(
        key="any_window_open",
        attr_key="any_window_open",
        name="Windows",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    AudiBinarySensorEntityDescription(
        key="any_door_unlocked",
        attr_key="any_door_unlocked",
        name="Doors lock",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    AudiBinarySensorEntityDescription(
        key="any_door_open",
        attr_key="any_door_open",
        name="Doors",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    AudiBinarySensorEntityDescription(
        key="trunk_unlocked",
        attr_key="trunk_unlocked",
        name="Trunk lock",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    AudiBinarySensorEntityDescription(
        key="trunk_open",
        attr_key="trunk_open",
        name="Trunk",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    AudiBinarySensorEntityDescription(
        key="hood_open",
        attr_key="hood_open",
        name="Hood",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    AudiBinarySensorEntityDescription(
        key="left_front_door_open",
        attr_key="left_front_door_open",
        name="Left front door",
        device_class=BinarySensorDeviceClass.DOOR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiBinarySensorEntityDescription(
        key="right_front_door_open",
        attr_key="right_front_door_open",
        name="Right front door",
        device_class=BinarySensorDeviceClass.DOOR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiBinarySensorEntityDescription(
        key="left_rear_door_open",
        attr_key="left_rear_door_open",
        name="Left rear door",
        device_class=BinarySensorDeviceClass.DOOR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiBinarySensorEntityDescription(
        key="right_rear_door_open",
        attr_key="right_rear_door_open",
        name="Right rear door",
        device_class=BinarySensorDeviceClass.DOOR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiBinarySensorEntityDescription(
        key="left_front_window_open",
        attr_key="left_front_window_open",
        name="Left front window",
        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiBinarySensorEntityDescription(
        key="right_front_window_open",
        attr_key="right_front_window_open",
        name="Right front window",
        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiBinarySensorEntityDescription(
        key="left_rear_window_open",
        attr_key="left_rear_window_open",
        name="Left rear window",
        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiBinarySensorEntityDescription(
        key="right_rear_window_open",
        attr_key="right_rear_window_open",
        name="Right rear window",
        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiBinarySensorEntityDescription(
        key="braking_status",
        attr_key="braking_status",
        name="Braking status",
        device_class=BinarySensorDeviceClass.SAFETY,
        icon="mdi:car-brake-abs",
    ),
    AudiBinarySensorEntityDescription(
        key="oil_level_binary",
        attr_key="oil_level_binary",
        name="Oil Level Binary",
        icon="mdi:oil",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiBinarySensorEntityDescription(
        key="is_moving",
        attr_key="is_moving",
        name="Is moving",
        icon="mdi:motion-outline",
        device_class=BinarySensorDeviceClass.MOVING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities = [
        AudiBinarySensor(runtime_data.coordinator, description, vehicle)
        for config_vehicle in runtime_data.account.config_vehicles
        for description in BINARY_SENSOR_DESCRIPTIONS
        if is_entity_supported(
            (vehicle := config_vehicle.vehicle), description.attr_key
        )
    ]
    async_add_entities(entities)


class AudiBinarySensor(AudiEntity, BinarySensorEntity):
    """Representation of an Audi binary sensor."""

    entity_description: AudiBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        description: AudiBinarySensorEntityDescription,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self.entity_description = description
        self._attr_unique_id = (
            f"{vehicle.vin.lower()}_binary_sensor_{description.key}"
        )

    @property
    def is_on(self) -> bool | None:
        val = getattr(self._vehicle, self.entity_description.attr_key, None)
        if isinstance(val, (bool, list)):
            return bool(val)
        elif isinstance(val, str):
            return val != "Normal"
        return val


__all__ = ["AudiBinarySensor", "async_setup_entry"]
