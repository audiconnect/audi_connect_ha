"""Support for tracking an Audi."""
import logging

from homeassistant.components.device_tracker import SOURCE_TYPE_GPS
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.util import slugify
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.core import callback
from homeassistant.const import CONF_USERNAME

from .const import DOMAIN, SIGNAL_STATE_UPDATED, TRACKER_UPDATE

_LOGGER = logging.getLogger(__name__)

async def async_setup_scanner(hass, config, async_see, discovery_info=None):
    """Old way."""  

async def async_setup_entry(hass, config_entry, async_add_entities):
    async def see_vehicle(instrument):
        """Handle the reporting of the vehicle position."""
        if instrument.vehicle_name in hass.data[DOMAIN]["devices"]:
            return

        hass.data[DOMAIN]["devices"].add(instrument.vehicle_name)

        async_add_entities([AudiDeviceTracker(instrument)])

    async_dispatcher_connect(hass, TRACKER_UPDATE, see_vehicle)

    account = config_entry.data.get(CONF_USERNAME)
    audiData = hass.data[DOMAIN][account]

    for config_vehicle in audiData.config_vehicles:
        for device_tracker in config_vehicle.device_trackers:
            async_dispatcher_send(hass, TRACKER_UPDATE, device_tracker)

    return True

class AudiDeviceTracker(TrackerEntity):
    """Represent a tracked device."""

    def __init__(self, instrument):
        """Set up Locative entity."""
        self._unsub_dispatcher = None
        self._state = instrument.state
        self._vehicle_name = instrument.vehicle_name
        self._name = 'audi_{}'.format(slugify(instrument.vehicle_name))

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return "mdi:car"

    @property
    def latitude(self):
        """Return latitude value of the device."""
        return self._state[0]

    @property
    def longitude(self):
        """Return longitude value of the device."""
        return self._state[1]

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def source_type(self):
        """Return the source type, eg gps or router, of the device."""
        return SOURCE_TYPE_GPS

    async def async_added_to_hass(self):
        """Register state update callback."""
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, TRACKER_UPDATE, self._async_receive_data
        )

    async def async_will_remove_from_hass(self):
        """Clean up after entity before removal."""
        self._unsub_dispatcher()

    @callback
    def _async_receive_data(self, instrument):
        """Update device data."""
        if instrument.vehicle_name != self._vehicle_name:
            return

        self._state = instrument.state

        self.async_write_ha_state()
