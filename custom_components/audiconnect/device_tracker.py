"""Support for tracking an Audi."""
import logging

from homeassistant.components.device_tracker import SOURCE_TYPE_GPS
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import slugify

from . import DATA_KEY, SIGNAL_STATE_UPDATED

_LOGGER = logging.getLogger(__name__)


async def async_setup_scanner(hass, config, async_see, discovery_info=None):
    """Set up the Audi tracker."""
    if discovery_info is None:
        return

    vin, component, attr = discovery_info
    data = hass.data[DATA_KEY]
    instrument = data.instrument(vin, component, attr)

    async def see_vehicle():
        """Handle the reporting of the vehicle position."""
        host_name = instrument.vehicle_name
        dev_id = 'audi_{}'.format(slugify(host_name))
        await async_see(dev_id=dev_id,
                        host_name=host_name,
                        source_type=SOURCE_TYPE_GPS,
                        gps=instrument.state,
                        icon='mdi:car')

    async_dispatcher_connect(hass, SIGNAL_STATE_UPDATED, see_vehicle)

    return True
