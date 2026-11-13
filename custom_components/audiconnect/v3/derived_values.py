"""V3 normalization of historical profile/timer data from one GET batch.

Never persist profile coordinates in HA entities or diagnostics. No inferred
timezone, no fabricated defaults, and no extra cloud request.
"""

from __future__ import annotations
from datetime import timedelta
from .registry import read_json_path
from .freshness import timestamp_is_fresh


def observe_derived(car, profile, payload: dict, observed_at, accepts) -> None:
    def record(ident, value, captured, job, path):
        if value is None or not accepts(car.readings.get(ident), captured):
            return
        fresh = timestamp_is_fresh(captured, observed_at)
        car.readings[ident] = {
            "value": value,
            "captured": captured,
            "observed": observed_at.isoformat(),
            "fresh": fresh,
            "path": path,
            "job": job,
            "family": "cariad",
            "status": "verified" if fresh else "readable_but_stale",
        }
        # Derived observations need no extra API route; HA setup can see them
        # directly while the original batch job remains in the polling plan.

    # Independent historical aliases use the original HA keys. Preserve
    # existing source timestamps rather than inventing new observations.
    for ident, source in (
        ("charging_type", "chargeType"),
        ("plug_led_color", "plugledColor"),
        ("primary_engine_type", "engineTypeFirstEngine"),
        ("secondary_engine_type", "engineTypeSecondEngine"),
        ("max_charge_current", "chargingCurrentLimitA"),
    ):
        row = car.readings.get(source)
        if row and row.get("value") is not None:
            record(
                ident,
                row["value"],
                row.get("captured"),
                row.get("job"),
                row.get("path"),
            )
    remaining = car.readings.get("remainingChargingTime", {})
    from .attribute_runtime import _capture_in_utc

    stamp = _capture_in_utc(remaining.get("captured"))
    minutes = remaining.get("value")
    if stamp and type(minutes) in (int, float) and 0 < minutes <= 10080:
        record(
            "charging_complete_time",
            (stamp + timedelta(minutes=minutes)).isoformat(),
            remaining["captured"],
            "charging",
            remaining.get("path"),
        )

    # Complementary identity fields are present even if manufacturer media is null.
    from .vehicle import normalize_powertrain

    fuel_level = read_json_path(payload, "measurements.fuelLevelStatus.value")
    if isinstance(fuel_level, dict):
        stamp = fuel_level.get("carCapturedTimestamp")
        raw_type = fuel_level.get("carType")
        if normalize_powertrain(raw_type) is not None:
            record(
                "measuredCarType",
                raw_type,
                stamp,
                "measurements",
                "measurements.fuelLevelStatus.value.carType",
            )
        for role in ("primary", "secondary"):
            value = fuel_level.get(role + "EngineType")
            if normalize_powertrain(value) in ("electric", "combustion"):
                record(
                    role + "_engine_type",
                    value.strip().lower(),
                    stamp,
                    "measurements",
                    "measurements.fuelLevelStatus.value." + role + "EngineType",
                )

    # Explicit-unit alternative sources from the same already-fetched batch.
    def metric(block, field, ident, job, path, maximum):
        if not isinstance(block, dict):
            return
        value = block.get(field)
        if type(value) in (int, float) and 0 <= value <= maximum:
            record(
                ident, value, block.get("carCapturedTimestamp"), job, path + "." + field
            )

    path = "measurements.rangeStatus.value"
    block = read_json_path(payload, path)
    for field, ident in (
        ("electricRange", "measuredElectricRange"),
        ("gasolineRange", "measuredFuelRange"),
        ("totalRange_km", "measuredTotalRange"),
    ):
        metric(block, field, ident, "measurements", path, 10000)
    path = "charging.batteryStatus.value"
    metric(
        read_json_path(payload, path),
        "cruisingRangeElectric_km",
        "batteryElectricRange",
        "charging",
        path,
        10000,
    )
    path = "measurements.fuelLevelStatus.value"
    metric(
        fuel_level, "currentSOC_pct", "measuredElectricSOC", "measurements", path, 100
    )
    path = "vehicleHealthInspection.maintenanceStatus.value"
    metric(
        read_json_path(payload, path),
        "mileage_km",
        "maintenanceMileage",
        "vehicleHealthInspection",
        path,
        2000000,
    )

    # Explicit alternative fuel and range readings; engine SOC is not fuel by assumption.
    engines = read_json_path(payload, "fuelStatus.rangeStatus.value")
    if isinstance(engines, dict):
        for role in ("primary", "secondary"):
            obj = engines.get(role + "Engine")
            if not isinstance(obj, dict):
                continue
            fuel = obj.get("currentFuelLevel_pct")
            if type(fuel) in (int, float) and 0 <= fuel <= 100:
                stamp = engines.get("carCapturedTimestamp")
                path = (
                    "fuelStatus.rangeStatus.value."
                    + role
                    + "Engine.currentFuelLevel_pct"
                )
                record(role + "EngineFuelLevel", fuel, stamp, "fuelStatus", path)
                # Keep engine-specific values; the product contract decides
                # whether this is the actual combustion tank. Never last-wins
                # across primary and secondary engines.
    # Operational window heating is not the preference windowHeatingEnabled,
    # and is not the legacy mirror-heating signal.
    from .vehicle import window_heating_active

    path = "climatisation.windowHeatingStatus.value"
    windows = read_json_path(payload, path)
    if isinstance(windows, dict):
        stamp = windows.get("carCapturedTimestamp")
        active = window_heating_active(windows.get("windowHeatingStatus"))
        if active is None:
            from .attribute_runtime import record_invalid_observation

            record_invalid_observation(
                car,
                "windowHeatingActive",
                stamp,
                observed_at,
                path,
                "climatisation",
                "unknown_window_heating_state",
            )
        else:
            record("windowHeatingActive", active, stamp, "climatisation", path)

    # Historical auxiliary-heating status is distinct from electric cabin
    # climatisation. Do not infer heating from a generic climate state.
    path = "climatisation.auxiliaryHeatingStatus.value"
    auxiliary = read_json_path(payload, path)
    if isinstance(auxiliary, dict):
        stamp = auxiliary.get("carCapturedTimestamp")
        state = auxiliary.get("climatisationState")
        if isinstance(state, str):
            state = state.strip().lower()
            active = (
                True
                if state in ("heating", "on", "active")
                else (False if state in ("off", "inactive", "stopped") else None)
            )
            record("preheater_active", active, stamp, "climatisation", path)
        for ident, field in (
            ("preheater_duration", "climatisationDuration"),
            ("preheater_remaining", "remainingClimateTime"),
        ):
            value = auxiliary.get(field)
            if type(value) is int and value >= 0:
                record(ident, value, stamp, "climatisation", path)

    # Derive native access booleans from explicit status enums, not from
    # absence of a "closed" token (unknown must never mean open/unlocked).
    path = "access.accessStatus.value"
    block = read_json_path(payload, path)
    if isinstance(block, dict):
        captured = block.get("carCapturedTimestamp")
        names = {
            "frontLeft": "left_front",
            "frontRight": "right_front",
            "rearLeft": "left_rear",
            "rearRight": "right_rear",
        }
        opened, unlocked, windows = {}, {}, {}

        def component_state(states, positive, negative):
            if not isinstance(states, list) or any(
                token in states for token in ("unsupported", "invalid", "unknown")
            ):
                return None
            if (positive in states) == (negative in states):
                return None
            return positive in states

        def invalidate_missing(ident):
            from .attribute_runtime import record_invalid_observation

            record_invalid_observation(
                car,
                ident,
                captured,
                observed_at,
                path,
                "access",
                "partial_or_unknown_component_state",
            )

        trunk_open = trunk_unlocked = None
        seen_doors, seen_windows = set(), set()
        for row in (
            block.get("doors", []) if isinstance(block.get("doors"), list) else []
        ):
            if not isinstance(row, dict):
                continue
            name, states = row.get("name"), row.get("status")
            if name not in (*names, "trunk", "bonnet"):
                continue
            duplicate = name in seen_doors
            seen_doors.add(name)
            open_state = (
                None if duplicate else component_state(states, "open", "closed")
            )
            lock_state = (
                None if duplicate else component_state(states, "unlocked", "locked")
            )
            if name in names:
                record(names[name] + "_door_open", open_state, captured, "access", path)
                opened[name] = open_state
                unlocked[name] = lock_state
            elif name == "trunk":
                record("trunk_open", open_state, captured, "access", path)
                record("trunk_unlocked", lock_state, captured, "access", path)
                trunk_open, trunk_unlocked = open_state, lock_state
            elif name == "bonnet":
                record("hood_open", open_state, captured, "access", path)
        if isinstance(block.get("doors"), list):
            for name, key in names.items():
                if opened.get(name) is None and (
                    name in seen_doors or key + "_door_open" not in car.readings
                ):
                    invalidate_missing(key + "_door_open")
            if trunk_open is None and (
                "trunk" in seen_doors or "trunk_open" not in car.readings
            ):
                invalidate_missing("trunk_open")
            if trunk_unlocked is None and (
                "trunk" in seen_doors or "trunk_unlocked" not in car.readings
            ):
                invalidate_missing("trunk_unlocked")
            if "bonnet" in seen_doors and not any(
                row.get("name") == "bonnet"
                and component_state(row.get("status"), "open", "closed") is not None
                for row in block["doors"]
                if isinstance(row, dict)
            ):
                invalidate_missing("hood_open")
        # Positive is conclusive even if other components are not present.
        # Negative requires complete, known evidence; no fabricated safe state.
        for key, values in (("any_door_open", opened), ("any_door_unlocked", unlocked)):
            value = (
                True
                if True in values.values()
                else False
                if len(values) == 4 and all(x is False for x in values.values())
                else None
            )
            if value is None:
                if isinstance(block.get("doors"), list):
                    invalidate_missing(key)
            else:
                record(key, value, captured, "access", path)
        if True in opened.values() or trunk_open is True:
            record("doors_trunk_status", "Open", captured, "access", path)
        elif (
            len(opened) == 4
            and all(x is False for x in opened.values())
            and trunk_open is False
        ):
            if True in unlocked.values() or trunk_unlocked is True:
                record("doors_trunk_status", "Closed", captured, "access", path)
            elif (
                len(unlocked) == 4
                and all(x is False for x in unlocked.values())
                and trunk_unlocked is False
            ):
                record("doors_trunk_status", "Locked", captured, "access", path)
            else:
                invalidate_missing("doors_trunk_status")
        elif isinstance(block.get("doors"), list):
            invalidate_missing("doors_trunk_status")
        for row in (
            block.get("windows", []) if isinstance(block.get("windows"), list) else []
        ):
            if not isinstance(row, dict):
                continue
            name, states = row.get("name"), row.get("status")
            if name not in (*names, "sunRoof", "roofCover"):
                continue
            duplicate = name in seen_windows
            seen_windows.add(name)
            state = None if duplicate else component_state(states, "open", "closed")
            key = (
                names[name] + "_window_open"
                if name in names
                else {"sunRoof": "sun_roof", "roofCover": "roof_cover"}.get(name)
            )
            if key:
                if state is None:
                    invalidate_missing(key)
                else:
                    record(key, state, captured, "access", path)
                if name in names:
                    windows[name] = state
        if isinstance(block.get("windows"), list):
            for name, key in names.items():
                if windows.get(name) is None and (
                    name in seen_windows or key + "_window_open" not in car.readings
                ):
                    invalidate_missing(key + "_window_open")
        value = (
            True
            if True in windows.values()
            else False
            if len(windows) == 4 and all(x is False for x in windows.values())
            else None
        )
        if value is None:
            if isinstance(block.get("windows"), list):
                invalidate_missing("any_window_open")
        else:
            record("any_window_open", value, captured, "access", path)
    path = "vehicleLights.lightsStatus.value"
    lights = read_json_path(payload, path)
    if isinstance(lights, dict) and isinstance(lights.get("lights"), list):
        # Explicit component identity is mandatory; headlights are not parking lights.
        # Unknown or conflicting evidence cannot imply OFF.
        # Upstream Audi status examples and V2 LIGHT_STATUS identify the
        # parking lights by left/right. Accept explicit aggregate labels too.
        rows = [
            x
            for x in lights["lights"]
            if isinstance(x, dict)
            and x.get("name") in ("left", "right", "parkingLight", "parkingLights")
        ]
        names = [x["name"] for x in rows]
        states = [x.get("status") for x in rows]
        valid = len(set(names)) == len(names) and all(
            x in ("on", "off") for x in states
        )
        active = None
        if valid and "on" in states:
            active = True
        elif (
            valid
            and states
            and (
                {"left", "right"} <= set(names)
                or set(names) & {"parkingLight", "parkingLights"}
            )
        ):
            active = False
        if active is not None:
            record(
                "parking_light",
                active,
                lights.get("carCapturedTimestamp"),
                "vehicleLights",
                path,
            )
        else:
            from .attribute_runtime import record_invalid_observation

            record_invalid_observation(
                car,
                "parking_light",
                lights.get("carCapturedTimestamp"),
                observed_at,
                path,
                "vehicleLights",
                "unknown_parking_light_state",
            )
    oil = read_json_path(payload, "oilLevel.oilLevelStatus.value")
    if isinstance(oil, dict) and type(oil.get("value")) is bool:
        record(
            "oil_level_binary",
            not oil["value"],
            oil.get("carCapturedTimestamp"),
            "oilLevel",
            "oilLevel.oilLevelStatus.value",
        )
    elif (
        isinstance(oil, dict)
        and type(oil.get("value")) in (int, float)
        and "oil_level_binary" in car.readings
    ):
        from .attribute_runtime import record_invalid_observation

        record_invalid_observation(
            car,
            "oil_level_binary",
            oil.get("carCapturedTimestamp"),
            observed_at,
            "oilLevel.oilLevelStatus.value",
            "oilLevel",
            "numeric_oil_level_no_binary_warning",
        )
    # The preference block may lack a timestamp. Borrow ONLY the sibling
    # charging status clock from this response, matching the historical source.
    mode = read_json_path(payload, "charging.chargeMode.value")
    charge = read_json_path(payload, "charging.chargingStatus.value")
    if isinstance(mode, dict) and isinstance(charge, dict):
        captured = mode.get("carCapturedTimestamp") or charge.get(
            "carCapturedTimestamp"
        )
        for key in ("preferredChargeMode", "availableChargeModes"):
            record(
                key, mode.get(key), captured, "charging", "charging.chargeMode.value"
            )
    path = "chargingProfiles.chargingProfilesStatus.value"
    block = read_json_path(payload, path)
    if isinstance(block, dict) and isinstance(block.get("profiles"), list):
        captured = block.get("carCapturedTimestamp")
        if accepts(
            {"captured": car.charging_profiles_captured}
            if car.charging_profiles_captured
            else None,
            captured,
        ):
            from .structured_details import (
                _clock,
                _boolean,
                _timer,
                _array,
                _zoned_datetime,
            )

            def percentage(value):
                return (
                    value if type(value) in (int, float) and 0 <= value <= 100 else None
                )

            def preference(t):
                return {
                    "id": t.get("id") if type(t.get("id")) is int else None,
                    "enabled": _boolean(t.get("enabled")),
                    "startTimeLocal": _clock(
                        t.get("startTimeLocal") or t.get("startTime")
                    ),
                    "endTimeLocal": _clock(t.get("endTimeLocal") or t.get("endTime")),
                }

            profiles = [
                dict(
                    id=x["id"],
                    name=x.get("name") if isinstance(x.get("name"), str) else None,
                    targetSOC_pct=percentage(x.get("targetSOC_pct")),
                    minSOC_pct=percentage(x.get("minSOC_pct")),
                    minSOC_enabled=_boolean(x.get("minSOC_enabled")),
                    maxChargingCurrent=x.get("maxChargingCurrent")
                    if x.get("maxChargingCurrent") in ("max", "reduced")
                    else None,
                    options={
                        k: v
                        for k, v in (x.get("options") or {}).items()
                        if k
                        in ("autoUnlockPlugWhenCharged", "usePreferredChargingTimes")
                        and (
                            type(v) is bool
                            or v in ("on", "off", "permanent", "unsupported", "invalid")
                        )
                    }
                    if isinstance(x.get("options"), dict)
                    else {},
                    timers=_array(x.get("timers"), _timer, 30),
                    preferredChargingTimes=[
                        preference(t)
                        for t in x.get("preferredChargingTimes", [])[:12]
                        if isinstance(t, dict)
                    ]
                    if isinstance(x.get("preferredChargingTimes"), list)
                    else [],
                )
                for x in block["profiles"][:30]
                if isinstance(x, dict) and type(x.get("id")) is int
            ]
            car.charging_profiles = profiles
            car.charging_profiles_captured = captured
            active_id = block.get("vehiclePositionedInProfileID")
            car.active_charging_profile_id = (
                active_id if type(active_id) is int else None
            )
            next_timer = block.get("nextChargingTimer")
            record(
                "charging_profile_context_detail",
                {
                    "vehicle_time": _zoned_datetime(block.get("timeInCar")),
                    "next_charging_timer": {
                        "id": next_timer.get("id")
                        if type(next_timer.get("id")) is int
                        else None,
                        "target_soc_reachable": _boolean(
                            next_timer.get("targetSOCreachable")
                        ),
                    }
                    if isinstance(next_timer, dict)
                    else None,
                },
                captured,
                "chargingProfiles",
                path,
            )
            active = next(
                (x for x in profiles if x["id"] == car.active_charging_profile_id), None
            )
            keys = {
                "active_charging_profile_target_soc": "targetSOC_pct",
                "active_charging_profile_name": "name",
                "active_charging_profile_min_soc": "minSOC_pct",
            }
            for ident, key in keys.items():
                car.readings.pop(ident, None)
                if active:
                    record(ident, active.get(key), captured, "chargingProfiles", path)
            for ident in (
                "preferred_charging_time_start",
                "preferred_charging_time_end",
            ):
                car.readings.pop(ident, None)
            if active and active["preferredChargingTimes"]:
                times = active["preferredChargingTimes"]
                window = next((x for x in times if x.get("enabled") is True), None)
                if window is not None:
                    record(
                        "preferred_charging_time_start",
                        window.get("startTimeLocal"),
                        captured,
                        "chargingProfiles",
                        path,
                    )
                    record(
                        "preferred_charging_time_end",
                        window.get("endTimeLocal"),
                        captured,
                        "chargingProfiles",
                        path,
                    )

    for job, count in (
        ("chargingTimers", "charging_timer_enabled_count"),
        ("climatisationTimers", "climatisation_timer_enabled_count"),
    ):
        path = f"{job}.{job}Status.value"
        block = read_json_path(payload, path)
        if not isinstance(block, dict) or not isinstance(block.get("timers"), list):
            continue
        captured = block.get("carCapturedTimestamp")
        entries = [t for t in block["timers"][:30] if isinstance(t, dict)]
        record(
            count, sum(t.get("enabled") is True for t in entries), captured, job, path
        )
        if job == "climatisationTimers":
            starts = sorted(
                v
                for t in entries
                if t.get("enabled") is True
                and isinstance(t.get("singleTimer"), dict)
                and isinstance(v := t["singleTimer"].get("startDateTimeLocal"), str)
            )
            if starts:
                record("next_climatisation_timer_local", starts[0], captured, job, path)
            elif accepts(car.readings.get("next_climatisation_timer_local"), captured):
                car.readings.pop("next_climatisation_timer_local", None)
