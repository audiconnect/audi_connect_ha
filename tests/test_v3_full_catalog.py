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
        not op.get("delivery") == "existing_poll"
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
