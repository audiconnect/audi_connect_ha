"""Critical historical vehicle controls remain in V3 with manual evidence gate."""

import pytest
from custom_components.audiconnect.v3.registry import CapabilityRegistry, VehicleContext
from custom_components.audiconnect.v3.runtime import catalog_path
from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
from custom_components.audiconnect.v3.profile_store import restore_profile
from custom_components.audiconnect.v3.action_discovery import DiscoveryError


def test_critical_cariad_controls_registered_but_never_auto_triggered():
    model = CapabilityRegistry.from_json_file(catalog_path())
    for cap, act in (
        ("remote", "wake"),
        ("access", "lock"),
        ("access", "unlock"),
        ("charging", "start"),
        ("charging", "stop"),
        ("climate", "start"),
        ("climate", "stop"),
        ("climate", "window_heating_start"),
        ("climate", "window_heating_stop"),
    ):
        allowed = model.resolve(cap, act, VehicleContext(auth="auth0"))[
            "available_operations"
        ]
        assert allowed
        assert all(
            model.operations[op]["method"] == "POST"
            and model.operations[op]["delivery"] == "manual"
            for op in allowed
        )
    assert model.resolve("access", "lock", VehicleContext(auth="legacy"))[
        "available_operations"
    ] == ["mbb.access.lock"]


def test_wake_can_only_become_active_after_physical_user_review():
    model = CapabilityRegistry.from_json_file(catalog_path())
    p = DevelopmentProfile(model, VehicleContext(auth="auth0"), cooldown_seconds=0)
    route = "cariad.remote.wake"
    assert "remote.wake" not in p.active
    attempt = p.begin_test("remote", "wake", route, now=100)
    p.observe_http(attempt.sequence, 202)
    assert "remote.wake" not in p.active
    with pytest.raises(DiscoveryError):
        p.begin_test("remote", "wake", route, now=110)
    p.confirm(attempt.sequence, worked=True, inspected_vehicle=True, now=120)
    p.choose_working("remote", "wake", route)
    assert p.active["remote.wake"] == route
    restored = restore_profile(
        model, VehicleContext(auth="auth0"), p.snapshot(), cooldown_seconds=0
    )
    assert restored.active["remote.wake"] == route


def test_lock_routes_require_secret_not_stored_in_catalog():
    model = CapabilityRegistry.from_json_file(catalog_path())
    for op in ("cariad.access.lock", "cariad.access.unlock"):
        assert model.operations[op]["request_mode"] == "secure_spin"
        assert model.operations[op]["request_body"] == {"spin": "{SPIN}"}
