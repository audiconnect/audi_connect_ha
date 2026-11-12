"""Independent V3 preheater and OEM-scoped engine controls (synthetic only)."""

from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import asyncio

import pytest

from custom_components.audiconnect.v3.command_policy import eligible_operation
from custom_components.audiconnect.v3.command_payloads import build
from custom_components.audiconnect.v3.family_executors import CARIADExecutor
from custom_components.audiconnect.v3.entities import V3PreheaterSwitch
from custom_components.audiconnect.v3.derived_values import observe_derived
from custom_components.audiconnect.v3.attribute_runtime import _accept_observation
from custom_components.audiconnect.v3.vehicle import V3Vehicle

VIN = "WAUZZZ4M0MD123456"


def auth():
    return NS(
        uses_auth0=True,
        country="DE",
        service=NS(_spin="test-pin"),
        access_token=lambda family: "fake-token",
    )


def eligible_car():
    car = V3Vehicle(VIN, "Audi", "Audi A6", "a6", "DE", car_type="gasoline")
    car.advertised_capabilities.add("remoteEngineStart")
    return car


@pytest.mark.parametrize(
    "model, family, drive",
    [
        ("Audi Q8", "", ""),
        ("", "q8", ""),
        ("Audi A6", "a6", "phev"),
    ],
)
def test_engine_never_enabled_on_excluded_vehicles(model, family, drive):
    car = eligible_car()
    car.model, car.model_family, car.car_type = model, family, drive
    assert eligible_operation(car, auth(), "remote", "engine_start") is None
    assert eligible_operation(car, auth(), "remote", "engine_stop") is None


def test_engine_proof_is_required_and_never_reused():
    car = eligible_car()
    a = auth()
    assert (
        eligible_operation(car, a, "remote", "engine_start")
        == "cariad.remote.engine_start"
    )
    transport = NS(
        request=AsyncMock(
            return_value=NS(status=200, data={"userPromptProof": "test-proof"})
        )
    )
    engine = NS(auth=a, transport=transport)
    body = asyncio.run(build(engine, car, "engine_start", {}))
    assert body == {"spin": "test-pin", "securedActivationData": "test-proof"}
    transport.request.assert_awaited_once_with(
        "cariad",
        "PUT",
        f"/vehicle/v1/engine/{VIN}/userpromptproof",
        body={"spin": "test-pin"},
        explicit_action=True,
    )
    transport.request.return_value = NS(status=403, data={})
    with pytest.raises(ValueError, match="no start sent"):
        asyncio.run(build(engine, car, "engine_start", {}))
    car.impaired_capabilities.add("remoteEngineStart")
    with pytest.raises(ValueError, match="not supported"):
        asyncio.run(build(engine, car, "engine_start", {}))


def test_engine_transport_exact_method_path_and_body():
    executor, a = CARIADExecutor(), auth()
    prefix = f"/vehicle/v1/engine/{VIN}"
    assert executor.plan(a, "POST", prefix + "/stop", explicit_action=True).body is None
    assert (
        executor.plan(
            a,
            "PUT",
            prefix + "/userpromptproof",
            {"spin": "test"},
            explicit_action=True,
        ).method
        == "PUT"
    )
    for method, suffix, body, intent in (
        ("GET", "/start", None, False),
        ("POST", "/start", {"spin": "test"}, True),
        ("POST", "/stop", {}, True),
        ("POST", "/unknown", None, True),
    ):
        with pytest.raises(ValueError):
            executor.plan(a, method, prefix + suffix, body, explicit_action=intent)


def test_preheater_uses_own_state_and_historical_unique_id():
    car = V3Vehicle(VIN, "Audi", "Audi Q8", "q8", "DE")
    now = datetime.now(UTC)
    car.advertised_capabilities.add("auxiliaryHeating")
    observe_derived(
        car,
        NS(),
        {
            "climatisation": {
                "auxiliaryHeatingStatus": {
                    "value": {
                        "climatisationState": "heating",
                        "carCapturedTimestamp": now.isoformat(),
                        "climatisationDuration": 30,
                        "remainingClimateTime": 12,
                    }
                }
            }
        },
        now,
        _accept_observation,
    )
    coordinator = NS(
        async_add_listener=lambda cb: None,
        last_update_success=True,
        engine=NS(control_enabled=lambda *args: True),
    )
    switch = V3PreheaterSwitch(coordinator, car)
    assert switch.unique_id == VIN.lower() + "_switch_preheater_active"
    assert switch.available and switch.is_on is True
    assert car.readings["preheater_remaining"]["value"] == 12
    car.readings.clear()
    car.set_climate(
        "heating", now.isoformat(), route="test", observed_at=now, http_status=200
    )
    assert switch.is_on is None
