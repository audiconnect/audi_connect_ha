"""Support for Audi Connect switches"""
import logging

from homeassistant.helpers.entity import ToggleEntity

from . import DATA_KEY, AudiEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
        hass, config, async_add_entities, discovery_info=None):
    """Set up a Audi switch."""
    if discovery_info is None:
        return
    async_add_entities([AudiSwitch(hass.data[DATA_KEY], *discovery_info)])


class AudiSwitch(AudiEntity, ToggleEntity):
    """Representation of a Audi switch."""

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self.instrument.state

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self.instrument.turn_on()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self.instrument.turn_off()
