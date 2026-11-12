"""Conservative physical state readback for supported command semantics.

No new mutation or extra per-command request. An observed expected state
is separate from backend execution proof; unsupported transient commands
remain backend-only or require manual review.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .attribute_runtime import _capture_in_utc
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
    if match:
        record.readback_attribute, record.readback_values = match


def configure_discovery_readback(record, car, params):
    """Only auto-confirm an observed change from a known, different pre-test state."""
    configure_readback(record, params)
    if not record.readback_attribute:
        return
    if record.readback_attribute == "climate":
        value, captured = car.climate_state, car.climate_captured
    else:
        row = car.readings.get(record.readback_attribute) or {}
        value, captured = row.get("value"), _capture_in_utc(row.get("captured"))
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


def reconcile_readback(record, car, now=None) -> bool:
    if record.state not in ("accepted_unconfirmed", "backend_completed", "uncertain"):
        return False
    if not record.readback_attribute or not record.readback_values:
        return False
    if record.readback_attribute == "climate":
        value, captured = car.climate_state, car.climate_captured
    else:
        row = car.readings.get(record.readback_attribute) or {}
        value, captured = row.get("value"), _capture_in_utc(row.get("captured"))
    now = now or datetime.now(UTC)
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
    record.state = "verified"
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
    """Consume only reviewed actual telemetry envelopes, never request status."""
    if family != "cariad" or not isinstance(response.data, dict):
        return
    from .attribute_runtime import observe_read_only
    from .registry import read_json_path

    paths = {
        "climate": ("climatisation", "climatisationStatus"),
        "chargingState": ("charging", "chargingStatus"),
        "windowHeatingActive": ("climatisation", "windowHeatingStatus"),
        "doorLockStatus": ("access", "accessStatus"),
        "targetstateOfCharge": ("charging", "chargingSettings"),
        "preferredChargeMode": ("charging", "chargeMode"),
    }
    if record.readback_attribute in (
        "climatisationWindowHeatingEnabled",
        "climatisationAtUnlock",
        "climatisationZoneFrontLeft",
        "climatisationZoneFrontRight",
        "climatisationZoneRearLeft",
        "climatisationZoneRearRight",
    ):
        paths[record.readback_attribute] = ("climatisation", "climatisationSettings")
    path = paths.get(record.readback_attribute)
    if not path:
        return
    job, group = path
    envelope = read_json_path(response.data, f"{job}.{group}")
    if not isinstance(envelope, dict):
        return
    value = envelope.get("value")
    captured = (
        _capture_in_utc(value.get("carCapturedTimestamp"))
        if isinstance(value, dict)
        else None
    )
    if captured is None or captured.timestamp() <= record.started_at:
        return
    observe_read_only(car, profile, {job: {group: envelope}}, response.observed_at)
    reconcile_readback(record, car, response.observed_at)
