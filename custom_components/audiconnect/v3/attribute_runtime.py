"""V3 read-only attribute recovery from one shared CARIAD selective-status batch.

No V2 runtime imports, no automatic vehicle commands or position requests.
"""

from __future__ import annotations
from datetime import UTC, datetime
from typing import Any
from .freshness import capture_age_minutes, timestamp_is_fresh
from .historical_catalog import (
    ATTRIBUTES,
    V2_JOBS,
    advertised_capabilities,
    extract_attributes,
)
from .api_value_mappings import normalize_api_value, transform_for
from .attribute_contracts import semantic_value_issue


def planned_jobs(vehicle: Any, profile: Any) -> tuple[str, ...]:
    """One reviewed batch; negative evidence only suppresses extra probes.

    Including known jobs in this existing GET costs no additional request and
    allows a previously unsupported job to recover through normal polling.
    """
    return tuple(V2_JOBS)


def _capture_in_utc(value: Any) -> datetime | None:
    """Parse a vehicle capture time without treating cloud receipt as capture."""
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(UTC) if stamp.tzinfo is not None else None


def _accept_observation(previous: dict[str, Any] | None, captured: Any) -> bool:
    """Never replace a newer car reading with an older cached API value."""
    if previous is None:
        return True
    prior = _capture_in_utc(previous.get("captured"))
    incoming = _capture_in_utc(captured)
    if prior is None:
        return True
    return incoming is not None and incoming >= prior


def validate_last_known_climate(row, now=None):
    """Bounded display-only observation; never a source of authorization."""
    from .freshness import capture_age_minutes
    from .vehicle import CLIMATE_OFF_STATES, CLIMATE_ON_STATES

    if not isinstance(row, dict):
        return None
    value, captured = row.get("value"), row.get("captured")
    if (
        not isinstance(value, str)
        or value not in CLIMATE_OFF_STATES + CLIMATE_ON_STATES
        or capture_age_minutes(captured, now) is None
    ):
        return None
    return {"value": value, "captured": captured}


def remember_climate(profile, reading, now=None):
    """Keep the most recent valid sample, including across sentinel responses."""
    if reading.get("status") not in ("verified", "readable_but_stale"):
        return
    row = validate_last_known_climate(reading, now)
    if row and _accept_observation(
        getattr(profile, "last_known_climate", None), row["captured"]
    ):
        profile.last_known_climate = row


def _observation_rank(row, registry, now):
    """One ordering at the write boundary: valid, fresh, family, capture."""
    family = row.get("family", "")
    priority = (
        registry.family_priority(family)
        if registry is not None and family in registry.families
        else 100
    )
    age = capture_age_minutes(row.get("captured"), now)
    valid = row.get("value") is not None and row.get("status") != "invalid_value"
    stamp = _capture_in_utc(row.get("captured")) if age is not None else None
    captured = stamp.timestamp() if stamp else float("-inf")
    if valid and age is not None and age <= 60:
        return (3, -priority, captured, family)
    if valid and age is not None:
        return (2, captured, -priority, family)
    if valid:
        return (1, -priority, captured, family)
    return (0, captured, -priority, family)


def _current_candidates(vehicle, ident):
    previous = vehicle.readings.get(ident)
    candidates = vehicle.family_readings.setdefault(ident, {})
    if previous is None:
        candidates.clear()
    else:
        # Preserve a newer existing direct projection rather than reviving cache.
        source = previous.get("family", "")
        if _accept_observation(candidates.get(source), previous.get("captured")):
            candidates[source] = previous
    return candidates


def _select_observation(vehicle, ident, candidates, registry, now):
    vehicle.readings[ident] = max(
        candidates.values(), key=lambda sample: _observation_rank(sample, registry, now)
    )


def _commit_observation(vehicle, ident, row, registry, now):
    """Keep one sample per family; choose from the same set in either arrival order."""
    candidates = _current_candidates(vehicle, ident)
    family = row["family"]
    if not _accept_observation(candidates.get(family), row.get("captured")):
        return False
    candidates[family] = row
    _select_observation(vehicle, ident, candidates, registry, now)
    return vehicle.readings[ident] is row


def refresh_family_observations(vehicle, profile, now):
    """Re-evaluate cached competing observations at the existing publish boundary."""
    for ident in vehicle.family_readings:
        candidates = _current_candidates(vehicle, ident)
        if len(candidates) > 1:
            _select_observation(vehicle, ident, candidates, profile.registry, now)


def record_invalid_observation(
    vehicle: Any,
    ident: str,
    captured: Any,
    observed_at: datetime,
    path: str,
    job: str | None,
    reason: str,
    family: str = "cariad",
    *,
    profile=None,
) -> None:
    """An explicit invalid sample invalidates only the originating family."""
    _commit_observation(
        vehicle,
        ident,
        {
            "value": None,
            "captured": captured,
            "observed": observed_at.isoformat(),
            "fresh": False,
            "path": path,
            "job": job,
            "status": "invalid_value",
            "family": family,
            "reason": reason,
        },
        getattr(profile, "registry", None),
        observed_at,
    )


def record_observation(
    vehicle,
    profile,
    ident,
    value,
    captured,
    observed_at,
    path,
    job,
    family,
    *,
    fresh,
    operation,
    persist_evidence=True,
    delivered_at=None,
):
    """Commit one normalized observation; persist only reviewed mapping evidence."""
    status = "verified" if fresh else "readable_but_stale"
    row = {
        "value": value,
        "captured": captured,
        "observed": observed_at.isoformat(),
        "fresh": fresh,
        "path": path,
        "job": job,
        "status": status,
        "family": family,
        "operation": operation,
    }
    if delivered_at is not None:
        row["delivered_at"] = delivered_at
    if not _commit_observation(
        vehicle, ident, row, getattr(profile, "registry", None), observed_at
    ):
        return False
    if ident == "climatisationState":
        remember_climate(profile, row, observed_at)
    if persist_evidence:
        profile.attribute_evidence[ident] = {
            "status": status,
            "path": path,
            "job": job,
            "source": "mbb.legacy" if family == "mbb" else "cariad.selectivestatus",
            "timestamp_present": bool(captured),
        }
    return True


def normalize_attribute_value(definition, value, conversion):
    """Shared scalar mapping semantics for batch and selected attribute routes.

    Preserve meaningful false/zero and external-power 'unavailable'. Reject
    error envelopes and never turn missing data into a working mapping.
    """
    ident = definition["id"]
    if ident == "availableChargeModes":
        # An explicit empty list is meaningful: no advertised write options.
        if (
            isinstance(value, list)
            and len(value) <= 32
            and all(isinstance(mode, str) and len(mode) <= 80 for mode in value)
        ):
            return value, None
        return None, "invalid_charge_mode_options"
    if ident == "preferredChargeMode" and not isinstance(value, str):
        return None, "invalid_preferred_charge_mode"
    if (
        value is None
        or isinstance(value, dict)
        and ("error" in value or not value)
        or isinstance(value, list)
        and not value
    ):
        return None, None
    try:
        value = normalize_api_value(value, conversion)
    except ValueError:
        return None, None
    if definition.get("local"):
        from .custom_attributes import normalize_local_value

        value = normalize_local_value(value, definition)
    issue = semantic_value_issue(
        definition["entity_key"], value, definition.get("contract")
    )
    if issue:
        return None, issue
    if (
        isinstance(value, str)
        and value.strip().lower()
        in (
            "",
            "unknown",
            "unsupported",
            "invalid",
            "unavailable",
            "error",
            "notavailable",
        )
        and not (
            definition["id"] == "externalPower"
            and value.strip().lower() == "unavailable"
        )
    ):
        return None, {
            "chargingState": "unknown_charging_state",
            "preferredChargeMode": "invalid_preferred_charge_mode",
        }.get(ident)
    if value is not None and len(str(value)) > 10000:
        return None, None
    return value, None


def observe_read_only(
    vehicle: Any, profile: Any, payload: Any, observed_at: datetime
) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {"mapped": 0, "fresh": 0}
    reported, impaired = advertised_capabilities(payload)
    if reported:
        vehicle.advertised_capabilities = reported
        vehicle.impaired_capabilities = impaired
    mapped = fresh_count = 0
    for row in extract_attributes(payload):
        ident = row["id"]
        selected = profile.attribute_routes.get(ident)
        if selected and selected != "cariad.selectivestatus.batch":
            continue
        value, issue = normalize_attribute_value(
            ATTRIBUTES[ident], row["value"], transform_for("cariad", ident)
        )
        if issue:
            record_invalid_observation(
                vehicle,
                ident,
                row["captured"],
                observed_at,
                row["path"],
                row["job"],
                issue,
                profile=profile,
            )
        if value is None:
            continue
        fresh = timestamp_is_fresh(row["captured"], observed_at)
        if not record_observation(
            vehicle,
            profile,
            ident,
            value,
            row["captured"],
            observed_at,
            row["path"],
            row["job"],
            "cariad",
            fresh=fresh,
            operation="cariad.climate.status.batch",
        ):
            continue
        # A proven V2 response field is *readable* even if the vehicle's
        # capture time is older than 60 minutes.  Activation exposes a clearly
        # marked last-known sensor, not a fresh control or lock reading.
        if (
            ident not in profile.attribute_routes
            and ident not in getattr(profile, "attribute_disabled", ())
            and ATTRIBUTES[ident]["platform"] in ("sensor", "binary_sensor")
        ):
            profile.attribute_routes[ident] = "cariad.selectivestatus.batch"
        mapped += 1
        fresh_count += int(fresh)
    from .derived_values import observe_derived

    observe_derived(vehicle, profile, payload, observed_at, _accept_observation)
    from .structured_details import observe_structured

    observe_structured(vehicle, payload, observed_at, _accept_observation)
    vehicle.v2_initial_discovery_completed = True
    return {"mapped": mapped, "fresh": fresh_count}


def data_act_observations(payload, now, registry):
    """Exact UUID + field-name mappings; one best timestamp per semantic field."""
    fields = registry.families["eu_data_act"]["observations"]
    candidates = {}
    for item in payload["Data"]:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            continue
        key = item["key"]
        mapping = fields.get(key)
        if not mapping or item.get("dataFieldName") != mapping["field"]:
            continue
        raw = item.get("value")
        if type(raw) not in (str, int, float):
            continue
        ident = mapping["attribute"]
        if "values" in mapping:
            value = mapping["values"].get(str(raw))
            if value is None:
                continue
        else:
            try:
                value = float(raw)
            except (ValueError, OverflowError):
                continue
            if not mapping["min"] <= value <= mapping["max"]:
                continue
            # The OEM mileage field is unsignedInt, not a bounded uint16 signal.
            if ident == "UTC_TIME_AND_KILOMETER_STATUS" and not value.is_integer():
                continue
            if "scale" in mapping:
                value = round(value * mapping["scale"] + mapping["offset"], 2)
        value, _ = normalize_attribute_value(ATTRIBUTES[ident], value, None)
        if value is None:
            continue
        captured = item.get("timestampUtc")
        if capture_age_minutes(captured, now) is None:
            captured = None
        candidates.setdefault(ident, []).append((captured, value, key))
    result = {}
    for ident, rows in candidates.items():
        latest = max((_capture_in_utc(row[0]) for row in rows if row[0]), default=None)
        matching = [row for row in rows if _capture_in_utc(row[0]) == latest]
        if len({row[1] for row in matching}) != 1:
            continue
        captured, value, key = min(matching, key=lambda row: row[2])
        result[ident] = {"value": value, "captured": captured, "path": key}
    return result


def observe_data_act(vehicle, profile, payload, observed_at, delivered_at):
    """Reuse canonical informational readings; never activate control evidence."""
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("vin"), str)
        or payload["vin"].upper() != vehicle.vin.upper()
        or not isinstance(payload.get("Data"), list)
    ):
        return False
    accepted = False
    for ident, sample in data_act_observations(
        payload, observed_at, profile.registry
    ).items():
        if ident in getattr(profile, "attribute_disabled", ()):
            continue
        accepted |= record_observation(
            vehicle,
            profile,
            ident,
            sample["value"],
            sample["captured"],
            observed_at,
            sample["path"],
            ATTRIBUTES[ident]["job"],
            "eu_data_act",
            fresh=timestamp_is_fresh(sample["captured"], observed_at),
            operation="eu_data_act.dataset",
            persist_evidence=False,
            delivered_at=delivered_at,
        )
    return accepted
