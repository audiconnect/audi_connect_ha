"""Support for Audi Connect sensors."""
import logging

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


class AudiSensor(AudiEntity):
    """Representation of a Audi sensor."""

    @property
    def state(self):
        """Return the state."""
        return self._instrument.state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._instrument.unit
