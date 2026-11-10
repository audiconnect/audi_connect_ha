"""Capability snapshot: no raw vehicle identifiers or private HAR fields."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

p = (
    Path(__file__).resolve().parents[1]
    / "custom_components/audiconnect/capability_catalog.py"
)
spec = importlib.util.spec_from_file_location("audi_capability_catalog", p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_three_way_verdict_and_no_ids():
    car = NS(
        capabilities=frozenset(["charging", "vehicleWakeUp", "SECRET_CUSTOM"]),
        impaired_capabilities=frozenset(["vehicleWakeUp"]),
        has_capability=lambda c: c in ["charging", "vehicleWakeUp", "SECRET_CUSTOM"],
    )
    data = m.snapshot_capabilities(car)
    assert data["groups"]["charging"]["charging"] == "reported"
    assert data["groups"]["remote"]["vehicleWakeUp"] == "reported_impaired"
    assert (
        data["groups"]["service"]["dealerAppointment"]
        == "not_reported_for_this_vehicle"
    )
    assert "SECRET_CUSTOM" not in repr(data)
    assert data["command_authorization_confirmed"] is False


def test_empty_capabilities_are_unknown():
    car = NS(
        capabilities=frozenset(),
        impaired_capabilities=frozenset(),
        has_capability=lambda c: None,
    )
    data = m.snapshot_capabilities(car)
    assert data["groups"]["charging"]["charging"] == "unknown"
