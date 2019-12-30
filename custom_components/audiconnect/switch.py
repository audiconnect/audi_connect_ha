"""Support for Audi Connect switches"""
import logging

from homeassistant.helpers.entity import ToggleEntity
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
        for switch in config_vehicle.switches:
            sensors.append(AudiSwitch(config_vehicle, switch))

    async_add_entities(sensors)


class AudiSwitch(AudiEntity, ToggleEntity):
    """Representation of a Audi switch."""

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._instrument.state

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self._instrument.turn_on()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self._instrument.turn_off()
