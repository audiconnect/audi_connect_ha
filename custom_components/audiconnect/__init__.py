"""Support for Audi Connect."""

from datetime import timedelta
import voluptuous as vol
import logging

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
        _LOGGER.info("Scheduled cloud update started...")
        await data.update(utcnow())

    # Schedule the update_data function if option is true
    if _scan_active:
        _LOGGER.info(
            "Scheduling cloud update every %d minutes.", scan_interval.seconds / 60
        )
        async_track_time_interval(hass, update_data, scan_interval)
    else:
        _LOGGER.info(
            "Active Polling at Scan Interval is turned off in user options. Skipping scheduling..."
        )

    # Initially update the data if option is true
    if _scan_initial:
        _LOGGER.info("Requesting initial cloud update...")
        return await data.update(utcnow())
    else:
        _LOGGER.info(
            "Cloud Update at Start is turned off in user options. Skipping initial update..."
        )

    _LOGGER.debug("Audi Connect Setup Complete.")
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


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    return True


async def async_migrate_entry(
    self, hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
    """Migrates an old configuration entry to version 2."""

    if config_entry.version == 1:
        # Update config entry data with spread operator
        new_data = {**config_entry.data}
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, minor_version=0, version=2
        )
        _LOGGER.info(
            f"Migration to version {config_entry.version}.{config_entry.minor_version} successful"
        )

        # Get device registry and iterate through devices
        device_registry = await dr.async_get(hass)
        for entry_id, device in device_registry.devices.items():
            if device.domain == DOMAIN and "identifiers" in device.config_entries:
                old_identifier = device.config_entries["identifiers"][0]

                # Check for old identifier using f-string for clarity
                if old_identifier[1] == self._instrument.vehicle_name:
                    _LOGGER.info(
                        f"Migrating device {device.name} ({device.id}) to new identifier"
                    )
                    new_identifier = (DOMAIN, self._instrument.vehicle_vin)
                    try:
                        await device_registry.async_update_device(
                            entry_id, device_id=new_identifier["id"]
                        )
                        _LOGGER.info(f"Migration for device {device.name} successful")
                    except Exception as e:
                        _LOGGER.error(f"Migration for device {device.name} failed: {e}")
                else:
                    _LOGGER.info(
                        f"No migration necessary for device {device.name} ({device.id}) to new identifier"
                    )

    else:
        _LOGGER.info(
            f"No migration necessary for config entry version {config_entry.version}"
        )

    return True