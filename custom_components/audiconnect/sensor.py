"""Support for Audi Connect sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
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
        AudiSensor(runtime_data.coordinator, sensor)
        for config_vehicle in runtime_data.account.config_vehicles
        for sensor in config_vehicle.sensors
    ]
    async_add_entities(entities)


class AudiSensor(AudiEntity, SensorEntity):
    """Representation of an Audi sensor."""

    @property
    def native_value(self) -> Any:
        return self._instrument.state

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._instrument.unit

    @property
    def device_class(self) -> SensorDeviceClass | None:
        return self._instrument.device_class

    @property
    def state_class(self) -> SensorStateClass | None:
        return self._instrument.state_class

    @property
    def entity_category(self) -> EntityCategory | None:
        return self._instrument.entity_category

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self._instrument.extra_state_attributes

    @property
    def suggested_display_precision(self) -> int | None:
        return self._instrument.suggested_display_precision


__all__ = ["AudiSensor", "async_setup_entry"]
