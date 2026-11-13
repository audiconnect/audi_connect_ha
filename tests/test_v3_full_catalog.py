"""Full registry includes historical capability groups and safely separated variants."""

import json
from pathlib import Path
from custom_components.audiconnect.v3.registry import CapabilityRegistry, VehicleContext

ROOT = Path(__file__).resolve().parents[1] / "custom_components/audiconnect/v3"
FULL = ROOT / "full_catalog.json"


def test_full_catalog_is_integration_runtime_entrypoint_and_not_climate_pilot():
    model = CapabilityRegistry(json.loads(FULL.read_text()))
    assert set(model.capabilities) >= {
        "climate",
        "charging",
        "vehicle_status",
        "access",
        "service",
        "mobility",
    }
    assert len(model.operations) >= 25
    assert len(model.capabilities["charging"]["status"]["operations"]) >= 3
    assert model.resolve("charging", "status", VehicleContext(auth="auth0"))[
        "available_operations"
    ]
    assert any(
        item.startswith("mbb.")
        for item in model.resolve("charging", "status", VehicleContext(auth="legacy"))[
            "available_operations"
        ]
    )
    assert all(
        o.get("delivery") == "manual"
        for o in model.operations.values()
        if o["method"] == "POST"
    )


def test_historical_controls_are_not_auto_executable_by_catalog_entry():
    raw = json.loads(FULL.read_text())
    model = CapabilityRegistry(raw)
    assert any(x["id"] == "lock" for x in raw["controls_reference"])
    assert model.operations_for("access", "lock") == [
        "cariad.access.lock",
        "mbb.access.lock",
    ]
    assert all(
        op.get("delivery") != "existing_poll"
        for op in model.operations.values()
        if op["method"] == "POST"
    )


def test_legacy_host_routes_never_selected_for_auth0():
    reg = CapabilityRegistry(json.loads(FULL.read_text()))
    q = reg.resolve(
        "charging", "status", VehicleContext(auth="auth0", model_family="q8")
    )
    assert all(
        reg.operations[op]["family"] == "cariad" for op in q["available_operations"]
    )


def test_runtime_read_templates_are_owned_by_the_builtin_catalog():
    from custom_components.audiconnect.v3.attribute_routes import read_variants
    from custom_components.audiconnect.v3.legacy_read_mappings import read_routes
    from custom_components.audiconnect.v3.registry import (
        builtin_read_path,
        selective_status_path,
    )

    model = CapabilityRegistry.from_json_file(FULL)
    routes = read_routes()
    assert list(routes) == [
        "charger",
        "climater",
        "vehicle_data",
        "preheater",
        "timer",
    ]
    assert set(routes.values()) == {
        op["path"]
        for op in model.operations.values()
        if op["family"] == "mbb" and op["method"] == "GET"
    }
    assert routes["climater"] == model.operations["mbb.climate.status.climater"]["path"]
    variants = read_variants("stateOfCharge", {})
    assert variants[0]["path"] == selective_status_path()
    assert variants[1]["path"] == model.operations["cariad.status.charging"]["path"]
    assert variants[2]["path"] == routes["charger"]
    # A mutable local registry must not change the reviewed built-in template.
    model.operations["cariad.climate.status.batch"]["path"] = "/local"
    assert builtin_read_path("cariad.climate.status.batch") == variants[0]["path"]
