"""Support for Audi Connect locks."""
import logging

from homeassistant.components.lock import LockEntity
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
        for lock in config_vehicle.locks:
            sensors.append(AudiLock(config_vehicle, lock))

    async_add_entities(sensors)


class AudiLock(AudiEntity, LockEntity):
    """Represents a car lock."""

    @property
    def is_locked(self):
        """Return true if lock is locked."""
        return self._instrument.is_locked

    async def async_lock(self, **kwargs):
        """Lock the car."""
        await self._instrument.lock()

    async def async_unlock(self, **kwargs):
        """Unlock the car."""
        await self._instrument.unlock()
