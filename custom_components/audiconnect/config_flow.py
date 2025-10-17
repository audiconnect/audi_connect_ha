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
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .audi_connect_account import AudiConnectAccount
from .const import (
    DOMAIN,
    CONF_SPIN,
    DEFAULT_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    CONF_SCAN_INITIAL,
    CONF_SCAN_ACTIVE,
    REGIONS,
    CONF_API_LEVEL,
    DEFAULT_API_LEVEL,
    API_LEVELS,
)

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
        self._api_level = DEFAULT_API_LEVEL

    async def async_step_user(self, user_input=None):
        """Handle a user initiated config flow."""
        errors = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._spin = user_input.get(CONF_SPIN)
            self._region = REGIONS[user_input.get(CONF_REGION)]
            self._scan_interval = user_input[CONF_SCAN_INTERVAL]
            self._api_level = user_input[CONF_API_LEVEL]

            try:
                # pylint: disable=no-value-for-parameter
                session = async_get_clientsession(self.hass)
                connection = AudiConnectAccount(
                    session=session,
                    username=vol.Email()(self._username),
                    password=self._password,
                    country=self._region,
                    spin=self._spin,
                    api_level=self._api_level,
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
                            CONF_API_LEVEL: self._api_level,
                        },
                    )

        data_schema = OrderedDict()
        data_schema[vol.Required(CONF_USERNAME, default=self._username)] = str
        data_schema[vol.Required(CONF_PASSWORD, default=self._password)] = str
        data_schema[vol.Optional(CONF_SPIN, default=self._spin)] = str
        data_schema[vol.Required(CONF_REGION, default=self._region)] = vol.In(REGIONS)
        data_schema[
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_UPDATE_INTERVAL)
        ] = int
        data_schema[
            vol.Optional(CONF_API_LEVEL, default=API_LEVELS[DEFAULT_API_LEVEL])
        ] = vol.All(vol.Coerce(int), vol.In(API_LEVELS))

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(data_schema),
            errors=errors,
        )

    async def async_step_import(self, user_input):
        """Import a config flow from configuration."""
        username = user_input[CONF_USERNAME]
        password = user_input[CONF_PASSWORD]
        api_level = user_input[CONF_API_LEVEL]

        spin = None
        if user_input.get(CONF_SPIN):
            spin = user_input[CONF_SPIN]

        region = "DE"
        if user_input.get(CONF_REGION):
            region = REGIONS[user_input.get(CONF_REGION)]

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
                api_level=api_level,
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
                CONF_API_LEVEL: api_level,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        _LOGGER.debug(
            "Initializing options flow for audiconnect: %s", config_entry.title
        )

    async def async_step_init(self, user_input: dict | None = None):
        _LOGGER.debug(
            "Options flow initiated for audiconnect: %s", self._config_entry.title
        )

        if user_input is not None:
            _LOGGER.debug(
                "Received user input for options: %s",
                {k: "****" if k == CONF_PASSWORD else v for k, v in user_input.items()},
            )

            # Pull password out of options payload
            new_password = user_input.pop(CONF_PASSWORD, None)

            # Update the entry data only if user actually provided a new password
            if new_password:
                new_data = dict(self._config_entry.data)
                new_data[CONF_PASSWORD] = new_password
                _LOGGER.debug(
                    "Updating config_entry.data with new password for %s",
                    self._config_entry.title,
                )
                self.hass.config_entries.async_update_entry(
                    self._config_entry, data=new_data
                )

            # Store the remaining items as options as usual
            return self.async_create_entry(title="", data=user_input)

        current_scan_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )

        current_api_level = self._config_entry.options.get(
            CONF_API_LEVEL,
            self._config_entry.data.get(CONF_API_LEVEL, API_LEVELS[DEFAULT_API_LEVEL]),
        )

        _LOGGER.debug(
            "Retrieved current scan interval for audiconnect %s: %s minutes",
            self._config_entry.title,
            current_scan_interval,
        )

        _LOGGER.debug(
            "Preparing options form for %s with defaults",
            self._config_entry.title,
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INITIAL,
                    default=self._config_entry.options.get(CONF_SCAN_INITIAL, True),
                ): bool,
                vol.Required(
                    CONF_SCAN_ACTIVE,
                    default=self._config_entry.options.get(CONF_SCAN_ACTIVE, True),
                ): bool,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=current_scan_interval
                ): vol.All(vol.Coerce(int), vol.Clamp(min=MIN_UPDATE_INTERVAL)),
                vol.Optional(CONF_API_LEVEL, default=current_api_level): vol.All(
                    vol.Coerce(int), vol.In(API_LEVELS)
                ),
                vol.Optional(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
