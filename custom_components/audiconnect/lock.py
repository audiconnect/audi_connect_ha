"""Support for Audi Connect locks."""
import logging

from homeassistant.components.lock import LockDevice

from . import DATA_KEY, AudiEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
        hass, config, async_add_entities, discovery_info=None):
    """Set up the Audi On Call lock."""
    if discovery_info is None:
        return

    async_add_entities([AudiLock(hass.data[DATA_KEY], *discovery_info)])


class AudiLock(AudiEntity, LockDevice):
    """Represents a car lock."""

    @property
    def is_locked(self):
        """Return true if lock is locked."""
        return self.instrument.is_locked

    async def async_lock(self, **kwargs):
        """Lock the car."""
        await self.instrument.lock()

    async def async_unlock(self, **kwargs):
        """Unlock the car."""
        await self.instrument.unlock()
