"""Privacy-aware normalization of Audi's last parked position.

The only supported source is the reviewed CARIAD parkingposition GET. Never
infer driving coordinates from the last parked sample. No position is recorded
to V3 API evidence or diagnostic logs.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from .freshness import capture_age_minutes


def parse_parked_position(
    payload: Any, now: datetime | None = None
) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return None
    item = payload["data"]
    lat, lon = item.get("lat"), item.get("lon")
    if isinstance(lat, bool) or isinstance(lon, bool):
        return None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (
        math.isfinite(lat)
        and math.isfinite(lon)
        and -90 <= lat <= 90
        and -180 <= lon <= 180
    ):
        return None
    captured = item.get("carCapturedTimestamp")
    timestamp = None
    if capture_age_minutes(captured, now) is not None:
        timestamp = datetime.fromisoformat(captured.replace("Z", "+00:00"))
        timestamp = timestamp.astimezone(UTC).isoformat()
    return {"latitude": lat, "longitude": lon, "timestamp": timestamp}


def keep_newest_position(
    previous: Any, incoming: dict[str, Any], now: datetime | None = None
) -> bool:
    now = now or datetime.now(UTC)
    old = previous.get("timestamp") if isinstance(previous, dict) else None
    new = incoming.get("timestamp")
    if capture_age_minutes(old, now) is None:
        return True
    if capture_age_minutes(new, now) is None:
        return False
    return datetime.fromisoformat(new.replace("Z", "+00:00")) >= datetime.fromisoformat(
        old.replace("Z", "+00:00")
    )


def observe_parking(vehicle, profile, reply, operation):
    """Use the shared writer; a parking response is not live motion telemetry."""
    from .attribute_runtime import record_observation
    from .freshness import timestamp_is_fresh

    if reply.status == 204:
        samples = (("is_moving", True, None, "parkingposition HTTP 204"),)
    elif 200 <= reply.status < 300:
        point = parse_parked_position(reply.data, reply.observed_at)
        if not point or not keep_newest_position(
            vehicle.position, point, reply.observed_at
        ):
            return
        vehicle.position = point
        stamp = point["timestamp"]
        samples = (("is_moving", False, None, "parkingposition parked sample"),)
        if stamp:
            samples += tuple(
                (ident, stamp, stamp, "parkingposition.data.carCapturedTimestamp")
                for ident in ("position_last_updated", "park_time")
            )
    else:
        return

    for ident, value, stamp, path in samples:
        record_observation(
            vehicle,
            profile,
            ident,
            value,
            stamp,
            reply.observed_at,
            path,
            None,
            "cariad",
            fresh=timestamp_is_fresh(stamp, reply.observed_at),
            operation=operation,
            persist_evidence=False,
        )
