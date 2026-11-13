"""Audi V2/V3 runtime switches preserve entity identity and HA presentation.

Only the migration's OWN previously disabled integration entities are restored.
Unimplemented V3 values may be unavailable, never given new identifiers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace as NS

from homeassistant.helpers import entity_registry as er

from custom_components.audiconnect.audi_entity import entity_unique_id
from custom_components.audiconnect.v3.attribute_contracts import contract_for
from custom_components.audiconnect.v3.entities import V3ReadOnlySensor
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3 import registry_lifecycle as lifecycle


class MemoryStore:
    state = {}

    def __init__(self, _hass, _version, key):
        self.key = key

    async def async_load(self):
        return dict(self.state.get(self.key, {}))

    async def async_save(self, data):
        self.state[self.key] = dict(data)


def test_registry_switch_never_disables_existing_entities(monkeypatch):
    MemoryStore.state = {
        "audiconnect_v3_abc_hidden_entities": {
            "entity_ids": [
                "sensor.old_v2_mileage",
                "sensor.user_disabled",
                "sensor.other_account",
            ],
        },
    }
    registry = NS(
        entries={
            "sensor.old_v2_mileage": NS(
                entity_id="sensor.old_v2_mileage",
                disabled_by=er.RegistryEntryDisabler.INTEGRATION,
            ),
            "sensor.user_disabled": NS(
                entity_id="sensor.user_disabled",
                disabled_by=er.RegistryEntryDisabler.USER,
            ),
            "sensor.still_working": NS(
                entity_id="sensor.still_working",
                disabled_by=None,
            ),
            "sensor.other_account": NS(
                entity_id="sensor.other_account",
                disabled_by=er.RegistryEntryDisabler.INTEGRATION,
            ),
        },
        updates=[],
    )

    def get(entity_id):
        return registry.entries.get(entity_id)

    def update(entity_id, *, disabled_by):
        assert disabled_by is None, "V3 must never disable a historical V2 entity"
        registry.entries[entity_id].disabled_by = disabled_by
        registry.updates.append(entity_id)

    registry.async_get = get
    registry.async_update_entity = update
    monkeypatch.setattr(lifecycle, "Store", MemoryStore)
    monkeypatch.setattr(lifecycle.er, "async_get", lambda _hass: registry)
    monkeypatch.setattr(
        lifecycle.er,
        "async_entries_for_config_entry",
        lambda _registry, _entry: [
            registry.entries[k]
            for k in (
                "sensor.old_v2_mileage",
                "sensor.user_disabled",
                "sensor.still_working",
            )
        ],
    )
    entry = NS(entry_id="abc")
    asyncio.run(lifecycle.async_apply_v3_entity_visibility(None, entry, True))
    asyncio.run(lifecycle.async_apply_v3_entity_visibility(None, entry, False))
    assert registry.updates == ["sensor.old_v2_mileage"]
    assert registry.entries["sensor.old_v2_mileage"].disabled_by is None
    assert (
        registry.entries["sensor.user_disabled"].disabled_by
        == er.RegistryEntryDisabler.USER
    )
    assert (
        registry.entries["sensor.other_account"].disabled_by
        == er.RegistryEntryDisabler.INTEGRATION
    )
    assert MemoryStore.state["audiconnect_v3_abc_hidden_entities"] == {"entity_ids": []}


def test_ha_entity_ids_survive_v2_to_v3_for_same_vehicle():
    car = V3Vehicle(
        vin="WAUZZZ4M0MD123456", name="Audi", model="Q8", model_family="", country="DE"
    )
    coordinator = NS(async_add_listener=lambda callback: None)
    for attr_id, entity_key in (
        ("stateOfCharge", "state_of_charge"),
        ("TOTAL_RANGE", "range"),
        ("UTC_TIME_AND_KILOMETER_STATUS", "mileage"),
    ):
        entity = V3ReadOnlySensor(
            coordinator,
            car,
            {"id": attr_id, "entity_key": entity_key, "capability": "vehicle_status"},
        )
        assert entity.unique_id == entity_unique_id(car, "sensor", entity_key)


def test_v2_source_remains_unmodified_and_v3_owns_categories():
    """V2 upstream keeps its own HA metadata; presentation change is V3-only."""
    root = Path(__file__).resolve().parents[1] / "custom_components" / "audiconnect"
    sensor = (root / "sensor.py").read_text().split("async def async_setup_entry", 1)[0]
    binary = (
        (root / "binary_sensor.py")
        .read_text()
        .split("async def async_setup_entry", 1)[0]
    )
    assert "entity_category=EntityCategory.DIAGNOSTIC" in sensor
    assert "entity_category=EntityCategory.DIAGNOSTIC" in binary
    for key in (
        "mileage",
        "service_inspection_time",
        "service_inspection_distance",
        "oil_change_time",
        "oil_change_distance",
        "car_type",
        "active_charging_profile_name",
        "charging_timer_enabled_count",
    ):
        assert contract_for(key).get("category") != "diagnostic"
    v3 = (root / "v3" / "entities.py").read_text()
    assert "_attr_entity_category = EntityCategory.DIAGNOSTIC" in v3
    assert 'if contract.get("category") == "diagnostic"' in v3


def test_exact_pilot_retirement_and_single_account_refresh_anchor(monkeypatch):
    """No display-name matching; retain registry records, V2 and user choices."""
    MemoryStore.state = {}
    vin = "wauzzz4m0md123456"
    other = "wauzzz4m0md123457"
    names = {
        "sensor.pilot": (vin + "_sensor_v3_climate_capability", None),
        "sensor.health_pilot": (vin + "_sensor_v3_poll_status", None),
        "sensor.v2": (vin + "_sensor_climatisation_state", None),
        "button.refresh": (vin + "_button_v3_refresh_cloud", None),
        "button.duplicate": (other + "_button_v3_refresh_cloud", None),
        "button.vehicle": (vin + "_button_refresh_vehicle_data", None),
        "sensor.user_pilot": (
            other + "_sensor_v3_climate_capability",
            er.RegistryEntryDisabler.USER,
        ),
        "sensor.other_entry": (vin + "_sensor_v3_poll_status", None),
        "button.old_start": (vin + "_button_start_climate_car_settings", None),
        "button.old_stop": (vin + "_button_stop_climate", None),
        "button.user_old": (
            other + "_button_stop_climate",
            er.RegistryEntryDisabler.USER,
        ),
    }
    entries = {
        eid: NS(entity_id=eid, unique_id=uid, disabled_by=disabled)
        for eid, (uid, disabled) in names.items()
    }
    updates = []

    def update(entity_id, *, disabled_by):
        updates.append(entity_id)
        entries[entity_id].disabled_by = disabled_by

    registry = NS(async_get=entries.get, async_update_entity=update)
    monkeypatch.setattr(lifecycle, "Store", MemoryStore)
    monkeypatch.setattr(lifecycle.er, "async_get", lambda _: registry)
    monkeypatch.setattr(
        lifecycle.er,
        "async_entries_for_config_entry",
        lambda *_: [v for k, v in entries.items() if k != "sensor.other_entry"],
    )
    engine = NS(
        vehicles={other: NS(inventory_present=True), vin: NS(inventory_present=True)}
    )
    entry = NS(entry_id="abc", runtime_data=NS(v3=engine))
    asyncio.run(lifecycle.async_apply_v3_entity_visibility(None, entry, True))
    assert engine.cloud_refresh_vin == vin
    assert set(updates) == {
        "sensor.pilot",
        "sensor.health_pilot",
        "button.duplicate",
        "button.old_start",
        "button.old_stop",
    }
    assert (
        entries["button.old_start"].disabled_by == er.RegistryEntryDisabler.INTEGRATION
    )
    assert (
        entries["button.old_stop"].disabled_by == er.RegistryEntryDisabler.INTEGRATION
    )
    assert entries["button.user_old"].disabled_by == er.RegistryEntryDisabler.USER
    assert entries["sensor.v2"].disabled_by is None
    assert entries["button.vehicle"].disabled_by is None
    assert entries["sensor.user_pilot"].disabled_by == er.RegistryEntryDisabler.USER
    assert entries["sensor.other_entry"].disabled_by is None
    # The anchor is stable for the current runtime, even if its VIN disappears.
    engine.vehicles[vin].inventory_present = False
    asyncio.run(lifecycle.async_apply_v3_entity_visibility(None, entry, True))
    assert engine.cloud_refresh_vin == vin
    # On reload the remaining car may inherit account refresh, restoring only
    # its migration-disabled button, never a user-disabled one.
    engine.cloud_refresh_vin = None
    asyncio.run(lifecycle.async_apply_v3_entity_visibility(None, entry, True))
    assert engine.cloud_refresh_vin == other
    assert entries["button.duplicate"].disabled_by is None
    assert entries["button.refresh"].disabled_by == er.RegistryEntryDisabler.INTEGRATION


def test_b10_compatibility_visibility_requires_evidence():
    from custom_components.audiconnect.v3.product_contract import compatibility_hidden

    car = NS(
        readings={
            "stateOfCharge": {"value": 77},
            "secondary_engine_type": {"value": "electric"},
        }
    )
    assert compatibility_hidden(car, "switch.climate_quick_control")
    assert compatibility_hidden(car, "sensor.secondary_engine_range_percent")
    assert not compatibility_hidden(car, "sensor.primary_engine_range_percent")
    assert not compatibility_hidden(car, "sensor.oil_level")
    car.readings["OIL_LEVEL_DIPSTICKS_PERCENTAGE"] = {
        "reason": "boolean_oil_level_use_binary"
    }
    assert compatibility_hidden(car, "sensor.oil_level")


def test_b10_electric_sources_resolve_by_role_and_capture():
    from custom_components.audiconnect.v3.product_contract import (
        projection_reading,
        engine_role,
    )
    from custom_components.audiconnect.v3.historical_catalog import ATTRIBUTES

    car = NS(
        readings={
            "stateOfCharge": {"value": 70, "captured": "2026-11-12T08:00:00Z"},
            "primary_engine_type": {"value": "electric"},
            "primaryEngineRangePercent": {
                "value": 77,
                "captured": "2026-11-12T09:00:00Z",
            },
            "secondary_engine_type": {"value": "gasoline"},
            "secondaryEngineRangePercent": {
                "value": 100,
                "captured": "2026-11-12T10:00:00Z",
            },
        }
    )
    assert engine_role(car, "primary") == "electric"
    assert projection_reading(car, ATTRIBUTES["stateOfCharge"])[1]["value"] == 77


def test_b10_registry_migration_preserves_user_choices_and_restores_owned_changes(
    monkeypatch,
):
    MemoryStore.state = {}
    vin = "wauzzz4m0md123456"
    car = NS(inventory_present=True, readings={})
    engine = NS(vehicles={vin: car})
    from homeassistant.const import EntityCategory

    def row(suffix, category=None, hidden=None, disabled=None):
        return NS(
            entity_id=suffix,
            unique_id=vin + "_" + suffix,
            entity_category=category,
            hidden_by=hidden,
            disabled_by=disabled,
        )

    door = row("binary_sensor_left_front_door_open", EntityCategory.DIAGNOSTIC)
    position = row("device_tracker_position", EntityCategory.DIAGNOSTIC)
    refresh = row("button_refresh_vehicle_data", EntityCategory.DIAGNOSTIC)
    cloud = row("button_v3_refresh_cloud", EntityCategory.DIAGNOSTIC)
    quick = row("switch_climate_quick_control")
    user = row("sensor_climatisation_state", hidden=er.RegistryEntryHider.USER)
    disabled = row("sensor_hybrid_range", disabled=er.RegistryEntryDisabler.USER)
    entries = {
        x.entity_id: x for x in (door, position, refresh, cloud, quick, user, disabled)
    }

    def update(entity_id, **changes):
        for key, value in changes.items():
            setattr(entries[entity_id], key, value)

    registry = NS(async_get=entries.get, async_update_entity=update)
    monkeypatch.setattr(lifecycle, "Store", MemoryStore)
    monkeypatch.setattr(lifecycle.er, "async_get", lambda _: registry)
    monkeypatch.setattr(
        lifecycle.er,
        "async_entries_for_config_entry",
        lambda *_: list(entries.values()),
    )
    entry = NS(entry_id="abc", runtime_data=NS(v3=engine))
    asyncio.run(lifecycle.async_apply_v3_entity_visibility(None, entry, True))
    assert door.entity_category is None
    assert position.entity_category is None
    assert refresh.entity_category is None
    assert cloud.entity_category == EntityCategory.DIAGNOSTIC
    assert quick.hidden_by == er.RegistryEntryHider.INTEGRATION
    assert quick.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert user.hidden_by == er.RegistryEntryHider.USER
    assert disabled.disabled_by == er.RegistryEntryDisabler.USER
    asyncio.run(lifecycle.async_apply_v3_entity_visibility(None, entry, False))
    assert door.entity_category == EntityCategory.DIAGNOSTIC
    assert position.entity_category == EntityCategory.DIAGNOSTIC
    assert refresh.entity_category == EntityCategory.DIAGNOSTIC
    assert quick.hidden_by is None
    assert quick.disabled_by is None
    assert user.hidden_by == er.RegistryEntryHider.USER
    assert disabled.disabled_by == er.RegistryEntryDisabler.USER


def test_registry_product_names_clean_unavailable_and_preserve_user_name(monkeypatch):
    MemoryStore.state = {}
    vin = "wauzzz4m0md123456"
    rows = [
        NS(
            entity_id="sensor." + key,
            unique_id=vin + "_sensor_" + key,
            original_name=old,
            name=user,
            entity_category=None,
            hidden_by=None,
            disabled_by=None,
        )
        for key, old, user in (
            ("last_trip", "Last trip (CARIAD)", None),
            (
                "next_climatisation_timer_local",
                "Next Climate Timer (Car Local Time)",
                None,
            ),
            ("hybrid_range", "Combined range (compatibility)", "My custom range"),
        )
    ]
    entries = {row.entity_id: row for row in rows}

    def update(entity_id, **changes):
        for key, value in changes.items():
            setattr(entries[entity_id], key, value)

    registry = NS(async_get=entries.get, async_update_entity=update)
    monkeypatch.setattr(lifecycle, "Store", MemoryStore)
    monkeypatch.setattr(lifecycle.er, "async_get", lambda _: registry)
    monkeypatch.setattr(lifecycle.er, "async_entries_for_config_entry", lambda *_: rows)
    entry = NS(
        entry_id="abc",
        runtime_data=NS(v3=NS(vehicles={vin: NS(readings={}, inventory_present=True)})),
    )
    asyncio.run(lifecycle.async_apply_v3_entity_visibility(None, entry, True))
    assert [row.original_name for row in rows] == [
        "Last trip",
        "Next climate timer",
        "Combined range",
    ]
    assert rows[2].name == "My custom range"
    assert rows[2].entity_id == "sensor.hybrid_range"
    asyncio.run(lifecycle.async_apply_v3_entity_visibility(None, entry, False))
    assert [row.original_name for row in rows] == [
        "Last trip (CARIAD)",
        "Next Climate Timer (Car Local Time)",
        "Combined range (compatibility)",
    ]
    assert rows[2].name == "My custom range"


def test_stateful_button_visibility_is_reversible_without_disabling_automations(
    monkeypatch,
):
    MemoryStore.state = {}
    vin = "wauzzz4m0md123456"
    car = V3Vehicle(vin, "Audi", "Audi Q8", "q8", "DE")
    car.readings["chargingState"] = {"value": "charging", "status": "verified"}
    engine = NS(vehicles={vin: car}, control_enabled=lambda *args: True)
    rows = [
        NS(
            entity_id="button." + key,
            unique_id=vin + "_button_" + key,
            hidden_by=hidden,
            disabled_by=None,
            entity_category=None,
        )
        for key, hidden in (
            ("start_charging_modern", None),
            ("stop_charging_modern", er.RegistryEntryHider.USER),
        )
    ]
    entries = {row.entity_id: row for row in rows}

    def update(entity_id, **changes):
        for key, value in changes.items():
            setattr(entries[entity_id], key, value)

    registry = NS(async_get=entries.get, async_update_entity=update)
    monkeypatch.setattr(lifecycle, "Store", MemoryStore)
    monkeypatch.setattr(lifecycle.er, "async_get", lambda _: registry)
    monkeypatch.setattr(lifecycle.er, "async_entries_for_config_entry", lambda *_: rows)
    entry = NS(entry_id="abc", runtime_data=NS(v3=engine))
    asyncio.run(lifecycle.async_apply_v3_entity_visibility(None, entry, True))
    assert rows[0].hidden_by == er.RegistryEntryHider.INTEGRATION
    assert rows[1].hidden_by == er.RegistryEntryHider.USER
    assert all(row.disabled_by is None for row in rows)
    car.readings.clear()
    asyncio.run(lifecycle.async_apply_v3_entity_visibility(None, entry, True))
    assert rows[0].hidden_by is None
    assert rows[1].hidden_by == er.RegistryEntryHider.USER
    assert all(row.disabled_by is None for row in rows)
