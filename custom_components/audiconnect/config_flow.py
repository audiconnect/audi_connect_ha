from __future__ import annotations

import base64
import logging
import secrets
from collections.abc import Mapping
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qs, urlparse

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
from .audi_services import AudiAuthError, AudiTokenRefreshError
from .local_extensions import (
    DEALER_FIELDS,
    get_local_dealer,
    update_local_dealer_options,
)
from .const import (
    API_LEVELS,
    AUTH0_REDIRECT_URI,
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
    MIN_UPDATE_INTERVAL,
    REGIONS,
    UPDATE_SLEEP,
    entry_uses_auth0,
    uses_auth0,
)

_LOGGER = logging.getLogger(__name__)

REGION_OPTIONS = {str(k): v for k, v in REGIONS.items()}
REGION_REVERSE = {v: k for k, v in REGIONS.items()}
CONF_CALLBACK_URL = "callback_url"


def _generate_auth0_pkce() -> tuple[str, str, str]:
    """Return a PKCE verifier, challenge and OAuth state."""
    verifier = secrets.token_urlsafe(48)
    digest = sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge, secrets.token_urlsafe(24)


def _parse_auth0_callback(callback_url: str, expected_state: str) -> str:
    """Validate a myAudi callback and return its authorization code."""
    parsed = urlparse(callback_url.strip())
    expected = urlparse(AUTH0_REDIRECT_URI)
    params = parse_qs(parsed.query)
    if (
        parsed.scheme,
        parsed.hostname,
        parsed.port,
        parsed.path,
    ) != (
        expected.scheme,
        expected.hostname,
        expected.port,
        expected.path,
    ):
        raise ValueError("invalid_auth0_callback")
    if params.get("error"):
        raise ValueError("auth0_denied")
    state = (params.get("state") or [None])[0]
    code = (params.get("code") or [None])[0]
    if not state or not secrets.compare_digest(state, expected_state) or not code:
        raise ValueError("invalid_auth0_callback")
    return code


class AudiConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 3

    def __init__(self) -> None:
        self._flow_data: dict[str, Any] = {}
        self._connection: AudiConnectAccount | None = None
        self._device_code: str | None = None
        self._verification_uri: str | None = None
        self._user_code: str | None = None
        self._auth0_verifier: str | None = None
        self._auth0_state: str | None = None
        self._auth0_authorization_url: str | None = None
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
            if uses_auth0(self._flow_data[CONF_REGION]):
                return await self.async_step_auth0()
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
            except Exception:
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
            # Schedule the reload ourselves: async_update_reload_and_abort is
            # deprecated (HA 2026.12) for entries that register an update
            # listener, which this integration does.
            self.hass.config_entries.async_schedule_reload(self._reauth_entry.entry_id)
            return self.async_update_and_abort(
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

    async def async_step_auth0(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Interactive Auth0 login using the myAudi PKCE client."""
        errors: dict[str, str] = {}
        if self._connection is None:
            self._connection = self._build_connection()

        if self._auth0_authorization_url is None:
            verifier, challenge, state = _generate_auth0_pkce()
            try:
                authorization_url = await self._connection.get_auth0_authorization_url(
                    challenge, state
                )
            except Exception:
                _LOGGER.exception("Audi Auth0 authorization failed")
                return self.async_abort(reason="auth0_auth_failed")
            self._auth0_verifier = verifier
            self._auth0_state = state
            self._auth0_authorization_url = authorization_url

        if user_input is not None:
            assert self._auth0_state is not None
            assert self._auth0_verifier is not None
            try:
                code = _parse_auth0_callback(
                    user_input[CONF_CALLBACK_URL], self._auth0_state
                )
            except ValueError as err:
                errors["base"] = str(err)
            else:
                try:
                    await self._connection.login_with_auth0_code(
                        code, self._auth0_verifier
                    )
                except (AudiAuthError, AudiTokenRefreshError):
                    errors["base"] = "auth0_auth_failed"
                except Exception:
                    _LOGGER.exception("Audi Auth0 token exchange failed")
                    errors["base"] = "unexpected"
                else:
                    return await self._finish_token_login()

        step_id = "reauth_auth0" if self._reauth_entry is not None else "auth0"
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CALLBACK_URL,
                        default=(user_input or {}).get(CONF_CALLBACK_URL, ""),
                    ): TextSelector()
                }
            ),
            description_placeholders={
                "authorization_url": self._auth0_authorization_url or ""
            },
            errors=errors,
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
            except Exception:
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
            except Exception:
                _LOGGER.exception("Audi device token poll failed")
                status = None
                errors["base"] = "device_auth_failed"
            if status == "ok":
                return await self._finish_token_login()
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

    async def _finish_token_login(self) -> ConfigFlowResult:
        assert self._connection is not None
        refresh_token = self._connection.refresh_token
        if not refresh_token:
            # Approved but no refresh token issued; do not persist a dead entry.
            return self.async_abort(reason="device_auth_failed")

        if self._reauth_entry is not None:
            # Schedule the reload ourselves (see _finish_password_login). A
            # token reauth only changes the refresh token, which the
            # update listener deliberately ignores, so the reload has to be
            # scheduled here explicitly.
            self.hass.config_entries.async_schedule_reload(self._reauth_entry.entry_id)
            return self.async_update_and_abort(
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
        assert self._reauth_entry is not None
        if entry_uses_auth0(self._reauth_entry.data):
            return await self.async_step_auth0(user_input)
        return await self.async_step_credentials(user_input)

    async def async_step_reauth_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reauth form id for the credentials path (see async_step_credentials)."""
        return await self.async_step_credentials(user_input)

    async def async_step_reauth_auth0(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reauth form id for the Auth0 path."""
        return await self.async_step_auth0(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            # Schedule the reload ourselves (see _finish_password_login).
            self.hass.config_entries.async_schedule_reload(reconfigure_entry.entry_id)
            return self.async_update_and_abort(
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
                        # The S-PIN is optional, and an entry created without one
                        # stores None (not a missing key), so the "" fallback of
                        # .get() never applies. Coerce it, or the str validator
                        # rejects the default with "expected str".
                        default=reconfigure_entry.data.get(CONF_SPIN) or "",
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
    """Configure polling and optional per-vehicle, local dealer details."""

    _pending_options: dict[str, Any] | None = None
    _dealer_vin: str | None = None
    _discovery_vin: str | None = None
    _discovery_action: str | None = None
    _discovery_candidate: tuple | None = None
    _discovery_sequence: int | None = None
    _discovery_skipped: set[str] | None = None

    def _dealer_vehicles(self) -> list[tuple[str, str]]:
        """Vehicles already loaded in this account; no extra Audi API request."""
        runtime = getattr(self.config_entry, "runtime_data", None)
        items: list[tuple[str, str]] = []
        for config_vehicle in getattr(
            getattr(runtime, "account", None), "config_vehicles", []
        ):
            vehicle = getattr(config_vehicle, "vehicle", None)
            vin = getattr(vehicle, "vin", None)
            if not isinstance(vin, str) or not vin:
                continue
            name = (
                getattr(vehicle, "title", None)
                or getattr(vehicle, "model", None)
                or "Audi"
            )
            items.append((vin, f"{name} (…{vin[-4:]})"))
        # V3 owns its own vehicle inventory and no longer creates AudiAccount.
        if not items:
            v3 = getattr(runtime, "v3", None)
            for vehicle in getattr(v3, "vehicles", {}).values():
                items.append((vehicle.vin, f"{vehicle.name} (…{vehicle.vin[-4:]})"))
        return items

    async def async_step_dealer_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        vehicles = self._dealer_vehicles()
        if not vehicles:
            return self.async_abort(reason="no_vehicle_available")
        if len(vehicles) == 1:
            self._dealer_vin = vehicles[0][0]
            return await self.async_step_dealer()
        if user_input is not None:
            vin = user_input.get("vehicle")
            if vin not in {key for key, _ in vehicles}:
                return self.async_show_form(
                    step_id="dealer_vehicle",
                    data_schema=vol.Schema(
                        {vol.Required("vehicle"): vol.In(dict(vehicles))}
                    ),
                    errors={"base": "invalid_vehicle"},
                )
            self._dealer_vin = vin
            return await self.async_step_dealer()
        return self.async_show_form(
            step_id="dealer_vehicle",
            data_schema=vol.Schema(
                {
                    vol.Required("vehicle", default=vehicles[0][0]): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": vin, "label": label}
                                for vin, label in vehicles
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_dealer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        vin = self._dealer_vin
        if not vin:
            return await self.async_step_dealer_vehicle()
        pending = self._pending_options or dict(self.config_entry.options)
        errors: dict[str, str] = {}
        if user_input is not None:
            updates = {
                key: user_input[key] for key in DEALER_FIELDS if key in user_input
            }
            try:
                options = update_local_dealer_options(
                    pending, vin, updates, clear=bool(user_input.get("clear", False))
                )
            except ValueError:
                errors["base"] = "invalid_dealer"
            else:
                return self.async_create_entry(title="", data=options)
        existing = get_local_dealer(pending, vin)
        data_schema = vol.Schema(
            {
                **{
                    vol.Optional(
                        key,
                        default=(
                            user_input.get(key, existing.get(key, ""))
                            if user_input is not None
                            else existing.get(key, "")
                        ),
                    ): TextSelector()
                    for key in DEALER_FIELDS
                },
                vol.Optional("clear", default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="dealer", data_schema=data_schema, errors=errors
        )

    def _discovery_engine(self):
        runtime = getattr(self.config_entry, "runtime_data", None)
        return getattr(runtime, "v3", None)

    def _discovery_context(self):
        engine = self._discovery_engine()
        if engine is None or self._discovery_vin is None:
            raise ValueError("No active V3 vehicle")
        car = engine.require_vehicle(self._discovery_vin)
        return engine, car, engine.profiles[car.vin.lower()]

    async def async_step_discovery_vehicle(self, user_input=None):
        engine = self._discovery_engine()
        if engine is None:
            return self.async_abort(reason="no_vehicle_available")
        vehicles = [
            (car.vin, f"{car.name} (…{car.vin[-4:]})")
            for car in engine.vehicles.values()
            if car.inventory_present
        ]
        if not vehicles:
            return self.async_abort(reason="no_vehicle_available")
        if len(vehicles) == 1:
            self._discovery_vin = vehicles[0][0]
            return await self.async_step_discovery()
        if user_input and user_input.get("vehicle") in dict(vehicles):
            self._discovery_vin = user_input["vehicle"]
            return await self.async_step_discovery()
        return self.async_show_form(
            step_id="discovery_vehicle",
            data_schema=vol.Schema({vol.Required("vehicle"): vol.In(dict(vehicles))}),
        )

    async def async_step_discovery(self, user_input=None):
        from .v3.read_discovery import user_test_candidates

        engine, car, profile = self._discovery_context()
        active = profile.discovery._active
        if active is not None:
            self._discovery_sequence = active.sequence
            return await self.async_step_discovery_review()
        if profile.last_command is not None and profile.last_command.unresolved:
            return await self.async_step_discovery_recover()
        if self._discovery_skipped is None:
            self._discovery_skipped = set()
        candidates = {
            key: value
            for key, value in user_test_candidates(engine, car, profile).items()
            if key not in self._discovery_skipped
        }
        if user_input is not None:
            choice = user_input.get("action")
            if choice == "finish":
                return self.async_create_entry(
                    title="",
                    data=self._pending_options or dict(self.config_entry.options),
                )
            if choice == "refresh":
                await engine.resume_read_discovery(car.vin)
                return await self.async_step_discovery()
        if candidates:
            self._discovery_action, self._discovery_candidate = next(
                iter(candidates.items())
            )
            return await self.async_step_discovery_consent()
        progress = engine.discovery_progress(car, profile)
        return self.async_show_form(
            step_id="discovery",
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="finish"): vol.In(
                        {
                            "finish": "Finish",
                            "refresh": "Resume unresolved read discovery",
                        }
                    )
                }
            ),
            description_placeholders={
                "vehicle": car.name,
                "read_state": str(progress["read_state"]).replace("_", " "),
                "read": str(progress["read_assessment_percent"]),
                "assessed": str(progress["read_assessed"]),
                "total": str(progress["read_total"]),
                "verified": str(progress["controls_physically_verified"]),
                "controls": str(progress["controls_catalog_applicable"]),
            },
        )

    async def async_step_discovery_consent(self, user_input=None):
        from .v3.read_discovery import user_test_candidates

        engine, car, profile = self._discovery_context()
        candidate = user_test_candidates(engine, car, profile).get(
            self._discovery_action
        )
        if candidate is None or candidate != self._discovery_candidate:
            # Do not reuse a consent when discovery changed the actual route.
            self._discovery_candidate = None
            return await self.async_step_discovery()
        label, capability, action, operation, group = candidate
        errors = {}
        if user_input is not None:
            answer = user_input.get("accept")
            if answer == "finish":
                return self.async_create_entry(
                    title="",
                    data=self._pending_options or dict(self.config_entry.options),
                )
            if answer is not True and answer != "yes":
                if self._discovery_skipped is None:
                    self._discovery_skipped = set()
                self._discovery_skipped.add(self._discovery_action)
                self._discovery_candidate = None
                return await self.async_step_discovery()
            self._discovery_candidate = None  # Single-use explicit action approval.
            try:
                result = await engine.approved_control_discovery(
                    car.vin,
                    action,
                    operation,
                    approval=group,
                    capability=capability,
                    guided=True,
                )
            except (ValueError, RuntimeError, OSError, TimeoutError):
                errors["base"] = "discovery_test_failed"
                if profile.discovery._active is not None:
                    self._discovery_sequence = profile.discovery._active.sequence
                    return await self.async_step_discovery_review()
                # Keep the same question available for an explicit retry after cooldown.
                self._discovery_candidate = candidate
            else:
                self._discovery_sequence = result["sequence"]
                return await self.async_step_discovery_review()
        progress = engine.discovery_progress(car, profile)
        return self.async_show_form(
            step_id="discovery_consent",
            data_schema=vol.Schema(
                {
                    vol.Required("accept", default="no"): vol.In(
                        {"yes": "Yes", "no": "No / skip", "finish": "Finish"}
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "vehicle": car.name,
                "action": label,
                "verified": str(progress["controls_physically_verified"]),
                "controls": str(progress["controls_catalog_applicable"]),
                "skipped": str(len(self._discovery_skipped or ())),
            },
        )

    async def async_step_discovery_review(self, user_input=None):
        engine, car, profile = self._discovery_context()
        active = profile.discovery._active
        if active is None:
            return await self.async_step_discovery()
        errors = {}
        if user_input is not None:
            outcome = user_input.get("outcome")
            if outcome in ("worked", "failed", "uncertain"):
                try:
                    await engine.review_action(car.vin, active.sequence, outcome)
                except (ValueError, RuntimeError, OSError):
                    errors["base"] = "discovery_test_failed"
                else:
                    if outcome == "uncertain":
                        return self.async_create_entry(
                            title="",
                            data=self._pending_options
                            or dict(self.config_entry.options),
                        )
                    return await self.async_step_discovery()
        return self.async_show_form(
            step_id="discovery_review",
            data_schema=vol.Schema(
                {
                    vol.Required("outcome", default="uncertain"): vol.In(
                        {
                            "worked": "OK",
                            "failed": "Not OK",
                            "uncertain": "Not sure — retain pending review",
                        }
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "vehicle": car.name,
                "action": active.action,
                "transport": active.transport,
            },
        )

    async def async_step_discovery_recover(self, user_input=None):
        engine, car, profile = self._discovery_context()
        command = profile.last_command
        if command is None or not command.unresolved:
            return await self.async_step_discovery()
        if user_input is not None:
            if user_input.get("inspected"):
                await engine.review_normal_command(car.vin, command.command_id)
                return await self.async_step_discovery()
            return self.async_create_entry(
                title="", data=self._pending_options or dict(self.config_entry.options)
            )
        return self.async_show_form(
            step_id="discovery_recover",
            data_schema=vol.Schema({vol.Required("inspected", default=False): bool}),
            description_placeholders={"vehicle": car.name, "action": command.action},
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            # Keep historical V2 options while the clean V3 form only
            # exposes integration-level runtime, interval and vehicle filter.
            # A switch back to V2 must recover those V2 preferences.
            submitted = user_input
            user_input = {**self.config_entry.options, **submitted}
            user_input.setdefault("runtime_version", "v2")
            if user_input["runtime_version"] != "v3_climate":
                user_input.pop("v3_data_act_enabled", None)
            if user_input.get("v3_data_act_enabled", False):
                # Blank password retains the current portal credential. It is
                # never sent back as a default to the browser.
                if not submitted.get("v3_data_act_password"):
                    same_email = user_input.get("v3_data_act_email", "") == (
                        self.config_entry.options.get("v3_data_act_email", "")
                    )
                    user_input["v3_data_act_password"] = (
                        self.config_entry.options.get("v3_data_act_password", "")
                        if same_email
                        else ""
                    )
            else:
                user_input.pop("v3_data_act_email", None)
                user_input.pop("v3_data_act_password", None)
            # Workbench is opt-in and belongs only to the V3 runtime. Leave
            # existing custom API profiles untouched when it is turned off.
            if user_input["runtime_version"] != "v3_climate":
                user_input["v3_development_workbench"] = False
            else:
                user_input.setdefault("v3_development_workbench", False)
            edit_dealer = bool(user_input.pop("edit_local_dealer", False))
            run_discovery = bool(user_input.pop("run_vehicle_discovery", False))
            # On runtime switch, some HA clients submit only the changed
            # fields. Never let an absent interval prevent saving the choice.
            interval = user_input.get(
                CONF_SCAN_INTERVAL,
                self.config_entry.options.get(
                    CONF_SCAN_INTERVAL,
                    self.config_entry.data.get(
                        CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL
                    ),
                ),
            )
            try:
                user_input[CONF_SCAN_INTERVAL] = max(int(interval), MIN_UPDATE_INTERVAL)
            except (TypeError, ValueError):
                # Re-display an actionable form error instead of a silent
                # failure while the modal stays on the previous runtime.
                return self.async_show_form(
                    step_id="init",
                    errors={"base": "invalid_scan_interval"},
                    data_schema=self._options_schema(user_input),
                )
            # OptionsFlow replaces all options; preserve per-vehicle metadata.
            if "local_dealers" in self.config_entry.options:
                user_input["local_dealers"] = self.config_entry.options["local_dealers"]
            if (
                run_discovery
                and user_input["runtime_version"] == "v3_climate"
                and self._discovery_engine() is not None
            ):
                self._pending_options = user_input
                return await self.async_step_discovery_vehicle()
            if edit_dealer:
                self._pending_options = user_input
                return await self.async_step_dealer_vehicle()
            return self.async_create_entry(title="", data=user_input)

        # V3 owns API routes and experimental actions in its development
        # dashboard, never inside this account configuration wizard.
        return self.async_show_form(
            step_id="init", data_schema=self._options_schema(self.config_entry.options)
        )

    def _options_schema(self, values: dict[str, Any]) -> vol.Schema:
        """Build the form from the persisted mode, preserving legacy V2 UX."""
        schema = {
            vol.Required(
                "runtime_version",
                default=values.get("runtime_version", "v2"),
            ): vol.In({"v2": "V2 — Stable", "v3_climate": "V3 — Experimental"}),
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

        if values.get("runtime_version", "v2") == "v3_climate":
            schema[vol.Optional("edit_local_dealer", default=False)] = bool
            schema[
                vol.Optional(
                    "v3_data_act_enabled",
                    default=values.get("v3_data_act_enabled", False),
                )
            ] = bool
            schema[
                vol.Optional(
                    "v3_data_act_email", default=values.get("v3_data_act_email", "")
                )
            ] = TextSelector()
            schema[vol.Optional("v3_data_act_password", default="")] = TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            )
            schema[vol.Optional("run_vehicle_discovery", default=False)] = bool
            schema[
                vol.Required(
                    "v3_development_workbench",
                    default=self.config_entry.options.get(
                        "v3_development_workbench", False
                    ),
                )
            ] = bool
        else:
            # Preserve every historical V2 option and user metadata.
            # API route editing is reserved for the opt-in V3 Workbench.
            schema.update(
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
                }
            )
        return vol.Schema(schema)


__all__ = ["AudiConfigFlow", "OptionsFlowHandler"]
