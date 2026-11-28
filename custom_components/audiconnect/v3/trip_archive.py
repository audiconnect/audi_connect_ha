"""Private, bounded per-entry archive of normalized completed CARIAD trips.

Never store raw OEM payloads, coordinates, trip IDs or credentials here.
The archive survives restart and rollback; it is not HA Recorder history.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
import math

from .trips import MAX_TRIP_HISTORY, _timestamp, _number

_NUMERIC = {
    "mileage": 2000000,
    "startMileage": 2000000,
    "overallMileage": 2000000,
    "averageSpeed": 350,
    "traveltime": 100000,
    "averageFuelConsumption": 100,
    "averageElectricEngineConsumption": 150,
    "totalElectricConsumption": 3000000,
    "totalFuelConsumption": 1000000,
    "zeroEmissionDistance": 2000000,
}
_UNITS = {
    "mileage": "km",
    "averageSpeed": "km/h",
    "traveltime": "min",
    "averageFuelConsumption": "L/100km",
    "averageElectricEngineConsumption": "kWh/100km",
    "totalElectricConsumption": "kWh",
    "totalFuelConsumption": "L",
    "zeroEmissionDistance": "km",
}


def clean_trip(row, *, allow_longterm=False, allow_legacy=False):
    """Revalidate stored and incoming rows; only completed modern trips."""
    if not isinstance(row, Mapping) or row.get("source") not in (
        ("cariad_modern", "mbb_legacy") if allow_legacy else ("cariad_modern",)
    ):
        return None
    if row.get("tripType") not in (
        (None, "shortTerm", "longTerm") if allow_longterm else (None, "shortTerm")
    ):
        return None
    stamp = _timestamp(row.get("timestamp"))
    if stamp is None:
        return None
    values = {key: _number(row, (key,), 0, limit) for key, limit in _NUMERIC.items()}
    if all(value is None for value in values.values()):
        return None
    vehicle_type = row.get("vehicleType")
    return {
        "timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "tripType": row.get("tripType")
        if allow_longterm or allow_legacy
        else "shortTerm",
        "vehicleType": vehicle_type
        if vehicle_type in ("hybrid", "phev", "electric", "combustion")
        else None,
        "source": row["source"],
        "tripID": None,
        "units": dict(_UNITS),
        **values,
    }


def merge_history(*groups):
    """Prefer newer non-null fields on exact identity, never sum trip windows."""
    records = {}
    for group in groups:
        if not isinstance(group, list):
            continue
        for raw in group:
            row = clean_trip(raw)
            if row is None:
                continue
            key = (row["timestamp"], row["startMileage"], row["overallMileage"])
            previous = records.get(key, {})
            records[key] = {
                **row,
                **previous,
                **{k: v for k, v in row.items() if v is not None},
            }
    # A last-trip response may omit one odometer endpoint present in history.
    # Merge only a unique compatible complete interval at the same timestamp.
    # Never merge conflicting or ambiguous intervals, or infer missing mileage.
    complete = {}
    for key in records:
        if key[1] is not None and key[2] is not None:
            complete.setdefault(key[0], []).append(key)
    for key, partial in list(records.items()):
        stamp, start, end = key
        if (start is None) == (end is None):
            continue
        matches = [
            candidate
            for candidate in complete.get(stamp, ())
            if (start is None or candidate[1] == start)
            and (end is None or candidate[2] == end)
            and (
                partial["mileage"] is None
                or records[candidate]["mileage"] is None
                or partial["mileage"] == records[candidate]["mileage"]
            )
        ]
        if len(matches) == 1:
            target = matches[0]
            # Complete record wins conflicts; partial adds missing metrics only.
            records[target] = {
                **partial,
                **{k: v for k, v in records[target].items() if v is not None},
            }
            del records[key]
    return sorted(records.values(), key=lambda row: row["timestamp"], reverse=True)[
        :MAX_TRIP_HISTORY
    ]


_SCOPES = (
    "last_trip",
    "shortterm_current",
    "longterm_current",
    "shortterm_reset",
    "longterm_reset",
)


def merge_snapshots(*groups):
    """Retain last valid values per OEM scope; never derive cumulative totals from history."""
    result = {}
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        for key in _SCOPES:
            row = clean_trip(
                group.get(key),
                allow_longterm=key == "longterm_current" or key == "longterm_reset",
                allow_legacy=True,
            )
            if row is None:
                continue
            old = result.get(key)
            if old is None or _timestamp(row["timestamp"]) > _timestamp(
                old["timestamp"]
            ):
                result[key] = row
            elif (
                _timestamp(row["timestamp"]) == _timestamp(old["timestamp"])
                and row["source"] == old["source"]
                and all(
                    row[field] is None or old[field] is None or row[field] == old[field]
                    for field in ("startMileage", "overallMileage")
                )
            ):
                result[key] = {**old, **{k: v for k, v in row.items() if v is not None}}
    return result


def trip_history_payload(
    rows, *, offset=0, limit=100, export=False, start_date=None, end_date=None
):
    """Read-only projection, optionally filtered by UTC dates before pagination."""
    if export:
        if offset:
            raise ValueError("Full trip export must start at offset zero")
        limit = MAX_TRIP_HISTORY
    if start_date is not None or end_date is not None:
        start = _date_boundary(start_date)
        end = _date_boundary(end_date)
        if start is not None and end is not None and start >= end:
            raise ValueError("Trip start date must precede end date")
        rows = [
            row
            for raw in rows[:MAX_TRIP_HISTORY]
            if (row := clean_trip(raw)) is not None
            and (start is None or _timestamp(row["timestamp"]) >= start)
            and (end is None or _timestamp(row["timestamp"]) < end)
        ]
    else:
        rows = [
            row
            for raw in rows[:MAX_TRIP_HISTORY]
            if (row := clean_trip(raw)) is not None
        ]
    total = len(rows)
    metrics = {}
    for key in (
        "mileage",
        "totalElectricConsumption",
        "totalFuelConsumption",
        "traveltime",
    ):
        values = [row[key] for row in rows if row.get(key) is not None]
        metrics[key] = {
            "sum": math.fsum(values) if values else None,
            "reported_count": len(values),
        }
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "coverage": "observed_records",
        "metrics": metrics,
        "start_date": start_date,
        "end_date": end_date,
        "trips": [
            {
                key: value
                for key, value in row.items()
                if key != "tripID" and value is not None
            }
            for row in rows[offset : offset + limit]
        ],
    }


def _date_boundary(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Expected YYYY-MM-DD")
    day = date.fromisoformat(value)
    if day.isoformat() != value:
        raise ValueError("Expected YYYY-MM-DD")
    return datetime.combine(day, time.min, tzinfo=UTC)


class V3TripArchive:
    """Private HA storage, separate from evidence and configuration."""

    def __init__(self, hass, entry_id):
        from homeassistant.helpers.storage import Store

        self._store = Store(hass, 1, f"audiconnect_v3_{entry_id}_trips", private=True)
        self._lock = asyncio.Lock()

    async def async_remove(self):
        """Remove this entry's private trip archive on explicit removal."""
        async with self._lock:
            await self._store.async_remove()

    async def _load(self):
        data = await self._store.async_load()
        if data is None:
            return {}, {}
        if not isinstance(data, dict) or not isinstance(data.get("vehicles"), dict):
            raise ValueError("Invalid Audi trip archive")
        snapshots = data.get("snapshots", {})
        if not isinstance(snapshots, dict):
            raise ValueError("Invalid Audi trip snapshots")
        return data["vehicles"], snapshots

    async def restore(self, vehicles):
        async with self._lock:
            records, snapshots = await self._load()
            for key, car in vehicles.items():
                car.trip_history = merge_history(records.get(key, []), car.trip_history)
                car.trips.update(merge_snapshots(snapshots.get(key, {}), car.trips))

    async def save(self, vehicles):
        async with self._lock:
            records, snapshots = await self._load()
            updated, current = dict(records), dict(snapshots)
            for key, car in vehicles.items():
                if not car.inventory_present:
                    continue
                if car.trip_history:
                    updated[key] = merge_history(records.get(key, []), car.trip_history)
                if car.trips:
                    current[key] = merge_snapshots(snapshots.get(key, {}), car.trips)
            if updated != records or current != snapshots:
                await self._store.async_save(
                    {"vehicles": updated, "snapshots": current}
                )
