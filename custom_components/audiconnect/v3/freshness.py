"""Vehicle capture timestamps must be recent, not merely present."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def timestamp_is_fresh(
    captured: Any,
    observed_at: datetime,
    *,
    max_age_minutes: int = 60,
) -> bool:
    """Do not mistake cached 4-hour-old vehicle state for a current reading.

    Allow a 5-minute car/cloud clock skew into the future. A cloud HTTP
    response timestamp is not a substitute for a vehicle capture timestamp.
    """
    if not isinstance(captured, str) or observed_at.tzinfo is None:
        return False
    try:
        stamp = datetime.fromisoformat(captured.replace("Z", "+00:00"))
    except ValueError:
        return False
    if stamp.tzinfo is None:
        return False
    diff = (observed_at.astimezone(UTC) - stamp.astimezone(UTC)).total_seconds()
    return -300 <= diff <= max_age_minutes * 60


def capture_age_minutes(captured: Any, now: datetime | None = None) -> float | None:
    """Shared vehicle timestamp policy; never substitute a cloud clock."""
    if not isinstance(captured, str):
        return None
    try:
        stamp = datetime.fromisoformat(captured.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None or stamp.year < 2020:
        return None
    delta = ((now or datetime.now(UTC)) - stamp.astimezone(UTC)).total_seconds()
    return max(0.0, delta / 60) if delta >= -300 else None


def reading_freshness_attributes(row, *, allow_last_known=False, now=None):
    """Describe a reported sample, independently of its projected HA state."""
    row = row or {}
    now = now or datetime.now(UTC)
    age = capture_age_minutes(row.get("captured"), now)
    valid = row.get("value") is not None and row.get("status") != "invalid_value"
    return {
        "vehicle_captured": row.get("captured"),
        "age_minutes": age,
        "cloud_observed": row.get("observed"),
        "cloud_age_minutes": capture_age_minutes(row.get("observed"), now),
        "vehicle_freshness": (
            "unknown"
            if age is None or not valid
            else "fresh"
            if age <= 60
            else "stale_last_known"
            if allow_last_known
            else "stale"
        ),
        "verification": row.get("status", "unknown"),
    }


def newest_vehicle_reading(vehicle, now: datetime | None = None):
    """Return the capture and its source, excluding the derived summary itself."""
    reference = now or datetime.now(UTC)
    newest = None
    for ident, row in vehicle.readings.items():
        if (
            ident in ("last_update_time", "model")
            or row.get("status") == "invalid_value"
            or row.get("value") is None
        ):
            continue
        captured = row.get("captured")
        if capture_age_minutes(captured, reference) is not None:
            stamp = datetime.fromisoformat(captured.replace("Z", "+00:00"))
            if newest is None or (stamp, ident) > newest[:2]:
                newest = (stamp, ident, row)
    return newest


def newest_vehicle_capture(vehicle, now: datetime | None = None) -> datetime | None:
    """Newest real, valid vehicle measurement; never cloud receipt time."""
    newest = newest_vehicle_reading(vehicle, now)
    return newest[0] if newest else None


def vehicle_capture_summary(vehicle, now: datetime | None = None):
    """Shared global capture provenance for HA and diagnostics."""
    now = now or datetime.now(UTC)
    newest = newest_vehicle_reading(vehicle, now)
    stamp, ident, row = newest if newest else (None, None, {})
    last = stamp.isoformat() if stamp else None
    age = capture_age_minutes(last, now)
    return {
        "vehicle_last_update": last,
        "vehicle_age_minutes": int(age) if age is not None else None,
        "source_attribute": ident,
        "source_job": row.get("job"),
        "source_observed_at": row.get("observed"),
        "source_clock_ahead_seconds": (
            max(0, int((stamp - now).total_seconds())) if stamp else None
        ),
        "freshness_basis": "newest_valid_vehicle_capture",
    }


def capture_coverage(vehicle, now: datetime | None = None) -> dict[str, dict]:
    """Summarize observed job captures, not unobserved capability support.

    Multiple fields may share a timestamp. The oldest valid field in a job
    determines its conservative age. Invalid observations remain visible.
    """
    groups = {}
    for ident, row in vehicle.readings.items():
        if ident in ("last_update_time", "model"):
            continue
        job = row.get("job") or "unclassified"
        group = groups.setdefault(
            job,
            {
                "oldest_minutes": None,
                "newest_minutes": None,
                "observed": 0,
                "unknown": 0,
            },
        )
        group["observed"] += 1
        age = capture_age_minutes(row.get("captured"), now)
        if (
            age is None
            or row.get("status") == "invalid_value"
            or row.get("value") is None
        ):
            group["unknown"] += 1
            continue
        age = int(age)
        for key, compare in (("oldest_minutes", max), ("newest_minutes", min)):
            previous = group[key]
            group[key] = age if previous is None else compare(previous, age)
    return groups


def capture_field_timestamp(data: Any, path: str | None) -> str | None:
    """A status field's own timestamp, not HTTP receipt time."""
    if not path or not isinstance(data, dict):
        return None
    prefix = path.rsplit(".", 1)[0]
    value = data
    for key in prefix.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if not isinstance(value, dict):
        return None
    for key in ("carCapturedTimestamp", "timestamp"):
        if isinstance(value.get(key), str):
            return value[key]
    return None
