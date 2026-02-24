from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, SelectSelector, SelectSelectorConfig, SelectSelectorMode, TextSelector

from .audi_connect_account import AudiConnectAccount
from .const import (
    API_LEVELS,
    CONF_API_LEVEL,
    CONF_FILTER_VINS,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SCAN_ACTIVE,
    CONF_SCAN_INITIAL,
    CONF_SCAN_INTERVAL,
    CONF_SPIN,
    CONF_USERNAME,
    DEFAULT_API_LEVEL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MIN_UPDATE_INTERVAL,
    REGIONS,
)

_LOGGER = logging.getLogger(__name__)

REGION_OPTIONS = {str(k): v for k, v in REGIONS.items()}
REGION_REVERSE = {v: k for k, v in REGIONS.items()}


class AudiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()

            region = REGION_OPTIONS[user_input[CONF_REGION]]

            try:
                session = async_get_clientsession(self.hass)
                connection = AudiConnectAccount(
                    session=session,
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    country=region,
                    spin=user_input.get(CONF_SPIN),
                    api_level=int(user_input[CONF_API_LEVEL]),
                )
                if not await connection.try_login(False):
                    errors["base"] = "invalid_credentials"
                else:
                    return self.async_create_entry(
                        title=user_input[CONF_USERNAME],
                        data={
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            CONF_SPIN: user_input.get(CONF_SPIN),
                            CONF_REGION: region,
                            CONF_SCAN_INTERVAL: max(
                                user_input.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                                MIN_UPDATE_INTERVAL,
                            ),
                            CONF_API_LEVEL: int(user_input[CONF_API_LEVEL]),
                        },
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Audi config flow failed")
                errors["base"] = "unexpected"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_SPIN): str,
                    vol.Required(CONF_REGION, default="1"): SelectSelector(
                        SelectSelectorConfig(
                            options=[{"value": k, "label": v} for k, v in REGION_OPTIONS.items()],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): NumberSelector(
                        NumberSelectorConfig(min=MIN_UPDATE_INTERVAL, mode="box")
                    ),
                    vol.Required(CONF_API_LEVEL, default=str(API_LEVELS[DEFAULT_API_LEVEL])): SelectSelector(
                        SelectSelectorConfig(options=[str(level) for level in API_LEVELS], mode=SelectSelectorMode.DROPDOWN)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = max(
                int(user_input[CONF_SCAN_INTERVAL]), MIN_UPDATE_INTERVAL
            )
            user_input[CONF_API_LEVEL] = int(user_input[CONF_API_LEVEL])
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INITIAL,
                        default=self._config_entry.options.get(CONF_SCAN_INITIAL, True),
                    ): bool,
                    vol.Required(
                        CONF_SCAN_ACTIVE,
                        default=self._config_entry.options.get(CONF_SCAN_ACTIVE, True),
                    ): bool,
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_SCAN_INTERVAL,
                            self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                        ),
                    ): NumberSelector(NumberSelectorConfig(min=MIN_UPDATE_INTERVAL, mode="box")),
                    vol.Required(
                        CONF_API_LEVEL,
                        default=str(self._config_entry.options.get(
                            CONF_API_LEVEL,
                            self._config_entry.data.get(CONF_API_LEVEL, API_LEVELS[DEFAULT_API_LEVEL]),
                        )),
                    ): SelectSelector(
                        SelectSelectorConfig(options=[str(level) for level in API_LEVELS], mode=SelectSelectorMode.DROPDOWN)
                    ),
                    vol.Optional(
                        CONF_FILTER_VINS,
                        default=self._config_entry.options.get(
                            CONF_FILTER_VINS,
                            self._config_entry.data.get(CONF_FILTER_VINS, ""),
                        ),
                    ): TextSelector(),
                }
            ),
        )
