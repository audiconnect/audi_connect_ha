"""Generic control admin endpoints remain explicit and vehicle-scoped."""

from pathlib import Path
from custom_components.audiconnect.v3.registry import CapabilityRegistry, VehicleContext
from custom_components.audiconnect.v3.runtime import catalog_path


def test_generic_control_endpoints_exist_and_are_admin_only():
    path = (
        Path(__file__).resolve().parents[1]
        / "custom_components/audiconnect/v3/dashboard.py"
    )
    text = path.read_text()
    for name in ("control_routes", "control_test", "control_disable"):
        assert f'"audiconnect/v3/{name}"' in text
        assert f"def ws_{name}" in text
    assert text.count("@websocket_api.require_admin") >= 16


def test_control_action_catalog_includes_wakeup_and_lock_even_if_current_car_cannot_do_them():
    catalog = CapabilityRegistry.from_json_file(catalog_path())
    assert catalog.operations_for("remote", "wake") == ["cariad.remote.wake"]
    assert catalog.operations_for("access", "lock") == [
        "cariad.access.lock",
        "mbb.access.lock",
    ]
    assert (
        catalog.resolve("remote", "wake", VehicleContext(auth="legacy"))[
            "available_operations"
        ]
        == []
    )
