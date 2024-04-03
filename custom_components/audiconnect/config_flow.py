from collections import OrderedDict
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import callback

from .audi_connect_account import AudiConnectAccount
from .const import DOMAIN, CONF_SPIN, DEFAULT_UPDATE_INTERVAL, MIN_UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


@callback
def configured_accounts(hass):
    """Return tuple of configured usernames."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if entries:
        return (entry.data[CONF_USERNAME] for entry in entries)
    return ()


@config_entries.HANDLERS.register(DOMAIN)
class AudiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    def __init__(self):
        """Initialize."""
        self._username = vol.UNDEFINED
        self._password = vol.UNDEFINED
        self._spin = vol.UNDEFINED
        self._region = vol.UNDEFINED
        self._scan_interval = DEFAULT_UPDATE_INTERVAL

    async def async_step_user(self, user_input=None):
        """Handle a user initiated config flow."""
        errors = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._spin = user_input.get(CONF_SPIN)
            self._region = user_input.get(CONF_REGION)
            self._scan_interval = user_input[CONF_SCAN_INTERVAL]

            try:
                # pylint: disable=no-value-for-parameter
                session = async_get_clientsession(self.hass)
                connection = AudiConnectAccount(
                    session=session,
                    username=vol.Email()(self._username),
                    password=self._password,
                    country=self._region,
                    spin=self._spin,
                )

                if await connection.try_login(False) is False:
                    raise Exception(
                        "Unexpected error communicating with the Audi server"
                    )

            except vol.Invalid:
                errors[CONF_USERNAME] = "invalid_username"
            except Exception:
                errors["base"] = "invalid_credentials"
            else:
                if self._username in configured_accounts(self.hass):
                    errors["base"] = "user_already_configured"
                else:
                    return self.async_create_entry(
                        title=f"{self._username}",
                        data={
                            CONF_USERNAME: self._username,
                            CONF_PASSWORD: self._password,
                            CONF_SPIN: self._spin,
                            CONF_REGION: self._region,
                            CONF_SCAN_INTERVAL: self._scan_interval,
                        },
                    )

        data_schema = OrderedDict()
        data_schema[vol.Required(CONF_USERNAME, default=self._username)] = str
        data_schema[vol.Required(CONF_PASSWORD, default=self._password)] = str
        data_schema[vol.Optional(CONF_SPIN, default=self._spin)] = str
        data_schema[vol.Optional(CONF_REGION, default=self._region)] = str
        data_schema[
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_UPDATE_INTERVAL)
        ] = int

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(data_schema),
            errors=errors,
        )

    async def async_step_import(self, user_input):
        """Import a config flow from configuration."""
        username = user_input[CONF_USERNAME]
        password = user_input[CONF_PASSWORD]

        spin = None
        if user_input.get(CONF_SPIN):
            spin = user_input[CONF_SPIN]

        region = "DE"
        if user_input.get(CONF_REGION):
            region = user_input.get(CONF_REGION)

        scan_interval = DEFAULT_UPDATE_INTERVAL

        if user_input.get(CONF_SCAN_INTERVAL):
            scan_interval = user_input[CONF_SCAN_INTERVAL]

        if scan_interval < MIN_UPDATE_INTERVAL:
            scan_interval = MIN_UPDATE_INTERVAL

        try:
            session = async_get_clientsession(self.hass)
            connection = AudiConnectAccount(
                session=session,
                username=username,
                password=password,
                country=region,
                spin=spin,
            )

            if await connection.try_login(False) is False:
                raise Exception("Unexpected error communicating with the Audi server")

        except Exception:
            _LOGGER.error("Invalid credentials for %s", username)
            return self.async_abort(reason="invalid_credentials")

        return self.async_create_entry(
            title=f"{username} (from configuration)",
            data={
                CONF_USERNAME: username,
                CONF_PASSWORD: password,
                CONF_SPIN: spin,
                CONF_REGION: region,
                CONF_SCAN_INTERVAL: scan_interval,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry: config_entries.ConfigEntry = config_entry
        _LOGGER.debug("Initializing options flow for %s", config_entry.title)

    async def async_step_init(self, user_input=None):
        _LOGGER.debug("Options flow initiated")
        if user_input is not None:
            _LOGGER.debug("Received user input for options: %s", user_input)
            return self.async_create_entry(title="", data=user_input)

        current_scan_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
        _LOGGER.debug("Current scan interval: %s minutes", current_scan_interval)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=current_scan_interval
                    ): vol.All(vol.Coerce(int), vol.Clamp(min=MIN_UPDATE_INTERVAL)),
                }
            ),
        )
