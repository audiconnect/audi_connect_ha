from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .audi_connect_account import AudiConnectAccount
from .audi_services import AudiAuthError
from .const import (
    API_LEVELS,
    CONF_API_LEVEL,
    CONF_FILTER_VINS,
    CONF_PASSWORD,
    CONF_REFRESH_AFTER_ACTION,
    CONF_REFRESH_TOKEN,
    CONF_REGION,
    CONF_SCAN_INITIAL,
    CONF_SCAN_INTERVAL,
    CONF_SPIN,
    CONF_UPDATE_SLEEP,
    CONF_USERNAME,
    DEFAULT_API_LEVEL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    UPDATE_SLEEP,
    MIN_UPDATE_INTERVAL,
    REGIONS,
    uses_device_code,
)

_LOGGER = logging.getLogger(__name__)

REGION_OPTIONS = {str(k): v for k, v in REGIONS.items()}
REGION_REVERSE = {v: k for k, v in REGIONS.items()}


class AudiConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 3

    def __init__(self) -> None:
        self._flow_data: dict[str, Any] = {}
        self._connection: AudiConnectAccount | None = None
        self._device_code: str | None = None
        self._verification_uri: str | None = None
        self._user_code: str | None = None
        self._reauth_entry: ConfigEntry | None = None

    def _build_connection(
        self, username: str | None = None, password: str | None = None
    ) -> AudiConnectAccount:
        session = async_get_clientsession(self.hass)
        return AudiConnectAccount(
            session=session,
            country=self._flow_data[CONF_REGION],
            spin=self._flow_data.get(CONF_SPIN),
            api_level=self._flow_data.get(CONF_API_LEVEL, DEFAULT_API_LEVEL),
            username=username,
            password=password,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._flow_data = {
                CONF_REGION: REGION_OPTIONS[user_input[CONF_REGION]],
                CONF_SPIN: user_input.get(CONF_SPIN),
                CONF_API_LEVEL: int(user_input[CONF_API_LEVEL]),
                CONF_SCAN_INTERVAL: max(
                    int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL)),
                    MIN_UPDATE_INTERVAL,
                ),
            }
            if uses_device_code(self._flow_data[CONF_REGION]):
                return await self.async_step_device()
            return await self.async_step_credentials()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SPIN): str,
                    vol.Required(CONF_REGION, default="1"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": k, "label": v}
                                for k, v in REGION_OPTIONS.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                    ): NumberSelector(
                        NumberSelectorConfig(min=MIN_UPDATE_INTERVAL, mode="box")
                    ),
                    vol.Required(
                        CONF_API_LEVEL, default=str(API_LEVELS[DEFAULT_API_LEVEL])
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[str(level) for level in API_LEVELS],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Username/password sign-in, for regions without attestation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            connection = self._build_connection(username, password)
            try:
                if await connection.try_login(False):
                    return await self._finish_password_login(username, password)
                errors["base"] = "invalid_credentials"
            except AudiAuthError:
                errors["base"] = "invalid_credentials"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Audi password login failed")
                errors["base"] = "unexpected"

        step_id = (
            "reauth_credentials" if self._reauth_entry is not None else "credentials"
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=(user_input or {}).get(CONF_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def _finish_password_login(
        self, username: str, password: str
    ) -> ConfigFlowResult:
        """Persist a username/password entry (or update it on reauth)."""
        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data={
                    **self._reauth_entry.data,
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                },
            )

        await self.async_set_unique_id(username.lower())
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=username,
            data={
                **self._flow_data,
                CONF_USERNAME: username,
                CONF_PASSWORD: password,
            },
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Device Authorization Grant: show a code/URL, then poll for approval."""
        errors: dict[str, str] = {}

        if self._connection is None:
            self._connection = self._build_connection()

        if self._device_code is None:
            try:
                response = await self._connection.request_device_code()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Audi device authorization request failed")
                return self.async_abort(reason="device_auth_failed")
            self._device_code = response["device_code"]
            self._verification_uri = response.get(
                "verification_uri_complete"
            ) or response.get("verification_uri")
            self._user_code = response.get("user_code")

        if user_input is not None:
            try:
                status = await self._connection.poll_device_token(self._device_code)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Audi device token poll failed")
                status = None
                errors["base"] = "device_auth_failed"
            if status == "ok":
                return await self._finish_device_login()
            if status in ("authorization_pending", "slow_down"):
                errors["base"] = "authorization_pending"
            elif status == "expired":
                # Code timed out; mint a fresh one and show it again.
                self._device_code = None
                return await self.async_step_device()
            elif status is not None:
                errors["base"] = "device_auth_failed"

        step_id = "reauth_confirm" if self._reauth_entry is not None else "device"
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({}),
            description_placeholders={
                "verification_uri": self._verification_uri or "",
                "user_code": self._user_code or "",
            },
            errors=errors,
        )

    async def _finish_device_login(self) -> ConfigFlowResult:
        assert self._connection is not None
        refresh_token = self._connection.refresh_token
        if not refresh_token:
            # Approved but no refresh token issued; do not persist a dead entry.
            return self.async_abort(reason="device_auth_failed")

        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data={
                    **self._reauth_entry.data,
                    CONF_REFRESH_TOKEN: refresh_token,
                },
            )

        identifier = self._connection.account_identifier()
        if identifier:
            await self.async_set_unique_id(identifier.lower())
            self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=identifier or "Audi Connect",
            data={**self._flow_data, CONF_REFRESH_TOKEN: refresh_token},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        self._reauth_entry = self._get_reauth_entry()
        self._flow_data = {
            CONF_REGION: self._reauth_entry.data.get(CONF_REGION),
            CONF_SPIN: self._reauth_entry.data.get(CONF_SPIN),
            CONF_API_LEVEL: self._reauth_entry.data.get(
                CONF_API_LEVEL, DEFAULT_API_LEVEL
            ),
        }
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if uses_device_code(self._flow_data.get(CONF_REGION)):
            return await self.async_step_device(user_input)
        return await self.async_step_credentials(user_input)

    async def async_step_reauth_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reauth form id for the credentials path (see async_step_credentials)."""
        return await self.async_step_credentials(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            return self.async_update_reload_and_abort(
                reconfigure_entry,
                data_updates={
                    CONF_SPIN: user_input.get(CONF_SPIN),
                    CONF_REGION: REGION_OPTIONS[user_input[CONF_REGION]],
                    CONF_API_LEVEL: int(user_input[CONF_API_LEVEL]),
                },
            )

        current_region = reconfigure_entry.data.get(CONF_REGION, "DE")
        current_region_key = str(REGION_REVERSE.get(current_region, 1))

        return self.async_show_form(
            step_id="reconfigure",
            # 2.2.0 interpolated {username} into the reconfigure description.
            # A browser session from before the update still has that string
            # cached, and rendering it without the value fails hard (formatjs
            # MISSING_VALUE), leaving an empty dialog. Keep providing it.
            description_placeholders={"username": reconfigure_entry.title},
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SPIN,
                        default=reconfigure_entry.data.get(CONF_SPIN, ""),
                    ): str,
                    vol.Required(
                        CONF_REGION, default=current_region_key
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": k, "label": v}
                                for k, v in REGION_OPTIONS.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_API_LEVEL,
                        default=str(
                            reconfigure_entry.data.get(
                                CONF_API_LEVEL, API_LEVELS[DEFAULT_API_LEVEL]
                            )
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[str(level) for level in API_LEVELS],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = max(
                int(user_input[CONF_SCAN_INTERVAL]), MIN_UPDATE_INTERVAL
            )
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INITIAL,
                        default=self.config_entry.options.get(CONF_SCAN_INITIAL, True),
                    ): bool,
                    vol.Required(
                        CONF_REFRESH_AFTER_ACTION,
                        default=self.config_entry.options.get(
                            CONF_REFRESH_AFTER_ACTION, False
                        ),
                    ): bool,
                    vol.Required(
                        CONF_UPDATE_SLEEP,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_SLEEP, UPDATE_SLEEP
                        ),
                    ): NumberSelector(NumberSelectorConfig(min=0, mode="box")),
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL,
                            self.config_entry.data.get(
                                CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL
                            ),
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(min=MIN_UPDATE_INTERVAL, mode="box")
                    ),
                    vol.Optional(
                        CONF_FILTER_VINS,
                        default=self.config_entry.options.get(
                            CONF_FILTER_VINS,
                            self.config_entry.data.get(CONF_FILTER_VINS, ""),
                        ),
                    ): TextSelector(),
                }
            ),
        )


__all__ = ["AudiConfigFlow", "OptionsFlowHandler"]
