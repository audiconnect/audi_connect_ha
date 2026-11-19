"""Privacy-aware normalization of Audi's last parked position.

The only supported source is the reviewed CARIAD parkingposition GET. Never
infer driving coordinates from the last parked sample. No position is recorded
to V3 API evidence or diagnostic logs.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from .freshness import capture_age_minutes


def parked_coordinates(lat, lon) -> tuple[float, float] | None:
    """One coordinate validity contract for parsing and local HA projections."""
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
    return lat, lon


def parse_parked_position(
    payload: Any, now: datetime | None = None
) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return None
    item = payload["data"]
    coordinates = parked_coordinates(item.get("lat"), item.get("lon"))
    if coordinates is None:
        return None
    lat, lon = coordinates
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


REVERSE_GEOCODING = "v3_reverse_geocoding"
GEOCODING_ENDPOINT = "v3_geocoding_endpoint"


def valid_geocoding_endpoint(value):
    """An explicitly configured HTTPS reverse endpoint, never the public OSM API."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        return False
    if any(char.isspace() or ord(char) < 32 for char in value):
        return False
    try:
        url = urlsplit(value)
        return bool(
            url.scheme == "https"
            and url.hostname
            # Reject ambiguous host spellings before the HTTP client can
            # normalize them into a blocked public endpoint. Use ASCII IDNA
            # (punycode) for internationalized authorized hostnames.
            and url.hostname.isascii()
            and "%" not in url.hostname
            and url.hostname.rstrip(".").lower() != "nominatim.openstreetmap.org"
            and url.username is None
            and url.password is None
            and (url.port is None or 0 < url.port <= 65535)
            and not url.query
            and not url.fragment
            and url.path.rstrip("/").endswith("/reverse")
        )
    except ValueError:
        return False


def geocoding_endpoint(entry):
    options = getattr(entry, "options", {})
    endpoint = options.get(GEOCODING_ENDPOINT)
    return (
        endpoint
        if options.get(REVERSE_GEOCODING) is True and valid_geocoding_endpoint(endpoint)
        else None
    )


def geocoding_point(position):
    """Reduce location precision before constructing any external request."""
    point = parked_coordinates(
        (position or {}).get("latitude"), (position or {}).get("longitude")
    )
    return tuple(round(value, 3) for value in point) if point is not None else None


async def reverse_address(hass, endpoint, point):
    """Optional address enrichment, not an Audi API or a new location source."""
    import json

    from aiohttp import ClientError, ClientTimeout
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    if (
        not valid_geocoding_endpoint(endpoint)
        or not isinstance(point, (tuple, list))
        or len(point) != 2
    ):
        return None
    rounded = geocoding_point({"latitude": point[0], "longitude": point[1]})
    if rounded is None:
        return None
    lat, lon = rounded
    try:
        session = async_get_clientsession(hass)
        async with session.get(
            endpoint,
            params={"lat": str(lat), "lon": str(lon), "format": "jsonv2"},
            headers={
                "User-Agent": "AudiConnectHA/3 (+https://github.com/audiconnect/audi_connect_ha)"
            },
            timeout=ClientTimeout(total=5),
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                return None
            body = bytearray()
            async for chunk in response.content.iter_chunked(8192):
                body.extend(chunk)
                if len(body) > 65536:
                    return None
        payload = json.loads(body)
    except (ClientError, OSError, TimeoutError, ValueError, RecursionError):
        return None
    address = payload.get("display_name") if isinstance(payload, dict) else None
    if not isinstance(address, str) or not address.strip():
        return None
    # HA sensor state has a 255-character limit. Do not retain a raw response.
    return " ".join(address.split())[:255]
