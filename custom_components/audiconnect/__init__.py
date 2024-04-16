"""Support for Audi Connect."""

from datetime import timedelta
import voluptuous as vol
import logging

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util.dt import utcnow
from homeassistant import config_entries
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_RESOURCES,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)

from .audi_account import AudiAccount

from .const import (
    DOMAIN,
    CONF_REGION,
    CONF_MUTABLE,
    CONF_SCAN_INITIAL,
    CONF_SCAN_ACTIVE,
    DEFAULT_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    RESOURCES,
    COMPONENTS,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=timedelta(minutes=DEFAULT_UPDATE_INTERVAL),
                ): vol.All(
                    cv.time_period,
                    vol.Clamp(min=timedelta(minutes=MIN_UPDATE_INTERVAL)),
                ),
                vol.Optional(CONF_NAME, default={}): cv.schema_with_slug_keys(
                    cv.string
                ),
                vol.Optional(CONF_RESOURCES): vol.All(
                    cv.ensure_list, [vol.In(RESOURCES)]
                ),
                vol.Optional(CONF_REGION): cv.string,
                vol.Optional(CONF_MUTABLE, default=True): cv.boolean,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    if hass.config_entries.async_entries(DOMAIN):
        return True

    if DOMAIN not in config:
        return True

    names = config[DOMAIN].get(CONF_NAME)
    if len(names) == 0:
        return True

    data = {}
    data[CONF_USERNAME] = config[DOMAIN].get(CONF_USERNAME)
    data[CONF_PASSWORD] = config[DOMAIN].get(CONF_PASSWORD)
    data[CONF_SCAN_INTERVAL] = config[DOMAIN].get(CONF_SCAN_INTERVAL).seconds / 60
    data[CONF_REGION] = config[DOMAIN].get(CONF_REGION)

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=data
        )
    )

    return True


async def async_setup_entry(hass, config_entry):
    """Set up this integration using UI."""
    _LOGGER.debug("Audi Connect starting...")
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    """Set up the Audi Connect component."""
    hass.data[DOMAIN]["devices"] = set()

    # Attempt to retrieve the scan interval from options, then fall back to data, or use default
    scan_interval = timedelta(
        minutes=config_entry.options.get(
            CONF_SCAN_INTERVAL,
            config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
    )
    _LOGGER.debug("User option for CONF_SCAN_INTERVAL is %s", scan_interval)

    # Get Initial Scan Option - Default to True
    _scan_initial = config_entry.options.get(CONF_SCAN_INITIAL, True)
    _LOGGER.debug("User option for CONF_SCAN_INITIAL is %s.", _scan_initial)

    # Get Active Scan Option - Default to True
    _scan_active = config_entry.options.get(CONF_SCAN_ACTIVE, True)
    _LOGGER.debug("User option for CONF_SCAN_ACTIVE is %s.", _scan_active)

    account = config_entry.data.get(CONF_USERNAME)

    if account not in hass.data[DOMAIN]:
        data = hass.data[DOMAIN][account] = AudiAccount(hass, config_entry)
        data.init_connection()
    else:
        data = hass.data[DOMAIN][account]

    # Define a callback function for the timer to update data
    async def update_data(now):
        """Update the data with the latest information."""
        _LOGGER.debug("ACTIVE POLLING: Requesting scheduled cloud data refresh...")
        await data.update(utcnow())

    # Schedule the update_data function if option is true
    if _scan_active:
        _LOGGER.debug(
            "ACTIVE POLLING: Scheduling cloud data refresh every %d minutes.",
            scan_interval.seconds / 60,
        )
        async_track_time_interval(hass, update_data, scan_interval)
    else:
        _LOGGER.debug(
            "ACTIVE POLLING: Active Polling at Scan Interval is turned off in user options. Skipping scheduling..."
        )

    # Initially update the data if option is true
    if _scan_initial:
        _LOGGER.debug("Requesting initial cloud data update...")
        return await data.update(utcnow())
    else:
        _LOGGER.debug(
            "Cloud Update at Start is turned off in user options. Skipping initial update..."
        )

    _LOGGER.debug("Audi Connect Setup Complete")
    return True


async def async_unload_entry(hass, config_entry):
    account = config_entry.data.get(CONF_USERNAME)

    data = hass.data[DOMAIN][account]

    for component in COMPONENTS:
        await hass.config_entries.async_forward_entry_unload(
            data.config_entry, component
        )

    del hass.data[DOMAIN][account]

    return True
