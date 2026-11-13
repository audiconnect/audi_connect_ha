"""Canonical product identity and read-only source projection regression."""

import json
from pathlib import Path
from types import SimpleNamespace as NS

from custom_components.audiconnect.v3.product_contract import (
    product_inventory,
    projection_descriptor,
    projection_reading,
    retired_pilot_entity,
    entity_key,
    entity_projection_report,
)
from custom_components.audiconnect.v3.historical_catalog import ATTRIBUTES

ROOT = Path(__file__).resolve().parents[1]
VIN = "wauzzz4m0md123456"


def test_product_contract_covers_v2_plus_only_deliberate_extensions():
    baseline = json.loads((ROOT / "docs/V2_V3_PARITY_BASELINE.json").read_text())
    historical = {row["id"] for row in baseline["entities"]}
    inventory = product_inventory()
    assert set(inventory["entities"]) == historical | {
        "sensor.discovery_coverage",
        "sensor.last_trip",
        "button.v3_refresh_cloud",
        "switch.climate_quick_control",
        "switch.charging",
        "switch.window_heating",
        "sensor.last_trip_distance",
        "sensor.last_trip_duration",
        "sensor.last_trip_average_speed",
        "sensor.last_trip_average_fuel_consumption",
        "sensor.last_trip_average_electric_consumption",
        "sensor.last_trip_fuel_consumption",
        "sensor.last_trip_electric_consumption",
        "sensor.longterm_trip_distance",
        "sensor.longterm_trip_duration",
        "sensor.longterm_trip_average_speed",
        "sensor.longterm_trip_average_fuel_consumption",
        "sensor.longterm_trip_average_electric_consumption",
        "sensor.longterm_trip_fuel_consumption",
        "sensor.longterm_trip_electric_consumption",
        "sensor.shortterm_trip_distance",
        "sensor.shortterm_trip_duration",
        "sensor.shortterm_trip_average_speed",
        "sensor.shortterm_trip_average_fuel_consumption",
        "sensor.shortterm_trip_average_electric_consumption",
        "sensor.shortterm_trip_fuel_consumption",
        "sensor.shortterm_trip_electric_consumption",
        "sensor.last_trip_zero_emission_distance",
        "sensor.shortterm_trip_zero_emission_distance",
        "sensor.longterm_trip_zero_emission_distance",
        "sensor.trip_history",
        "sensor.integration_status",
        "sensor.last_error",
        "binary_sensor.integration_problem",
        "sensor.door_status",
        "sensor.window_status",
        "binary_sensor.charging_ready",
    }
    assert all(
        "sensor." + key not in historical for key in inventory["retired_v3_sensors"]
    )
    for key in inventory["retired_v3_sensors"]:
        assert retired_pilot_entity(VIN + "_sensor_" + key)
    assert not retired_pilot_entity(VIN + "_sensor_charging_mode")
    for key in ("start_climate_car_settings", "stop_climate"):
        assert retired_pilot_entity(VIN + "_button_" + key)
        assert entity_key(VIN + "_button_" + key, "example") == "button." + key
    assert not retired_pilot_entity(VIN + "_button_start_charging_modern")


def test_actual_and_preferred_charging_modes_never_share_a_sensor():
    assert projection_descriptor(ATTRIBUTES["preferredChargeMode"]) is None
    descriptor = projection_descriptor(ATTRIBUTES["chargeMode"])
    car = NS(
        readings={
            "preferredChargeMode": {"value": "timer"},
            "chargeMode": {"value": "manual"},
        }
    )
    assert projection_reading(car, descriptor)[1]["value"] == "manual"
    car.readings.pop("chargeMode")
    assert projection_reading(car, descriptor)[1] is None


def test_historical_range_alias_resolves_same_identity_from_newest_capture():
    raw = ATTRIBUTES["TOTAL_RANGE"]
    assert projection_descriptor(ATTRIBUTES["range"])["id"] == raw["id"]
    car = NS(
        readings={
            "range": {"value": 600, "captured": "2026-01-01T12:00:00Z"},
            "TOTAL_RANGE": {"value": 590, "captured": "2026-01-01T11:00:00Z"},
        }
    )
    assert projection_reading(car, raw)[0] == "range"
    assert projection_reading(car, raw)[1]["value"] == 600


def test_registry_diagnostics_does_not_export_identifiers_or_values(monkeypatch):
    from homeassistant.helpers import entity_registry as er

    entries = [
        NS(
            unique_id=VIN + "_sensor_state_of_charge",
            entity_id="sensor.private_vehicle",
            domain="sensor",
            disabled_by=None,
        ),
        NS(
            unique_id=VIN + "_button_v3_climate_legacy",
            entity_id="button.private_name",
            domain="button",
            disabled_by=None,
        ),
    ]
    monkeypatch.setattr(er, "async_get", lambda _: NS())
    monkeypatch.setattr(er, "async_entries_for_config_entry", lambda *_: entries)
    engine = NS(
        projected_entities={"sensor": {entries[0].unique_id}},
        entry=NS(entry_id="secret"),
        hass=NS(data={}, states=NS(get=lambda _: NS(state="75"))),
    )
    report = entity_projection_report(engine)
    assert report["registered"] == 2 and report["projected"] == 1
    assert report["counts"] == {"projected": 1, "registered_not_projected": 1}
    data = json.dumps(report)
    for private in (VIN, "private_vehicle", "private_name", "secret", '"75"'):
        assert private not in data
    assert (
        entity_key(VIN + "_number_charge_profile_42_target_soc", "secret")
        == "number.charge_profile_{profile_id}_target_soc"
    )
    assert (
        entity_key("secret_api_requests_remaining", "secret")
        == "sensor.api_requests_remaining"
    )


def test_canonical_category_resolves_from_shared_metadata_and_product_contract():
    from custom_components.audiconnect.v3.product_contract import (
        canonical_entity_category,
    )
    from custom_components.audiconnect.v3.attribute_contracts import binary_contracts

    for key in binary_contracts():
        assert canonical_entity_category("binary_sensor." + key) is None
    for key in (
        "number.target_state_of_charge",
        "number.active_charging_profile_target_soc",
        "number.charge_profile_{profile_id}_target_soc",
        "select.charge_mode",
    ):
        assert canonical_entity_category(key) == "config"


def test_product_diagnostic_allowlist_is_explicit_and_vehicle_properties_are_not_diagnostics():
    from custom_components.audiconnect.v3.product_contract import (
        canonical_entity_category,
    )

    keys = product_inventory()["entities"]
    assert {k for k in keys if canonical_entity_category(k) == "diagnostic"} == {
        "sensor.discovery_coverage",
        "sensor.api_requests_remaining",
        "sensor.cloud_last_successful_poll",
        "sensor.vehicle_data_age",
        "sensor.vehicle_data_freshness",
        "button.v3_refresh_cloud",
        "sensor.integration_status",
        "sensor.last_error",
        "binary_sensor.integration_problem",
    }
    assert canonical_entity_category("device_tracker.position") is None
    assert canonical_entity_category("button.refresh_vehicle_data") is None


def test_every_builtin_product_identity_has_clean_functional_label():
    from custom_components.audiconnect.v3.product_contract import canonical_entity_name
    import re

    for key in product_inventory()["entities"]:
        label = canonical_entity_name(key)
        assert label, key
        assert not re.search(
            r"\(|\)|\b(cariad|mbb|compatibility|experimental|legacy|pilot|v2|v3)\b",
            label,
            re.I,
        ), (key, label)
        assert label[0].isupper(), (key, label)
    assert canonical_entity_name("sensor.last_trip") == "Last trip"
    assert (
        canonical_entity_name("sensor.next_climatisation_timer_local")
        == "Next climate timer"
    )
    assert canonical_entity_name("sensor.hybrid_range") == "Combined range"


def test_unavailable_reason_distinguishes_missing_trip_parking_and_stale_capture():
    from datetime import UTC, datetime, timedelta
    from custom_components.audiconnect.v3.product_contract import (
        entity_availability_reason,
    )
    from custom_components.audiconnect.v3.vehicle import V3Vehicle

    car = V3Vehicle(VIN, "Audi", "Test", "q8", "DE")
    engine = NS(vehicles={VIN.lower(): car})

    def reason(key):
        return entity_availability_reason(
            engine, VIN + "_example", key, "projected_unavailable", True
        )

    assert reason("sensor.last_trip_distance") == "trip_snapshot_missing"
    assert reason("button.flash_lights") == "parking_position_missing"
    car.readings["chargingState"] = {
        "value": "charging",
        "status": "readable_but_stale",
        "captured": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
    }
    assert reason("sensor.charging_state") == "vehicle_capture_stale"
    car.readings["chargingState"]["status"] = "invalid_value"
    assert reason("sensor.charging_state") == "invalid_vehicle_value"


def test_product_control_descriptors_reference_reviewed_catalog():
    from custom_components.audiconnect.v3.command_payloads import CLIMATE_FIELDS
    from custom_components.audiconnect.v3.historical_catalog import ATTRIBUTES
    from custom_components.audiconnect.v3.product_contract import (
        climate_switches,
        control_buttons,
    )
    from custom_components.audiconnect.v3.registry import CapabilityRegistry
    from custom_components.audiconnect.v3.runtime import catalog_path

    registry = CapabilityRegistry.from_json_file(catalog_path())
    buttons = control_buttons()
    switches = climate_switches()
    assert len(buttons) == 9
    assert len(switches) == 6
    for key, name, icon, capability, aspect in buttons:
        assert name and icon
        assert registry.operations_for(capability, aspect)
        assert "button." + key in product_inventory()["entities"]
    for key, attribute, field in switches:
        assert attribute in ATTRIBUTES
        assert field in CLIMATE_FIELDS
        assert "switch." + key in product_inventory()["entities"]


def test_historical_aliases_are_covered_by_product_sources():
    from custom_components.audiconnect.v3.historical_catalog import ALIAS_OF, ATTRIBUTES

    for alias, canonical in ALIAS_OF.items():
        attribute = ATTRIBUTES[canonical]
        key = f"{attribute['platform']}.{attribute['entity_key']}"
        sources = product_inventory()["entities"][key]["source_attributes"]
        assert alias in sources and canonical in sources


def test_missing_entity_reason_uses_native_sources_without_private_values():
    from custom_components.audiconnect.v3.product_contract import (
        entity_availability_reason,
    )
    from custom_components.audiconnect.v3.vehicle import V3Vehicle

    car = V3Vehicle(VIN, "Audi", "Test", "q8", "DE")
    engine = NS(vehicles={VIN.lower(): car})

    def reason(key):
        return entity_availability_reason(
            engine, VIN + "_example", key, "registered_not_projected", False
        )

    assert reason("sensor.shortterm_reset") == "trip_snapshot_missing"
    assert reason("sensor.remaining_charging_time") == "source_not_observed"
    car.readings["remainingClimatisationTime"] = {
        "value": None,
        "status": "invalid_value",
        "reason": "negative_duration",
    }
    assert reason("sensor.remaining_climatisation_time") == "negative_duration"


def test_alias_projection_uses_same_family_preference_as_observation_writer():
    from datetime import UTC, datetime, timedelta

    from custom_components.audiconnect.v3.registry import CapabilityRegistry
    from custom_components.audiconnect.v3.runtime import catalog_path

    now = datetime.now(UTC)
    registry = CapabilityRegistry.from_json_file(catalog_path())
    car = NS(
        readings={
            "TOTAL_RANGE": {
                "family": "eu_data_act",
                "value": 700,
                "captured": now.isoformat(),
            },
            "measuredTotalRange": {
                "family": "cariad",
                "value": 690,
                "captured": (now - timedelta(minutes=10)).isoformat(),
            },
        }
    )
    descriptor = ATTRIBUTES["TOTAL_RANGE"]
    assert projection_reading(car, descriptor, registry=registry, now=now)[0] == (
        "measuredTotalRange"
    )
    car.readings["measuredTotalRange"]["captured"] = (
        now - timedelta(hours=3)
    ).isoformat()
    assert projection_reading(car, descriptor, registry=registry, now=now)[0] == (
        "TOTAL_RANGE"
    )
