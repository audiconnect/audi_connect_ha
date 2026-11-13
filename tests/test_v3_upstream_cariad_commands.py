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
    from custom_components.audiconnect.v3.command_readback import projected_state

    engine, car = make_engine()
    profile = engine.profiles[VIN.lower()]
    stamp = datetime.now(UTC) - timedelta(minutes=2)
    car.set_climate(
        "off", stamp.isoformat(), route="test", observed_at=stamp, http_status=200
    )
    notifications = []

    def notify():
        notifications.append(
            projected_state(profile, "climate", car.climate_state, car.climate_captured)
        )

    async def confirm(*args):
        assert notifications == [("on", "command_pending")]
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
        assert notifications[-1] == ("off", "vehicle")
    else:
        record = await engine.commands.send_control(VIN, "start", "climate")
        assert record.state == "accepted_unconfirmed"
        assert record.backend_result == outcome
        assert notifications[-1] == ("on", "command_pending")
    assert car.climate_state == "off"
    assert car.climate_captured == stamp


def test_empty_charge_modes_require_local_route_verification():
    from custom_components.audiconnect.v3.command_policy import supported_charge_modes
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
            attempt.sequence, worked=True, inspected_vehicle=True, now=sequence * 100 + 1
        )
        profile.choose_working("charging", "set_charge_mode", route)
        assert supported_charge_modes(car, profile) == ["manual", "timer"][:sequence]
    from custom_components.audiconnect.v3.profile_store import restore_profile
    from custom_components.audiconnect.v3.registry import VehicleContext

    restored = restore_profile(profile.registry, car.context, profile.snapshot())
    assert supported_charge_modes(car, restored) == ["manual", "timer"]
    restored.rebind_context(VehicleContext(auth="auth0", region="BE"))
    assert supported_charge_modes(car, restored) == []
    assert engine.control_enabled(VIN, "set_charge_mode", "charging")
    car.readings["availableChargeModes"] = {"value": ["manual"]}
    assert supported_charge_modes(car, profile) == ["manual"]
    car.readings["availableChargeModes"] = {"value": None, "status": "invalid_value"}
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
    observe_derived(car, profile, payload, now, lambda *_: True)
    key = "next_climatisation_timer_local"
    assert car.readings[key]["value"] == "2026-11-13T14:00:00"
    assert car.readings["climatisation_timer_enabled_count"]["value"] == 3
    block.pop("timeInCar")
    observe_derived(car, profile, payload, now, lambda *_: True)
    assert key not in car.readings
    block["timers"] = block["timers"][2:]
    observe_derived(car, profile, payload, now, lambda *_: True)
    assert car.readings[key]["value"] == "2026-11-15T14:00:00"
