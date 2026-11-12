"""One V2 account/auth owner, V3 active engine, and stable HA service facade.

These are isolated tests. Physical Q8 command success is NOT inferred from them.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.audiconnect.v3.service_commands import (
    execute as _v3_service_command,
)
from custom_components.audiconnect.v3.auth import V3Auth


def test_v3_auth_uses_existing_v2_audi_service_and_refresh_owner():
    service = SimpleNamespace(
        refresh_token_if_necessary=AsyncMock(return_value=True),
        uses_auth0=True,
    )
    connection = SimpleNamespace(
        _audi_service=service,
        _loggedin=False,
        _logintime=0,
        _sync_refresh_token=lambda: calls.append("save"),
    )
    calls = []

    async def login():
        calls.append("login")
        connection._loggedin = True
        connection._logintime = 1.0

    connection.login = AsyncMock(side_effect=login)
    account = SimpleNamespace(connection=connection)
    entry = SimpleNamespace(data={"region": "DE"})
    auth = V3Auth(SimpleNamespace(), entry, shared_account=account)

    assert auth.service is service
    asyncio.run(auth.ensure_ready())
    connection.login.assert_awaited_once()
    service.refresh_token_if_necessary.assert_awaited_once()
    assert calls == ["login", "save"]
    assert connection._logintime > 1.0


def test_v3_services_dispatch_only_to_approved_v3_engine_controls():
    engine = SimpleNamespace(send_control=AsyncMock())
    for name, capability, aspect in (
        ("lock", "access", "lock"),
        ("unlock", "access", "unlock"),
        ("start_climatisation", "climate", "start"),
        ("stop_climatisation", "climate", "stop"),
        ("start_charger", "charging", "start"),
        ("stop_charger", "charging", "stop"),
        ("start_window_heating", "climate", "window_heating_start"),
        ("stop_window_heating", "climate", "window_heating_stop"),
        ("start_engine", "remote", "engine_start"),
        ("stop_engine", "remote", "engine_stop"),
        ("start_preheater", "climate", "preheater_start"),
        ("stop_preheater", "climate", "preheater_stop"),
    ):
        asyncio.run(
            _v3_service_command(engine, "TESTVIN", name, {"device_id": "device"})
        )
        engine.send_control.assert_awaited_with("TESTVIN", aspect, capability)


def test_v3_unsupported_actions_fail_closed_and_do_not_invoke_v2():
    engine = SimpleNamespace(send_control=AsyncMock())
    for name in ("nonsense",):
        with pytest.raises(HomeAssistantError, match="not yet V3-verified"):
            asyncio.run(_v3_service_command(engine, "TESTVIN", name))
    engine.send_control.assert_not_awaited()


def test_v3_parameterized_climate_start_never_discards_temperature():
    engine = SimpleNamespace(send_control=AsyncMock())
    asyncio.run(
        _v3_service_command(
            engine,
            "TESTVIN",
            "start_climatisation",
            {"device_id": "dev", "temp_c": 22},
        )
    )
    engine.send_control.assert_awaited_once_with(
        "TESTVIN", "start_with_settings", "climate", params={"temp_c": 22}
    )


def test_v3_command_rejection_is_surfaced_as_ha_error():
    engine = SimpleNamespace(
        send_control=AsyncMock(side_effect=RuntimeError("not activated"))
    )
    with pytest.raises(HomeAssistantError, match="not activated"):
        asyncio.run(_v3_service_command(engine, "TESTVIN", "lock"))
