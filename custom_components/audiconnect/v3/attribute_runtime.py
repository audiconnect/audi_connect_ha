"""V3 read-only attribute recovery from one shared CARIAD selective-status batch.

No V2 runtime imports, no automatic vehicle commands or position requests.
"""

from __future__ import annotations

import re
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


def _valid_capture(value: Any, now: datetime | None = None) -> datetime | None:
    """Use the shared capture validity policy for chronological ordering."""
    if capture_age_minutes(value, now) is None:
        return None
    return _capture_in_utc(value)


def _accept_observation(
    previous: dict[str, Any] | None, captured: Any, now: datetime | None = None
) -> bool:
    """Never replace a newer car reading with an older cached API value."""
    if previous is None:
        return True
    prior = _valid_capture(
        previous.get("captured"), _capture_in_utc(previous.get("observed")) or now
    )
    incoming = _valid_capture(captured, now)
    if prior is None:
        return True
    return incoming is not None and incoming >= prior


# Persist native, dated scalar status only; no location, raw payload,
# custom attributes, capability proof or optional Data Act data.
_RETAINED_CONTROL_FIELDS = {
    "doorLockStatus",
    "climatisationState",
    "chargingState",
    "preferredChargeMode",
    "targetstateOfCharge",
    "climatisationTargetTemperatureC",
    "windowHeatingActive",
    "preheater_active",
    "climatisationWindowHeatingEnabled",
    "climatisationAtUnlock",
    "climatisationZoneFrontLeft",
    "climatisationZoneFrontRight",
    "climatisationZoneRearLeft",
    "climatisationZoneRearRight",
}


def retained_status_field(ident):
    from .attribute_contracts import binary_contract_for, contract_for

    if ident in _RETAINED_CONTROL_FIELDS:
        return True
    descriptor = ATTRIBUTES.get(ident, {})
    key = descriptor.get("entity_key", "")
    if not key or any(
        word in key for word in ("position", "park_time", "profile_name")
    ):
        return False
    contract = (
        binary_contract_for(key)
        if descriptor.get("platform") == "binary_sensor"
        else contract_for(key)
    )
    return contract.get("display_last_known") is True


def status_snapshot(readings, *, now=None):
    """Serialize the canonical status map, not an independent runtime cache."""
    result = {}
    for ident, reading in readings.items():
        known = last_known_observation(reading)
        value, captured = known.get("value"), known.get("captured")
        family = known.get("family")
        if (
            retained_status_field(ident)
            and family in ("cariad", "mbb")
            and type(value) in (str, int, float, bool)
            and (not isinstance(value, str) or 0 < len(value) <= 100)
            and (type(value) not in (int, float) or abs(value) <= 1e100)
            and _valid_capture(captured, now) is not None
            and not semantic_value_issue(
                ATTRIBUTES.get(ident, {}).get("entity_key", ""), value
            )
        ):
            result[ident] = {
                "value": value,
                "captured": captured,
                "family": family,
                "status": "readable_but_stale",
            }
    return result


def restore_status(saved, legacy_climate=None):
    """Restore as historical evidence only, never as an API response."""
    if not isinstance(saved, dict):
        saved = {}
    if (
        "climatisationState" not in saved
        and isinstance(legacy_climate, dict)
        and legacy_climate.get("value")
        in (
            "off",
            "stopped",
            "inactive",
            "heating",
            "cooling",
            "ventilation",
            "on",
            "active",
        )
    ):
        saved = {
            **saved,
            "climatisationState": {**legacy_climate, "family": "cariad"},
        }
    rows = {
        ident: row
        for ident, row in saved.items()
        if isinstance(ident, str) and isinstance(row, dict)
    }
    return {
        ident: {
            "value": None,
            "captured": row["captured"],
            "family": row["family"],
            "status": "invalid_value",
            "reason": "restored_history",
            "last_known": row,
        }
        for ident, row in status_snapshot(rows).items()
    }


def bind_status(vehicle, profile):
    """One live map per VIN; profiles only serialize/restore that map."""
    if profile is None or not hasattr(profile, "status_readings"):
        return
    if profile.status_readings is not vehicle.readings:
        for ident, row in profile.status_readings.items():
            vehicle.readings.setdefault(ident, row)
        profile.status_readings = vehicle.readings


def _observation_rank(row, registry, now):
    """Newest valid capture wins; priority only breaks equivalent timestamps."""
    family = row.get("family", "")
    priority = (
        registry.family_priority(family)
        if registry is not None and family in registry.families
        else 100
    )
    restored = row.get("reason") == "restored_history"
    valid = (
        row.get("value") is not None and row.get("status") != "invalid_value"
    ) or restored
    stamp = _valid_capture(
        row.get("captured"), _capture_in_utc(row.get("observed")) or now
    )
    captured = stamp.timestamp() if stamp else float("-inf")
    if valid and stamp is not None:
        return (2, captured, not restored, -priority, family)
    if valid:
        return (1, -priority, captured, family)
    return (0, captured, -priority, family)


def select_reading(
    vehicle, sources, canonical, *, registry=None, now=None, families=None
):
    """Select equivalent observations in the existing Status owner.

    A family restriction supplies evidence, not dispatch authorization.
    """
    valid = []
    cache = getattr(vehicle, "family_readings", {})
    for a in dict.fromkeys(sources):
        if a not in vehicle.readings:
            continue
        row = vehicle.readings[a]
        candidates = (
            dict(cache.get(a, {}))
            if registry is not None or families is not None
            else {}
        )
        candidates[row.get("family", "")] = row
        valid.extend(
            (a, sample)
            for sample in candidates.values()
            if (families is None or sample.get("family", "") in families)
            and (
                sample.get("value") is not None
                or sample.get("status") == "invalid_value"
            )
        )
    if not valid:
        return canonical, None

    reference = now or datetime.now(UTC)

    def score(item):
        row = item[1]
        stamp = _valid_capture(
            row.get("captured"), _capture_in_utc(row.get("observed")) or reference
        )
        return (
            stamp.timestamp() if stamp is not None else float("-inf"),
            item[0] == canonical,
            item[0],
        )

    # Resolve historical aliases within each family by capture first, then
    # apply the same family ranking as the observation writer. An explicit
    # invalid newer sample must still invalidate its own family.
    by_family = {}
    for item in valid:
        family = item[1].get("family", "")
        previous = by_family.get(family)
        if previous is None or score(item) > score(previous):
            by_family[family] = item
    if len(by_family) == 1 or (registry is None and families is None):
        return max(valid, key=score)
    return max(
        by_family.values(),
        key=lambda item: (
            _observation_rank(item[1], registry, reference),
            item[0] == canonical,
            item[0],
        ),
    )


def last_known_observation(row):
    """Return actual historical telemetry, never an inferred command outcome."""
    if not row:
        return {}
    if row.get("status") != "invalid_value" and row.get("value") is not None:
        return row
    known = row.get("last_known") or {}
    return known if known.get("status") != "invalid_value" else {}


def _retain_history(selected, previous, incoming, now):
    """Keep the newest strictly older dated scalar, even if delivered late."""
    boundary = _valid_capture(selected.get("captured"), now)
    if boundary is None:
        return selected
    candidates = []
    for sample in (previous, incoming):
        for candidate in (sample, sample.get("last_known") or {}):
            stamp = _valid_capture(candidate.get("captured"), now)
            if stamp is None or stamp >= boundary:
                continue
            if (
                candidate.get("status") == "invalid_value"
                and candidate.get("reason") == "conflicting_source_values"
            ) or type(candidate.get("value")) in (str, int, float, bool):
                candidates.append((stamp, candidate))
    if not candidates:
        return selected
    newest = max(stamp for stamp, _ in candidates)
    rows = [candidate for stamp, candidate in candidates if stamp == newest]
    first = rows[0]
    if any(
        row.get("status") == "invalid_value"
        or type(row.get("value")) is not type(first.get("value"))
        or row.get("value") != first.get("value")
        for row in rows
    ):
        known = {
            "value": None,
            "captured": newest.isoformat(),
            "family": selected.get("family"),
            "status": "invalid_value",
            "reason": "conflicting_source_values",
        }
    else:
        known = {
            key: first.get(key) for key in ("value", "captured", "family", "status")
        }
    if selected.get("last_known") == known:
        return selected
    return {**selected, "last_known": known}


def _merge_observation(previous, row, now):
    """Compare vehicle time only; equal/unordered conflicts cannot pick a winner."""
    if previous is None:
        return row
    if row.get("informational") and previous.get("informational"):
        # Undated OEM request metadata is diagnostic receipt evidence only.
        # It must not participate in vehicle state, capability or command proof.
        old_receipt = _capture_in_utc(previous.get("observed"))
        new_receipt = _capture_in_utc(row.get("observed"))
        return (
            row
            if new_receipt and (not old_receipt or new_receipt > old_receipt)
            else previous
        )
    prior = _valid_capture(
        previous.get("captured"), _capture_in_utc(previous.get("observed")) or now
    )
    incoming = _valid_capture(
        row.get("captured"), _capture_in_utc(row.get("observed")) or now
    )
    if prior is not None and (incoming is None or incoming < prior):
        return _retain_history(previous, previous, row, now)
    if incoming is not None and (prior is None or incoming > prior):
        return _retain_history(row, previous, row, now)
    if previous.get("reason") == "restored_history" and incoming == prior:
        # A real same-capture observation replaces restored display evidence.
        # Contradictory values at that capture still fail closed.
        known = previous.get("last_known") or {}
        if row.get("status") != "invalid_value" and (
            type(row.get("value")) is type(known.get("value"))
            and row.get("value") == known.get("value")
        ):
            return row
        previous = {**known, "observed": None}
    # Both captures are equal or absent. An invalid undated report is not
    # a new vehicle event; two incompatible values are an explicit conflict.
    old_invalid = previous.get("status") == "invalid_value"
    new_invalid = row.get("status") == "invalid_value"
    if incoming is None and old_invalid != new_invalid:
        if previous.get("reason") == "conflicting_source_values":
            return previous
        if row.get("reason") == "conflicting_source_values":
            return row
        return row if old_invalid else previous
    if (
        old_invalid == new_invalid
        and type(previous.get("value")) is type(row.get("value"))
        and previous.get("value") == row.get("value")
        and previous.get("reason") == row.get("reason")
    ):
        return previous
    # Keep the same capture boundary until a strictly newer event resolves
    # the conflict. Never retain either conflicting value as last known.
    if previous.get("reason") == "conflicting_source_values":
        return _retain_history(previous, previous, row, now)
    conflict = {
        "value": None,
        "captured": row.get("captured"),
        "observed": row.get("observed"),
        "family": row.get("family", ""),
        "job": row.get("job"),
        "status": "invalid_value",
        "reason": "conflicting_source_values",
        "fresh": False,
    }
    return _retain_history(conflict, previous, row, now)


def _current_candidates(vehicle, ident, now):
    previous = vehicle.readings.get(ident)
    candidates = vehicle.family_readings.setdefault(ident, {})
    if previous is None:
        candidates.clear()
    else:
        source = previous.get("family", "")
        if previous is not candidates.get(source):
            candidates[source] = _merge_observation(
                candidates.get(source), previous, now
            )
    return candidates


def _select_observation(vehicle, ident, candidates, registry, now):
    vehicle.readings[ident] = max(
        candidates.values(), key=lambda sample: _observation_rank(sample, registry, now)
    )


def commit_observation(vehicle, ident, row, registry, now):
    """Keep one canonical sample per family; never order by polling time."""
    received = _capture_in_utc(row.get("observed")) or now
    if _valid_capture(row.get("captured"), received) is None:
        row["captured"] = None
        if row.get("status") == "verified":
            row["status"] = "readable_but_stale"
        if "fresh" in row:
            row["fresh"] = False
    candidates = _current_candidates(vehicle, ident, now)
    family = row["family"]
    previous = candidates.get(family)
    selected = _merge_observation(previous, row, now)
    if ident == "availableChargeModes" and family != "eu_data_act":
        # Historical capability evidence is bounded and is never a write gate.
        modes = set((previous or {}).get("discovered_options", ()))
        for sample in (previous or {}, row):
            values = sample.get("value")
            if isinstance(values, list) and sample.get("status") != "invalid_value":
                modes.update(mode for mode in ("manual", "timer") if mode in values)
        if modes != set(selected.get("discovered_options", ())):
            selected = {**selected, "discovered_options": sorted(modes)}
    if selected is previous:
        return False
    candidates[family] = selected
    _select_observation(vehicle, ident, candidates, registry, now)
    # A historical-only enrichment is not a new current observation.
    return previous is None or any(
        selected.get(key) != previous.get(key)
        for key in ("value", "captured", "status", "reason", "discovered_options")
    )


def invalidate_attribute(vehicle, ident):
    """A route/enablement change invalidates both current and competing samples."""
    vehicle.readings.pop(ident, None)
    vehicle.family_readings.pop(ident, None)


def refresh_family_observations(vehicle, profile, now):
    """Re-evaluate cached competing observations at the existing publish boundary."""
    for ident in vehicle.family_readings:
        candidates = _current_candidates(vehicle, ident, now)
        if len(candidates) > 1:
            _select_observation(vehicle, ident, candidates, profile.registry, now)


def remove_family_observations(vehicle, profile, family, now):
    """Remove explicitly revoked read access without losing other observations."""
    changed = False
    for ident in set(vehicle.readings) | set(vehicle.family_readings):
        current = vehicle.readings.get(ident)
        if (current or {}).get("family") != family and family not in (
            vehicle.family_readings.get(ident, {})
        ):
            continue
        candidates = _current_candidates(vehicle, ident, now)
        candidates.pop(family, None)
        if current is None or current.get("family") != family:
            continue
        if candidates:
            _select_observation(vehicle, ident, candidates, profile.registry, now)
        else:
            vehicle.readings.pop(ident, None)
        changed = True
    return changed


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
    detail=False,
    operation=None,
    delivered_at=None,
) -> None:
    """An explicit invalid sample invalidates only the originating family."""
    if ident in getattr(profile, "attribute_disabled", ()):
        return
    commit_observation(
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
            **({"detail": True} if detail else {}),
            **({"operation": operation} if operation else {}),
            **({"delivered_at": delivered_at} if delivered_at else {}),
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
    detail=False,
):
    """Return whether the family accepted the sample, not whether it won selection."""
    if ident in getattr(profile, "attribute_disabled", ()):
        return False
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
    if detail:
        row["detail"] = True
    accepted = commit_observation(
        vehicle, ident, row, getattr(profile, "registry", None), observed_at
    )
    if not accepted:
        return False
    if persist_evidence:
        row = vehicle.family_readings[ident][family]
        profile.attribute_evidence[ident] = {
            "status": row["status"],
            "path": row.get("path", path),
            "job": row.get("job", job),
            "source": "mbb.legacy" if family == "mbb" else "cariad.selectivestatus",
            "timestamp_present": bool(row["captured"]),
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
    vehicle: Any,
    profile: Any,
    payload: Any,
    observed_at: datetime,
    *,
    operation="cariad.climate.status.batch",
    complete_discovery=True,
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
        if ident in getattr(profile, "attribute_disabled", ()):
            continue
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
                operation=operation,
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
            operation=operation,
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

    observe_derived(
        vehicle,
        profile,
        payload,
        observed_at,
        _accept_observation,
        operation=operation,
    )
    from .structured_details import observe_structured

    observe_structured(
        vehicle, payload, observed_at, _accept_observation, operation=operation
    )
    if complete_discovery:
        vehicle.v2_initial_discovery_completed = True
    return {"mapped": mapped, "fresh": fresh_count}


def _data_act_value(mapping, raw):
    """Return a contract-valid scalar, or None for a rejected supplied value."""
    if type(raw) not in (str, int, float):
        return None
    if "values" in mapping:
        value = mapping["values"].get(str(raw))
    elif mapping.get("presence"):
        value = True if isinstance(raw, str) and raw.strip() else None
    elif mapping.get("token"):
        value = (
            raw
            if isinstance(raw, str)
            and re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", raw)
            and raw.lower()
            not in {
                "unknown",
                "invalid",
                "unsupported",
                "unavailable",
                "error",
                "notavailable",
            }
            else None
        )
    else:
        try:
            value = float(raw)
        except (ValueError, OverflowError):
            return None
        if not mapping["min"] <= value <= mapping["max"]:
            return None
        if (
            mapping["attribute"] == "UTC_TIME_AND_KILOMETER_STATUS"
            and not value.is_integer()
        ):
            return None
        if "scale" in mapping:
            value = round(value * mapping["scale"] + mapping["offset"], 2)
    if not mapping.get("detail") and value is not None:
        value, _ = normalize_attribute_value(
            ATTRIBUTES[mapping["attribute"]], value, None
        )
    return value


def data_act_observations(payload, now, registry):
    """One latest observation per semantic field, including timed invalid evidence."""
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
        if raw is None:
            continue  # Absence is not evidence that a previous value became invalid.
        captured = item.get("timestampUtc")
        if capture_age_minutes(captured, now) is None:
            captured = None
        value = _data_act_value(mapping, raw)
        if value is None and captured is None:
            continue  # Undated rejection cannot invalidate a known observation.
        candidates.setdefault(mapping["attribute"], []).append((captured, value, key))
    result = {}
    for ident, rows in candidates.items():
        latest = max((_capture_in_utc(row[0]) for row in rows if row[0]), default=None)
        matching = [row for row in rows if _capture_in_utc(row[0]) == latest]
        captured, value, key = min(matching, key=lambda row: row[2])
        conflict = len({row[1] for row in matching}) != 1
        if conflict and latest is None:
            continue
        sample = {
            "value": None if conflict else value,
            "captured": captured,
            "path": key,
        }
        if sample["value"] is None:
            sample["reason"] = (
                "conflicting_source_values" if conflict else "invalid_source_value"
            )
        result[ident] = sample
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
    changed = False
    for ident, sample in data_act_observations(
        payload, observed_at, profile.registry
    ).items():
        if ident in getattr(profile, "attribute_disabled", ()):
            continue
        previous = vehicle.readings.get(ident)
        mapping = profile.registry.families["eu_data_act"]["observations"][
            sample["path"]
        ]
        detail = bool(mapping.get("detail"))
        if sample["value"] is None:
            record_invalid_observation(
                vehicle,
                ident,
                sample["captured"],
                observed_at,
                sample["path"],
                ATTRIBUTES[ident]["job"] if ident in ATTRIBUTES else None,
                sample["reason"],
                "eu_data_act",
                profile=profile,
                detail=detail,
                operation="eu_data_act.dataset",
                delivered_at=delivered_at,
            )
            changed |= vehicle.readings.get(ident) is not previous
            continue
        record_observation(
            vehicle,
            profile,
            ident,
            sample["value"],
            sample["captured"],
            observed_at,
            sample["path"],
            ATTRIBUTES[ident]["job"] if ident in ATTRIBUTES else None,
            "eu_data_act",
            fresh=timestamp_is_fresh(sample["captured"], observed_at),
            operation="eu_data_act.dataset",
            persist_evidence=False,
            delivered_at=delivered_at,
            detail=detail,
        )
        changed |= vehicle.readings.get(ident) is not previous
    return changed
