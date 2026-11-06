"""Tests for the interactive Auth0 config-flow helpers."""

from __future__ import annotations

import base64
from hashlib import sha256

import pytest

from custom_components.audiconnect.config_flow import (
    AudiConfigFlow,
    _generate_auth0_pkce,
    _parse_auth0_callback,
)
from custom_components.audiconnect.const import entry_uses_auth0, uses_auth0


class FakeConnection:
    refresh_token = "auth0:refresh-token"

    def __init__(self) -> None:
        self.exchange: tuple[str, str] | None = None

    async def get_auth0_authorization_url(self, code_challenge: str, state: str) -> str:
        return f"https://login.example/?challenge={code_challenge}&state={state}"

    async def login_with_auth0_code(self, code: str, verifier: str) -> None:
        self.exchange = (code, verifier)


def test_pkce_values_are_valid() -> None:
    verifier, challenge, state = _generate_auth0_pkce()
    expected = base64.urlsafe_b64encode(sha256(verifier.encode()).digest())

    assert 43 <= len(verifier) <= 128
    assert challenge == expected.decode().rstrip("=")
    assert state


def test_auth0_callback_returns_code() -> None:
    callback = (
        "http://localhost:8080/myaudi-callback?code=auth-code&state=expected-state"
    )

    assert _parse_auth0_callback(callback, "expected-state") == "auth-code"


@pytest.mark.parametrize(
    ("callback", "error"),
    [
        ("https://example.com/?code=x&state=expected", "invalid_auth0_callback"),
        (
            "http://localhost:8080/myaudi-callback?code=x&state=wrong",
            "invalid_auth0_callback",
        ),
        (
            "http://localhost:8080/myaudi-callback?state=expected",
            "invalid_auth0_callback",
        ),
        (
            "http://localhost:8080/myaudi-callback?error=access_denied&state=expected",
            "auth0_denied",
        ),
    ],
)
def test_auth0_callback_rejects_invalid_responses(callback: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        _parse_auth0_callback(callback, "expected")


def test_auth0_region_routing() -> None:
    assert uses_auth0("DE") is True
    assert uses_auth0("CA") is True
    assert uses_auth0("US") is False
    assert entry_uses_auth0({"region": "US", "refresh_token": "auth0:token"})


async def test_auth0_step_exchanges_the_callback(monkeypatch) -> None:
    flow = AudiConfigFlow()
    connection = FakeConnection()
    flow._connection = connection

    form = await flow.async_step_auth0()
    assert form["step_id"] == "auth0"
    assert flow._auth0_state is not None
    assert flow._auth0_verifier is not None

    async def finish():
        return {"type": "finished"}

    monkeypatch.setattr(flow, "_finish_token_login", finish)
    callback = (
        "http://localhost:8080/myaudi-callback"
        f"?code=auth-code&state={flow._auth0_state}"
    )

    result = await flow.async_step_auth0({"callback_url": callback})

    assert result == {"type": "finished"}
    assert connection.exchange == ("auth-code", flow._auth0_verifier)
