"""Refresh lifecycle is independent of the background poll and uses one journal."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import time

import pytest

from custom_components.audiconnect.v3.command_journal import CommandRecord
from custom_components.audiconnect.v3.registry import CapabilityRegistry
from custom_components.audiconnect.v3.engine import V3Engine
from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3.transport import V3Response
from custom_components.audiconnect.const import (
    CONF_REFRESH_AFTER_ACTION,
    CONF_UPDATE_SLEEP,
)

VIN = "WAUZZZ4M0MD123456"
ROOT = Path(__file__).resolve().parents[1] / "custom_components/audiconnect/v3"


def fixture(opt_in=False):
    registry = CapabilityRegistry.from_json_file(ROOT / "full_catalog.json")
    vehicle = V3Vehicle(VIN, "Audi", "Audi Q8", "q8", "DE", car_type="phev")
    vehicle.advertised_capabilities.update({"climatisation", "vehicleWakeUp"})
    events = []
    coordinator = NS(async_request_refresh=AsyncMock())
    entry = NS(
        entry_id="test",
        options={CONF_UPDATE_SLEEP: 0, CONF_REFRESH_AFTER_ACTION: opt_in},
        runtime_data=NS(coordinator=coordinator),
    )

    async def request(family, method, path, **kwargs):
        if method == "POST":
            rid = "refresh-id" if path.endswith("vehiclewakeup") else "climate-id"
            return V3Response(200, {"data": {"requestID": rid}}, datetime.now(UTC), 50)
        return V3Response(
            200,
            {
                "data": [
                    {"id": "climate-id", "status": "successful"},
                    {"id": "refresh-id", "status": "successful"},
                ]
            },
            datetime.now(UTC),
            49,
        )

    transport = NS(request=AsyncMock(side_effect=request), remaining_calls=50)
    engine = V3Engine(
        NS(bus=NS(async_fire=lambda event, data: events.append((event, data)))),
        entry,
        registry,
        auth=NS(uses_auth0=True, service=NS()),
        transport=transport,
        storage=NS(async_save=AsyncMock()),
    )
    engine.vehicles[VIN.lower()] = vehicle
    engine.profiles[VIN.lower()] = DevelopmentProfile(registry, vehicle.context)
    return engine, transport, coordinator, events


@pytest.mark.asyncio
@pytest.mark.parametrize("opt_in", [False, True])
async def test_completed_climate_has_one_cloud_followup_and_optional_linked_wake(
    opt_in,
):
    engine, transport, coordinator, events = fixture(opt_in)
    await engine.send_control(VIN, "start", "climate")
    posts = [
        c.args[2] for c in transport.request.await_args_list if c.args[1] == "POST"
    ]
    assert len(posts) == (2 if opt_in else 1)
    assert posts[0].endswith("climatisation/start")
    coordinator.async_request_refresh.assert_awaited_once()
    history = engine.profiles[VIN.lower()].command_journal
    if opt_in:
        assert posts[1].endswith("vehiclewakeup")
        assert history[-1].parent_command_id == history[0].command_id
        assert history[-1].state == "backend_completed"
        assert events == [
            (
                "audiconnect_refresh_completed",
                {"vin": "*" * 13 + VIN[-4:], "outcome": "backend_completed"},
            )
        ]
    else:
        assert events == []
        assert len(history) == 1


@pytest.mark.asyncio
async def test_refresh_is_not_repeated_and_uncertainty_never_creates_followup():
    engine, transport, coordinator, events = fixture(True)
    await engine.send_control(VIN, "refresh", "remote")
    posts = [c for c in transport.request.await_args_list if c.args[1] == "POST"]
    assert len(posts) == 1
    coordinator.async_request_refresh.assert_awaited_once()
    engine, transport, coordinator, events = fixture(True)
    transport.request.side_effect = None
    transport.request.return_value = V3Response(200, {}, datetime.now(UTC), 50)
    await engine.send_control(VIN, "start", "climate")
    assert transport.request.await_count == 1
    assert events == []
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_unrelated_parent_cannot_bypass_cooldown_or_trigger_refresh():
    engine, transport, coordinator, events = fixture(True)
    p = engine.profiles[VIN.lower()]
    parent = CommandRecord.begin(
        "climate", "start", "cariad.climate.start.stored", time.time()
    )
    parent.state = "backend_completed"
    p.track_command(parent)
    with pytest.raises(RuntimeError, match="parent command"):
        await engine.commands.send_control(
            VIN, "refresh", "remote", _follow_up_to="wrong"
        )
    transport.request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("wake_action", ["wake", "refresh"])
async def test_accepted_wake_does_not_block_immediate_climate_action(wake_action):
    engine, transport, coordinator, events = fixture(False)
    original_request = transport.request.side_effect

    async def request(family, method, path, **kwargs):
        if method == "POST" and path.endswith(
            ("vehiclewakeup", "vehiclewakeuptrigger")
        ):
            # Q8 b12 observed 204, no request ID or physical readback.
            return V3Response(204, {}, datetime.now(UTC), 50)
        return await original_request(family, method, path, **kwargs)

    transport.request.side_effect = request
    await engine.send_control(VIN, wake_action, "remote")
    await engine.send_control(VIN, "start", "climate")
    posts = [
        c.args[2] for c in transport.request.await_args_list if c.args[1] == "POST"
    ]
    assert len(posts) == 2
    assert posts[0].endswith(("vehiclewakeup", "vehiclewakeuptrigger"))
    assert posts[1].endswith("climatisation/start")


@pytest.mark.asyncio
async def test_linked_refresh_does_not_hide_real_command_cooldown_or_stop():
    engine, transport, coordinator, events = fixture(True)
    await engine.send_control(VIN, "start", "climate")
    with pytest.raises(RuntimeError, match="cooldown"):
        await engine.commands.send_control(VIN, "start", "climate")
    await engine.commands.send_control(VIN, "stop", "climate")
    posts = [
        c.args[2] for c in transport.request.await_args_list if c.args[1] == "POST"
    ]
    assert len(posts) == 3
    assert posts[-1].endswith("climatisation/stop")


@pytest.mark.asyncio
async def test_wake_budget_and_uncertain_command_guard_remain_independent():
    engine, transport, coordinator, events = fixture(False)
    await engine.send_control(VIN, "wake", "remote")
    with pytest.raises(RuntimeError, match="wake budget"):
        await engine.commands.send_control(VIN, "wake", "remote")
    assert (
        len([c for c in transport.request.await_args_list if c.args[1] == "POST"]) == 1
    )
    wake = engine.profiles[VIN.lower()].last_command
    wake.state = "uncertain"
    wake.started_at -= 120
    wake.completed_at = wake.started_at + 1
    with pytest.raises(RuntimeError, match="wake budget"):
        await engine.commands.send_control(VIN, "wake", "remote")
    await engine.commands.send_control(VIN, "start", "climate")
    assert wake.unresolved
    assert (
        len([c for c in transport.request.await_args_list if c.args[1] == "POST"]) == 2
    )


def test_wake_does_not_hide_previous_command_readback():
    engine, _, _, _ = fixture(False)
    car = engine.vehicles[VIN.lower()]
    profile = engine.profiles[VIN.lower()]
    from custom_components.audiconnect.v3.command_readback import configure_readback

    start = CommandRecord.begin(
        "climate", "start", "cariad.climate.start.stored", time.time() - 10
    )
    start.state = "backend_completed"
    configure_readback(start, {})
    profile.track_command(start)
    wake = CommandRecord.begin(
        "remote", "refresh", "cariad.remote.refresh", time.time() - 5
    )
    wake.state = "accepted_unconfirmed"
    profile.track_command(wake)
    now = datetime.now(UTC)
    car.set_climate(
        "heating", now.isoformat(), route="test", observed_at=now, http_status=200
    )
    engine.commands.reconcile_commands()
    assert start.state == "verified"
    assert wake.state == "accepted_unconfirmed"


def test_acknowledged_wake_survives_restart_without_blocking_climate():
    from custom_components.audiconnect.v3.command_journal import (
        restore_history,
        check_command_sequence,
    )

    wake = CommandRecord.begin("remote", "wake", "cariad.remote.wake", 1000)
    wake.state = wake.backend_result = "accepted_unconfirmed"
    rows, latest = restore_history([wake.snapshot()])
    assert latest.state == "accepted_unconfirmed"
    check_command_sequence(
        NS(last_command=latest, command_journal=rows),
        1001,
        capability="climate",
        action="start",
    )
    wake.backend_result = None  # interrupted before durable acknowledgement
    rows, latest = restore_history([wake.snapshot()])
    assert latest.unresolved
    with pytest.raises(RuntimeError, match="uncertain"):
        check_command_sequence(
            NS(last_command=latest, command_journal=rows),
            1020,
            capability="remote",
            action="wake",
        )
    check_command_sequence(
        NS(last_command=latest, command_journal=rows),
        1030,
        capability="remote",
        action="wake",
    )
    check_command_sequence(
        NS(last_command=latest, command_journal=rows),
        1020,
        capability="climate",
        action="start",
    )


@pytest.mark.asyncio
async def test_http_502_reports_error_and_allows_explicit_retry_after_cooldown():
    engine, transport, _, _ = fixture(False)
    original = transport.request.side_effect
    transport.request.side_effect = None
    transport.request.return_value = V3Response(502, {}, datetime.now(UTC), 50)
    with pytest.raises(RuntimeError, match=r"Audi climate.start: HTTP 502; uncertain"):
        await engine.send_control(VIN, "start", "climate")
    profile = engine.profiles[VIN.lower()]
    failed = profile.last_command
    assert failed.state == "uncertain"
    assert engine.control_enabled(VIN, "start", "climate")
    assert engine.control_enabled(VIN, "wake", "remote")
    with pytest.raises(RuntimeError, match="try again in"):
        await engine.send_control(VIN, "start", "climate")
    assert transport.request.await_count == 1
    failed.started_at -= 60
    failed.completed_at = failed.started_at + 1
    transport.request.side_effect = original
    await engine.send_control(VIN, "start", "climate")
    assert failed.state == "uncertain"
    assert profile.last_command.state == "backend_completed"
    assert (
        len([c for c in transport.request.await_args_list if c.args[1] == "POST"]) == 2
    )
