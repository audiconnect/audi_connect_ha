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


def newest_vehicle_capture(vehicle, now: datetime | None = None) -> datetime | None:
    """Newest real, valid vehicle measurement; never cloud receipt time."""
    reference = now or datetime.now(UTC)
    stamps = []
    for ident, row in vehicle.readings.items():
        if ident == "model" or row.get("status") == "invalid_value":
            continue
        captured = row.get("captured")
        if capture_age_minutes(captured, reference) is not None:
            stamps.append(datetime.fromisoformat(captured.replace("Z", "+00:00")))
    return max(stamps, default=None)


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
        if age is None or row.get("status") == "invalid_value":
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
