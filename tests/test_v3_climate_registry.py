"""Minimal synthetic catalog tests for the generic registry, not a second runtime."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "audiconnect" / "v3"
SPEC = importlib.util.spec_from_file_location("v3_registry_pure", ROOT / "registry.py")
assert SPEC is not None and SPEC.loader is not None
registry_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = registry_module
SPEC.loader.exec_module(registry_module)

CapabilityRegistry = registry_module.CapabilityRegistry
RouteEvidence = registry_module.RouteEvidence
VehicleContext = registry_module.VehicleContext
RegistryError = registry_module.RegistryError


def get_registry():
    return CapabilityRegistry(
        json.loads(
            (
                Path(__file__).resolve().parent / "fixtures/v3_climate_catalog.json"
            ).read_text()
        )
    )


def test_minimal_fixture_has_one_capability():
    model = get_registry()
    assert list(model.capabilities) == ["climate"]
    assert set(model.capabilities["climate"]) == {"status", "control"}


def test_modern_status_uses_same_existing_poll_not_second_get():
    result = get_registry().resolve(
        "climate", "status", VehicleContext(auth="auth0", region="EU")
    )
    assert result["operation"] == "cariad.climate.status.batch"
    assert result["reason"] == "existing_poll"


def test_legacy_maps_to_legacy_family_only():
    result = get_registry().resolve("climate", "status", VehicleContext(auth="legacy"))
    assert result["operation"] == "mbb.climate.status"
    assert all(name.startswith("mbb.") for name in result["available_operations"])


def test_modern_start_defaults_bodyless_and_stops_with_one_operation():
    model = get_registry()
    ctx = VehicleContext(auth="auth0", model_family="q8", vehicle_type="phev")
    assert (
        model.resolve("climate", "start", ctx)["operation"]
        == "cariad.climate.start.stored"
    )
    assert model.resolve("climate", "stop", ctx)["operation"] == "cariad.climate.stop"


def test_explicit_variant_can_override_default_but_not_auth_family():
    model = get_registry()
    ctx = VehicleContext(auth="auth0", region="EU")
    assert (
        model.resolve(
            "climate", "start", ctx, preferred="cariad.climate.start.vehicle_settings"
        )["operation"]
        == "cariad.climate.start.vehicle_settings"
    )
    with pytest.raises(RegistryError):
        model.resolve("climate", "start", ctx, preferred="mbb.climate.start")


def test_unknown_response_does_not_disable_a_capability():
    item = RouteEvidence()
    for status in (429, 502, 401, 200):
        item.record(status, usable=False, now=100)
    assert not item.suspended(101)
    assert item.readable == 0


def test_three_consecutive_404_quarantines_route_for_one_day():
    item = RouteEvidence()
    for tick in (1, 2, 3):
        item.record(404, usable=False, now=tick)
    assert item.suspended(4)
    model = get_registry()
    ctx = VehicleContext(auth="auth0")
    result = model.resolve(
        "climate",
        "status",
        ctx,
        {"cariad.climate.status.batch": item},
        now=4,
    )
    assert result["operation"] is None  # explicit probe remains manual
    assert "cariad.climate.status.probe" in result["available_operations"]
    assert (
        model.resolve(
            "climate",
            "status",
            ctx,
            {"cariad.climate.status.batch": item},
            now=86404,
        )["operation"]
        == "cariad.climate.status.batch"
    )


def test_readable_resets_quarantine_and_tracks_presence_only():
    item = RouteEvidence()
    for tick in (1, 2, 3):
        item.record(404, usable=False, now=tick)
    item.record(200, usable=True, now=4)
    assert item.readable == 1
    assert not item.suspended(5)


@pytest.mark.parametrize("field", ["climatisationStatus", "auxiliaryHeatingStatus"])
def test_both_cariad_response_variants_are_configured(field):
    sample = {"climatisation": {field: {"value": {"climatisationState": "off"}}}}
    assert get_registry().extract("cariad.climate.status.batch", sample)[0] == "off"


def test_scope_refinement_is_optional():
    raw = json.loads(
        (
            Path(__file__).resolve().parent / "fixtures/v3_climate_catalog.json"
        ).read_text()
    )
    raw["operations"]["cariad.climate.start.vehicle_settings"]["scope"] = {
        "region": "EU",
        "vehicle_type": "phev",
    }
    model = CapabilityRegistry(raw)
    assert (
        "cariad.climate.start.vehicle_settings"
        in model.resolve(
            "climate",
            "start",
            VehicleContext(auth="auth0", region="EU", vehicle_type="phev"),
        )["available_operations"]
    )
    assert (
        "cariad.climate.start.vehicle_settings"
        not in model.resolve(
            "climate",
            "start",
            VehicleContext(auth="auth0", region="CA", vehicle_type="phev"),
        )["available_operations"]
    )


def test_url_host_override_and_unsupported_methods_rejected():
    raw = json.loads(
        (
            Path(__file__).resolve().parent / "fixtures/v3_climate_catalog.json"
        ).read_text()
    )
    raw["operations"]["cariad.climate.status.batch"]["path"] = (
        "https://bad.invalid/{VIN}"
    )
    with pytest.raises(RegistryError):
        CapabilityRegistry(raw)
    raw = json.loads(
        (
            Path(__file__).resolve().parent / "fixtures/v3_climate_catalog.json"
        ).read_text()
    )
    raw["operations"]["cariad.climate.start.stored"]["method"] = "DELETE"
    with pytest.raises(RegistryError):
        CapabilityRegistry(raw)


def test_status_and_control_are_independently_optional():
    raw = json.loads(
        (
            Path(__file__).resolve().parent / "fixtures/v3_climate_catalog.json"
        ).read_text()
    )
    raw["capabilities"]["climate"].pop("control")
    model = CapabilityRegistry(raw)
    assert (
        model.resolve("climate", "start", VehicleContext(auth="auth0"))["operation"]
        is None
    )
    raw["capabilities"]["climate"] = {
        "control": get_registry().capabilities["climate"]["control"]
    }
    assert (
        CapabilityRegistry(raw).resolve(
            "climate", "status", VehicleContext(auth="auth0")
        )["operation"]
        is None
    )


def test_bodyless_start_default_is_q8_scoped_not_auth0_global():
    model = get_registry()
    assert (
        model.resolve(
            "climate", "start", VehicleContext(auth="auth0", model_family="")
        )["operation"]
        == "cariad.climate.start.vehicle_settings"
    )
    with pytest.raises(RegistryError):
        model.resolve(
            "climate",
            "start",
            VehicleContext(auth="auth0", model_family=""),
            preferred="cariad.climate.start.stored",
        )
