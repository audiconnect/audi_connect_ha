"""Conservative physical state readback for supported command semantics.

No new mutation or extra per-command request. An observed expected state
is separate from backend execution proof; unsupported transient commands
remain backend-only or require manual review.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .attribute_runtime import _capture_in_utc, _valid_capture, select_reading
from .vehicle import (
    CLIMATE_ON_STATES,
    CLIMATE_OFF_STATES,
    CHARGING_ON_STATES,
    CHARGING_OFF_STATES,
)


def configure_readback(record, params):
    values = params or {}
    lookup = {
        ("climate", "start"): ("climate", list(CLIMATE_ON_STATES)),
        ("climate", "start_with_settings"): ("climate", list(CLIMATE_ON_STATES)),
        ("climate", "stop"): ("climate", list(CLIMATE_OFF_STATES)),
        ("charging", "start"): ("chargingState", list(CHARGING_ON_STATES)),
        ("charging", "stop"): ("chargingState", list(CHARGING_OFF_STATES)),
        ("climate", "window_heating_start"): ("windowHeatingActive", [True]),
        ("climate", "window_heating_stop"): ("windowHeatingActive", [False]),
        ("climate", "preheater_start"): ("preheater_active", [True]),
        ("climate", "preheater_stop"): ("preheater_active", [False]),
        ("access", "lock"): ("doorLockStatus", ["locked"]),
        ("access", "unlock"): ("doorLockStatus", ["unlocked"]),
    }
    match = lookup.get((record.capability, record.action))
    if (record.capability, record.action) == ("charging", "set_target_soc"):
        value = values.get("value")
        if type(value) is int and value in range(20, 101, 5):
            match = ("targetstateOfCharge", [value])
    if (record.capability, record.action) == ("charging", "set_charge_mode"):
        value = values.get("value")
        if value in ("manual", "timer"):
            match = ("preferredChargeMode", [value])
    if (record.capability, record.action) == ("climate", "set_settings"):
        fields = {
            "windowHeatingEnabled": "climatisationWindowHeatingEnabled",
            "climatizationAtUnlock": "climatisationAtUnlock",
            "zoneFrontLeftEnabled": "climatisationZoneFrontLeft",
            "zoneFrontRightEnabled": "climatisationZoneFrontRight",
            "zoneRearLeftEnabled": "climatisationZoneRearLeft",
            "zoneRearRightEnabled": "climatisationZoneRearRight",
        }
        if len(values) == 1:
            field, value = next(iter(values.items()))
            if field in fields and type(value) is bool:
                match = (fields[field], [value])
    if (
        record.capability == "climate"
        and record.action in ("start_with_settings", "set_settings")
        and {"temp_c", "temp_f"} & values.keys()
    ):
        from .command_parameters import temperature_celsius

        match = (
            "climatisationTargetTemperatureC",
            [temperature_celsius(values, None)],
        )
    if match:
        record.readback_attribute, record.readback_values = match


def _readback_row(car, attribute, now=None, *, registry=None):
    """Use native evidence, independently of the selected display observation."""
    key = "climatisationState" if attribute == "climate" else attribute
    _, row = select_reading(
        car, (key,), key, now=now, registry=registry, families=("cariad", "mbb", "")
    )
    return row or {}


def _readback_value(car, attribute, now=None, *, registry=None, started_at=None):
    row = _readback_row(car, attribute, now, registry=registry)
    observed = _capture_in_utc(row.get("observed"))
    if row.get("status") == "invalid_value" or (
        started_at is not None
        and (observed is None or observed.timestamp() <= started_at)
    ):
        return None, None
    return row.get("value"), _valid_capture(row.get("captured"), observed or now)


def configure_discovery_readback(record, car, params, *, registry=None):
    """Only auto-confirm an observed change from a known, different pre-test state."""
    configure_readback(record, params)
    if not record.readback_attribute:
        return
    value, captured = _readback_value(car, record.readback_attribute, registry=registry)
    if isinstance(value, str):
        value = value.strip().lower()
    now = datetime.now(UTC)
    known_states = {
        "climate": CLIMATE_ON_STATES + CLIMATE_OFF_STATES,
        "chargingState": CHARGING_ON_STATES + CHARGING_OFF_STATES,
    }
    states = known_states.get(record.readback_attribute)
    # Restrict unattended verification to well-defined comfort/charging states
    # and boolean window heating. Security and wake require explicit review.
    known = (
        value in states
        if states
        else record.readback_attribute == "windowHeatingActive" and type(value) is bool
    )
    if (
        not known
        or captured is None
        or not -300 <= (now - captured).total_seconds() <= 3600
        or value in record.readback_values
    ):
        record.readback_attribute, record.readback_values = None, None


def reconcile_readback(record, car, now=None, *, registry=None) -> bool:
    if record.state not in ("accepted_unconfirmed", "backend_completed", "uncertain"):
        return False
    if not record.readback_attribute or not record.readback_values:
        return False
    now = now or datetime.now(UTC)
    value, captured = _readback_value(
        car,
        record.readback_attribute,
        now,
        registry=registry,
        started_at=record.started_at,
    )
    if captured is None or captured.timestamp() <= record.started_at:
        return False
    age = (now - captured).total_seconds()
    if not -300 <= age <= 3600:
        return False
    if isinstance(value, str):
        value = value.strip().lower()
    expects_bool = all(type(v) is bool for v in record.readback_values)
    if (type(value) is bool) != expects_bool:
        return False
    if value not in record.readback_values:
        return False
    if (
        record.action == "start_with_settings"
        and record.readback_attribute == "climatisationTargetTemperatureC"
    ):
        climate, climate_stamp = _readback_value(
            car, "climate", now, registry=registry, started_at=record.started_at
        )
        if (
            not isinstance(climate, str)
            or climate.strip().lower() not in CLIMATE_ON_STATES
            or climate_stamp is None
            or climate_stamp.timestamp() <= record.started_at
            or not -300 <= (now - climate_stamp).total_seconds() <= 3600
        ):
            return False
    record.state = "verified"
    record.completed_at = max(record.started_at, now.timestamp())
    return True


def reconcile_access_mismatch(record, car, now=None, *, registry=None) -> bool:
    """Close an accepted lock attempt on a later reliable contrary observation.

    This is not proof that the command physically failed: the car may have
    been operated externally. Never close a transport-uncertain mutation this way.
    """
    from .command_journal import TEMPORARY_ERROR_COOLDOWN_SECONDS

    if (
        record.origin != "home_assistant"
        or record.capability != "access"
        or record.readback_attribute != "doorLockStatus"
        or record.state
        not in ("accepted_unconfirmed", "backend_completed", "uncertain")
        or record.http_status is None
        or not 200 <= record.http_status < 300
        or record.backend_result == "transport_uncertain"
    ):
        return False
    now = now or datetime.now(UTC)
    value, stamp = _readback_value(
        car, "doorLockStatus", now, registry=registry, started_at=record.started_at
    )
    if (
        stamp is None
        or stamp.timestamp() < record.started_at + TEMPORARY_ERROR_COOLDOWN_SECONDS
        or not 0 <= (now - stamp).total_seconds() <= 3600
        or not isinstance(value, str)
        or value.strip().lower() not in ("locked", "unlocked")
        or not record.readback_values
        or value.strip().lower() in record.readback_values
    ):
        return False
    record.state = "readback_mismatch"
    record.completed_at = max(record.started_at, now.timestamp())
    return True


# UI projection is separate from actual telemetry and physical evidence.
# Only explicit, successfully accepted HA actions are eligible.
OPTIMISTIC_TTL_SECONDS = 30 * 60
_ACCEPTED = frozenset({"accepted_unconfirmed", "backend_completed"})
_OPTIMISTIC = {
    "climate": ("on", "off"),
    "chargingState": ("charging", "off"),
}


def latest_readback_command(profile, attribute):
    return next(
        (
            record
            for record in reversed(getattr(profile, "command_journal", ()))
            if record.origin == "home_assistant"
            and record.readback_attribute == attribute
            and record.state != "rejected"
        ),
        None,
    )


def command_attributes(profile, capability, actions, *, attribute=None):
    """Shared command evidence, including rejection, scoped to this control."""
    record = next(
        (
            row
            for row in reversed(getattr(profile, "command_journal", ()))
            if row.origin == "home_assistant"
            and row.capability == capability
            and row.action in actions
            and (
                attribute is None
                or row.readback_attribute == attribute
                or (
                    attribute == "climate"
                    and row.action == "start_with_settings"
                    and row.readback_attribute == "climatisationTargetTemperatureC"
                )
            )
        ),
        None,
    )
    requested = None
    if record is not None:
        values = record.readback_values or []
        if record.readback_attribute in _OPTIMISTIC:
            requested = _OPTIMISTIC[record.readback_attribute][
                1 if record.action == "stop" else 0
            ]
        elif len(values) == 1:
            requested = values[0]
    return {
        "command_status": record.state if record else None,
        "command_requested_state": requested,
        "command_action": record.action if record else None,
        "command_backend_result": record.backend_result if record else None,
        "command_http_status": record.http_status if record else None,
        "command_requested_at": (
            datetime.fromtimestamp(record.started_at, UTC).isoformat()
            if record
            else None
        ),
        "command_completed_at": (
            datetime.fromtimestamp(record.completed_at, UTC).isoformat()
            if record and record.completed_at is not None
            else None
        ),
    }


def last_known_climate(profile):
    """Return (value, timestamp, source) without promoting historical evidence."""
    from .attribute_runtime import validate_last_known_climate

    row = validate_last_known_climate(getattr(profile, "last_known_climate", None))
    # A verified command or an explicitly reviewed physical test can supply a
    # historical observation even when the API status field is unavailable.
    record = next(
        (
            record
            for record in reversed(getattr(profile, "command_journal", ()))
            if record.capability == "climate"
            and record.action in ("start", "stop", "start_with_settings")
            and record.state == "verified"
            and record.completed_at is not None
            and (
                record.readback_attribute == "climate"
                or (
                    record.origin == "workbench"
                    and getattr(profile, "control_results", {}).get(record.operation)
                    == "worked"
                )
            )
        ),
        None,
    )
    if row and (
        record is None
        or _capture_in_utc(row["captured"]).timestamp() > record.started_at
    ):
        return row["value"], row["captured"], "last_known_vehicle"
    if record is not None:
        try:
            stamp = datetime.fromtimestamp(record.completed_at, UTC)
        except (ValueError, OverflowError, OSError):
            stamp = None
        if stamp and stamp.year >= 2020 and stamp <= datetime.now(UTC):
            return (
                "off" if record.action == "stop" else "on",
                stamp.isoformat(),
                "last_verified_command",
            )
    if row:
        return row["value"], row["captured"], "last_known_vehicle"
    return None, None, "unknown"


def projected_state(
    profile, attribute, reported, captured, *, now=None, optimistic=True
):
    """Return (effective value, source). A newer valid report always wins.

    No optimistic write to readings, no physical verification from HTTP,
    no replay, and no optimism for workbench, rejected or uncertain commands.
    """
    record = latest_readback_command(profile, attribute)
    if record is None:
        return reported, "vehicle" if reported is not None else "unknown"
    stamp = captured if isinstance(captured, datetime) else _capture_in_utc(captured)
    if (
        reported is not None
        and stamp is not None
        and stamp.timestamp() > record.started_at
    ):
        return reported, "vehicle"
    if record.state not in _ACCEPTED | {"pending", "uncertain"}:
        return reported, "vehicle" if reported is not None else "unknown"
    if record.origin != "home_assistant":
        return reported, "vehicle" if reported is not None else "unknown"
    age = (now or datetime.now(UTC)).timestamp() - record.started_at
    if record.state not in _ACCEPTED or not 0 <= age < OPTIMISTIC_TTL_SECONDS:
        return None, "unknown"
    if not optimistic:
        return None, "command_pending"
    values = record.readback_values or []
    if not values:
        return None, "unknown"
    if attribute in _OPTIMISTIC:
        value = _OPTIMISTIC[attribute][1 if record.action == "stop" else 0]
    elif len(values) == 1:
        value = values[0]
    else:
        return None, "unknown"
    return value, "command_pending"


def observe_command_response(record, car, profile, family, response):
    """Normalize real post-command captures through the existing observation writer.

    Only reviewed selective-status jobs and their value envelopes are eligible.
    A request echo, status, receipt clock or HTTP success is not telemetry.
    """
    if (
        family != "cariad"
        or not 200 <= response.status < 300
        or not isinstance(response.data, dict)
        or response.observed_at.timestamp() <= record.started_at
    ):
        return False
    from .attribute_runtime import observe_read_only
    from .freshness import project_vehicle_capture
    from .historical_catalog import V2_JOBS

    payload = {}
    for job in V2_JOBS:
        groups = response.data.get(job)
        if not isinstance(groups, dict):
            continue
        for group, envelope in groups.items():
            if not isinstance(envelope, dict):
                continue
            value = envelope.get("value")
            if not isinstance(value, dict):
                continue
            captured = _valid_capture(
                value.get("carCapturedTimestamp"), response.observed_at
            )
            if captured is None or captured.timestamp() <= record.started_at:
                continue
            payload.setdefault(job, {})[group] = {"value": value}
    if not payload:
        return False
    observe_read_only(
        car,
        profile,
        payload,
        response.observed_at,
        operation=record.operation,
        complete_discovery=False,
    )
    project_vehicle_capture(car, response.observed_at)
    reconcile_readback(record, car, response.observed_at, registry=profile.registry)
    reconcile_access_mismatch(
        record, car, response.observed_at, registry=profile.registry
    )
    return True
