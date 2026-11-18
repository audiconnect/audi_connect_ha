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


def test_native_climate_setting_gate_requires_both_values_for_switch():
    from custom_components.audiconnect.v3.command_parameters import climate_variant
    from custom_components.audiconnect.v3.operation_revision import operation_revision

    engine, car = make_engine()
    car.advertised_capabilities.add("climatisation")
    profile = engine.profiles[VIN.lower()]
    route = "cariad.climate.settings"
    revision = operation_revision(profile.registry.operations[route])
    assert engine.control_enabled(VIN, "set_settings")
    assert engine.control_enabled(VIN, "set_settings", params={"temp_c": 22})
    for value in (False, True):
        params = {"windowHeatingEnabled": value}
        assert not engine.control_enabled(VIN, "set_settings", params=params)
        profile.verified_climate_variants.setdefault(route, {})[
            climate_variant(route, params)
        ] = revision
        assert engine.control_enabled(VIN, "set_settings", params=params)
    assert not engine.control_enabled(
        VIN, "set_settings", params={"zoneFrontLeftEnabled": True}
    )
    assert not engine.control_enabled(
        VIN, "set_settings", params={"windowHeatingEnabled": "true"}
    )
    assert not engine.control_enabled(
        VIN, "set_settings", params={"temp_c": 22, "windowHeatingEnabled": True}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 405])
async def test_selective_climate_service_requires_its_own_review_after_restart(status):
    from homeassistant.exceptions import HomeAssistantError
    from custom_components.audiconnect.v3.attribute_runtime import observe_read_only
    from custom_components.audiconnect.v3.profile_store import restore_profile
    from custom_components.audiconnect.v3.service_commands import execute

    engine, car = make_engine()
    car.advertised_capabilities.add("climatisation")
    profile = engine.profiles[VIN.lower()]
    profile.discovery.cooldown_seconds = 0
    route = "cariad.climate.start.vehicle_settings"
    action = "start_with_settings"
    base = profile.begin_test("climate", action, route, now=100)
    profile.observe_http(base.sequence, 200)
    profile.confirm(base.sequence, worked=True, inspected_vehicle=True, now=101)
    profile.choose_working("climate", action, route)
    now = datetime.now(UTC)
    payload = {
        "climatisation": {
            "climatisationSettings": {
                "value": {
                    "targetTemperature_C": 20,
                    "windowHeatingEnabled": False,
                    "carCapturedTimestamp": now.isoformat(),
                }
            },
            "climatisationStatus": {
                "value": {
                    "climatisationState": "off",
                    "carCapturedTimestamp": now.isoformat(),
                }
            },
        }
    }
    observe_read_only(car, profile, payload, now)
    calls = []

    class Transport:
        async def request(self, family, method, path, **kwargs):
            calls.append((family, method, path, kwargs))
            if method == "GET":
                return V3Response(207, payload, datetime.now(UTC))
            data = {"error": {"code": "unsupported"}} if status == 405 else {}
            return V3Response(status, data, datetime.now(UTC))

    engine.transport = Transport()
    params = {"glass_heating": True}
    with pytest.raises(HomeAssistantError, match="requires vehicle discovery"):
        await execute(engine, VIN, "start_climatisation", params)
    assert calls == []
    result = await engine.approved_control_discovery(
        VIN,
        action,
        route,
        approval="non_spin",
        params=params,
        guided=True,
        expert=True,
    )
    assert [row[1] for row in calls] == ["GET", "POST"]
    assert calls[-1][3]["body"]["windowHeatingEnabled"] is True
    assert profile.engineering_record(result["sequence"]).readback_attribute is None
    if status == 200:
        assert result["physical_result"] == "requires_user_confirmation"
        assert not profile.verified_climate_variants
        await engine.review_action(VIN, result["sequence"], "worked")
    else:
        assert result["physical_result"] == "rejected"
    assert profile.control_results[route] == "worked"
    assert profile.active["climate." + action] == route
    restored = restore_profile(
        profile.registry, car.context, profile.snapshot(), cooldown_seconds=0
    )
    engine.profiles[VIN.lower()] = restored
    assert engine.control_enabled(VIN, action, params={"temp_c": 22})
    assert not engine.control_enabled(VIN, action, params={"glass_heating": False})
    with pytest.raises(HomeAssistantError, match="requires vehicle discovery"):
        await execute(engine, VIN, "start_climatisation", {"glass_heating": False})
    assert len(calls) == 2
    if status == 200:
        await execute(engine, VIN, "start_climatisation", params)
        assert [row[1] for row in calls] == ["GET", "POST", "GET", "POST"]
    else:
        with pytest.raises(HomeAssistantError, match="requires vehicle discovery"):
            await execute(engine, VIN, "start_climatisation", params)
        assert len(calls) == 2


@pytest.mark.parametrize("failed", [False, True])
def test_q8_empty_charge_modes_with_invalid_preference_are_discoverable(failed):
    from custom_components.audiconnect.v3.command_policy import supported_charge_modes
    from custom_components.audiconnect.v3.read_discovery import user_test_candidates

    engine, car = make_engine()
    profile = engine.profiles[VIN.lower()]
    car.advertised_capabilities.add("charging")
    car.readings.update(
        availableChargeModes={"family": "cariad", "value": []},
        preferredChargeMode={"family": "cariad", "status": "invalid_value"},
        chargeMode={"family": "cariad", "value": "manual"},
    )
    route = "cariad.charging.mode"
    if failed:
        profile.control_results[route] = "failed"
    assert supported_charge_modes(car, profile) == []
    assert not engine.control_enabled(VIN, "set_charge_mode", "charging")
    for expert in (False, True):
        candidate = user_test_candidates(engine, car, profile, include_verified=expert)[
            "charging.set_charge_mode"
        ]
        assert candidate["operation"] == route
        assert candidate["parameter_schema"]["value"]["enum"] == ["manual", "timer"]
    car.impaired_capabilities.add("charging")
    assert "charging.set_charge_mode" not in user_test_candidates(engine, car, profile)


def test_failed_native_control_is_discoverable_but_not_dispatch_ready():
    from custom_components.audiconnect.v3.read_discovery import user_test_candidates

    engine, car = make_engine()
    profile = engine.profiles[VIN.lower()]
    car.advertised_capabilities.add("climatisation")
    route = "cariad.climate.window_heating_start"
    profile.control_results[route] = "failed"
    assert not engine.control_enabled(VIN, "window_heating_start", "climate")
    for expert in (False, True):
        candidate = user_test_candidates(engine, car, profile, include_verified=expert)[
            "climate.window_heating_start"
        ]
        assert candidate["operation"] == route
    profile.discovery.disabled.add("climate.window_heating_start")
    assert "climate.window_heating_start" not in user_test_candidates(
        engine, car, profile
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("combined", [False, True])
async def test_expert_charging_routes_are_explicit_and_never_auto_retried(combined):
    from custom_components.audiconnect.v3.read_discovery import user_test_candidates

    engine, car = make_engine()
    profile = engine.profiles[VIN.lower()]
    car.advertised_capabilities.add("charging")
    direct = "cariad.charging.start"
    alternate = direct + ".combined"
    profile.control_results[direct] = "failed"
    candidates = user_test_candidates(engine, car, profile, include_verified=True)
    assert {
        row["operation"]
        for row in candidates.values()
        if row["capability"] == "charging" and row["action"] == "start"
    } == {direct, alternate}
    assert not engine.control_enabled(VIN, "start", "charging")
    calls = []

    class Transport:
        async def request(self, family, method, path, **kwargs):
            calls.append((family, method, path, kwargs))
            return V3Response(405, {"error": "unsupported"}, datetime.now(UTC))

    engine.transport = Transport()
    chosen = alternate if combined else direct
    result = await engine.approved_control_discovery(
        VIN,
        "start",
        chosen,
        approval="non_spin",
        capability="charging",
        guided=True,
        expert=True,
    )
    assert result["physical_result"] == "rejected"
    assert result["operation"] == chosen
    assert len(calls) == 1
    assert calls[0][2].endswith("/start-stop" if combined else "/start")
    assert calls[0][3]["body"] == ({"action": "start"} if combined else {})
    assert not engine.control_enabled(VIN, "start", "charging")


@pytest.mark.asyncio
async def test_explicit_read_rescan_retests_prior_evidence_in_bounded_batches():
    from custom_components.audiconnect.v3.read_discovery import full_read_plan

    engine, car = make_engine()
    profile = engine.profiles[VIN.lower()]
    plan, _ = full_read_plan(profile, car.context, "cariad")
    expected = [ident for ident, _ in sorted(plan)]
    assert len(expected) > 12
    for ident in expected:
        profile.api_observations[ident] = {"http_status": 200}
    calls = []

    class Transport:
        async def request(self, family, method, path, **kwargs):
            calls.append((family, method, path))
            return V3Response(200, {}, datetime.now(UTC))

    engine.transport = Transport()
    normal = await engine.test_family_reads(VIN, "cariad", full=True)
    assert normal["request_count"] == 0
    result = await engine.test_family_reads(VIN, "cariad", full=True, rescan_after="")
    assert result["request_count"] == 12
    assert [row["operation"] for row in result["results"]] == expected[:12]
    assert result["next_rescan_after"] == expected[11]
    assert result["remaining_routes"] == expected[12:]
    result = await engine.test_family_reads(
        VIN, "cariad", full=True, rescan_after=result["next_rescan_after"]
    )
    assert [row["operation"] for row in result["results"]] == expected[12:24]
    assert len(calls) <= 24
    assert all(method == "GET" for _, method, _ in calls)
    assert not car.readings
    with pytest.raises(ValueError, match="Rescan route changed"):
        await engine.test_family_reads(
            VIN, "cariad", full=True, rescan_after="not_a_reviewed_route"
        )


@pytest.mark.parametrize(
    "job,detail,count",
    [
        ("chargingTimers", "charging_timers_detail", "charging_timer_enabled_count"),
        (
            "climatisationTimers",
            "climate_timers_detail",
            "climatisation_timer_enabled_count",
        ),
    ],
)
def test_timer_count_follows_selected_list_even_when_count_is_unchanged(
    job, detail, count
):
    from datetime import timedelta
    from custom_components.audiconnect.v3.attribute_runtime import observe_read_only

    engine, car = make_engine()
    profile = engine.profiles[VIN.lower()]
    now = datetime.now(UTC)

    def observe(timers, capture, receipt):
        observe_read_only(
            car,
            profile,
            {
                job: {
                    job + "Status": {
                        "value": {
                            "carCapturedTimestamp": capture.isoformat(),
                            "timers": timers,
                        }
                    }
                }
            },
            receipt,
        )

    observe([{"id": 1, "enabled": False}], now, now)
    assert car.readings[count]["value"] == 0
    observe([{"id": 2, "enabled": False}], now, now + timedelta(seconds=1))
    assert car.readings[detail]["reason"] == "conflicting_source_values"
    assert car.readings[count]["value"] is None
    assert car.readings[count]["reason"] == "conflicting_source_values"
    observe(
        [{"id": 1, "enabled": True}],
        now - timedelta(minutes=1),
        now + timedelta(seconds=2),
    )
    assert car.readings[count]["value"] is None
    newer = now + timedelta(seconds=3)
    observe([{"id": 2, "enabled": True}], newer, newer)
    assert car.readings[count]["value"] == 1
    assert car.readings[detail]["value"]["items"][0]["id"] == 2
    assert car.readings[count]["captured"] == car.readings[detail]["captured"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "backend,telemetry,expected",
    [
        ("timeout", "charging", True),
        ("in_progress", "charging", False),
        ("successful", "charging", False),
        ("failed", "charging", False),
        ("timeout", "readyForCharging", False),
        ("timeout", "stale", False),
        ("timeout", "stale_then_fresh", True),
        ("timeout", "data_act", False),
        ("timeout", "superseded", False),
        ("timeout", "workbench_superseded", False),
        ("timeout", "workbench_during_refresh", False),
        ("timeout", "disabled", False),
        ("timeout", "disabled_during_refresh", False),
        ("native_timeout", "charging", True),
        ("native_timeout", "readyForCharging", False),
        ("native_error", "charging", False),
        ("timeout", "disabled_during_save", False),
        ("timeout", "retry_zero_during_save", False),
        ("timeout", "stopped_during_save", False),
    ],
)
async def test_charging_stop_recovery_requires_exact_timeout_and_fresh_native_state(
    monkeypatch, backend, telemetry, expected
):
    from datetime import timedelta
    from custom_components.audiconnect.v3.command_journal import CommandRecord
    from custom_components.audiconnect.v3.command_readback import configure_readback
    from custom_components.audiconnect.v3.operation_revision import operation_revision

    engine, car = make_engine()
    engine.entry.options["v3_charging_stop_retry"] = telemetry != "disabled"
    profile = engine.profiles[VIN.lower()]
    route = "cariad.charging.stop"
    monkeypatch.setattr(engine.commands, "command_route", lambda *args: route)
    started = datetime.now(UTC) - timedelta(seconds=301)
    first = CommandRecord.begin(
        "charging",
        "stop",
        route,
        started.timestamp(),
        operation_revision=operation_revision(profile.registry.operations[route]),
    )
    first.observe_http(200)
    first.observe_backend("in_progress", started.timestamp())
    first.request_id = "original"
    first.request_context = profile.discovery.context
    configure_readback(first, {})
    profile.track_command(first)
    calls = []
    refresh_count = 0

    async def no_delay(_seconds):
        pass

    monkeypatch.setattr(
        "custom_components.audiconnect.v3.command_engine.asyncio.sleep", no_delay
    )

    def workbench_start(stamp):
        attempt = profile.begin_test(
            "charging", "start", "cariad.charging.start", now=stamp
        )
        profile.observe_http(attempt.sequence, 200)
        profile.confirm(
            attempt.sequence, worked=True, inspected_vehicle=True, now=stamp + 1
        )
        assert profile.last_command is first

    if telemetry == "workbench_superseded":
        # The experiment is complete and its normal cooldown has elapsed.
        workbench_start(started.timestamp() + 10)

    if backend in ("native_timeout", "native_error"):
        engine.commands.reconcile_native_requests(
            car,
            profile,
            {
                "charging": {
                    "chargingStatus": {
                        "requests": [
                            {
                                "requestId": "original",
                                "operation": "stop",
                                "status": backend.removeprefix("native_"),
                            }
                        ]
                    }
                }
            },
            datetime.now(UTC),
        )
        assert first.state == "rejected"
        assert first.stop_retry_timed_out == (backend == "native_timeout")
        assert not CommandRecord.restore(first.snapshot()).stop_retry_timed_out

    class Transport:
        async def request(self, family, method, path, **kwargs):
            calls.append((family, method, path))
            if method == "POST":
                return V3Response(
                    200, {"data": {"requestID": "second"}}, datetime.now(UTC)
                )
            item = (
                {"id": "original", "status": backend}
                if len(calls) == 1
                else {"id": "second", "status": "successful"}
            )
            return V3Response(200, {"data": [item]}, datetime.now(UTC))

    engine.transport = Transport()

    async def refresh(current):
        assert current()
        nonlocal refresh_count
        refresh_count += 1
        now = datetime.now(UTC)
        car.readings["chargingState"] = {
            "value": "readyForCharging"
            if telemetry == "readyForCharging"
            else "charging",
            "family": "eu_data_act" if telemetry == "data_act" else "cariad",
            "captured": (
                started
                if telemetry == "stale"
                or (telemetry == "stale_then_fresh" and refresh_count == 1)
                else now
            ).isoformat(),
            "observed": now.isoformat(),
            "status": "verified",
        }
        if telemetry == "disabled_during_refresh":
            engine.entry.options["v3_charging_stop_retry"] = False
        if telemetry == "superseded":
            profile.track_command(
                CommandRecord.begin("charging", "start", route, now.timestamp())
            )
        if telemetry == "workbench_during_refresh":
            workbench_start(now.timestamp())

    if telemetry in (
        "disabled_during_save",
        "retry_zero_during_save",
        "stopped_during_save",
    ):

        async def save(_profiles):
            latest = profile.last_command
            if latest.parent_command_id != first.command_id:
                return
            if telemetry == "disabled_during_save":
                engine.entry.options["v3_charging_stop_retry"] = False
            elif telemetry == "retry_zero_during_save":
                engine.entry.options["v3_stop_extra_retries"] = 0
            else:
                stamp = datetime.now(UTC).isoformat()
                car.readings["chargingState"].update(
                    value="readyForCharging", captured=stamp, observed=stamp
                )

        monkeypatch.setattr(engine.storage, "async_save", save)

    result = await engine.commands.retry_charging_stop(VIN, first, refresh)
    writes = [call for call in calls if call[1] == "POST"]
    if telemetry == "stale_then_fresh":
        assert refresh_count == 2
    if telemetry == "stale":
        assert refresh_count == 10
    if telemetry in ("disabled", "workbench_superseded") or backend == "native_error":
        assert calls == []
    if backend == "native_timeout":
        assert all(call[1] != "GET" for call in calls[:1])
    assert len(writes) == int(expected)
    if expected:
        assert writes == [
            ("cariad", "POST", f"/vehicle/v1/vehicles/{VIN}/charging/stop")
        ]
        assert result.parent_command_id == first.command_id
        assert first.state == "rejected"
        assert result.state == "backend_completed"
        assert result.readback_observed_at is None
        restored = CommandRecord.restore(result.snapshot())
        assert restored.parent_command_id == first.command_id
        before = list(calls)
        assert await engine.commands.retry_charging_stop(VIN, first, refresh) is None
        assert calls == before
    else:
        assert result is None
    if telemetry in (
        "disabled_during_save",
        "retry_zero_during_save",
        "stopped_during_save",
    ):
        child = profile.last_command
        assert child.parent_command_id == first.command_id
        assert child.state == "rejected"
        assert child.http_status is None
    if backend == "in_progress":
        assert first.state == "accepted_unconfirmed"
    if backend == "successful":
        assert first.state == "backend_completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome,readback,current,superseded,notice",
    [
        (None, False, None, False, None),
        ("rejected", False, None, False, "rejected"),
        ("local_cancel", False, None, False, None),
        ("uncertain", False, None, False, "could not be confirmed"),
        ("accepted_unconfirmed", False, None, False, "could not be confirmed"),
        ("backend_completed", False, None, False, "could not be confirmed"),
        ("backend_completed", True, "readyForCharging", False, None),
        ("accepted_unconfirmed", True, "readyForCharging", False, None),
        ("backend_completed", True, "charging", False, "still reports charging"),
        ("backend_completed", True, None, False, "could not be confirmed"),
        ("backend_completed", False, "readyForCharging", False, None),
        ("rejected", False, None, True, None),
    ],
)
async def test_second_stop_reports_failure_or_unconfirmed_once(
    monkeypatch, outcome, readback, current, superseded, notice
):
    from unittest.mock import AsyncMock, Mock

    from homeassistant.components import persistent_notification

    from custom_components.audiconnect.v3.command_journal import CommandRecord

    engine, car = make_engine()
    engine.hass = object()
    profile = engine.profiles[VIN.lower()]
    first = CommandRecord.begin(
        "charging", "stop", "cariad.charging.stop", datetime.now(UTC).timestamp()
    )
    profile.track_command(first)
    notify = Mock()
    monkeypatch.setattr(persistent_notification, "async_create", notify)

    async def retry(*args):
        if outcome is None:
            return
        second = CommandRecord.begin(
            "charging",
            "stop",
            first.operation,
            datetime.now(UTC).timestamp(),
            parent_command_id=first.command_id,
        )
        second.state = "rejected" if outcome == "local_cancel" else outcome
        second.http_status = None if outcome in ("local_cancel", "uncertain") else 200
        if readback:
            second.readback_observed_at = second.started_at + 1
        if current is not None:
            from datetime import timedelta

            second.started_at -= 2
            stamp = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
            car.readings["chargingState"] = {
                "value": current,
                "captured": stamp,
                "observed": stamp,
                "family": "cariad",
                "status": "verified",
            }
        profile.track_command(second)
        if superseded:
            profile.track_command(
                CommandRecord.begin(
                    "charging", "start", "cariad.charging.start", second.started_at
                )
            )

    monkeypatch.setattr(engine.commands, "retry_charging_stop", retry)
    refresh = AsyncMock()
    monkeypatch.setattr(engine, "_recovery_cloud", refresh)
    monkeypatch.setattr(
        engine.commands,
        "charging_stop_retry_current",
        lambda *args, **kwargs: not superseded,
    )

    async def verify(*args):
        if outcome == "rejected":
            return None, "dispatch_or_verification_failed"
        if current == "readyForCharging":
            return False, "expected_state_observed"
        if current == "charging":
            return True, "fresh_still_charging"
        return None, "fresh_capture_unavailable"

    monkeypatch.setattr(engine.commands, "verify_recovery_attempt", verify)
    await engine._recover_charging_stop(VIN, first)
    if notice is None:
        notify.assert_not_called()
    else:
        notify.assert_called_once()
        assert notice in notify.call_args.args[1]
        assert "No further automatic STOP" in notify.call_args.args[1]
        assert VIN not in notify.call_args.kwargs["notification_id"]
    refresh.assert_not_awaited()  # The shared verification owns reads.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,backend,expected",
    [(True, "timeout", True), (False, "timeout", False), (True, "error", False)],
)
async def test_initial_stop_confirmation_timeout_preserves_recovery_intent(
    monkeypatch, enabled, backend, expected
):
    """An exact early timeout remains a rejection and may schedule one recovery."""
    from custom_components.audiconnect.v3.command_journal import CommandRecord

    engine, _car = make_engine()
    engine.entry.options["v3_charging_stop_retry"] = enabled
    engine.hass = object()
    route = "cariad.charging.stop"
    monkeypatch.setattr(engine.commands, "command_route", lambda *args: route)
    calls = []
    tasks = []

    def create_task(hass, coroutine, name):
        tasks.append(name)
        coroutine.close()

    engine.entry.async_create_background_task = create_task

    class Transport:
        async def request(self, family, method, path, **kwargs):
            calls.append(method)
            if method == "POST":
                return V3Response(
                    200, {"data": {"requestID": "original"}}, datetime.now(UTC)
                )
            return V3Response(
                200,
                {"data": [{"id": "original", "status": backend}]},
                datetime.now(UTC),
            )

    engine.transport = Transport()
    with pytest.raises(RuntimeError, match="rejected"):
        await engine.send_control(VIN, "stop", "charging")
    record = engine.profiles[VIN.lower()].last_command
    assert record.state == "rejected"
    assert record.stop_retry_timed_out is expected
    assert not CommandRecord.restore(record.snapshot()).stop_retry_timed_out
    assert calls == ["POST", "GET"]
    assert tasks == (["Audi charging STOP recovery"] if enabled else [])


@pytest.mark.parametrize(
    "capture_offset,receipt_offset,family,value,expected",
    [
        (-1, 2, "cariad", "charging", None),
        (0, 2, "cariad", "charging", None),
        (1, 2, "cariad", "charging", True),
        (1, 2, "cariad", "readyForCharging", False),
        (1, 2, "eu_data_act", "charging", None),
        (1, -1, "cariad", "charging", None),
    ],
)
def test_recovery_readback_requires_capture_after_timeout(
    capture_offset, receipt_offset, family, value, expected
):
    from datetime import timedelta

    from custom_components.audiconnect.v3.command_journal import CommandRecord
    from custom_components.audiconnect.v3.command_readback import recent_charging_state

    engine, car = make_engine()
    now = datetime.now(UTC)
    timeout = now - timedelta(seconds=5)
    record = CommandRecord.begin(
        "charging", "stop", "cariad.charging.stop", timeout.timestamp() - 300
    )
    car.readings["chargingState"] = {
        "value": value,
        "family": family,
        "captured": (timeout + timedelta(seconds=capture_offset)).isoformat(),
        "observed": (timeout + timedelta(seconds=receipt_offset)).isoformat(),
        "status": "verified",
    }
    assert (
        recent_charging_state(
            record,
            car,
            registry=engine.registry,
            now=now,
            receipt_after=timeout.timestamp(),
            capture_after=timeout.timestamp(),
        )
        is expected
    )


@pytest.mark.asyncio
async def test_recovery_reuses_already_fresh_native_evidence():
    from unittest.mock import AsyncMock

    from custom_components.audiconnect.v3.command_journal import CommandRecord

    engine, _car = make_engine()
    record = CommandRecord.begin(
        "charging", "stop", "cariad.charging.stop", datetime.now(UTC).timestamp()
    )
    refresh = AsyncMock()
    result = await engine.commands.verify_recovery(
        record, refresh, lambda: True, lambda: False
    )
    assert result == (False, "fresh_native_capture")
    refresh.assert_not_awaited()


def test_linked_stop_timeout_is_evidence_not_retry_authority():
    from custom_components.audiconnect.v3.command_journal import CommandRecord

    engine, car = make_engine()
    engine.entry.options["v3_charging_stop_retry"] = True
    profile = engine.profiles[VIN.lower()]
    now = datetime.now(UTC).timestamp()
    child = CommandRecord.begin(
        "charging",
        "stop",
        "cariad.charging.stop",
        now - 10,
        parent_command_id="a" * 32,
    )
    child.observe_http(200)
    child.observe_backend("timeout", now)
    assert child.stop_retry_timed_out
    assert not engine.commands.charging_stop_retry_current(car, profile, child)
    assert not CommandRecord.restore(child.snapshot()).stop_retry_timed_out


@pytest.mark.asyncio
async def test_skipped_stop_recovery_notifies_without_second_write(monkeypatch):
    from unittest.mock import Mock

    from homeassistant.components import persistent_notification

    from custom_components.audiconnect.v3.command_journal import CommandRecord

    engine, _car = make_engine()
    engine.hass = object()
    engine.entry.options["v3_charging_stop_retry"] = True
    profile = engine.profiles[VIN.lower()]
    first = CommandRecord.begin(
        "charging", "stop", "cariad.charging.stop", datetime.now(UTC).timestamp()
    )
    profile.track_command(first)

    async def retry(*args):
        first.recovery_result = "fresh_capture_unavailable"

    monkeypatch.setattr(engine.commands, "retry_charging_stop", retry)
    monkeypatch.setattr(
        engine.commands, "charging_stop_retry_current", lambda *a, **kw: True
    )
    notify = Mock()
    monkeypatch.setattr(persistent_notification, "async_create", notify)
    await engine._recover_charging_stop(VIN, first)
    notify.assert_called_once()
    assert "No retry was sent" in notify.call_args.args[1]
    assert profile.last_command is first


@pytest.mark.asyncio
@pytest.mark.parametrize("final_state", ["readyForCharging", "charging"])
async def test_recovery_uses_only_targeted_reads_for_both_attempts(
    monkeypatch, final_state
):
    from datetime import timedelta
    from unittest.mock import Mock

    from homeassistant.components import persistent_notification

    from custom_components.audiconnect.v3.command_journal import CommandRecord
    from custom_components.audiconnect.v3.command_readback import configure_readback
    from custom_components.audiconnect.v3.operation_revision import operation_revision

    engine, car = make_engine()
    engine.hass = object()
    engine.entry.options["v3_charging_stop_retry"] = True
    profile = engine.profiles[VIN.lower()]
    route = "cariad.charging.stop"
    monkeypatch.setattr(engine.commands, "command_route", lambda *args: route)
    monkeypatch.setattr(engine, "_notify_discovery_change", lambda **kwargs: None)

    async def no_delay(_seconds):
        pass

    monkeypatch.setattr(
        "custom_components.audiconnect.v3.command_engine.asyncio.sleep", no_delay
    )
    now = datetime.now(UTC)
    first = CommandRecord.begin(
        "charging",
        "stop",
        route,
        (now - timedelta(seconds=301)).timestamp(),
        operation_revision=operation_revision(profile.registry.operations[route]),
    )
    configure_readback(first, {})
    first.observe_http(200)
    first.request_id = "original"
    first.request_context = profile.discovery.context
    first.observe_backend("timeout", now.timestamp())
    profile.track_command(first)
    calls = []

    class Transport:
        async def request(self, family, method, path, **kwargs):
            calls.append((method, path))
            stamp = datetime.now(UTC)
            if method == "POST":
                return V3Response(200, {"data": {"requestID": "second"}}, stamp)
            if path.endswith("/pendingrequests"):
                return V3Response(
                    200, {"data": [{"id": "second", "status": "timeout"}]}, stamp
                )
            assert path.endswith("/selectivestatus?jobs=charging")
            value = final_state if any(m == "POST" for m, _ in calls) else "charging"
            return V3Response(
                200,
                {
                    "charging": {
                        "chargingStatus": {
                            "value": {
                                "carCapturedTimestamp": stamp.isoformat(),
                                "chargingState": value,
                            }
                        }
                    }
                },
                stamp,
            )

    engine.transport = Transport()
    notify = Mock()
    monkeypatch.setattr(persistent_notification, "async_create", notify)
    await engine._recover_charging_stop(VIN, first)
    assert [method for method, _ in calls].count("POST") == 1
    assert sum(path.endswith("jobs=charging") for _, path in calls) == 2
    assert len(profile.command_journal) == 2
    child = profile.last_command
    assert child.parent_command_id == first.command_id
    assert child.stop_retry_timed_out
    assert not car.v2_initial_discovery_completed
    if final_state == "charging":
        notify.assert_called_once()
        assert child.recovery_result == "fresh_still_charging"
    else:
        notify.assert_not_called()
        assert child.recovery_result == "expected_state_observed"
