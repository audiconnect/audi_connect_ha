"""Support for Audi Connect sensors."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_USERNAME

from .audi_entity import AudiEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Old way."""


async def async_setup_entry(hass, config_entry, async_add_entities):
    sensors = []

    account = config_entry.data.get(CONF_USERNAME)
    audiData = hass.data[DOMAIN][account]

    for config_vehicle in audiData.config_vehicles:
        for sensor in config_vehicle.sensors:
            sensors.append(AudiSensor(config_vehicle, sensor))

    async_add_entities(sensors, True)


class AudiSensor(AudiEntity, SensorEntity):
    """Representation of a Audi sensor."""

    @property
    def native_value(self):
        """Return the native value."""
        return self._instrument.state

    @property
    def native_unit_of_measurement(self):
        """Return the native unit of measurement."""
        return self._instrument.unit

    @property
    def device_class(self):
        """Return the device_class."""
        return self._instrument.device_class

    @property
    def state_class(self):
        """Return the state_class."""
        return self._instrument.state_class

    @property
    def entity_category(self):
        """Return the entity_category."""
        return self._instrument.entity_category

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return self._instrument.extra_state_attributes
