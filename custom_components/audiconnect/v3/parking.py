"""Privacy-aware normalization of Audi's last parked position.

The only supported source is the reviewed CARIAD parkingposition GET. Never
infer driving coordinates from the last parked sample. No position is recorded
to V3 API evidence or diagnostic logs.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any


def parse_parked_position(payload: Any) -> dict[str, Any] | None:
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
    if not (math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    captured = item.get("carCapturedTimestamp")
    timestamp = None
    if isinstance(captured, str):
        try:
            parsed = datetime.fromisoformat(captured.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is not None:
            timestamp = parsed.astimezone(UTC).isoformat()
    return {"latitude": lat, "longitude": lon, "timestamp": timestamp}


def keep_newest_position(previous: Any, incoming: dict[str, Any]) -> bool:
    if not isinstance(previous, dict) or not previous.get("timestamp"):
        return True
    old, new = previous.get("timestamp"), incoming.get("timestamp")
    if not isinstance(new, str):
        return False
    try:
        old_at = datetime.fromisoformat(old)
        new_at = datetime.fromisoformat(new)
    except (ValueError, TypeError):
        return False
    return new_at >= old_at
