"""Support for Audi Connect binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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
        AudiBinarySensor(runtime_data.coordinator, sensor)
        for config_vehicle in runtime_data.account.config_vehicles
        for sensor in config_vehicle.binary_sensors
    ]
    async_add_entities(entities)


class AudiBinarySensor(AudiEntity, BinarySensorEntity):
    """Representation of an Audi binary sensor."""

    @property
    def is_on(self) -> bool | None:
        return self._instrument.is_on

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        return self._instrument.device_class

    @property
    def entity_category(self) -> EntityCategory | None:
        return self._instrument.entity_category


__all__ = ["AudiBinarySensor", "async_setup_entry"]
