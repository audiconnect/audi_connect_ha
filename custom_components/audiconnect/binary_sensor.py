"""Support for Audi Connect sensors."""

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
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
        for binary_sensor in config_vehicle.binary_sensors:
            sensors.append(AudiSensor(config_vehicle, binary_sensor))

    async_add_entities(sensors)


class AudiSensor(AudiEntity, BinarySensorEntity):
    """Representation of an Audi sensor."""

    @property
    def is_on(self):
        """Return True if the binary sensor is on."""
        return self._instrument.is_on

    @property
    def device_class(self):
        """Return the device_class of this sensor."""
        return self._instrument.device_class

    @property
    def entity_category(self):
        """Return the entity_category."""
        return self._instrument.entity_category
