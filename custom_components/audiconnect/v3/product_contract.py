"""Canonical HA product identity, source resolution and presentation policy."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from .historical_catalog import ATTRIBUTES, ALIAS_OF

CORE_STATUS_KINDS = ("cloud", "age", "freshness", "discovery")


@lru_cache(maxsize=1)
def product_inventory():
    return json.loads(Path(__file__).with_name("product_entities.json").read_text())


def control_buttons():
    """Native button descriptors from the HA product contract."""
    return tuple(
        (
            key.removeprefix("button."),
            definition["name"],
            command["icon"],
            command["capability"],
            command["aspect"],
        )
        for key, definition in product_inventory()["entities"].items()
        if (command := definition.get("command")) is not None
        and key.startswith("button.")
    )


def climate_switches():
    """Native configuration switches reference the same product contract."""
    return tuple(
        (key.removeprefix("switch."), setting["attribute"], setting["field"])
        for key, definition in product_inventory()["entities"].items()
        if (setting := definition.get("climate_setting")) is not None
        and key.startswith("switch.")
    )


def retired_sensor_keys():
    return frozenset(product_inventory()["retired_v3_sensors"])


def retired_pilot_entity(unique_id: str) -> bool:
    """Match exact retired V3-only pilot identities."""
    if not isinstance(unique_id, str):
        return False
    vin, separator, suffix = unique_id.partition("_")
    if not separator or len(vin) != 17 or not vin.isalnum():
        return False
    if suffix.startswith("sensor_"):
        return suffix.removeprefix("sensor_") in retired_sensor_keys()
    if suffix.startswith("binary_sensor_"):
        return suffix.removeprefix("binary_sensor_") in product_inventory().get(
            "retired_v3_binary_sensors", ()
        )
    if suffix.startswith("button_"):
        return suffix.removeprefix("button_") in product_inventory().get(
            "retired_legacy_buttons", ()
        )
    return False


def account_cloud_refresh_vin(vehicles):
    """Use one stable existing VIN identity per account, preserving single-car IDs."""
    return next(
        (
            vin
            for vin in sorted(vehicles)
            if getattr(vehicles[vin], "inventory_present", True)
        ),
        None,
    )


def projection_descriptor(attribute):
    """Only historical product properties and explicit local extensions project.

    Raw preferredChargeMode is a configuration source for select.charge_mode,
    not the actual in-progress chargeMode shown by sensor.charging_mode.
    """
    if attribute.get("local"):
        return attribute
    ident = attribute["id"]
    if ident in product_inventory()["raw_only_attributes"]:
        return None
    canonical = ATTRIBUTES.get(ALIAS_OF.get(ident, ident), attribute)
    key = f"{canonical['platform']}.{canonical['entity_key']}"
    return canonical if key in product_inventory()["entities"] else None


def control_reading(vehicle, attribute, *, registry=None):
    """Use the Status selector for a control's exact reported attribute."""
    from .attribute_runtime import select_reading

    _, row = select_reading(
        vehicle, (attribute,), attribute, registry=registry, allow_last_known=True
    )
    return row or {}


def control_projection(profile, attribute, reading, *, now=None):
    """Effective HA control state, never a physical or authorization proof.

    Keep actual observations separate from bounded command intent. A newer
    valid capture wins, even when contrary to the request. After an accepted
    mutation, an older sample is historical, not the effective control state.
    """
    from datetime import UTC, datetime

    from .attribute_runtime import _valid_capture, last_known_observation
    from .command_readback import (
        accepted_projection_attributes,
        latest_projection_command,
        optimistic_expiry,
        requested_projection,
    )
    from .freshness import timestamp_is_fresh

    now = now or datetime.now(UTC)
    reading = reading or {}
    known = last_known_observation(reading)
    record = latest_projection_command(profile, attribute)
    charging = attribute == "chargingState"
    expiry = optimistic_expiry(record)
    stamp = _valid_capture(known.get("captured"), now)
    observed_stamp = _valid_capture(reading.get("captured"), now)
    if (
        expiry is not None
        and record.started_at <= now.timestamp() < expiry
        and (stamp is None or stamp.timestamp() <= record.started_at)
        and (observed_stamp is None or observed_stamp.timestamp() <= record.started_at)
        and record.readback_observed_at is None
        and record.readback_mismatch_at is None
    ):
        requested = requested_projection(record, attribute)
        if requested is not None:
            return requested, "optimistic"
    # A known HTTP acceptance may have changed the vehicle. Keep this
    # boundary after expiry, restart or a subsequent rejected attempt.
    accepted = next(
        (
            row
            for row in reversed(getattr(profile, "command_journal", ()))
            if attribute in accepted_projection_attributes(row)
            and row.started_at <= now.timestamp()
        ),
        None,
    )
    historical = accepted is not None and (
        stamp is None or stamp.timestamp() <= accepted.started_at
    )
    if historical and not charging:
        return None, "unknown"
    # A newer explicit invalid cabin-climate capture cannot be shown as
    # a current HVAC mode. Keep the historical value in control attributes.
    if known.get("value") is None or (
        attribute == "climate" and reading.get("status") == "invalid_value"
    ):
        return None, "unknown"
    return known["value"], (
        "vehicle"
        if not historical
        and known is reading
        and timestamp_is_fresh(known.get("captured"), now)
        else "last_known_vehicle"
    )


def projection_reading(vehicle, attribute, *, registry=None, now=None):
    """Resolve only declared same-semantic historical aliases, never by order."""
    from .attribute_runtime import retained_status_field, select_reading

    ident = attribute["id"]
    canonical = ALIAS_OF.get(ident, ident)
    key = attribute.get("entity_key") or ATTRIBUTES.get(canonical, {}).get("entity_key")
    platform = attribute.get("platform") or ATTRIBUTES.get(canonical, {}).get(
        "platform"
    )
    definition = product_inventory()["entities"].get(f"{platform}.{key}", {})
    declared = definition.get("source_attributes", ())
    # Raw/configuration-only readings must not become alternate sensor values.
    sources = list(declared) if canonical in declared else [canonical]
    if key == "range":
        sources.extend(("hybridRange", "measuredTotalRange"))
    if key == "state_of_charge":
        sources.extend(electric_soc_sources(vehicle))
    if key in ("primary_engine_range", "secondary_engine_range"):
        slot = key.split("_", 1)[0]
        role = engine_role(vehicle, slot)
        other = engine_role(vehicle, "secondary" if slot == "primary" else "primary")
        # An aggregate role value cannot identify either of two engines
        # of the same type. Keep the slot-specific readings in that case.
        if role == "electric" and other != role:
            sources.extend(("measuredElectricRange", "batteryElectricRange"))
        elif role == "fuel" and other != role:
            sources.append("measuredFuelRange")
    if key == "tank_level":
        sources.extend(
            role + "EngineFuelLevel"
            for role in ("primary", "secondary")
            if engine_role(vehicle, role) == "fuel"
        )
    if key == "mileage":
        sources.append("maintenanceMileage")
    selected, row = select_reading(
        vehicle,
        sources,
        canonical,
        registry=registry,
        now=now,
        allow_last_known=retained_status_field(canonical),
    )
    if key in ("remaining_charging_time", "charging_complete_time"):
        from .attribute_runtime import _capture_in_utc
        from .vehicle import charging_active

        charging = vehicle.readings.get("chargingState", {})
        stamp = _capture_in_utc(charging.get("captured"))
        duration = vehicle.readings.get("remainingChargingTime", {})
        duration_stamp = _capture_in_utc(duration.get("captured"))
        if (
            stamp is not None
            and charging.get("status") != "invalid_value"
            and charging_active(charging.get("value")) is False
            and (duration_stamp is None or stamp >= duration_stamp)
        ):
            return canonical, {
                **{
                    key: charging.get(key)
                    for key in ("captured", "observed", "family", "operation")
                },
                "value": None,
                "status": "invalid_value",
                "reason": "charging_not_active",
                "derived_from": "chargingState",
            }
    return (selected, row) if row is not None else (ident, vehicle.readings.get(ident))


def entity_key(unique_id, entry_id):
    """Return a product contract key, never a raw VIN or user-defined name."""
    if unique_id == f"{entry_id}_api_requests_remaining":
        return "sensor.api_requests_remaining"
    if not isinstance(unique_id, str) or len(unique_id) < 20:
        return None
    vin, sep, suffix = unique_id.partition("_")
    if not sep or len(vin) != 17 or not vin.isalnum():
        return None
    for platform in (
        "binary_sensor",
        "device_tracker",
        "sensor",
        "button",
        "switch",
        "number",
        "select",
        "climate",
        "lock",
    ):
        prefix = platform + "_"
        if not suffix.startswith(prefix):
            continue
        key = suffix[len(prefix) :]
        if platform in ("sensor", "binary_sensor") and key.startswith("v3_custom_"):
            return f"{platform}.custom_attribute"
        if platform == "number" and re.fullmatch(
            r"charge_profile_[0-9]+_target_soc", key
        ):
            return "number.charge_profile_{profile_id}_target_soc"
        candidate = f"{platform}.{key}"
        if candidate in product_inventory()["entities"]:
            return candidate
        if platform == "sensor" and key in retired_sensor_keys():
            return candidate
        if platform == "binary_sensor" and key in product_inventory().get(
            "retired_v3_binary_sensors", ()
        ):
            return candidate
        if platform == "button" and key in product_inventory().get(
            "retired_legacy_buttons", ()
        ):
            return candidate
        return None
    return None


def entity_availability_reason(engine, uid, key, status, state_present):
    """Bounded evidence for unavailable entities; no private values or IDs."""
    if status == "projected":
        return "available"
    if status == "projected_unknown":
        if key == "climate.climatisation":
            return "climate_actual_state_unknown"
        if key == "select.charge_mode":
            return "charge_mode_reported_outside_writable_options"
        return "state_unknown"
    if status == "disabled":
        return "registry_disabled"
    not_offered = status == "registered_not_projected"
    if not state_present and not not_offered:
        return "state_not_created"
    car = getattr(engine, "vehicles", {}).get(uid.split("_", 1)[0].lower())
    if car is None or key is None:
        return "not_offered_by_runtime" if not_offered else "runtime_state_unavailable"
    if not getattr(car, "inventory_present", True):
        return "vehicle_not_in_inventory"
    if key == "sensor.model" and not car.model:
        return "manufacturer_identity_missing"
    if getattr(engine, "last_cloud_poll_succeeded", None) is False:
        return "cloud_poll_failed"
    if (
        key
        in (
            "button.flash_lights",
            "device_tracker.position",
            "sensor.park_time",
            "sensor.parked_in",
            "sensor.parking_address",
            "sensor.position_last_updated",
        )
        and car.position is None
    ):
        return "parking_position_missing"
    if key == "sensor.parking_address":
        from .parking import geocoding_endpoint

        if geocoding_endpoint(getattr(engine, "entry", None)) is None:
            return "reverse_geocoding_disabled"
        return "parking_address_not_resolved"
    # The same control decision as the actual command resolver, not an
    # independent permission model. Never export a custom route name.
    profile = getattr(engine, "profiles", {}).get(car.vin.lower())
    if profile is not None and key.startswith(
        ("button.", "climate.", "switch.", "lock.", "number.", "select.")
    ):
        from .control_resolution import control_decision

        controls = [
            (cap, action)
            for button, _, _, cap, action in control_buttons()
            if key == "button." + button
        ]
        if key == "climate.climatisation":
            controls = [
                ("climate", action)
                for action in ("start", "stop", "start_with_settings")
            ]
        if key == "lock.lock":
            controls = [("access", "lock"), ("access", "unlock")]
        elif key == "select.charge_mode":
            controls = [("charging", "set_charge_mode")]
        elif key == "number.target_state_of_charge":
            if car.readings.get("targetstateOfCharge", {}).get("value") is None:
                return "target_soc_not_observed"
            controls = [("charging", "set_target_soc")]
        elif key == "switch.preheater_active":
            controls = [
                ("climate", "preheater_start"),
                ("climate", "preheater_stop"),
            ]
        stateful = (
            stateful_controls().get(key.removeprefix("switch."))
            if key.startswith("switch.")
            else None
        )
        if stateful:
            controls = [
                (stateful["capability"], stateful[action]) for action in ("on", "off")
            ]
        if controls:
            decisions = [
                control_decision(car, profile, engine.auth, cap, action)
                for cap, action in controls
            ]
            if not any(row["operation"] for row in decisions):
                reasons = {row["reason"] or row["status"] for row in decisions}
                return (
                    next(iter(reasons))
                    if len(reasons) == 1
                    else "control_routes_blocked"
                )
            return "control_eligible_entity_state_unavailable"
    definition = product_inventory()["entities"].get(key, {})
    metric = definition.get("trip_metric")
    scope = (
        metric["source"]
        if metric
        else key.removeprefix("sensor.")
        if key
        in (
            "sensor.last_trip",
            "sensor.shortterm_current",
            "sensor.longterm_current",
            "sensor.shortterm_reset",
            "sensor.longterm_reset",
        )
        else None
    )
    if scope and not car.trips.get(scope):
        return "trip_snapshot_missing"
    if metric and trip_metric_value(car, key.removeprefix("sensor.")) is None:
        return "trip_metric_missing"
    from .freshness import reading_availability_reason

    sources = definition.get("source_attributes", ())
    found = False
    for ident in sources:
        attribute = ATTRIBUTES.get(ident)
        if not attribute:
            continue
        _, reading = projection_reading(
            car, attribute, registry=getattr(engine, "registry", None)
        )
        if not reading:
            continue
        found = True
        reason = reading_availability_reason(reading)
        if reason != "available":
            return reason
    if sources and not found:
        if key == "sensor.next_climatisation_timer_local":
            count = car.readings.get("climatisation_timer_enabled_count", {})
            if count.get("status") == "invalid_value":
                return "incomplete_timer_data"
            enabled = count.get("value")
            if type(enabled) is int:
                return (
                    "no_enabled_climatisation_timer"
                    if enabled == 0
                    else "next_single_timer_not_determined"
                )
        return "source_not_observed"
    return "not_offered_by_runtime" if not_offered else "runtime_state_unavailable"


def entity_projection_report(engine):
    """Separate registry records, offered entities and HA state availability.

    No entity IDs, unique IDs, VINs or names leave this function.
    Only allowlisted technical HA state values are included.
    Unknown registry keys get a suffix fingerprint for a later exact migration.
    """
    from collections import Counter
    from .attribute_runtime import _capture_in_utc
    from .capability_status import diagnostic_ha_state, diagnostic_route_label

    projected = {uid for group in engine.projected_entities.values() for uid in group}
    report = {"projected": len(projected), "registry_available": False, "rows": []}
    if not hasattr(engine.hass, "states") or not hasattr(engine.hass, "data"):
        return report
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(engine.hass)
    entries = er.async_entries_for_config_entry(registry, engine.entry.entry_id)
    counts = Counter()
    rows = []
    vehicle_slots = {
        vin.lower(): index
        for index, vin in enumerate(getattr(engine, "vehicles", {}), 1)
    }
    catalog = getattr(engine, "registry", None)
    for entry in entries:
        uid = entry.unique_id
        key = entity_key(uid, engine.entry.entry_id)
        platform = entry.domain
        offered = uid in projected
        state = engine.hass.states.get(entry.entity_id)
        state_present = state is not None
        unavailable = state_present and state.state == "unavailable"
        unknown = state_present and state.state == "unknown" and platform != "button"
        disabled = entry.disabled_by
        status = (
            "disabled"
            if disabled is not None
            else "projected_unknown"
            if offered and unknown
            else "projected"
            if offered and state_present and not unavailable
            else "projected_unavailable"
            if offered
            else "registered_not_projected"
        )
        counts[status] += 1
        attrs = getattr(state, "attributes", {})
        source = attrs.get("state_source")
        captured = _capture_in_utc(attrs.get("vehicle_captured"))
        operation = attrs.get("source_operation")
        row = {
            "vehicle_slot": vehicle_slots.get(uid.split("_", 1)[0].lower()),
            "platform": platform,
            "contract_key": key or "unrecognized_registry_key",
            "status": status,
            "offered_by_runtime": offered,
            "state_present": state_present,
            "ha_state_kind": "missing"
            if not state_present
            else state.state
            if state.state in ("unknown", "unavailable")
            else "known",
            "ha_projected_state": diagnostic_ha_state(key, state, catalog)
            if key
            else None,
            "ha_state_source": source
            if source in ("vehicle", "optimistic", "last_known_vehicle", "unknown")
            else None,
            "ha_vehicle_captured": captured.isoformat() if captured else None,
            "ha_source_operation": diagnostic_route_label(operation, catalog)
            if catalog is not None and isinstance(operation, str)
            else None,
            "availability_reason": (
                "button_no_press_timestamp"
                if platform == "button"
                and status == "projected"
                and state.state == "unknown"
                else entity_availability_reason(engine, uid, key, status, state_present)
            ),
            "disabled_by": getattr(disabled, "value", None),
            "entity_category": getattr(
                getattr(entry, "entity_category", None), "value", None
            ),
            "hidden_by": getattr(getattr(entry, "hidden_by", None), "value", None),
            "original_icon": getattr(entry, "original_icon", None),
            "device_class": getattr(state, "attributes", {}).get("device_class"),
            "state_class": getattr(state, "attributes", {}).get("state_class"),
            "unit_of_measurement": getattr(state, "attributes", {}).get(
                "unit_of_measurement"
            ),
            "expected_category": canonical_entity_category(key)
            if key in product_inventory()["entities"]
            else None,
            "category_drift": bool(
                key in product_inventory()["entities"]
                and getattr(getattr(entry, "entity_category", None), "value", None)
                != canonical_entity_category(key)
            ),
        }
        if key is None:
            suffix = uid.split("_", 1)[-1] if isinstance(uid, str) else ""
            row["key_fingerprint"] = hashlib.sha256(suffix.encode()).hexdigest()[:16]
        rows.append(row)
    report.update(
        registry_available=True,
        registered=len(entries),
        counts=dict(counts),
        offered_including_disabled=len(projected),
        offered_enabled=sum(
            row["offered_by_runtime"] and row["status"] != "disabled" for row in rows
        ),
        rows=rows[:250],
        truncated=len(rows) > 250,
    )
    return report


def compatibility_hidden(vehicle, key):
    """Hide redundant representations only with supporting semantic evidence."""
    readings = getattr(vehicle, "readings", {})
    if key in product_inventory()["default_hidden_compatibility"]:
        if key == "sensor.hybrid_range":
            return any(
                readings.get(x, {}).get("value") is not None
                for x in ("TOTAL_RANGE", "range")
            )
        return True
    if key == "sensor.oil_level":
        return (
            readings.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE", {}).get("reason")
            == "boolean_oil_level_use_binary"
        )
    for role in ("primary", "secondary"):
        if key != "sensor." + role + "_engine_range_percent":
            continue
        if engine_role(vehicle, role) == "electric":
            return readings.get("stateOfCharge", {}).get("value") is not None
        if engine_role(vehicle, role) == "fuel":
            # Never assume generic engine SOC means fuel; require explicit fuel value.
            engine_fuel = readings.get(role + "EngineFuelLevel", {}).get("value")
            engine_percent = readings.get(role + "EngineRangePercent", {}).get("value")
            return (
                type(engine_fuel) in (int, float)
                and engine_fuel == engine_percent
                and any(
                    readings.get(x, {}).get("value") is not None
                    for x in ("TANK_LEVEL_IN_PERCENTAGE", "tank_level")
                )
            )
    return False


def canonical_entity_category(key):
    """Resolve presentation from the authoritative product/metadata contracts."""
    from .attribute_contracts import binary_contract_for, contract_for

    definition = product_inventory()["entities"].get(key, {})
    platform, _, entity = key.partition(".")
    if definition.get("metadata_contract"):
        if platform == "binary_sensor":
            return binary_contract_for(entity).get("category")
        if platform == "sensor":
            return contract_for(entity).get("category")
    return definition.get("category")


def electric_soc_sources(vehicle):
    readings = vehicle.readings
    sources = [
        role + "EngineRangePercent"
        for role in ("primary", "secondary")
        if readings.get(role + "_engine_type", {}).get("value") == "electric"
    ]
    from .vehicle import powertrain_identity

    if powertrain_identity(vehicle)["value"] in ("electric", "hybrid", "phev"):
        sources.append("measuredElectricSOC")
    return sources


def engine_role(vehicle, role):
    value = vehicle.readings.get(role + "_engine_type", {}).get("value")
    return (
        "electric"
        if value == "electric"
        else "fuel"
        if value in ("gasoline", "diesel", "petrol", "cng", "lpg")
        else None
    )


def canonical_entity_presentation(key, vehicle=None):
    """One product label and translation identity, including range-role aliases."""
    from .attribute_contracts import binary_contract_for, contract_for

    definition = product_inventory()["entities"].get(key)
    if definition is None:
        return None, None
    platform, _, ident = key.partition(".")
    if vehicle is not None and ident in (
        "primary_engine_range",
        "secondary_engine_range",
    ):
        role = engine_role(vehicle, ident.split("_", 1)[0])
        if role:
            return role.capitalize() + " range", "v3_" + role + "_range"
    name = definition.get("name")
    if not name and platform == "sensor":
        name = contract_for(ident).get("name")
    if not name and platform == "binary_sensor":
        name = binary_contract_for(ident).get("name")
    return name, "v3_" + ident.replace("_{profile_id}", "")


def canonical_entity_name(key, vehicle=None):
    return canonical_entity_presentation(key, vehicle)[0]


def canonical_entity_translation_key(key, vehicle=None):
    return canonical_entity_presentation(key, vehicle)[1]


def stateful_controls():
    return product_inventory()["stateful_controls"]


def stateful_reading(vehicle, key, *, registry=None):
    """Shared operational state normalization, independent of write support."""
    from .attribute_runtime import last_known_observation
    from .vehicle import charging_active

    definition = stateful_controls()[key]
    row = control_reading(vehicle, definition["attribute"], registry=registry)
    known = last_known_observation(row)
    value = known.get("value")
    state = (
        charging_active(value)
        if key == "charging"
        else value
        if type(value) is bool
        else None
    )
    return row, state if known.get("status") in (
        "verified",
        "readable_but_stale",
    ) else None


def stateful_control_supported(engine, vehicle, key):
    definition = stateful_controls()[key]
    _, value = stateful_reading(
        vehicle, key, registry=getattr(engine, "registry", None)
    )
    return value is not None and all(
        engine.control_enabled(
            vehicle.vin, definition[action], definition["capability"]
        )
        for action in ("on", "off")
    )


def superseded_control_button(engine, vehicle, key):
    return any(
        key == "button." + button
        and stateful_control_supported(engine, vehicle, control)
        for control, definition in stateful_controls().items()
        for button in definition["compatibility_buttons"]
    )


def trip_metric_contracts():
    """Native trip metrics derive from the product inventory, not another catalog."""
    return {
        key.removeprefix("sensor."): definition["trip_metric"]
        for key, definition in product_inventory()["entities"].items()
        if "trip_metric" in definition
    }


def trip_metric_value(vehicle, key):
    import math

    contract = trip_metric_contracts()[key]
    trip = getattr(vehicle, "trips", {}).get(contract["source"], {})
    value = trip.get(contract["field"])
    return (
        value
        if type(value) in (int, float) and math.isfinite(value) and value >= 0
        else None
    )


def normalized_range_details(vehicle):
    """Explicit fuel/electric ranges, independent of primary/secondary ordering."""
    from .attribute_runtime import _capture_in_utc

    readings = vehicle.readings
    result = {}
    for kind, ids in (
        ("electric", ["measuredElectricRange", "batteryElectricRange"]),
        ("fuel", ["measuredFuelRange"]),
    ):
        ids.extend(
            role + "EngineRange"
            for role in ("primary", "secondary")
            if engine_role(vehicle, role) == kind
        )
        rows = [
            readings[i]
            for i in ids
            if i in readings
            and readings[i].get("status") in ("verified", "readable_but_stale")
            and type(readings[i].get("value")) in (int, float)
        ]
        if rows:
            row = max(
                rows,
                key=lambda item: (
                    _capture_in_utc(item.get("captured")).timestamp()
                    if _capture_in_utc(item.get("captured"))
                    else -1
                ),
            )
            result[kind + "_range_km"] = row["value"]
            result[kind + "_range_captured"] = row.get("captured")
    return result
