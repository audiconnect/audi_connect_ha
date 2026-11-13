"""One V2 account/auth owner, V3 active engine, and stable HA service facade.

These are isolated tests. Physical Q8 command success is NOT inferred from them.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError

from custom_components.audiconnect.audi_connect_account import AudiConnectAccount
from custom_components.audiconnect.audi_services import AudiAuthError

from custom_components.audiconnect.v3.service_commands import (
    execute as _v3_service_command,
)
from custom_components.audiconnect.v3.auth import V3Auth


def test_v3_auth_uses_existing_v2_audi_service_and_refresh_owner():
    connection = AudiConnectAccount(Mock(), "DE", None, 0, refresh_token="old-token")
    service = connection.authentication_service
    service.login_with_refresh_token = AsyncMock(return_value="new-token")
    service.refresh_token_if_necessary = AsyncMock(side_effect=[True, False])
    service.current_refresh_token = Mock(return_value="rotated-token")
    persist = Mock()
    connection.set_refresh_token_listener(persist)
    account = SimpleNamespace(connection=connection)
    entry = SimpleNamespace(data={"region": "DE"})
    auth = V3Auth(SimpleNamespace(), entry, shared_account=account)

    async def concurrent_requests():
        await asyncio.gather(auth.ensure_ready(), auth.ensure_ready())

    assert auth.service is service
    asyncio.run(concurrent_requests())
    service.login_with_refresh_token.assert_awaited_once_with("old-token")
    assert service.refresh_token_if_necessary.await_count == 2
    assert [c.args for c in persist.call_args_list] == [
        ("new-token",),
        ("rotated-token",),
    ]
    assert connection.refresh_token == "rotated-token"
    assert auth.session_generation == connection.session_generation


def test_v3_auth_preserves_reauthentication_semantics():
    connection = AudiConnectAccount(Mock(), "DE", None, 0, refresh_token="old-token")
    connection.authentication_service.login_with_refresh_token = AsyncMock(
        side_effect=AudiAuthError("rejected")
    )
    auth = V3Auth(
        SimpleNamespace(),
        SimpleNamespace(data={"region": "DE"}),
        shared_account=SimpleNamespace(connection=connection),
    )
    with pytest.raises(ConfigEntryAuthFailed, match="rejected"):
        asyncio.run(auth.ensure_ready())


def test_v3_auth_transient_login_failure_does_not_request_reauth():
    connection = SimpleNamespace(
        authentication_service=Mock(),
        ensure_session=AsyncMock(return_value=False),
    )
    auth = V3Auth(
        SimpleNamespace(),
        SimpleNamespace(data={"region": "DE"}),
        shared_account=SimpleNamespace(connection=connection),
    )
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        asyncio.run(auth.ensure_ready())


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


@pytest.mark.parametrize(
    "action, data",
    [
        ("set_charge_mode", {"charge_mode": "timer", "unexpected": True}),
        ("set_charge_mode", {}),
        ("start_timed_charger", {"unexpected": True}),
    ],
)
def test_service_translation_never_discards_parameters(action, data):
    engine = SimpleNamespace(send_control=AsyncMock())
    with pytest.raises(HomeAssistantError):
        asyncio.run(_v3_service_command(engine, "TESTVIN", action, data))
    engine.send_control.assert_not_awaited()


def test_auth_redaction_includes_live_token_slots_and_active_pin():
    from custom_components.audiconnect.const import CONF_SPIN
    from custom_components.audiconnect.v3.auth import redaction_context

    service = SimpleNamespace(
        _spin="9876",
        _bearer_token_json={"access_token": "cariad-token"},
        audiToken={"id_token": "identity-token"},
        vwToken={"refresh_token": "legacy-token"},
    )
    pin, secrets = redaction_context(
        SimpleNamespace(data={CONF_SPIN: "1234"}), SimpleNamespace(service=service)
    )
    assert pin == "1234"
    assert {"9876", "cariad-token", "identity-token", "legacy-token"} <= set(secrets)
