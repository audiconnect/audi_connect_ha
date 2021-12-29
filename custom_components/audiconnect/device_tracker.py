"""Support for tracking an Audi."""
import logging

from homeassistant.components.device_tracker import SOURCE_TYPE_GPS
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
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
        self._instrument = instrument
        self._state = instrument.state

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
        """Return full name of the entity."""
        return "{} {}".format(self._vehicle_name, self._entity_name)

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
        await super().async_added_to_hass()
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, TRACKER_UPDATE, self._async_receive_data
        )

    async def async_will_remove_from_hass(self):
        """Clean up after entity before removal."""
        await super().async_will_remove_from_hass()
        self._unsub_dispatcher()

    @callback
    def _async_receive_data(self, instrument):
        """Update device data."""
        if instrument.vehicle_name != self._vehicle_name:
            return

        self._state = instrument.state

        self.async_write_ha_state()

    @property
    def _entity_name(self):
        return self._instrument.name

    @property
    def _vehicle_name(self):
        return self._instrument.vehicle_name

    @property
    def unique_id(self):
        return self._instrument.full_name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._instrument.vehicle_name)},
            "manufacturer": "Audi",
            "name": self._vehicle_name,
            "device_type": "device_tracker",
        }

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return dict(
            self._instrument.attributes,
            model="{}/{}".format(
                self._instrument.vehicle_model, self._instrument.vehicle_name
            ),
            model_year=self._instrument.vehicle_model_year,
            model_family=self._instrument.vehicle_model_family,
            title=self._instrument.vehicle_name,
            csid=self._instrument.vehicle_csid,
            vin=self._instrument.vehicle_vin,
        )
