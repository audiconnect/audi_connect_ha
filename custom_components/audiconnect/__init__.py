"""Support for Audi Connect."""
from datetime import timedelta
import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.util.dt import utcnow
from homeassistant import config_entries
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_RESOURCES,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME
)

from homeassistant.util.unit_system import (
    _CONF_UNIT_SYSTEM_US_CUSTOMARY,
    METRIC_SYSTEM,
    US_CUSTOMARY_SYSTEM,
    UnitSystem,
)

from .audi_account import AudiAccount
from .audi_services import AudiService

from .const import (
    DOMAIN,
    CONF_REGION,
    CONF_MUTABLE,
    DEFAULT_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    RESOURCES,
    COMPONENTS,
)

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

    account = config_entry.data.get(CONF_USERNAME)

    unit_system = "metric"
    if hass.config.units is US_CUSTOMARY_SYSTEM:
        unit_system = "imperial"

    if account not in hass.data[DOMAIN]:
        data = hass.data[DOMAIN][account] = AudiAccount(hass, config_entry, unit_system=unit_system)
        data.init_connection()
    else:
        data = hass.data[DOMAIN][account]

    return await data.update(utcnow())


async def async_unload_entry(hass, config_entry):
    account = config_entry.data.get(CONF_USERNAME)

    data = hass.data[DOMAIN][account]

    for component in COMPONENTS:
        await hass.config_entries.async_forward_entry_unload(
            data.config_entry, component
        )

    del hass.data[DOMAIN][account]

    return True
