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
    family, method, path, body = await engine.commands._command_request(
        car, "cariad.charging.mode", {"value": "timer"}
    )
    assert (family, method, path, body) == (
        "cariad",
        "PUT",
        f"/vehicle/v1/vehicles/{VIN}/charging/mode",
        {"preferredChargeMode": "timer"},
    )
