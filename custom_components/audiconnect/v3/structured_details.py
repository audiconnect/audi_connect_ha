"""Typed, bounded functional details from reviewed selective-status schemas.

This is a read-only projection of OEM data, not a new capability or control
authorization source. No unbounded raw dictionaries, geographic data or secrets.
"""

from __future__ import annotations

import re
from datetime import datetime
from .registry import read_json_path
from .freshness import reading_freshness_attributes, timestamp_is_fresh

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
_CLOCK = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9])?$")


def _token(value):
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else None


def _id(value):
    return value if type(value) is int and 0 <= value <= 1000000 else _token(value)


def _local_datetime(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return value if stamp.tzinfo is None and "T" in value else None


def _zoned_datetime(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.isoformat() if stamp.tzinfo is not None else None


def _clock(value):
    return value if isinstance(value, str) and _CLOCK.fullmatch(value) else None


def _boolean(value):
    return value if type(value) is bool else None


def _tokens(values, limit=32):
    if not isinstance(values, list):
        return None
    result = [_token(value) for value in values[:limit]]
    return [value for value in result if value is not None]


def _compact(values):
    return {key: value for key, value in values.items() if value is not None}


def _preferred_window(row):
    if not isinstance(row, dict):
        return None
    return (
        _compact(
            {
                "id": _id(row.get("id")),
                "enabled": _boolean(row.get("enabled")),
                "start_time_local": _clock(
                    row.get("startTimeLocal") or row.get("startTime")
                ),
                "end_time_local": _clock(row.get("endTimeLocal") or row.get("endTime")),
            }
        )
        or None
    )


def _timer(row):
    if not isinstance(row, dict):
        return None
    single = row.get("singleTimer")
    recurring = row.get("recurringTimer")
    result = _compact(
        {
            "id": _id(row.get("id")),
            "enabled": _boolean(row.get("enabled")),
            "climatisation": _boolean(row.get("climatisation")),
        }
    )
    if isinstance(row.get("preferredChargingTimes"), list):
        result["preferred_charging_times"] = _array(
            row["preferredChargingTimes"], _preferred_window, 12
        )
    if isinstance(single, dict):
        result.update(
            _compact(
                {
                    "start_datetime_local": _local_datetime(
                        single.get("startDateTimeLocal")
                    ),
                    "target_datetime_local": _local_datetime(
                        single.get("targetDateTimeLocal")
                    ),
                    "departure_datetime_local": _local_datetime(
                        single.get("departureDateTimeLocal")
                    ),
                    "start_datetime": _zoned_datetime(single.get("startDateTime")),
                    "target_datetime": _zoned_datetime(single.get("targetDateTime")),
                }
            )
        )
    if isinstance(recurring, dict):
        days = recurring.get("repetitionDays")
        if isinstance(days, list):
            days = [
                d
                for d in days[:7]
                if type(d) is int and 0 <= d <= 7 or _token(d) is not None
            ]
        else:
            days = None
        recurring_on = recurring.get("recurringOn")
        weekdays = (
            "mondays",
            "tuesdays",
            "wednesdays",
            "thursdays",
            "fridays",
            "saturdays",
            "sundays",
        )
        result.update(
            _compact(
                {
                    "departure_time_local": _clock(recurring.get("departureTimeLocal")),
                    "target_time_local": _clock(
                        recurring.get("targetTimeLocal") or recurring.get("targetTime")
                    ),
                    "start_time_local": _clock(recurring.get("startTime")),
                    "repetition_days": days,
                    "recurring_on": _compact(
                        {day: _boolean(recurring_on.get(day)) for day in weekdays}
                    )
                    if isinstance(recurring_on, dict)
                    else None,
                }
            )
        )
    return result or None


def _component(row):
    if not isinstance(row, dict) or (name := _token(row.get("name"))) is None:
        return None
    status = row.get("status")
    status = _tokens(status) if isinstance(status, list) else _token(status)
    return _compact({"name": name, "status": status})


def _window(row):
    if not isinstance(row, dict):
        return None
    location = row.get("windowLocation")
    if location not in ("front", "rear"):
        return None
    return _compact(
        {"location": location, "state": _token(row.get("windowHeatingState"))}
    )


def _service(row):
    if not isinstance(row, dict) or (ident := _token(row.get("id"))) is None:
        return None
    expiration = row.get("expirationDate")
    if isinstance(expiration, str) and len(expiration) <= 40:
        try:
            datetime.fromisoformat(expiration.replace("Z", "+00:00"))
        except ValueError:
            expiration = None
    else:
        expiration = None
    status = row.get("status")
    # Audi Q8 reports integer status codes. Preserve them separately from
    # textual enums; do not infer impairment meaning or control authority.
    codes = (
        [
            value
            for value in status[:32]
            if type(value) is int and 0 <= value <= 2147483647
        ]
        if isinstance(status, list)
        else [status]
        if type(status) is int and 0 <= status <= 2147483647
        else None
    )
    return _compact(
        {
            "id": ident,
            "expiration_date": expiration,
            "user_disabling_allowed": _boolean(row.get("userDisablingAllowed")),
            "status": _tokens(status) if isinstance(status, list) else _token(status),
            "status_codes": codes if codes else None,
        }
    )


def _warning(row):
    """Known Audi warning/campaign fields, no embedded SVG or personal IDs."""
    if not isinstance(row, dict):
        return None
    return (
        _compact(
            {
                "message_id": _token(row.get("messageId")),
                "event_id": _token(row.get("eventId")),
                "category": _token(row.get("category")),
                "priority": _token(row.get("priority")),
                "icon_color": _token(row.get("iconColor")),
                "type": _token(row.get("type")),
                "occurred_at": _zoned_datetime(row.get("timeOfOccurrence")),
                "online_update_relevance": _token(row.get("oruRelevant")),
                "text": row["text"][:300] if isinstance(row.get("text"), str) else None,
            }
        )
        or None
    )


def _request_status(row):
    """Observed OEM command metadata; never imply physical success or replay."""
    if not isinstance(row, dict):
        return None
    operation, status = _token(row.get("operation")), _token(row.get("status"))
    if operation is None or status is None:
        return None
    return _compact(
        {
            "operation": operation,
            "status": status,
            "group": row["group"]
            if type(row.get("group")) is int and 0 <= row["group"] <= 2147483647
            else None,
        }
    )


def _array(rows, normalizer, limit):
    if not isinstance(rows, list):
        return None
    values = [normalizer(row) for row in rows[:limit]]
    return {
        "items": [row for row in values if row is not None],
        "received_count": len(rows),
        "normalized_count": sum(row is not None for row in values),
        "truncated": len(rows) > limit,
        "all_items_recognized": len(rows) <= limit
        and all(row is not None for row in values),
    }


def observe_structured(vehicle, payload, observed_at, accepts):
    """Keep capture-aware structured readings alongside the native scalars."""

    def put(key, value, captured, path, *, invalid=False):
        if value is not None and accepts(vehicle.readings.get(key), captured):
            vehicle.readings[key] = {
                "value": value,
                "captured": captured,
                "observed": observed_at.isoformat(),
                "path": path,
                "family": "cariad",
                "job": path.split(".", 1)[0],
                "status": "invalid_value"
                if invalid
                else "verified"
                if timestamp_is_fresh(captured, observed_at)
                else "readable_but_stale",
            }

    for key, path, field, normalizer, limit in (
        (
            "charging_timers_detail",
            "chargingTimers.chargingTimersStatus.value",
            "timers",
            _timer,
            30,
        ),
        (
            "climate_timers_detail",
            "climatisationTimers.climatisationTimersStatus.value",
            "timers",
            _timer,
            30,
        ),
        (
            "ventilation_timers_detail",
            "climatisationTimers.activeVentilationTimersStatus.value",
            "timers",
            _timer,
            30,
        ),
        (
            "departure_charging_timers_detail",
            "departureTimers.chargingTimersStatus.value",
            "timers",
            _timer,
            30,
        ),
        (
            "departure_climate_timers_detail",
            "departureTimers.climatisationTimersStatus.value",
            "timers",
            _timer,
            30,
        ),
        ("door_detail", "access.accessStatus.value", "doors", _component, 30),
        ("window_detail", "access.accessStatus.value", "windows", _component, 30),
        ("light_detail", "vehicleLights.lightsStatus.value", "lights", _component, 30),
        (
            "window_heating_detail",
            "climatisation.windowHeatingStatus.value",
            "windowHeatingStatus",
            _window,
            12,
        ),
    ):
        block = read_json_path(payload, path)
        if isinstance(block, dict) and field in block:
            data = _array(block.get(field), normalizer, limit)
            if data is not None and normalizer is _timer:
                data["vehicle_time"] = _zoned_datetime(block.get("timeInCar"))
            from .vehicle import window_heating_active

            put(
                key,
                data,
                block.get("carCapturedTimestamp"),
                path,
                invalid=normalizer is _window
                and window_heating_active(block.get(field)) is None,
            )
    # An empty warningLights object is not a healthy-state claim.
    warnings_path = "vehicleHealthWarnings.warningLights.value"
    warnings = read_json_path(payload, warnings_path)
    if isinstance(warnings, dict):
        lights = _array(warnings.get("warningLights"), _warning, 50)
        campaigns = _array(warnings.get("campaigns"), _warning, 50)
        put(
            "health_warning_evidence_detail",
            {
                "envelope_present": True,
                "warning_state": "reported"
                if lights and lights["normalized_count"]
                else "unknown",
                "empty_envelope": not bool(warnings),
                "warnings": lights,
                "campaigns": campaigns,
                "mileage_km": warnings["mileage_km"]
                if type(warnings.get("mileage_km")) in (int, float)
                and 0 <= warnings["mileage_km"] <= 2000000
                else None,
            },
            warnings.get("carCapturedTimestamp"),
            warnings_path,
        )
    readiness_path = "readiness.readinessStatus.value"
    readiness = read_json_path(payload, readiness_path)
    if isinstance(readiness, dict):
        connection = readiness.get("connectionState")
        warning = readiness.get("connectionWarning")
        data = {}
        if isinstance(connection, dict):
            data.update(
                _compact(
                    {
                        "online": _boolean(connection.get("isOnline")),
                        "active": _boolean(connection.get("isActive")),
                        "battery_power_level": _token(
                            connection.get("batteryPowerLevel")
                        ),
                        "daily_power_budget_available": _boolean(
                            connection.get("dailyPowerBudgetAvailable")
                        ),
                    }
                )
            )
        if isinstance(warning, dict):
            data.update(
                _compact(
                    {
                        "insufficient_battery_warning": _boolean(
                            warning.get("insufficientBatteryLevelWarning")
                        ),
                        "daily_power_budget_warning": _boolean(
                            warning.get("dailyPowerBudgetWarning")
                        ),
                    }
                )
            )
        if data:
            put(
                "readiness_detail",
                data,
                readiness.get("carCapturedTimestamp"),
                readiness_path,
            )
    for care_path in (
        "batteryChargingCare.chargingCareSettings.value",
        "charging.chargingCareSettings.value",
    ):
        care = read_json_path(payload, care_path)
        if isinstance(care, dict):
            mode = care.get("batteryCareMode")
            if mode in ("activated", "deactivated"):
                put(
                    "battery_care_detail",
                    {"mode": mode},
                    care.get("carCapturedTimestamp"),
                    care_path,
                )
    # Shared CARIAD reference schema; not evidence of Audi support unless read.
    for detail_key, path in (
        ("low_voltage_battery_detail", "lvBattery.lvBatteryStatus.value"),
        ("battery_support_detail", "batterySupport.batterySupportStatus.value"),
    ):
        value = read_json_path(payload, path)
        if isinstance(value, dict):
            state = value.get("batterySupport")
            if state in (
                "notAllowed",
                "pendingDisable",
                "disabled",
                "pendingEnable",
                "enabled",
            ):
                put(
                    detail_key,
                    {"battery_support": state},
                    value.get("carCapturedTimestamp"),
                    path,
                )
    block = read_json_path(payload, "access.accessStatus.value")
    if isinstance(block, dict):
        put(
            "access_overall_detail",
            _token(block.get("overallStatus")),
            block.get("carCapturedTimestamp"),
            "access.accessStatus.value.overallStatus",
        )
    # b12 exposed these two fields in the climate status envelope. Its
    # vehicle capture belongs to the climate reading, not to the requests.
    for key, requests_path in (
        ("climate_requests_detail", "climatisation.climatisationStatus.requests"),
        ("access_requests_detail", "access.accessStatus.requests"),
    ):
        requests = read_json_path(payload, requests_path)
        if isinstance(requests, list):
            put(key, _array(requests, _request_status, 30), None, requests_path)
    services = read_json_path(payload, "userCapabilities.capabilitiesStatus.value")
    if isinstance(services, list):
        put(
            "connected_services_detail",
            _array(services, _service, 200),
            None,
            "userCapabilities.capabilitiesStatus.value",
        )


def details_for(vehicle, *keys):
    """Expose normalized data and its own provenance, never an invented timestamp."""
    result = {}
    for key in keys:
        row = vehicle.readings.get(key)
        if row is not None:
            result[key.removesuffix("_detail")] = {
                "data": row.get("value"),
                **reading_freshness_attributes(row),
                "source": row.get("path"),
            }
    return result
