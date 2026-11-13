"""V3 control availability uses verified vehicle capability, not registry hiding."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "audiconnect"


def test_controls_are_created_only_after_independent_v3_verification():
    platforms = (ROOT / "v3" / "ha_platforms.py").read_text()
    assert "engine.control_enabled(" in platforms
    assert '"start")' in platforms and '"stop")' in platforms
    assert '"lock", "access")' in platforms
    assert '"unlock", "access")' in platforms
    # The V2 modules are merely entrypoint selectors, not V3 implementers.
    for domain in ("button", "switch", "lock"):
        source = (ROOT / f"{domain}.py").read_text()
        assert "from .v3.ha_platforms import setup as v3_setup" in source


def test_registry_never_hides_v2_entities_to_gate_v3_controls():
    src = (ROOT / "v3" / "registry_lifecycle.py").read_text()
    assert "async_entries_for_config_entry" in src
    assert "RegistryEntryDisabler.INTEGRATION" in src  # restore only
    assert "registry.async_update_entity(entity_id, disabled_by=None)" in src
    assert "retired_pilot_entity(unique_id) or duplicate_refresh" in src
    # Exact migration behaviour is exercised in test_v3_entity_identity_and_categories.


def test_native_charging_settings_require_vehicle_read_and_write_evidence():
    from types import SimpleNamespace as NS
    from custom_components.audiconnect.v3.ha_platforms import setup
    from custom_components.audiconnect.v3.vehicle import V3Vehicle

    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")
    allowed, listeners, offered = set(), [], []
    engine = NS(
        vehicles={car.vin.lower(): car},
        profiles={},
        control_enabled=lambda vin, action, *args: action in allowed,
    )
    coordinator = NS(engine=engine, async_add_listener=lambda cb: listeners.append(cb))
    entry = NS(
        entry_id="entry",
        runtime_data=NS(v3=engine, coordinator=coordinator),
        async_on_unload=lambda cb: None,
    )
    setup("number", entry, offered.extend)
    setup("select", entry, offered.extend)
    assert not offered
    allowed.update(("set_target_soc", "set_charge_mode"))
    for cb in listeners:
        cb()
    assert not offered
    car.readings.update(
        targetstateOfCharge={"value": 80}, availableChargeModes={"value": ["manual"]}
    )
    for cb in listeners:
        cb()
    assert {e.unique_id for e in offered} == {
        car.vin.lower() + "_number_target_state_of_charge",
        car.vin.lower() + "_select_charge_mode",
    }
    assert all(e.entity_category.value == "config" for e in offered)


def test_pending_control_reason_distinguishes_uncertain_from_inflight():
    from types import SimpleNamespace as NS
    from custom_components.audiconnect.v3.control_resolution import control_decision
    from custom_components.audiconnect.v3.command_journal import CommandRecord
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    from custom_components.audiconnect.v3.registry import CapabilityRegistry
    from custom_components.audiconnect.v3.vehicle import V3Vehicle

    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE", auth_family="auth0")
    car.readings["doorLockStatus"] = {"value": "locked"}
    auth = NS(uses_auth0=True, service=NS(_spin="1234"))
    catalog = CapabilityRegistry.from_json_file(ROOT / "v3" / "full_catalog.json")
    profile = DevelopmentProfile(catalog, car.context)
    record = CommandRecord.begin("access", "unlock", "cariad.access.unlock", 10)
    profile.track_command(record)
    pending = control_decision(car, profile, auth, "access", "lock")
    assert pending["reason"] == "vehicle_command_in_progress"
    assert pending["route_available"] is True
    assert pending["dispatch_ready"] is False
    record.state = "uncertain"
    result = control_decision(car, profile, auth, "access", "lock")
    assert result["status"] == "pending_review" and result["operation"] is None
    assert result["reason"] == "previous_vehicle_command_uncertain"


def test_charge_mode_select_keeps_verified_option_when_reported_mode_differs():
    from types import SimpleNamespace as NS
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    from custom_components.audiconnect.v3.entities import V3ChargeModeSelect
    from custom_components.audiconnect.v3.registry import CapabilityRegistry
    from custom_components.audiconnect.v3.vehicle import V3Vehicle

    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE", auth_family="auth0")
    catalog = CapabilityRegistry.from_json_file(ROOT / "v3" / "full_catalog.json")
    profile = DevelopmentProfile(catalog, car.context)
    route = "cariad.charging.mode"
    attempt = profile.begin_test("charging", "set_charge_mode", route, now=100)
    profile.engineering_record(attempt.sequence).requested_charge_mode = "manual"
    profile.observe_http(attempt.sequence, 200)
    profile.confirm(attempt.sequence, worked=True, inspected_vehicle=True, now=101)
    profile.choose_working("charging", "set_charge_mode", route)
    car.readings.update(
        availableChargeModes={"value": [], "status": "verified"},
        preferredChargeMode={"value": "timer", "status": "verified"},
    )
    engine = NS(profiles={car.vin.lower(): profile}, control_enabled=lambda *_: True)
    entity = V3ChargeModeSelect(NS(engine=engine), car)
    assert entity.options == ["manual"]
    assert entity.available
    assert entity.current_option is None
    assert entity.extra_state_attributes["last_reported_state"] == "timer"
