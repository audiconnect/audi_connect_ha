"""Strict, read-only normalization of modern CARIAD trip responses.

Only documented fields with unambiguous units are mapped. Unknown payload
shapes or unit scaling never create a pretend trip reading.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

_TRIP_FIELDS = frozenset(
    (
        "tripEndTimestamp",
        "timestamp",
        "vehicleType",
        "tripType",
        "mileage_km",
        "startMileage_km",
        "overallMileage_km",
        "averageSpeed_kmph",
        "travelTime",
        "travelTime_min",
        "traveltime",
        "averageFuelConsumption",
        "averageFuelConsumption_L_per_100km",
        "averageElectricEngineConsumption_kWh_per_100km",
        "averageElectricConsumption",
        "totalElectricConsumption_kwh",
        "totalFuelConsumption_L",
        "totalFuelConsumption_l",
        "averageFuelConsumptionUnit",
        "averageElectricConsumptionUnit",
        "averageElectricEngineConsumptionUnit",
        "zeroEmissionDistance_km",
        "zeroEmissionDistance",
        "mileage",
        "startMileage",
        "overallMileage",
        "averageSpeed",
    )
)
_MAX_CANDIDATE_RECORDS = 10000
MAX_TRIP_HISTORY = 10000
MAX_TRIP_ENTITY_ROWS = 50
_MAX_CONTAINER_NODES = 30

# Explicitly permitted key names, never raw JSON values or unknown keys.
_SAFE_SCHEMA_KEYS = frozenset(
    (
        "tripEndTimestamp",
        "timestamp",
        "tripType",
        "vehicleType",
        "mileage_km",
        "startMileage_km",
        "overallMileage_km",
        "averageSpeed_kmph",
        "travelTime",
        "travelTime_min",
        "averageFuelConsumption",
        "averageFuelConsumption_L_per_100km",
        "averageElectricEngineConsumption_kWh_per_100km",
        "averageElectricConsumption",
        "totalElectricConsumption_kwh",
        "totalFuelConsumption_L",
        "totalFuelConsumption_l",
        "averageFuelConsumptionUnit",
        "averageElectricConsumptionUnit",
        "averageElectricEngineConsumptionUnit",
        "zeroEmissionDistance_km",
    )
)


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and 10 <= len(value) <= 45:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return None  # Audi must supply a timezone; do not guess.
    result = dt.astimezone(UTC)
    if result.year < 2000 or result.year > datetime.now(UTC).year + 2:
        return None
    return result


def _number(
    record: dict[str, Any], keys: tuple[str, ...], low: float, high: float
) -> float | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        num = float(value)
        if math.isfinite(num) and low <= num <= high:
            return num
    return None


def _records(payload: Any) -> list[dict[str, Any]]:
    """Look for bounded, known wrappers only; never walk arbitrary JSON."""
    if isinstance(payload, list):
        return [x for x in payload[:_MAX_CANDIDATE_RECORDS] if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    candidates: list[Any] = [payload]
    visited = 0
    while candidates and visited < _MAX_CONTAINER_NODES:
        visited += 1
        item = candidates.pop(0)
        if isinstance(item, list):
            rows = [x for x in item[:_MAX_CANDIDATE_RECORDS] if isinstance(x, dict)]
            if rows:
                return rows
            continue
        if not isinstance(item, dict):
            continue
        # A wrapper may contain unrelated numeric metadata. Require a
        # timestamp to treat it as a trip, otherwise descend into known keys.
        if "tripEndTimestamp" in item or "timestamp" in item:
            return [item]
        for key in ("data", "trips", "tripData", "tripDataList", "records", "items"):
            child = item.get(key)
            if isinstance(child, (dict, list)):
                candidates.append(child)
    return []


def describe_cariad_trip_schema(payload: Any) -> dict[str, Any]:
    """Return a bounded field-name fingerprint; no VIN, location or trip values.

    This helps us validate the real Audi JSON contract without saving or
    exporting personal trip history. Only allowlisted, fixed keys can appear.
    """
    envelope = (
        "object"
        if isinstance(payload, dict)
        else "array"
        if isinstance(payload, list)
        else "other"
    )
    records = _records(payload)
    candidate = next(
        (row for row in records if _SAFE_SCHEMA_KEYS.intersection(row)), None
    )
    known_fields = sorted(_SAFE_SCHEMA_KEYS.intersection(candidate or {}))
    timestamp = (
        _timestamp(candidate.get("tripEndTimestamp") or candidate.get("timestamp"))
        if candidate
        else None
    )
    return {
        "envelope": envelope,
        "recognized_record": candidate is not None,
        "known_fields": known_fields,
        "timestamp_with_timezone": timestamp is not None,
    }


def normalize_cariad_trip(
    payload: Any, *, final_units: bool = False
) -> tuple[dict[str, Any] | None, str]:
    """Return legacy-compatible values only when timestamp and units are valid.

    This parser intentionally does not convert legacy scaled fields like
    averageElectricEngineConsumption (1/10 kWh/100 km), because current CARIAD
    responses may already use display units. Unsupported fields remain None.
    """
    records = _records(payload)
    valid: list[tuple[datetime, dict[str, Any]]] = []
    for record in records:
        if record.get("error") is not None:
            continue
        stamp = _timestamp(record.get("tripEndTimestamp") or record.get("timestamp"))
        if stamp is not None:
            valid.append((stamp, record))
    if not valid:
        return None, "no_supported_timestamp_or_trip_schema"
    stamp, item = max(valid, key=lambda x: x[0])
    return _normalize_record(stamp, item, final_units=final_units)


def _normalize_record(stamp, item, *, final_units=False):
    distance = _number(item, ("mileage_km",), 0, 2000000)
    overall = _number(item, ("overallMileage_km",), 0, 2000000)
    starting = _number(item, ("startMileage_km",), 0, 2000000)
    speed = _number(item, ("averageSpeed_kmph",), 0, 350)
    duration = _number(item, ("travelTime_min", "travelTime"), 0, 100000)
    total_electric = _number(item, ("totalElectricConsumption_kwh",), 0, 3000000)
    total_fuel = _number(
        item, ("totalFuelConsumption_L", "totalFuelConsumption_l"), 0, 1000000
    )

    def average(explicit, names, units, maximum, total):
        # An explicit per-100 unit or unit-bearing field is authoritative.
        # Never convert MPG or legacy tenths on the modern app route.
        value = _number(item, (explicit,), 0, maximum)
        if value is not None:
            return value
        for name in names:
            if name not in item:
                continue
            unit = item.get(name + "Unit")
            if unit is not None and unit not in units:
                return None
            value = _number(item, (name,), 0, maximum)
            if value is None:
                return None
            if unit is not None:
                return value
            if distance is not None and distance > 0 and total is not None:
                return (
                    value
                    if math.isclose(
                        value * distance / 100, total, rel_tol=0.02, abs_tol=0.02
                    )
                    else None
                )
            return value if final_units else None
        return None

    fuel = average(
        "averageFuelConsumption_L_per_100km",
        ("averageFuelConsumption",),
        ("l_per_100km", "L_per_100km"),
        100,
        total_fuel,
    )
    # Keep the established conservative unsuffixed fuel fallback for older
    # modern responses without any unit or total (not the tenths API).
    if (
        fuel is None
        and not final_units
        and item.get("averageFuelConsumptionUnit") is None
        and total_fuel is None
    ):
        fuel = _number(item, ("averageFuelConsumption",), 0, 40)
    electric = average(
        "averageElectricEngineConsumption_kWh_per_100km",
        (
            ("averageElectricEngineConsumption", "averageElectricConsumption")
            if final_units
            else ("averageElectricConsumption",)
        ),
        ("kWh_per_100km",),
        150,
        total_electric,
    )
    zero_emission = _number(item, ("zeroEmissionDistance_km",), 0, 2000000)
    readings = [
        distance,
        overall,
        starting,
        speed,
        duration,
        fuel,
        electric,
        zero_emission,
        total_electric,
        total_fuel,
    ]
    if all(x is None for x in readings):
        return None, "no_unambiguous_numeric_trip_fields"
    from .vehicle import normalize_powertrain

    vehicle_type = normalize_powertrain(item.get("vehicleType"))
    trip_type = item.get("tripType")
    return {
        "tripID": None,  # Never persist trip identifiers without a need.
        "vehicleType": vehicle_type,
        "tripType": trip_type if trip_type in ("shortTerm", "longTerm") else None,
        "timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "averageElectricEngineConsumption": electric,
        "averageFuelConsumption": fuel,
        "totalElectricConsumption": total_electric,
        "totalFuelConsumption": total_fuel,
        "averageSpeed": speed,
        "mileage": distance,
        "startMileage": starting,
        "traveltime": duration,
        "overallMileage": overall,
        "zeroEmissionDistance": zero_emission,
        "source": "cariad_modern",
        "units": {
            "mileage": "km",
            "averageSpeed": "km/h",
            "averageFuelConsumption": "L/100km",
            "averageElectricEngineConsumption": "kWh/100km",
            "totalElectricConsumption": "kWh",
            "totalFuelConsumption": "L",
            "traveltime": "min",
            "zeroEmissionDistance": "km",
        },
    }, "normalized"


def normalize_mbb_trips(payload: Any) -> dict[str, dict]:
    """Historical trip API uses tenths for consumption and integer km/min."""
    if not isinstance(payload, dict):
        return {}
    wrapper = payload.get("tripDataList")
    rows = wrapper.get("tripData") if isinstance(wrapper, dict) else None
    if not isinstance(rows, list):
        return {}

    def integer(row, key):
        try:
            value = row.get(key)
            return int(value) if type(value) in (int, float, str) else None
        except (ValueError, TypeError, OverflowError):
            return None

    valid = [
        r
        for r in rows[:100]
        if isinstance(r, dict)
        and _timestamp(r.get("timestamp"))
        and integer(r, "overallMileage") is not None
        and integer(r, "startMileage") is not None
    ]
    if not valid:
        return {}
    valid.sort(key=lambda r: integer(r, "overallMileage"), reverse=True)
    current = valid[0]
    reset = next(
        (
            r
            for r in valid
            if integer(current, "startMileage") - integer(r, "startMileage") > 2
        ),
        current,
    )

    def normalized(row):
        result = {
            "timestamp": _timestamp(row["timestamp"]).isoformat(),
            "source": "mbb_legacy",
            "tripID": None,
        }
        for key in (
            "averageSpeed",
            "mileage",
            "startMileage",
            "traveltime",
            "overallMileage",
            "zeroEmissionDistance",
        ):
            result[key] = integer(row, key)
        for key in ("averageElectricEngineConsumption", "averageFuelConsumption"):
            try:
                value = float(row[key]) / 10
                result[key] = value if math.isfinite(value) and value >= 0 else None
            except (KeyError, TypeError, ValueError):
                result[key] = None
        return result

    return {"current": normalized(current), "reset": normalized(reset)}


CARIAD_TRIP_OPERATIONS = {
    "cariad.mobility.status.shortTerm": "shortterm_current",
    "cariad.mobility.status.longTerm": "longterm_current",
    "cariad.mobility.status.lastTrip": "last_trip",
}


def normalize_cariad_history(payload, *, final_units=False):
    """Normalize distinct completed trips; never combine cumulative long-term rows."""
    rows = []
    for record in _records(payload):
        if record.get("error") is not None:
            continue
        stamp = _timestamp(record.get("tripEndTimestamp") or record.get("timestamp"))
        if stamp is None:
            continue
        if record.get("tripType") not in (None, "shortTerm", "shortterm"):
            continue
        trip, _ = _normalize_record(stamp, record, final_units=final_units)
        if trip is None:
            continue
        rows.append(trip)
    # Use the same archive merge for duplicates within one response and across
    # polls. A later incomplete duplicate must not erase an earlier metric.
    from .trip_archive import merge_history

    return merge_history(rows)


def observe_cariad_trip(vehicle, operation, payload):
    """Single normalizer for ordinary polling and explicit engineering scans."""
    if operation not in CARIAD_TRIP_OPERATIONS:
        return False
    # The app /shortterm/last route has confirmed final display units. Other
    # routes still need explicit units or consistent same-record totals.
    final_units = operation == "cariad.mobility.status.lastTrip"
    trip, _ = normalize_cariad_trip(payload, final_units=final_units)
    if trip is None:
        return False
    key = CARIAD_TRIP_OPERATIONS[operation]
    if key in ("shortterm_current", "last_trip"):
        # Retain the normalized per-trip rows received in this session. The
        # dedicated last-trip endpoint and historical array can overlap.
        from .trip_archive import merge_history

        vehicle.trip_history = merge_history(
            getattr(vehicle, "trip_history", []),
            normalize_cariad_history(payload, final_units=final_units),
        )
    previous = _timestamp(vehicle.trips.get(key, {}).get("timestamp"))
    incoming = _timestamp(trip.get("timestamp"))
    if previous is not None and (incoming is None or incoming < previous):
        return False
    from .trip_archive import merge_snapshots

    # Same completed trip with partial values must not erase earlier metrics.
    vehicle.trips.update(merge_snapshots({key: vehicle.trips.get(key)}, {key: trip}))
    return True
