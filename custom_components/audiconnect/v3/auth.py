"""Shared authentication boundary. V3 never calls legacy vehicle operations.

Only OAuth/IDK credential exchange and persistence are shared with V2.
The V3 API transport, discovery, request budget and parsing are independent.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..audi_api import AudiAPI
from ..audi_services import AudiAuthError, AudiService
from ..const import (
    CONF_API_LEVEL, CONF_PASSWORD, CONF_REFRESH_TOKEN, CONF_REGION, CONF_SPIN,
    CONF_USERNAME, DEFAULT_API_LEVEL,
)


class V3Auth:
    """Per-config-entry token owner; never poll via AudiConnectAccount."""

    def __init__(self, hass: Any, entry: Any, *, shared_account: Any = None):
        self.hass = hass
        self.entry = entry
        self.country = (entry.data.get(CONF_REGION) or "DE").upper()
        # The HA runtime passes the SAME AudiAccount as V2. Reuse the already
        # configured transport/auth service and its single refresh token owner.
        # The fallback exists for isolated V3 unit tests and CLI discovery.
        self._shared_connection = (
            shared_account.connection if shared_account is not None else None
        )
        self.service = (
            self._shared_connection._audi_service
            if self._shared_connection is not None
            else AudiService(
                AudiAPI(async_get_clientsession(hass)), self.country,
                entry.data.get(CONF_SPIN),
                entry.data.get(CONF_API_LEVEL, DEFAULT_API_LEVEL),
            )
        )
        self._last_login: float | None = None
        self._refresh_lock = asyncio.Lock()

    async def ensure_ready(self) -> None:
        """Serialize the shared account's login and token rotation."""
        async with self._refresh_lock:
            await self._ensure_ready_locked()

    async def _ensure_ready_locked(self) -> None:
        if self._shared_connection is not None:
            # Never invoke AudiAccount.async_refresh_data or connection.update:
            # those own the V2 vehicle poll. Only authentication is shared.
            if not self._shared_connection._loggedin:
                try:
                    await self._shared_connection.login()
                except AudiAuthError as err:
                    raise ConfigEntryAuthFailed(str(err)) from err
                if not self._shared_connection._loggedin:
                    raise RuntimeError("Audi account login temporarily unavailable")
            elapsed = int(time.time() - self._shared_connection._logintime)
            try:
                refreshed = await self.service.refresh_token_if_necessary(elapsed)
            except AudiAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            if refreshed:
                self._shared_connection._logintime = time.time()
                self._shared_connection._sync_refresh_token()
            return
        if self._last_login is None:
            try:
                refresh = self.entry.data.get(CONF_REFRESH_TOKEN)
                if refresh:
                    rotated = await self.service.login_with_refresh_token(refresh)
                    self._save_refresh(rotated)
                else:
                    username = self.entry.data.get(CONF_USERNAME)
                    password = self.entry.data.get(CONF_PASSWORD)
                    if not username or not password:
                        raise ConfigEntryAuthFailed("Audi login is required")
                    await self.service.login(username, password)
            except AudiAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            self._last_login = time.monotonic()
            return
        elapsed = int(time.monotonic() - self._last_login)
        try:
            refreshed = await self.service.refresh_token_if_necessary(elapsed)
        except AudiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        if refreshed:
            self._last_login = time.monotonic()
            self._save_refresh(self.service.current_refresh_token())

    def _save_refresh(self, refresh: str | None) -> None:
        if refresh and self.entry.data.get(CONF_REFRESH_TOKEN) != refresh:
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_REFRESH_TOKEN: refresh}
            )

    @property
    def session_generation(self):
        """Local login/renewal marker, never a credential or exported claim."""
        if self._shared_connection is not None:
            return self._shared_connection._logintime
        return self._last_login

    @property
    def uses_auth0(self) -> bool:
        return self.service.uses_auth0

    @property
    def has_cariad_bearer(self) -> bool:
        token = getattr(self.service, "_bearer_token_json", None)
        return isinstance(token, dict) and isinstance(token.get("access_token"), str) and bool(token["access_token"])

    @property
    def legacy_api_level(self) -> int:
        return int(getattr(self.service, "_api_level", 0) or 0)

    def identity_auth_evidence(self, family: str = "graphql") -> dict:
        """Coarse unverified JWT metadata for diagnosis only. Never export a token or subject."""
        import base64
        import json
        name = {"graphql": "audiToken", "cariad": "_bearer_token_json", "mbb": "vwToken"}.get(family)
        token = getattr(self.service, name, None) if name else None
        bearer = getattr(self.service, "_bearer_token_json", None)
        access = token.get("access_token") if isinstance(token, dict) else None
        primary = bearer.get("access_token") if isinstance(bearer, dict) else None
        result = {"provider": "auth0" if self.uses_auth0 else "legacy",
                  "role": "cariad_bearer" if family == "cariad" else "audi_azs_slot" if family == "graphql" else "legacy_slot",
                  "same_as_cariad": bool(access and access == primary), "present": bool(access),
                  "audience": "unknown", "scopes": [], "age_minutes": None,
                  "claims_verified": False}
        if not isinstance(access, str) or len(access) > 32000:
            return result
        try:
            segment = access.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
            if not isinstance(claims, dict):
                return result
            audience = claims.get("aud")
            result["audience"] = "cariad" if audience == "https://api.cariad.com" or (
                isinstance(audience, list) and "https://api.cariad.com" in audience) else "other"
            scope = claims.get("scope")
            allowed = {"openid", "profile", "email", "offline_access", "mbb", "cars", "vin", "dealers"}
            result["scopes"] = sorted(set(scope.split()) & allowed) if isinstance(scope, str) else []
            iat = claims.get("iat")
            if type(iat) in (int, float) and 0 <= time.time() - iat <= 86400 * 365:
                result["age_minutes"] = int((time.time() - iat) / 60)
        except (ValueError, TypeError, IndexError, OverflowError, UnicodeError):
            pass
        return result

    def access_token(self, family: str) -> str:
        """Only reviewed family tokens; never expose in diagnostics."""
        if family == "cariad":
            token = getattr(self.service, "_bearer_token_json", None)
        elif family == "graphql":
            token = getattr(self.service, "audiToken", None)
        elif family == "mbb":
            token = getattr(self.service, "vwToken", None)
        else:
            raise ValueError("V3 family is not enabled")
        value = token.get("access_token") if isinstance(token, dict) else None
        if not isinstance(value, str) or not value:
            raise ConfigEntryAuthFailed("Audi authentication token unavailable")
        return value
