"""V3 normalization of historical profile/timer data from one GET batch.

Never persist profile coordinates in HA entities or diagnostics. No inferred
timezone, no fabricated defaults, and no extra cloud request.
"""

from __future__ import annotations
from datetime import UTC, datetime, timedelta
from .registry import read_json_path
from .freshness import timestamp_is_fresh


def project_charging_eta(car, profile, observed_at):
    """A derived timestamp follows the selected duration, not a second source cache."""
    from .attribute_runtime import _valid_capture, invalidate_attribute

    ident = "charging_complete_time"
    remaining = car.readings.get("remainingChargingTime", {})
    invalidate_attribute(car, ident)
    if ident in getattr(profile, "attribute_disabled", ()):
        return
    stamp = _valid_capture(remaining.get("captured"), observed_at)
    if stamp is None:
        return
    from .vehicle import charging_active

    charging = car.readings.get("chargingState", {})
    charging_stamp = _valid_capture(charging.get("captured"), observed_at)
    # A later explicit non-charging observation supersedes an older ETA.
    # Retain the source duration for engineering; do not invent a zero.
    if (
        charging.get("status") != "invalid_value"
        and charging_active(charging.get("value")) is False
        and charging_stamp is not None
        and charging_stamp >= stamp
    ):
        return
    minutes = remaining.get("value")
    if remaining.get("status") == "invalid_value":
        car.readings[ident] = {
            **remaining,
            "reason": remaining.get("reason") or "invalid_remaining_charging_time",
            "derived_from": "remainingChargingTime",
        }
    elif type(minutes) in (int, float) and 0 < minutes <= 10080:
        car.readings[ident] = {
            **remaining,
            "value": (stamp + timedelta(minutes=minutes)).isoformat(),
            "derived_from": "remainingChargingTime",
        }


def observe_derived(
    car,
    profile,
    payload: dict,
    observed_at,
    accepts,
    *,
    operation="cariad.climate.status.batch",
) -> None:
    from .attribute_runtime import (
        record_observation,
        _valid_capture,
        commit_observation,
    )

    def record(ident, value, captured, job, path):
        if value is not None:
            record_observation(
                car,
                profile,
                ident,
                value,
                captured,
                observed_at,
                path,
                job,
                "cariad",
                fresh=timestamp_is_fresh(captured, observed_at),
                operation=operation,
                persist_evidence=False,
            )

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
        if row and ident not in getattr(profile, "attribute_disabled", ()):
            commit_observation(
                car,
                ident,
                {**row, "family": row.get("family", "")},
                getattr(profile, "registry", None),
                observed_at,
            )
    from .attribute_runtime import record_invalid_observation

    # Derive from selected source observations, also for direct response consumers.
    project_charging_eta(car, profile, observed_at)

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
    # Candidate technical fields are read-only and remain absent unless
    # the existing batch actually supplies an explicit-unit numeric value.
    for path, field, ident, maximum in (
        (
            "charging.chargingSettings.value",
            "minChargeLimit_pct",
            "minimumChargeLimit",
            100,
        ),
        (
            "charging.batteryStatus.value",
            "navigationTargetSOC_pct",
            "navigationTargetSOC",
            100,
        ),
        (
            "charging.chargingStatus.value",
            "remainingChargingTimeNavigation_min",
            "navigationRemainingChargingTime",
            10080,
        ),
        (
            "measurements.temperatureBatteryStatus.value",
            "temperatureHvBatteryMin_K",
            "hvBatteryMinimumTemperature",
            400,
        ),
        (
            "measurements.temperatureBatteryStatus.value",
            "temperatureHvBatteryMax_K",
            "hvBatteryMaximumTemperature",
            400,
        ),
    ):
        block = read_json_path(payload, path)
        if ident.startswith("hvBattery") and (
            not isinstance(block, dict)
            or type(block.get(field)) not in (int, float)
            or block[field] < 173.15
        ):
            continue
        metric(block, field, ident, path.split(".", 1)[0], path, maximum)

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
    settings_path = "climatisation.climatisationSettings.value"
    climate_settings = read_json_path(payload, settings_path)
    if isinstance(climate_settings, dict) and climate_settings.get(
        "climatisationMode"
    ) in ("comfort", "economy"):
        record(
            "climatisationMode",
            climate_settings["climatisationMode"],
            climate_settings.get("carCapturedTimestamp"),
            "climatisation",
            settings_path + ".climatisationMode",
        )

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
                profile=profile,
                operation=operation,
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
                profile=profile,
                operation=operation,
            )

        def record_component(ident, value):
            if value is None:
                invalidate_missing(ident)
            else:
                record(ident, value, captured, "access", path)

        trunk_open = trunk_unlocked = None
        seen_doors = set()
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
                record_component(names[name] + "_door_open", open_state)
                opened[name] = open_state
                unlocked[name] = lock_state
            elif name == "trunk":
                record_component("trunk_open", open_state)
                record_component("trunk_unlocked", lock_state)
                trunk_open, trunk_unlocked = open_state, lock_state
            elif name == "bonnet":
                record_component("hood_open", open_state)
        # Omitted components retain their prior sample. Explicit unknown or
        # contradictory components invalidate only their own sample.
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
        seen_windows = set()
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
                else {"sunRoof": "sun_roof", "roofCover": "roof_cover"}[name]
            )
            record_component(key, state)
            if name in names:
                windows[name] = state
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
                profile=profile,
                operation=operation,
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
            profile=profile,
            operation=operation,
        )
    path = "chargingProfiles.chargingProfilesStatus.value"
    block = read_json_path(payload, path)
    if isinstance(block, dict) and isinstance(block.get("profiles"), list):
        captured = block.get("carCapturedTimestamp")
        if _valid_capture(captured, observed_at) is None:
            captured = None
        if accepts(
            {"captured": car.charging_profiles_captured}
            if car.charging_profiles_captured
            else None,
            captured,
            observed_at,
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
            active_id = block.get("vehiclePositionedInProfileID")
            next_timer = block.get("nextChargingTimer")
            record(
                "charging_profile_context_detail",
                {
                    "profiles": profiles,
                    "active_profile_id": active_id if type(active_id) is int else None,
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
            selected = car.readings.get("charging_profile_context_detail", {})
            snapshot = selected.get("value") or {}
            car.charging_profiles = snapshot.get("profiles", [])
            car.charging_profiles_captured = selected.get("captured")
            car.active_charging_profile_id = snapshot.get("active_profile_id")
            active = next(
                (
                    x
                    for x in car.charging_profiles
                    if x["id"] == car.active_charging_profile_id
                ),
                None,
            )
            captured = car.charging_profiles_captured
            keys = {
                "active_charging_profile_target_soc": "targetSOC_pct",
                "active_charging_profile_name": "name",
                "active_charging_profile_min_soc": "minSOC_pct",
            }
            window = next(
                (
                    x
                    for x in (active or {}).get("preferredChargingTimes", [])
                    if x.get("enabled") is True
                ),
                {},
            )
            values = {
                **{ident: (active or {}).get(key) for ident, key in keys.items()},
                "preferred_charging_time_start": window.get("startTimeLocal"),
                "preferred_charging_time_end": window.get("endTimeLocal"),
            }
            for ident, value in values.items():
                if value is not None:
                    record(ident, value, captured, "chargingProfiles", path)
                else:
                    record_invalid_observation(
                        car,
                        ident,
                        captured,
                        observed_at,
                        path,
                        "chargingProfiles",
                        selected.get("reason", "no_active_profile_value"),
                        profile=profile,
                        operation=operation,
                    )

    from .structured_details import observe_structured

    # Normalize the lists once. Derive scalars from the selected observation,
    # not independently from the incoming response.
    observe_structured(car, payload, observed_at, accepts, operation=operation)
    for job, detail, count in (
        ("chargingTimers", "charging_timers_detail", "charging_timer_enabled_count"),
        (
            "climatisationTimers",
            "climate_timers_detail",
            "climatisation_timer_enabled_count",
        ),
    ):
        source = car.readings.get(detail)
        # A retained detail cannot acquire a new receipt or capture time.
        if source is None or source.get("observed") != observed_at.isoformat():
            continue
        path = f"{job}.{job}Status.value"
        captured = source.get("captured")
        timers = source.get("value")
        if source.get("status") == "invalid_value" or not isinstance(timers, dict):
            for ident in (
                (count, "next_climatisation_timer_local")
                if detail == "climate_timers_detail"
                else (count,)
            ):
                record_invalid_observation(
                    car,
                    ident,
                    captured,
                    observed_at,
                    path,
                    job,
                    source.get("reason") or "incomplete_timer_data",
                    profile=profile,
                    operation=operation,
                )
            continue
        entries = timers["items"]
        complete = timers["all_items_recognized"] and all(
            "enabled" in timer for timer in entries
        )
        if complete:
            record(count, sum(t["enabled"] for t in entries), captured, job, path)
        else:
            record_invalid_observation(
                car,
                count,
                captured,
                observed_at,
                path,
                job,
                "incomplete_timer_data",
                profile=profile,
                operation=operation,
            )
        if detail == "climate_timers_detail":
            ident = "next_climatisation_timer_local"
            starts = [
                t["start_datetime_local"]
                for t in entries
                if t.get("enabled") is True and "start_datetime_local" in t
            ]
            # An enabled single timer with an unknown start could precede
            # every known candidate. Recurring schedules are not single starts.
            single_starts_complete = complete and all(
                timer.get("enabled") is not True
                or "start_datetime_local" in timer
                or timer.get("recurring_only") is True
                for timer in entries
            )
            # Local wall-clock timestamps require a vehicle clock anchor.
            # Never infer its timezone from the HA host or API market.
            clock = timers.get("vehicle_time")
            if (
                clock is not None
                and timestamp_is_fresh(clock, observed_at)
                and timestamp_is_fresh(captured, observed_at)
            ):
                local_now = observed_at.astimezone(
                    datetime.fromisoformat(clock).tzinfo
                ).replace(tzinfo=None)
                starts = [
                    value
                    for value in starts
                    if datetime.fromisoformat(value) > local_now
                ]
            elif observed_at.tzinfo is not None:
                # Without a local clock, do not skip a potentially earlier
                # future timer. Preserve all schedule details independently.
                utc_now = observed_at.astimezone(UTC).replace(tzinfo=None)
                earliest = utc_now - timedelta(hours=14)
                latest = utc_now + timedelta(hours=14)
                candidates = [
                    value
                    for value in starts
                    if datetime.fromisoformat(value) > earliest
                ]
                starts = (
                    candidates
                    if all(
                        datetime.fromisoformat(value) > latest for value in candidates
                    )
                    else []
                )
            else:
                starts = []
            if single_starts_complete and starts:
                record(
                    ident,
                    min(starts, key=datetime.fromisoformat),
                    captured,
                    job,
                    path,
                )
            else:
                record_invalid_observation(
                    car,
                    ident,
                    captured,
                    observed_at,
                    path,
                    job,
                    "no_enabled_climatisation_timer"
                    if complete and not any(t.get("enabled") is True for t in entries)
                    else "next_single_timer_not_determined"
                    if complete
                    else "incomplete_timer_data",
                    profile=profile,
                    operation=operation,
                )
