"""Explicit approval for protected and non-protected discovery."""

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import asyncio
import pytest
from custom_components.audiconnect.v3.action_discovery import (
    approval_group,
    validate_approval,
    DiscoveryError,
)
from custom_components.audiconnect.v3.engine import V3Engine
from custom_components.audiconnect.v3.registry import CapabilityRegistry
from custom_components.audiconnect.v3.runtime import catalog_path
from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
from custom_components.audiconnect.v3.vehicle import V3Vehicle

VIN = "WAUZZZ4M0MD123456"


@pytest.mark.parametrize(
    "cap,action,ident,group",
    [
        ("access", "unlock", "cariad.access.unlock", "spin"),
        ("remote", "engine_stop", "cariad.remote.engine_stop", "spin"),
        ("climate", "preheater_start", "cariad.climate.preheater_start", "spin"),
        ("remote", "wake", "cariad.remote.wake", "non_spin"),
        ("charging", "set_target_soc", "cariad.charging.settings", "non_spin"),
    ],
)
def test_approval_scope_is_server_derived(cap, action, ident, group):
    registry = CapabilityRegistry.from_json_file(catalog_path())
    op = registry.operations[ident]
    assert approval_group(cap, action, op) == group
    with pytest.raises(DiscoveryError):
        validate_approval(cap, action, op, None, has_spin=True)
    with pytest.raises(DiscoveryError):
        validate_approval(
            cap,
            action,
            op,
            "spin" if group == "non_spin" else "non_spin",
            has_spin=True,
        )
    if group == "spin":
        with pytest.raises(DiscoveryError):
            validate_approval(cap, action, op, group, has_spin=False)
    assert validate_approval(cap, action, op, group, has_spin=True) == group


def test_approved_discovery_rejects_missing_approval_before_any_command():
    registry = CapabilityRegistry.from_json_file(catalog_path())
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE", auth_family="auth0")
    obj = NS(
        require_vehicle=lambda vin: car,
        profiles={VIN.lower(): DevelopmentProfile(registry, car.context)},
        auth=NS(service=NS(_spin="test-pin")),
        test_action=AsyncMock(return_value={"sequence": 1}),
    )
    for wrong in (None, "non_spin", True):
        with pytest.raises(DiscoveryError):
            asyncio.run(
                V3Engine.approved_control_discovery(
                    obj,
                    VIN,
                    "unlock",
                    "cariad.access.unlock",
                    approval=wrong,
                    capability="access",
                )
            )
    obj.test_action.assert_not_awaited()
    result = asyncio.run(
        V3Engine.approved_control_discovery(
            obj,
            VIN,
            "unlock",
            "cariad.access.unlock",
            approval="spin",
            capability="access",
        )
    )
    assert result == {"sequence": 1}
    obj.test_action.assert_awaited_once_with(
        VIN, "unlock", "cariad.access.unlock", params=None, capability="access"
    )


def test_public_websocket_paths_cannot_bypass_approval():
    from pathlib import Path

    code = (
        Path(__file__).resolve().parents[1]
        / "custom_components/audiconnect/v3/dashboard.py"
    ).read_text()
    assert ".test_action(" not in code
    assert code.count(".approved_control_discovery(") == 1
    assert "audiconnect/v3/control_test" in code
    assert '"audiconnect/v3/test"' not in code


@pytest.mark.parametrize("expert", [False, True])
@pytest.mark.parametrize(
    "action,route",
    [
        ("start_with_settings", "cariad.climate.start.vehicle_settings"),
        ("set_settings", "cariad.climate.settings"),
    ],
)
def test_climate_discovery_requires_typed_temperature_before_dispatch(
    expert, action, route
):
    from custom_components.audiconnect.v3.command_engine import CommandEngine
    from custom_components.audiconnect.v3.read_discovery import user_test_candidates
    from custom_components.audiconnect.v3.command_parameters import (
        parameter_schema,
    )

    registry = CapabilityRegistry.from_json_file(catalog_path())
    car = V3Vehicle(VIN, "Audi", "", "", "DE", auth_family="auth0")
    car.advertised_capabilities.add("climatisation")
    profile = DevelopmentProfile(registry, car.context)
    prepare = AsyncMock(side_effect=RuntimeError("prepared"))
    obj = NS(
        require_vehicle=lambda vin: car,
        profiles={VIN.lower(): profile},
        auth=NS(uses_auth0=True, service=NS(_spin="")),
        _prepare_command=prepare,
    )
    candidate = user_test_candidates(obj, car, profile, include_verified=expert)[
        f"climate.{action}"
    ]
    assert candidate["operation"] == route
    assert candidate["parameter_schema"] == parameter_schema(
        registry.operations[route], {}, discovery_parameters=["temp_c"]
    )
    assert candidate["parameter_schema"] == {
        "temp_c": {
            "type": "number",
            "minimum": 15,
            "maximum": 30,
            "label": "Target temperature (°C)",
            "required": True,
        }
    }

    def execute(params):
        return asyncio.run(
            CommandEngine._test_action_once(
                obj,
                VIN,
                action,
                route,
                params=params,
                capability="climate",
                guided=True,
                expert=expert,
                approval="non_spin",
            )
        )

    for invalid in (
        {},
        {"temp_c": True},
        {"temp_c": 31},
        {"temp_c": 22, "spin": "1234"},
    ):
        with pytest.raises(ValueError):
            execute(invalid)
    prepare.assert_not_awaited()
    assert profile.discovery.active_attempt is None
    with pytest.raises(RuntimeError, match="prepared"):
        execute({"temp_c": 22})
    prepare.assert_awaited_once_with(car, route, {"temp_c": 22})


def test_discovery_can_extend_existing_command_by_catalog_metadata_only():
    import json

    from custom_components.audiconnect.v3.read_discovery import user_test_candidates
    from custom_components.audiconnect.v3.registry import RegistryError

    raw = json.loads(catalog_path().read_text())
    node = raw["capabilities"]["charging"]["control"]["set_target_soc"]
    node["discovery"] = {
        "label": "Set charge target",
        "instructions": "Check the selected target changed.",
        "order": 85,
        "parameters": ["value"],
    }
    registry = CapabilityRegistry(raw)
    car = V3Vehicle(VIN, "Audi", "", "", "DE", auth_family="auth0")
    car.advertised_capabilities.add("charging")
    car.readings["targetstateOfCharge"] = {"value": 80}
    engine = NS(auth=NS(uses_auth0=True, service=NS(_spin="")))
    profile = DevelopmentProfile(registry, car.context)
    for expert in (False, True):
        candidate = user_test_candidates(engine, car, profile, include_verified=expert)[
            "charging.set_target_soc"
        ]
        assert candidate["operation"] == "cariad.charging.settings"
        assert candidate["label"] == node["discovery"]["label"]
        assert candidate["instructions"] == node["discovery"]["instructions"]
        assert candidate["parameter_schema"]["value"]["required"]
        assert candidate["parameter_schema"]["value"]["maximum"] == 100

    node["discovery"]["parameters"] = ["unknown_parameter"]
    with pytest.raises(RegistryError, match="Unknown discovery parameter"):
        CapabilityRegistry(raw)
