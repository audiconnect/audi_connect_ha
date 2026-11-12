"""Normalize legacy read-only fields without importing V2 models."""

from __future__ import annotations
import math
from .legacy_read_mappings import FIELDS, FIELD_IDS
from .registry import read_json_path
from .attribute_runtime import (
    _accept_observation,
    _capture_in_utc,
    record_invalid_observation,
)
from .attribute_contracts import semantic_value_issue
from .historical_catalog import ATTRIBUTES
from .freshness import timestamp_is_fresh


def _number(value):
    if type(value) not in (int, float, str):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def observe_legacy(car, profile, kind, response):
    payload = response.data
    if not isinstance(payload, dict):
        return

    def record(key, value, stamp=None, path=None):
        selected = getattr(profile, "attribute_routes", {}).get(key)
        if selected and selected != f"mbb.{kind}.readonly":
            return
        if value is None or (
            isinstance(value, str)
            and value.lower()
            in ("", "invalid", "unknown", "unsupported", "unavailable")
        ):
            return
        descriptor = ATTRIBUTES.get(key, {})
        issue = semantic_value_issue(descriptor.get("entity_key", key), value)
        if issue:
            record_invalid_observation(
                car, key, stamp, response.observed_at, path or kind, None, issue, "mbb"
            )
            return
        if not _accept_observation(car.readings.get(key), stamp):
            return
        fresh = timestamp_is_fresh(stamp, response.observed_at)
        status = "verified" if fresh else "readable_but_stale"
        car.readings[key] = {
            "value": value,
            "captured": stamp,
            "observed": response.observed_at.isoformat(),
            "status": status,
            "family": "mbb",
            "path": path or kind,
            "job": None,
            "operation": f"mbb.{kind}.readonly",
        }
        # Persist only evidence that the existing route-schema validator can
        # reconstruct. Derived values remain in memory, like CARIAD derived
        # readings; do not corrupt the saved profile with raw field IDs.
        from .legacy_read_mappings import variant_for

        variant = variant_for(key)
        if key in ATTRIBUTES and variant and path in variant["response_paths"]:
            profile.attribute_evidence[key] = {
                "status": status,
                "path": path,
                "job": ATTRIBUTES[key]["job"],
                "source": "mbb.legacy",
                "timestamp_present": bool(stamp),
            }

    numeric = {
        "stateOfCharge",
        "actualChargeRate",
        "chargingPower",
        "remainingChargingTime",
        "hybridRange",
        "primaryEngineRange",
        "secondaryEngineRange",
        "remainingClimatisationTime",
        "max_charge_current",
    }
    for ident, (name, path) in FIELDS.items():
        if name != kind:
            continue
        value = read_json_path(payload, path)
        parent = read_json_path(payload, path.rsplit(".", 1)[0])
        stamp = (
            (parent.get("carCapturedTimestamp") or parent.get("tsCarCaptured"))
            if isinstance(parent, dict)
            else None
        )
        if ident in numeric:
            value = _number(value)
            if (
                value is not None
                and value < 0
                and ident not in ("remainingChargingTime", "remainingClimatisationTime")
            ):
                continue
        if ident == "glass_surface_heating" and isinstance(value, str):
            value = {"true": True, "false": False}.get(value.lower())
        record(ident, value, stamp, path)
    if kind == "climater":
        for ident, path, conversion in (
            (
                "outdoor_temperature",
                "climater.status.temperatureStatusData.outdoorTemperature.content",
                lambda v: round(v / 10 - 273, 1),
            ),
            (
                "climatisationTargetTemperatureC",
                "climater.settings.targetTemperature.content",
                lambda v: round((v - 2731) / 10, 1),
            ),
        ):
            raw = _number(read_json_path(payload, path))
            if raw is not None:
                record(ident, conversion(raw), path=path)
    if kind == "charger":
        for ident, source in (
            ("charging_type", "chargeType"),
            ("plug_led_color", "plugledColor"),
            ("primary_engine_type", "engineTypeFirstEngine"),
            ("secondary_engine_type", "engineTypeSecondEngine"),
        ):
            row = car.readings.get(source, {})
            record(ident, row.get("value"), row.get("captured"), row.get("path"))
    if kind == "preheater":
        path = "statusResponse.climatisationStateReport"
        block = read_json_path(payload, path)
        if isinstance(block, dict):
            stamp = block.get("carCapturedTimestamp")
            state = block.get("climatisationState")
            if isinstance(state, str):
                record(
                    "preheater_active",
                    True
                    if state.lower() in ("heating", "active", "on", "ventilation")
                    else False
                    if state.lower() in ("off", "inactive", "stopped")
                    else None,
                    stamp,
                    path,
                )
            for key, field in (
                ("preheater_duration", "climatisationDuration"),
                ("preheater_remaining", "remainingClimateTime"),
            ):
                v = _number(block.get(field))
                if v is not None and v >= 0:
                    record(key, v, stamp, path)
    if kind != "vehicle_data":
        return
    groups = read_json_path(payload, "StoredVehicleDataResponse.vehicleData.data")
    if groups is None:
        groups = read_json_path(payload, "vehicleData.data")
    if not isinstance(groups, list):
        return
    found = {}
    for group in groups[:100]:
        fields = group.get("field") if isinstance(group, dict) else None
        if not isinstance(fields, list):
            continue
        for row in fields[:100]:
            if not isinstance(row, dict):
                continue
            key = FIELD_IDS.get(row.get("id"))
            if key:
                found[key] = (
                    row.get("value"),
                    row.get("tsCarCaptured") or row.get("tsTssReceivedUtc"),
                )
    numeric_fields = {
        "UTC_TIME_AND_KILOMETER_STATUS",
        "TOTAL_RANGE",
        "TANK_LEVEL_IN_PERCENTAGE",
        "MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE",
        "MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE",
        "MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION",
        "MAINTENANCE_INTERVAL_TIME_TO_INSPECTION",
        "ADBLUE_RANGE",
        "OIL_LEVEL_DIPSTICKS_PERCENTAGE",
    }
    for key, (value, stamp) in found.items():
        if key == "OIL_LEVEL_DIPSTICKS_PERCENTAGE" and type(value) is bool:
            record_invalid_observation(
                car,
                key,
                stamp,
                response.observed_at,
                key,
                None,
                "boolean_oil_level_use_binary",
                "mbb",
            )
            record("oil_level_binary", not value, stamp, key)
        elif key in numeric_fields:
            record(key, _number(value), stamp, key)
        if key == "LIGHT_STATUS" and isinstance(value, list) and len(value) >= 2:
            states = [
                item.get("status") for item in value[:2] if isinstance(item, dict)
            ]
            if len(states) == 2 and all(state in ("on", "off") for state in states):
                record("parking_light", "on" in states, stamp, key)
        if key == "BRAKING_STATUS":
            record(
                "braking_status",
                True if str(value) == "1" else False if str(value) == "2" else None,
                stamp,
                key,
            )
        if key == "TEMPERATURE_OUTSIDE":
            n = _number(value)
            if n is not None:
                record("outdoor_temperature", round(n / 10 - 273, 1), stamp, key)
    doors = []
    locks = []
    windows = []
    for side in ("LEFT_FRONT", "RIGHT_FRONT", "LEFT_REAR", "RIGHT_REAR"):
        label = side.lower()
        for prefix, entity, closed, opened, aggregate in (
            ("OPEN_STATE_", label + "_door_open", "3", "2", doors),
            ("LOCK_STATE_", None, "2", "1", locks),
            ("STATE_", label + "_window_open", "3", "2", windows),
        ):
            key = prefix + side + ("_WINDOW" if prefix == "STATE_" else "_DOOR")
            value, stamp = found.get(key, (None, None))
            status = (
                False
                if str(value) == closed
                else True
                if str(value) == opened
                else None
            )
            aggregate.append((status, stamp))
            if entity:
                record(entity, status, stamp, key)
    for key, entity, closed, opened in (
        ("OPEN_STATE_TRUNK_LID", "trunk_open", "3", "2"),
        ("LOCK_STATE_TRUNK_LID", "trunk_unlocked", "2", "1"),
        ("OPEN_STATE_HOOD", "hood_open", "3", "2"),
        ("STATE_SUN_ROOF_MOTOR_COVER", "sun_roof", "3", "2"),
        ("STATE_DECK", "roof_cover", "3", "2"),
    ):
        value, stamp = found.get(key, (None, None))
        record(
            entity,
            False if str(value) == closed else True if str(value) == opened else None,
            stamp,
            key,
        )
    for entity, rows in (
        ("any_door_open", doors),
        ("any_door_unlocked", locks),
        ("any_window_open", windows),
    ):
        states = [v for v, s in rows]
        stamps = [_capture_in_utc(s) for v, s in rows if v is not None]
        stamp = min(stamps).isoformat() if stamps and all(stamps) else None
        value = (
            True
            if True in states
            else False
            if all(v is False for v in states)
            else None
        )
        record(entity, value, stamp, entity)
        if entity == "any_door_unlocked" and value is not None:
            record("doorLockStatus", "unlocked" if value else "locked", stamp, entity)
