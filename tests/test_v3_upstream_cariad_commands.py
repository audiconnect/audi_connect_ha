"""Regression: previously working upstream CARIAD climate and wake contracts.

These tests never send requests to a real car; physical confirmation still
requires manual user inspection in the V3 Workbench.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
from custom_components.audiconnect.v3.engine import V3Engine
from custom_components.audiconnect.v3.family_executors import CARIADExecutor
from custom_components.audiconnect.v3.registry import CapabilityRegistry
from custom_components.audiconnect.v3.runtime import catalog_path
from custom_components.audiconnect.v3.transport import V3Response
from custom_components.audiconnect.v3.vehicle import V3Vehicle

VIN = "WAUZZZ4M0MD123456"
CASES = (
    ("climate", "start", "cariad.climate.start.stored", "/climatisation/start", None),
    ("climate", "stop", "cariad.climate.stop", "/climatisation/stop", None),
    ("remote", "wake", "cariad.remote.wake", "/vehiclewakeuptrigger", {}),
)


def make_engine():
    model = CapabilityRegistry.from_json_file(catalog_path())
    car = V3Vehicle(
        vin=VIN,
        name="Audi",
        model="Q8",
        model_family="",
        country="DE",
        auth_family="auth0",
    )
    auth = SimpleNamespace(
        uses_auth0=True, country="DE", service=SimpleNamespace(_spin=None)
    )

    class Storage:
        async def async_save(self, profiles):
            pass

    engine = V3Engine(
        None,
        SimpleNamespace(entry_id="test", options={}, data={}),
        model,
        auth=auth,
        transport=object(),
        storage=Storage(),
    )
    engine.vehicles[VIN.lower()] = car
    engine.profiles[VIN.lower()] = DevelopmentProfile(model, car.context)
    return engine, car


@pytest.mark.parametrize("capability,action,operation,suffix,body", CASES)
def test_upstream_cariad_command_payload_parity(
    capability, action, operation, suffix, body
):
    engine, car = make_engine()
    available = engine.registry.resolve(capability, action, car.context)[
        "available_operations"
    ]
    assert operation in available
    family, method, path, actual = engine._operation_request(car, operation)
    assert (family, method, actual) == ("cariad", "POST", body)
    assert path == f"/vehicle/v1/vehicles/{VIN}{suffix}"
    assert engine.registry.operations[operation]["delivery"] == "manual"
    plan = CARIADExecutor().plan(
        SimpleNamespace(
            uses_auth0=True, country="DE", access_token=lambda family: "fake-token"
        ),
        method,
        path,
        actual,
        explicit_action=True,
    )
    assert plan.url.startswith("https://emea.bff.cariad.digital/")
    assert plan.body == body


@pytest.mark.asyncio
@pytest.mark.parametrize("capability,action,operation,suffix,body", CASES)
async def test_guided_action_sends_exactly_one_post_and_requires_confirmation(
    capability, action, operation, suffix, body
):
    engine, car = make_engine()
    calls = []

    class Transport:
        async def request(self, family, method, path, **kwargs):
            calls.append((family, method, path, kwargs))
            return V3Response(202, {"requestId": "test-only"}, datetime.now(UTC))

    engine.transport = Transport()
    outcome = await engine.test_action(VIN, action, operation, capability=capability)
    assert len(calls) == 1
    assert calls[0][:3] == ("cariad", "POST", f"/vehicle/v1/vehicles/{VIN}{suffix}")
    assert calls[0][3]["body"] == body
    assert calls[0][3]["explicit_action"] is True
    assert outcome["physical_result"] == "requires_user_confirmation"
    assert not engine.control_enabled(VIN, action, capability)
    assert f"{capability}.{action}" not in engine.profiles[VIN.lower()].active


@pytest.mark.asyncio
async def test_charge_mode_template_renders_exact_oem_request_without_preflight():
    engine, car = make_engine()
    family, method, path, body = await engine.commands.command_request(
        car, "cariad.charging.mode", {"value": "timer"}
    )
    assert (family, method, path, body) == (
        "cariad",
        "PUT",
        f"/vehicle/v1/vehicles/{VIN}/charging/mode",
        {"preferredChargeMode": "timer"},
    )


@pytest.mark.asyncio
async def test_charge_mode_service_rejects_unadvertised_mode_before_dispatch():
    from unittest.mock import AsyncMock
    from homeassistant.exceptions import HomeAssistantError
    from custom_components.audiconnect.v3.service_commands import execute

    engine, car = make_engine()
    car.readings["availableChargeModes"] = {"value": ["manual"]}
    engine.transport = SimpleNamespace(request=AsyncMock())
    for action, params in (
        ("set_charge_mode", {"charge_mode": "timer"}),
        ("start_timed_charger", {}),
    ):
        with pytest.raises(HomeAssistantError, match="not advertised"):
            await execute(engine, VIN, action, params)
    engine.transport.request.assert_not_awaited()
    assert not engine.profiles[VIN.lower()].command_journal


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["unknown", "quota_limited", "rejected"])
async def test_accepted_comfort_feedback_precedes_confirmation(monkeypatch, outcome):
    from datetime import timedelta
    from custom_components.audiconnect.v3 import request_status
    from custom_components.audiconnect.v3.entities import _reading_projection

    engine, car = make_engine()
    stamp = datetime.now(UTC) - timedelta(minutes=2)
    car.set_climate(
        "off", stamp.isoformat(), route="test", observed_at=stamp, http_status=200
    )
    notifications = []

    def notify():
        notifications.append(
            _reading_projection(
                SimpleNamespace(engine=engine), car, "climatisationState"
            )
        )

    async def confirm(*args):
        assert notifications == [("on", "optimistic")]
        assert car.climate_state == "off"
        return outcome

    class Transport:
        async def request(self, family, method, path, **kwargs):
            assert method == "POST"
            return V3Response(
                202, {"data": {"requestID": "test-id"}}, datetime.now(UTC)
            )

    engine.transport = Transport()
    monkeypatch.setattr(request_status, "confirm", confirm)
    monkeypatch.setattr(engine.commands, "_notify_discovery_change", notify)
    monkeypatch.setattr(
        engine.commands, "command_route", lambda *args: "cariad.climate.start.stored"
    )
    if outcome == "rejected":
        with pytest.raises(RuntimeError, match="rejected"):
            await engine.commands.send_control(VIN, "start", "climate")
        # A correlated rejection ends intent, but the pre-dispatch capture
        # cannot prove the current physical state after HTTP acceptance.
        assert notifications[-1] == (None, "unknown")
    else:
        record = await engine.commands.send_control(VIN, "start", "climate")
        assert record.state == "accepted_unconfirmed"
        assert record.backend_result == outcome
        assert notifications[-1] == ("on", "optimistic")
    assert car.climate_state == "off"
    assert car.climate_captured == stamp


def test_empty_charge_modes_require_local_route_verification():
    from custom_components.audiconnect.v3.command_policy import (
        charge_mode_evidence,
        supported_charge_modes,
    )
    from custom_components.audiconnect.v3.control_resolution import control_decision

    engine, car = make_engine()
    profile = engine.profiles[VIN.lower()]
    car.readings.update(
        availableChargeModes={"value": []},
        preferredChargeMode={"value": "manual"},
        chargingState={"value": "off"},
    )
    route = "cariad.charging.mode"
    assert not supported_charge_modes(car, profile)
    result = control_decision(car, profile, engine.auth, "charging", "set_charge_mode")
    assert result["reason"] == "charge_mode_fallback_requires_verification"
    assert result["operation"] is None
    profile.control_results[route] = "worked"
    profile.choose_working("charging", "set_charge_mode", route)
    assert supported_charge_modes(car, profile) == []
    assert charge_mode_evidence(car, profile) == {
        "last_known_advertised_modes": [],
        "locally_verified_modes": [],
        "writable_modes": [],
        "empty_list_fallback": True,
    }
    candidate = control_decision(
        car, profile, engine.auth, "charging", "set_charge_mode", for_discovery=True
    )
    assert candidate["operation"] == route
    assert candidate["dispatch_ready"] is False
    for sequence, mode in enumerate(("manual", "timer"), start=1):
        attempt = profile.begin_test(
            "charging", "set_charge_mode", route, now=sequence * 100
        )
        profile.engineering_record(attempt.sequence).requested_charge_mode = mode
        profile.observe_http(attempt.sequence, 200)
        profile.confirm(
            attempt.sequence,
            worked=True,
            inspected_vehicle=True,
            now=sequence * 100 + 1,
        )
        profile.choose_working("charging", "set_charge_mode", route)
        assert supported_charge_modes(car, profile) == ["manual", "timer"][:sequence]
        assert (
            charge_mode_evidence(car, profile)["locally_verified_modes"]
            == [
                "manual",
                "timer",
            ][:sequence]
        )
    from custom_components.audiconnect.v3.profile_store import restore_profile
    from custom_components.audiconnect.v3.registry import VehicleContext

    restored = restore_profile(profile.registry, car.context, profile.snapshot())
    assert supported_charge_modes(car, restored) == ["manual", "timer"]
    restored.rebind_context(VehicleContext(auth="auth0", region="BE"))
    assert supported_charge_modes(car, restored) == []
    assert engine.control_enabled(VIN, "set_charge_mode", "charging")
    attempt = profile.begin_test("charging", "set_charge_mode", route, now=400)
    pending = control_decision(car, profile, engine.auth, "charging", "set_charge_mode")
    assert pending["route_available"] is True
    assert pending["route_status"] == "local_verified"
    assert pending["operation"] is None
    assert pending["dispatch_ready"] is False
    assert pending["dispatch_reason"] == "engineering_command_awaiting_review"
    profile.observe_http(attempt.sequence, 200)
    profile.confirm(attempt.sequence, worked=True, inspected_vehicle=True, now=401)
    car.readings["availableChargeModes"] = {"value": ["manual"]}
    assert supported_charge_modes(car, profile) == ["manual"]
    car.readings["availableChargeModes"] = {"value": None, "status": "invalid_value"}
    assert supported_charge_modes(car, profile) == ["manual", "timer"]
    assert engine.control_enabled(VIN, "set_charge_mode", "charging")
    car.impaired_capabilities.add("charging")
    assert not engine.control_enabled(VIN, "set_charge_mode", "charging")


def test_next_climate_timer_excludes_expired_and_ambiguous_times():
    from custom_components.audiconnect.v3.derived_values import observe_derived

    engine, car = make_engine()
    profile = engine.profiles[VIN.lower()]
    now = datetime(2026, 11, 13, 12, tzinfo=UTC)
    block = {
        "carCapturedTimestamp": now.isoformat(),
        "timeInCar": "2026-11-13T13:00:00+01:00",
        "timers": [
            {
                "id": 1,
                "enabled": True,
                "singleTimer": {"startDateTimeLocal": "2026-11-13T12:00:00"},
            },
            {
                "id": 2,
                "enabled": True,
                "singleTimer": {"startDateTimeLocal": "2026-11-13T14:00:00"},
            },
            {
                "id": 3,
                "enabled": True,
                "singleTimer": {"startDateTimeLocal": "2026-11-15T14:00:00"},
            },
        ],
    }
    payload = {"climatisationTimers": {"climatisationTimersStatus": {"value": block}}}
    from datetime import timedelta

    def observe():
        nonlocal now
        block["carCapturedTimestamp"] = now.isoformat()
        observe_derived(car, profile, payload, now, lambda *_: True)
        now += timedelta(seconds=1)

    observe()
    key = "next_climatisation_timer_local"
    assert car.readings[key]["value"] == "2026-11-13T14:00:00"
    assert car.readings["climatisation_timer_enabled_count"]["value"] == 3
    block.pop("timeInCar")
    observe()
    assert car.readings[key]["value"] is None
    block["timers"] = block["timers"][2:]
    observe()
    assert car.readings[key]["value"] == "2026-11-15T14:00:00"
    block["timers"].append({"id": 4, "enabled": True, "singleTimer": {}})
    observe()
    assert car.readings[key]["value"] is None
    block["timers"].pop()
    block["timers"].append(
        {"id": 5, "enabled": True, "recurringTimer": {"startTime": "07:00"}}
    )
    observe()
    assert car.readings[key]["value"] == "2026-11-15T14:00:00"
    block["timeInCar"] = "2026-11-12T13:00:00+01:00"
    block["timers"].append(
        {
            "id": 6,
            "enabled": True,
            "singleTimer": {"startDateTimeLocal": "2026-11-13T14:00:00"},
        }
    )
    observe()
    assert car.readings[key]["value"] is None


def test_conflicting_undated_charge_modes_recover_only_through_explicit_discovery():
    from custom_components.audiconnect.v3.command_policy import supported_charge_modes
    from custom_components.audiconnect.v3.read_discovery import user_test_candidates

    engine, car = make_engine()
    profile = engine.profiles[VIN.lower()]
    route = "cariad.charging.mode"
    car.readings["availableChargeModes"] = {
        "value": None,
        "status": "invalid_value",
        "reason": "conflicting_source_values",
        "family": "cariad",
        "captured": None,
        "discovered_options": ["manual", "timer"],
    }
    assert not supported_charge_modes(car, profile)
    candidate = user_test_candidates(engine, car, profile)["charging.set_charge_mode"]
    assert candidate["operation"] == route
    assert candidate["parameter_schema"]["value"]["enum"] == ["manual", "timer"]
    attempt = profile.begin_test("charging", "set_charge_mode", route, now=100)
    profile.engineering_record(attempt.sequence).requested_charge_mode = "manual"
    profile.observe_http(attempt.sequence, 200)
    profile.confirm(attempt.sequence, worked=True, inspected_vehicle=True, now=101)
    profile.choose_working("charging", "set_charge_mode", route)
    assert supported_charge_modes(car, profile) == ["manual"]
    car.readings["availableChargeModes"]["captured"] = datetime.now(UTC).isoformat()
    assert supported_charge_modes(car, profile) == ["manual"]
    profile.control_results[route] = "failed"
    assert not supported_charge_modes(car, profile)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capability,action,operation",
    [
        ("charging", "stop", "cariad.charging.stop"),
        ("climate", "start", "cariad.climate.start.stored"),
    ],
)
async def test_post_acceptance_processing_error_retains_receipt(
    monkeypatch, capability, action, operation
):
    from custom_components.audiconnect.v3 import request_status
    from custom_components.audiconnect.v3.profile_store import restore_profile

    engine, car = make_engine()
    calls = []

    class Transport:
        async def request(self, family, method, path, **kwargs):
            calls.append((family, method, path, kwargs))
            return V3Response(
                202, {"data": {"requestID": "test-id"}}, datetime.now(UTC)
            )

    async def confirm(*args):
        raise ValueError("Invalid status response")

    engine.transport = Transport()
    monkeypatch.setattr(request_status, "confirm", confirm)
    monkeypatch.setattr(engine.commands, "command_route", lambda *args: operation)
    with pytest.raises(RuntimeError, match="HTTP 202; accepted_unconfirmed"):
        await engine.commands.send_control(VIN, action, capability)
    assert len(calls) == 1 and calls[0][1] == "POST"
    profile = engine.profiles[VIN.lower()]
    record = profile.last_command
    assert record.http_status == 202
    assert record.state == "accepted_unconfirmed"
    assert record.backend_result == "accepted_unconfirmed"
    assert car.last_command_result == record.state
    restored = restore_profile(profile.registry, car.context, profile.snapshot())
    assert restored.last_command.http_status == 202
    assert restored.last_command.state == "accepted_unconfirmed"


def test_failed_charge_mode_does_not_withdraw_independently_verified_mode():
    from custom_components.audiconnect.v3.command_policy import supported_charge_modes
    from custom_components.audiconnect.v3.profile_store import restore_profile

    engine, car = make_engine()
    profile = engine.profiles[VIN.lower()]
    car.readings["availableChargeModes"] = {"value": []}
    route = "cariad.charging.mode"
    for i, mode in enumerate(("manual", "timer"), start=1):
        attempt = profile.begin_test("charging", "set_charge_mode", route, now=i * 100)
        profile.engineering_record(attempt.sequence).requested_charge_mode = mode
        profile.observe_http(attempt.sequence, 200)
        profile.confirm(
            attempt.sequence, worked=i == 1, inspected_vehicle=True, now=i * 100 + 1
        )
        if i == 1:
            profile.choose_working("charging", "set_charge_mode", route)
    assert supported_charge_modes(car, profile) == ["manual"]
    restored = restore_profile(profile.registry, car.context, profile.snapshot())
    assert supported_charge_modes(car, restored) == ["manual"]
    assert restored.control_results[route] == "worked"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,http_status,backend,new_capture,expected",
    [
        (False, 200, "accepted_unconfirmed", False, False),
        (True, 200, "accepted_unconfirmed", False, True),
        (True, 200, "backend_completed", False, True),
        (True, 200, "accepted_unconfirmed", True, False),
        (True, 200, "quota_limited", False, False),
        (True, 200, "rejected", False, False),
        (True, 403, "rejected", False, False),
        (True, None, "transport_uncertain", False, False),
    ],
)
async def test_opt_in_refresh_requires_known_acceptance_and_missing_native_capture(
    enabled, http_status, backend, new_capture, expected
):
    from datetime import timedelta
    from unittest.mock import AsyncMock
    from custom_components.audiconnect.const import CONF_REFRESH_AFTER_ACTION
    from custom_components.audiconnect.v3.command_journal import CommandRecord
    from custom_components.audiconnect.v3.command_readback import configure_readback

    engine, car = make_engine()
    now = datetime.now(UTC)
    record = CommandRecord.begin(
        "charging",
        "start",
        "cariad.charging.start",
        (now - timedelta(seconds=5)).timestamp(),
    )
    record.observe_http(http_status)
    record.observe_backend(backend, now.timestamp())
    configure_readback(record, {})
    if new_capture:
        car.readings["chargingState"] = {
            "value": "off",
            "family": "cariad",
            "captured": now.isoformat(),
            "observed": now.isoformat(),
            "status": "verified",
        }
    engine.entry.options[CONF_REFRESH_AFTER_ACTION] = enabled
    engine.entry.runtime_data = SimpleNamespace(coordinator=object())
    engine.commands.send_control = AsyncMock(return_value=record)
    engine._refresh_event = lambda *args: None
    engine._follow_up_cloud = AsyncMock()
    await engine._after_command(VIN, record)
    engine._follow_up_cloud.assert_awaited_once()
    if expected:
        engine.commands.send_control.assert_awaited_once_with(
            VIN, "refresh", "remote", _follow_up_to=record.command_id
        )
    else:
        engine.commands.send_control.assert_not_awaited()
