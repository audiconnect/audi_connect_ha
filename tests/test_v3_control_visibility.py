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

    record = CommandRecord.begin("access", "unlock", "cariad.access.unlock", 10)
    profile = NS(discovery=NS(disabled=set(), _active=None), last_command=record)
    assert (
        control_decision(None, profile, None, "access", "lock")["reason"]
        == "vehicle_command_in_progress"
    )
    record.state = "uncertain"
    result = control_decision(None, profile, None, "access", "lock")
    assert result["status"] == "pending_review" and result["operation"] is None
    assert result["reason"] == "previous_vehicle_command_uncertain"
