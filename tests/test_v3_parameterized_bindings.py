"""Parameterized route activation and reviewed PUT ownership."""

from pathlib import Path

import pytest

from custom_components.audiconnect.v3.command_parameters import (
    map_parameters,
    runtime_ready,
)
from custom_components.audiconnect.v3.development_profiles import (
    DevelopmentProfile,
    DevelopmentProfileError,
)
from custom_components.audiconnect.v3.registry import CapabilityRegistry, VehicleContext
from custom_components.audiconnect.v3.profile_store import restore_profile

ROOT = Path(__file__).resolve().parents[1] / "custom_components/audiconnect/v3"


def workspace():
    model = CapabilityRegistry.from_json_file(ROOT / "full_catalog.json")
    return DevelopmentProfile(
        model, VehicleContext(auth="auth0", region="DE"), cooldown_seconds=0
    )


def mark_worked(profile, capability, action, operation):
    attempt = profile.begin_test(capability, action, operation, now=1)
    profile.observe_http(attempt.sequence, 200)
    profile.confirm(attempt.sequence, worked=True, inspected_vehicle=True, now=2)
    profile.choose_working(capability, action, operation)


def test_bound_temperature_command_survives_restart_and_validates_inputs():
    p = workspace()
    op = p.add(
        {
            "id": "user.climate.start_with_settings.temp",
            "capability": "climate",
            "aspect": "start_with_settings",
            "family": "cariad",
            "method": "POST",
            "path": "/vehicle/v1/vehicles/{VIN}/climatisation/start",
            "variables": {"TARGET": "number"},
            "parameter_bindings": {"TARGET": "temp_c"},
            "body": {"targetTemperature": "{TARGET}"},
        }
    )
    mark_worked(p, "climate", "start_with_settings", op)
    restored = restore_profile(
        CapabilityRegistry.from_json_file(ROOT / "full_catalog.json"),
        p.discovery.context,
        p.snapshot(),
    )
    assert restored.active["climate.start_with_settings"] == op
    route = restored.custom[op]
    assert runtime_ready(route)
    assert map_parameters(route, {"temp_c": 22.5}) == {"TARGET": 22.5}
    with pytest.raises(ValueError):
        map_parameters(route, {"temp_c": 100})
    with pytest.raises(ValueError):
        map_parameters(route, {"temp_c": 22, "unexpected": 1})


def test_put_alias_preserves_code_owned_read_modify_write_handler():
    p = workspace()
    row = {
        "id": "user.charging.set_target_soc.reviewed",
        "capability": "charging",
        "aspect": "set_target_soc",
        "family": "cariad",
        "method": "PUT",
        "path": "/vehicle/v1/vehicles/{VIN}/charging/settings",
        "handler": "cariad.charging.settings",
    }
    op = p.add(row)
    assert p.registry.operations[op]["request_mode"] == "charging_settings_update"
    assert p.registry.operations[op]["delivery"] == "manual"
    mark_worked(p, "charging", "set_target_soc", op)
    restored = restore_profile(
        CapabilityRegistry.from_json_file(ROOT / "full_catalog.json"),
        p.discovery.context,
        p.snapshot(),
    )
    assert restored.active["charging.set_target_soc"] == op
    assert (
        restored.registry.operations[op]["request_mode"] == "charging_settings_update"
    )
    for override in (
        {"handler": "cariad.charging.mode"},
        {"body": {"targetSOC_pct": 100}},
        {"path": "/vehicle/v1/vehicles/{VIN}/charging/other"},
        {"handler": None},
    ):
        with pytest.raises(DevelopmentProfileError):
            workspace().add({**row, **override})


def test_shared_parameter_contracts_reject_bad_types_and_supply_ui_schema():
    from custom_components.audiconnect.v3.command_parameters import (
        parameter_schema,
        validate_parameter,
        temperature_celsius,
    )

    p = workspace()
    mode = parameter_schema(p.registry.operations["cariad.charging.mode"], {})
    assert mode["value"]["enum"] == ["manual", "timer"]
    assert validate_parameter("manual", mode["value"]) == "manual"
    with pytest.raises(ValueError):
        validate_parameter("invalid", mode["value"])
    soc = parameter_schema(p.registry.operations["cariad.charging.settings"], {})[
        "value"
    ]
    for invalid in (True, 21, 101, 85.0):
        with pytest.raises(ValueError):
            validate_parameter(invalid, soc)
    assert temperature_celsius({"temp_f": 68}, None) == pytest.approx(20)


def test_charge_mode_is_a_declarative_template_and_put_alias_inherits_it():
    p = workspace()
    original = p.registry.operations["cariad.charging.mode"]
    assert map_parameters(original, {"value": "timer"}) == {"VALUE": "timer"}
    with pytest.raises(ValueError):
        map_parameters(original, {"value": "unsupported"})
    with pytest.raises(ValueError):
        map_parameters(original, {"value": "timer", "extra": 1})
    ident = p.add(
        {
            "id": "user.charging.set_charge_mode.reviewed",
            "capability": "charging",
            "aspect": "set_charge_mode",
            "family": "cariad",
            "method": "PUT",
            "path": original["path"],
            "handler": "cariad.charging.mode",
        }
    )
    assert p.registry.operations[ident]["request_body"] == original["request_body"]
    assert map_parameters(p.registry.operations[ident], {"value": "manual"}) == {
        "VALUE": "manual"
    }
