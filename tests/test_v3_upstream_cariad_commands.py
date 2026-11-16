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
