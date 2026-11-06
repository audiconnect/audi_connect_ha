"""Tests for the OAuth authentication state machine.

Mocks the full AudiAPI HTTP surface (markets, market config, OIDC discovery,
device authorization, token endpoints, AZS and mbboauth).
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from custom_components.audiconnect.audi_services import (
    AudiAuthError,
    AudiService,
    DEVICE_CODE_SCOPE,
)

TOKEN_ENDPOINT = "https://identity.vwgroup.io/oidc/v1/token"
AUTH0_TOKEN_ENDPOINT = "https://group.identity.vwgroup.io/oauth/token"
AUTH0_PREFIX = "auth0:"
DEVICE_AUTH_ENDPOINT = "https://identity.vwgroup.io/oidc/v1/device_authorization"
AZS_BASE = "https://azs.example.com/login/v1/audi"
MBB_BASE = "https://mbboauth.example.com/mbbcoauth"
CLIENT_ID = "test-client-id@apps_vw-dilab_com"


def _make_id_token(payload: dict[str, Any]) -> str:
    seg = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{seg}.signature"


ID_TOKEN = _make_id_token({"email": "luis@example.com", "sub": "sub-123"})

IDK_TOKEN_OK = {
    "access_token": "idk-access",
    "id_token": ID_TOKEN,
    "refresh_token": "idk-refresh-1",
    "token_type": "bearer",
    "expires_in": 3600,
}

AUTH0_TOKEN_OK = {
    "access_token": "auth0-access",
    "id_token": ID_TOKEN,
    "refresh_token": "auth0-refresh-1",
    "token_type": "bearer",
    "expires_in": 3600,
}


class FakeResponse:
    cookies = {"fake": "cookie"}


class FakeAudiAPI:
    """Stands in for AudiAPI: records calls and dispatches canned responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.token = "unset"
        self.xclientid = "unset"
        # Overridable per-test: response for the IDK token endpoint.
        self.token_endpoint_response: dict[str, Any] = IDK_TOKEN_OK
        self.auth0_token_endpoint_response: dict[str, Any] = AUTH0_TOKEN_OK
        self.vehicle_information_response: dict[str, Any] | None = None
        self.mbb_auth_includes_refresh = True

    def use_token(self, token) -> None:
        self.token = token

    def set_xclient_id(self, xclientid) -> None:
        self.xclientid = xclientid

    async def request(
        self,
        method: str,
        url: str,
        data: Any,
        headers: dict | None = None,
        allow_redirects: bool = True,
        rsp_wtxt: bool = False,
        cookies: Any = None,
        **kwargs: Any,
    ) -> Any:
        self.calls.append((method, url, data))
        body = self._dispatch(method, url, data)
        if rsp_wtxt:
            return FakeResponse(), json.dumps(body)
        return body

    def _dispatch(self, method: str, url: str, data: Any) -> dict[str, Any]:
        if url.endswith("/configurations/markets"):
            return {
                "countries": {
                    "countrySpecifications": {"DE": {"defaultLanguage": "de"}}
                }
            }
        if "/configurations/market/DE/de" in url:
            return {
                "idkClientIDAndroidLive": CLIENT_ID,
                "authorizationServerBaseURLLive": AZS_BASE,
                "myAudiAuthorizationServerProxyServiceURLProduction": AZS_BASE,
                "mbbOAuthBaseURLLive": MBB_BASE,
                "idkLoginServiceConfigurationURLProduction": "https://identity.vwgroup.io/.well-known/openid-configuration",
            }
        if "openid-configuration" in url:
            return {
                "token_endpoint": TOKEN_ENDPOINT,
                "device_authorization_endpoint": DEVICE_AUTH_ENDPOINT,
            }
        if url == DEVICE_AUTH_ENDPOINT:
            assert f"client_id={CLIENT_ID.replace('@', '%40')}" in data
            return {
                "device_code": "dev-code-1",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://identity.vwgroup.io/device",
                "verification_uri_complete": "https://identity.vwgroup.io/device?user_code=ABCD-EFGH",
                "interval": 5,
                "expires_in": 300,
            }
        if url == TOKEN_ENDPOINT:
            return self.token_endpoint_response
        if url == AUTH0_TOKEN_ENDPOINT:
            return self.auth0_token_endpoint_response
        if url == AZS_BASE + "/token":
            return {"access_token": "azs-access", "token_type": "bearer"}
        if url == MBB_BASE + "/mobile/register/v1":
            return {"client_id": "xclient-123"}
        if url == MBB_BASE + "/mobile/oauth2/v1/token":
            if isinstance(data, str) and "grant_type=id_token" in data:
                body = {"access_token": "mbb-auth-access", "token_type": "bearer"}
                if self.mbb_auth_includes_refresh:
                    body["refresh_token"] = "mbb-refresh"
                return body
            return {"access_token": "vw-access", "token_type": "bearer"}
        if url == "https://app-api.live-my.audi.com/vgql/v1/graphql":
            assert self.vehicle_information_response is not None
            return self.vehicle_information_response
        raise AssertionError(f"Unmocked endpoint: {method} {url}")


@pytest.fixture
def api() -> FakeAudiAPI:
    return FakeAudiAPI()


@pytest.fixture
def service(api: FakeAudiAPI) -> AudiService:
    return AudiService(api, "DE", None, 1)


async def test_request_device_code_discovers_and_returns_code(service, api):
    result = await service.request_device_code()

    assert result["user_code"] == "ABCD-EFGH"
    assert result["verification_uri"] == "https://identity.vwgroup.io/device"
    assert result["device_code"] == "dev-code-1"
    # Discovery resolved the dynamic client id from the market config.
    assert service._client_id == CLIENT_ID
    # The device-authorization request carried the RFC 8628 scope.
    _method, _url, body = api.calls[-1]
    assert "scope=" + DEVICE_CODE_SCOPE.replace(" ", "%20") in body


async def test_poll_device_token_pending_and_slow_down(service, api):
    await service.request_device_code()

    api.token_endpoint_response = {"error": "authorization_pending"}
    assert await service.poll_device_token("dev-code-1") == "authorization_pending"

    api.token_endpoint_response = {"error": "slow_down"}
    assert await service.poll_device_token("dev-code-1") == "slow_down"

    api.token_endpoint_response = {"error": "expired_token"}
    assert await service.poll_device_token("dev-code-1") == "expired"

    api.token_endpoint_response = {"error": "access_denied"}
    assert await service.poll_device_token("dev-code-1") == "denied"

    api.token_endpoint_response = {"error": "something_else"}
    assert await service.poll_device_token("dev-code-1") == "error"


async def test_poll_device_token_success_finalizes_session(service, api):
    await service.request_device_code()

    assert await service.poll_device_token("dev-code-1") == "ok"

    # Correct grant was sent to the token endpoint.
    _m, _u, body = next(c for c in api.calls if c[1] == TOKEN_ENDPOINT)
    assert "urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Adevice_code" in body
    assert "device_code=dev-code-1" in body

    # _finalize_session derived the downstream tokens.
    assert service.audiToken == {"access_token": "azs-access", "token_type": "bearer"}
    assert service.xclientId == "xclient-123"
    assert api.xclientid == "xclient-123"
    assert service.vwToken == {"access_token": "vw-access", "token_type": "bearer"}
    assert service.current_refresh_token() == "idk-refresh-1"


async def test_finalize_session_without_mbb_refresh_token(service, api):
    api.mbb_auth_includes_refresh = False
    await service.request_device_code()

    assert await service.poll_device_token("dev-code-1") == "ok"
    # Auth token used directly as vwToken when no refresh_token comes back.
    assert service.vwToken["access_token"] == "mbb-auth-access"


async def test_login_with_refresh_token_rotates(service, api):
    api.token_endpoint_response = dict(IDK_TOKEN_OK, refresh_token="idk-refresh-2")

    new_token = await service.login_with_refresh_token("idk-refresh-1")

    assert new_token == "idk-refresh-2"
    assert service.current_refresh_token() == "idk-refresh-2"
    # The refresh grant carried the stored token.
    _m, _u, body = next(c for c in api.calls if c[1] == TOKEN_ENDPOINT)
    assert "grant_type=refresh_token" in body
    assert "refresh_token=idk-refresh-1" in body
    # Session was finalized.
    assert service.audiToken["access_token"] == "azs-access"
    assert service.vwToken["access_token"] == "vw-access"


async def test_login_with_auth0_refresh_token_uses_direct_cariad_token(service, api):
    api.auth0_token_endpoint_response = dict(
        AUTH0_TOKEN_OK, refresh_token="auth0-refresh-2"
    )

    new_token = await service.login_with_refresh_token(f"{AUTH0_PREFIX}auth0-refresh-1")

    assert new_token == f"{AUTH0_PREFIX}auth0-refresh-2"
    assert service.current_refresh_token() == f"{AUTH0_PREFIX}auth0-refresh-2"
    assert service.uses_auth0 is True
    assert service.audiToken["access_token"] == "auth0-access"
    assert service.vwToken["access_token"] == "auth0-access"
    assert service.mbboauthToken is None
    assert service.xclientId is None
    assert api.xclientid is None

    _method, _url, body = next(c for c in api.calls if c[1] == AUTH0_TOKEN_ENDPOINT)
    assert "grant_type=refresh_token" in body
    assert "refresh_token=auth0-refresh-1" in body
    assert "audience=https%3A%2F%2Fapi.cariad.com" in body
    assert not any(call[1] == AZS_BASE + "/token" for call in api.calls)
    assert not any(call[1].startswith(MBB_BASE) for call in api.calls)


async def test_auth0_authorization_code_login(service, api):
    url = await service.get_auth0_authorization_url("challenge", "expected-state")
    params = parse_qs(urlparse(url).query)

    assert params["client_id"] == [CLIENT_ID]
    assert params["audience"] == ["https://api.cariad.com"]
    assert params["redirect_uri"] == ["http://localhost:8080/myaudi-callback"]
    assert params["code_challenge"] == ["challenge"]
    assert params["state"] == ["expected-state"]

    refresh_token = await service.login_with_auth0_code("auth-code", "verifier")

    assert refresh_token == f"{AUTH0_PREFIX}auth0-refresh-1"
    _method, _url, body = api.calls[-1]
    assert "grant_type=authorization_code" in body
    assert "code=auth-code" in body
    assert "code_verifier=verifier" in body
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fmyaudi-callback" in body


async def test_auth0_refresh_preserves_unrotated_token(service, api):
    api.auth0_token_endpoint_response = {
        key: value for key, value in AUTH0_TOKEN_OK.items() if key != "refresh_token"
    }

    new_token = await service.login_with_refresh_token(f"{AUTH0_PREFIX}auth0-refresh-1")

    assert new_token == f"{AUTH0_PREFIX}auth0-refresh-1"
    assert service.current_refresh_token() == f"{AUTH0_PREFIX}auth0-refresh-1"


async def test_auth0_refresh_if_necessary_stays_on_auth0(service, api):
    await service.login_with_refresh_token(f"{AUTH0_PREFIX}auth0-refresh-1")
    api.calls.clear()
    api.auth0_token_endpoint_response = dict(
        AUTH0_TOKEN_OK, refresh_token="auth0-refresh-2"
    )

    assert await service.refresh_token_if_necessary(3400) is True

    assert [call[1] for call in api.calls] == [AUTH0_TOKEN_ENDPOINT]
    assert service.current_refresh_token() == f"{AUTH0_PREFIX}auth0-refresh-2"


async def test_auth0_rejected_refresh_token_raises(service, api):
    api.auth0_token_endpoint_response = {
        "error": "invalid_grant",
        "error_description": "Unknown or invalid refresh token.",
    }

    with pytest.raises(AudiAuthError, match="Unknown or invalid refresh token"):
        await service.login_with_refresh_token(f"{AUTH0_PREFIX}stale-token")


async def test_vehicle_information_keeps_data_with_nonfatal_enrichment_errors(
    service, api
):
    service._language = "de"
    service.audiToken = AUTH0_TOKEN_OK
    api.vehicle_information_response = {
        "data": {
            "userVehicles": [
                {
                    "vin": "WAUZZZ4M1RD012345",
                    "csid": None,
                    "vehicle": None,
                    "nickname": "Test Car",
                }
            ]
        },
        "errors": [{"message": "Unable to fetch vehicle core data for given vin"}],
    }

    result = await service.get_vehicle_information()

    assert len(result.vehicles) == 1
    assert result.vehicles[0].vin == "WAUZZZ4M1RD012345"
    assert result.vehicles[0].title == "Test Car"


async def test_login_with_rejected_refresh_token_raises(service, api):
    api.token_endpoint_response = {"error": "invalid_grant"}

    with pytest.raises(AudiAuthError, match="invalid_grant"):
        await service.login_with_refresh_token("stale-token")


async def test_get_id_token_subject_parses_email(service, api):
    await service.request_device_code()
    await service.poll_device_token("dev-code-1")

    assert service.get_id_token_subject() == "luis@example.com"


async def test_get_id_token_subject_falls_back_to_sub(service):
    service._bearer_token_json = {
        "id_token": _make_id_token({"sub": "sub-only"}),
    }
    assert service.get_id_token_subject() == "sub-only"


async def test_get_id_token_subject_none_when_unauthenticated(service):
    assert service.get_id_token_subject() is None
    service._bearer_token_json = {"id_token": "not-a-jwt"}
    assert service.get_id_token_subject() is None


async def test_refresh_if_necessary_keys_on_idk_token_without_mbb_refresh(service, api):
    """Even when mbboauth issued no refresh_token, the IDK session must refresh."""
    api.mbb_auth_includes_refresh = False
    await service.request_device_code()
    await service.poll_device_token("dev-code-1")
    api.calls.clear()
    api.token_endpoint_response = dict(IDK_TOKEN_OK, refresh_token="idk-refresh-2")

    # Not yet near expiry: no refresh.
    assert await service.refresh_token_if_necessary(0) is False
    assert api.calls == []
    # Within 5 minutes of the 3600s expiry: refresh runs against the IDK endpoint.
    assert await service.refresh_token_if_necessary(3400) is True
    idk_calls = [c for c in api.calls if c[1] == TOKEN_ENDPOINT]
    assert len(idk_calls) == 1
    assert "grant_type=refresh_token" in idk_calls[0][2]
    assert service.current_refresh_token() == "idk-refresh-2"


async def test_refresh_if_necessary_rejected_raises_auth_error(service, api):
    await service.request_device_code()
    await service.poll_device_token("dev-code-1")
    api.token_endpoint_response = {"error": "invalid_grant"}

    with pytest.raises(AudiAuthError):
        await service.refresh_token_if_necessary(3400)
