"""Shared authentication boundary. V3 never calls legacy vehicle operations.

Only OAuth/IDK credential exchange and persistence are shared with V2.
The V3 API transport, discovery, request budget and parsing are independent.
"""

from __future__ import annotations

import time
from typing import Any
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..audi_connect_account import AudiConnectAccount
from ..audi_services import AudiAuthError
from ..const import (
    CONF_API_LEVEL,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_REGION,
    CONF_SPIN,
    CONF_USERNAME,
    DEFAULT_API_LEVEL,
)


# Only this boundary knows the historical credential slots.
_TOKEN_SLOTS = {
    "graphql": "audiToken",
    "cariad": "_bearer_token_json",
    "mbb": "vwToken",
}


def _token_record(service, family):
    name = _TOKEN_SLOTS.get(family)
    record = getattr(service, name, None) if name else None
    return record if isinstance(record, dict) else {}


def configured_spin(auth):
    """Internal credential access; callers must never expose the returned value."""
    return getattr(getattr(auth, "service", None), "_spin", None)


def service_api_level(auth):
    return getattr(getattr(auth, "service", None), "_api_level", None)


def redaction_context(entry, auth):
    """Collect known credentials only for local, in-memory masking."""
    settings = getattr(entry, "data", {})
    known = [
        settings.get(key) for key in (CONF_USERNAME, CONF_PASSWORD, CONF_REFRESH_TOKEN)
    ]
    service = getattr(auth, "service", None)
    for family in _TOKEN_SLOTS:
        token = _token_record(service, family)
        known.extend(
            token.get(k) for k in ("access_token", "refresh_token", "id_token")
        )
    pin = settings.get(CONF_SPIN)
    active_pin = configured_spin(auth)
    if active_pin is not None and str(active_pin) != str(pin):
        known.append(str(active_pin))
    return pin if pin is not None else active_pin, tuple(known)


class FamilyAuthUnavailable(RuntimeError):
    """A service credential is absent, not a failed shared account login."""


class V3Auth:
    """V3 credential adapter; the shared account owns the session lifecycle."""

    def __init__(
        self,
        hass: Any,
        entry: Any,
        *,
        shared_account: Any = None,
        data_act_session=None,
    ):
        self.hass = hass
        self.entry = entry
        self.country = (entry.data.get(CONF_REGION) or "DE").upper()
        # Both production and standalone callers use the same account session
        # implementation. Only the active runtime performs vehicle polling.
        self._connection = (
            shared_account.connection
            if shared_account is not None
            else AudiConnectAccount(
                session=async_get_clientsession(hass),
                country=self.country,
                spin=entry.data.get(CONF_SPIN),
                api_level=entry.data.get(CONF_API_LEVEL, DEFAULT_API_LEVEL),
                refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
                username=entry.data.get(CONF_USERNAME),
                password=entry.data.get(CONF_PASSWORD),
            )
        )
        if shared_account is None:
            self._connection.set_refresh_token_listener(self._save_refresh)
        self.service = self._connection.authentication_service
        # The optional session must already be authorized by its own auth owner.
        # Never reuse the native CARIAD session or import browser credentials.
        self.data_act_client = None
        if data_act_session is not None:
            from .data_act import DataActClient

            self.data_act_client = DataActClient(data_act_session)

    async def ensure_ready(self) -> None:
        """Delegate session management to the single account owner."""
        try:
            ready = await self._connection.ensure_session()
        except AudiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        if not ready:
            raise RuntimeError("Audi account login temporarily unavailable")

    def _save_refresh(self, refresh: str) -> None:
        if self.entry.data.get(CONF_REFRESH_TOKEN) != refresh:
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_REFRESH_TOKEN: refresh}
            )

    @property
    def session_generation(self) -> float:
        """Local login/renewal marker, never a credential or exported claim."""
        return self._connection.session_generation

    @property
    def uses_auth0(self) -> bool:
        return self.service.uses_auth0

    @property
    def has_cariad_bearer(self) -> bool:
        return self.has_family_token("cariad")

    def has_family_token(self, family: str) -> bool:
        """Credential presence only; operation authorization remains independent."""
        token = _token_record(self.service, family).get("access_token")
        return isinstance(token, str) and bool(token)

    @property
    def legacy_api_level(self) -> int:
        return int(service_api_level(self) or 0)

    def identity_auth_evidence(self, family: str = "graphql") -> dict:
        """Coarse unverified JWT metadata for diagnosis only. Never export a token or subject."""
        import base64
        import json

        access = _token_record(self.service, family).get("access_token")
        primary = _token_record(self.service, "cariad").get("access_token")
        result = {
            "provider": "auth0" if self.uses_auth0 else "legacy",
            "role": "cariad_bearer"
            if family == "cariad"
            or (family == "graphql" and access and access == primary)
            else "audi_azs_slot"
            if family == "graphql"
            else "legacy_slot",
            "same_as_cariad": bool(access and access == primary),
            "present": bool(access),
            "audience": "unknown",
            "scopes": [],
            "age_minutes": None,
            "claims_verified": False,
        }
        if not isinstance(access, str) or len(access) > 32000:
            return result
        try:
            segment = access.split(".")[1]
            claims = json.loads(
                base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
            )
            if not isinstance(claims, dict):
                return result
            audience = claims.get("aud")
            result["audience"] = (
                "cariad"
                if audience == "https://api.cariad.com"
                or (isinstance(audience, list) and "https://api.cariad.com" in audience)
                else "other"
            )
            scope = claims.get("scope")
            allowed = {
                "openid",
                "profile",
                "email",
                "offline_access",
                "mbb",
                "cars",
                "vin",
                "dealers",
            }
            result["scopes"] = (
                sorted(set(scope.split()) & allowed) if isinstance(scope, str) else []
            )
            iat = claims.get("iat")
            if type(iat) in (int, float) and 0 <= time.time() - iat <= 86400 * 365:
                result["age_minutes"] = int((time.time() - iat) / 60)
        except (ValueError, TypeError, IndexError, OverflowError, UnicodeError):
            pass
        return result

    def access_token(self, family: str) -> str:
        """Only reviewed family tokens; never expose in diagnostics."""
        if family not in _TOKEN_SLOTS:
            raise ValueError("V3 family is not enabled")
        value = _token_record(self.service, family).get("access_token")
        if not isinstance(value, str) or not value:
            raise FamilyAuthUnavailable("Audi API family token unavailable")
        return value
