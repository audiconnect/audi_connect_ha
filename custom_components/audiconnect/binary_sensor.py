"""Support for Audi Connect sensors."""
import logging

from homeassistant.components.binary_sensor import (
    DEVICE_CLASSES, BinarySensorDevice)

from . import DATA_KEY, AudiEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
        hass, config, async_add_entities, discovery_info=None):
    """Set up the Audi sensors."""
    if discovery_info is None:
        return
    async_add_entities([AudiSensor(hass.data[DATA_KEY], *discovery_info)])


class AudiSensor(AudiEntity, BinarySensorDevice):
    """Representation of an Audi sensor."""

    @property
    def is_on(self):
        """Return True if the binary sensor is on."""
        return self.instrument.is_on

    @property
    def device_class(self):
        """Return the class of this sensor, from DEVICE_CLASSES."""
        if self.instrument.device_class in DEVICE_CLASSES:
            return self.instrument.device_class
        return None
