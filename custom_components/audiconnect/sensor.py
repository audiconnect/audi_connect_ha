"""Support for Audi Connect sensors."""
import logging

from . import DATA_KEY, AudiEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
        hass, config, async_add_entities, discovery_info=None):
    """Set up the Audi sensors."""
    if discovery_info is None:
        return
    async_add_entities([AudiSensor(hass.data[DATA_KEY], *discovery_info)])


class AudiSensor(AudiEntity):
    """Representation of a Audi sensor."""

    @property
    def state(self):
        """Return the state."""
        return self.instrument.state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self.instrument.unit
