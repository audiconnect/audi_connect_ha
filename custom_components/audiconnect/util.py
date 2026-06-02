from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import reduce
from typing import Any

_LOGGER = logging.getLogger(__name__)


def get_attr(dictionary: dict[str, Any], keys: str, default: Any = None) -> Any:
    return reduce(
        lambda d, key: d.get(key, default) if isinstance(d, dict) else default,
        keys.split("."),
        dictionary,
    )


def to_byte_array(hexString: str) -> list[int]:
    result = []
    for i in range(0, len(hexString), 2):
        result.append(int(hexString[i : i + 2], 16))

    return result


def log_exception(exception: Exception, message: str) -> None:
    err = message + ": " + str(exception).rstrip("\n")
    _LOGGER.error(err)


def parse_int(val: Any) -> int | None:
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def parse_float(val: Any) -> float | None:
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def parse_datetime(time_value: Any) -> datetime | None:
    """Converts timestamp to datetime object if it's a string, or returns it directly if already datetime."""
    if isinstance(time_value, datetime):
        return time_value  # Return the datetime object directly if already datetime
    elif isinstance(time_value, str):
        formats = [
            "%Y-%m-%d %H:%M:%S%z",  # Format: 2024-04-12 05:56:17+00:00
            "%Y-%m-%dT%H:%M:%S.%fZ",  # Format: 2024-04-12T05:56:13.025Z
        ]
        for fmt in formats:
            try:
                return datetime.strptime(time_value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


__all__ = [
    "get_attr",
    "log_exception",
    "parse_datetime",
    "parse_float",
    "parse_int",
    "to_byte_array",
]
