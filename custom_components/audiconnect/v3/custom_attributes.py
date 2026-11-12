"""Vehicle-local, declarative read-only attribute contracts.

Never extend the global V2 inventory or authorize a mutation. New capability
groups are presentation/read-only groups, not executable control capabilities.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any
from collections.abc import Mapping

from .historical_catalog import ATTRIBUTES

MAX_CUSTOM_ATTRIBUTES = 20
_ID = re.compile(r"^user\.attribute\.([a-z][a-z0-9_]{0,31})$")
_GROUP = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_UNITS = {
    "pressure": {"bar", "kPa", "hPa", "psi"},
    "temperature": {"°C", "°F", "K"},
    "battery": {"%"},
    "distance": {"km", "m", "mi"},
    "duration": {"s", "min", "h"},
    "power": {"W", "kW"},
    "energy": {"Wh", "kWh"},
    "current": {"A", "mA"},
    "voltage": {"V", "mV"},
    "speed": {"km/h", "m/s", "mph"},
}


def validate_definition(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {"id", "capability", "name", "type"}
    optional = {
        "unit",
        "device_class",
        "state_class",
        "precision",
        "display_last_known",
    }
    if (
        not isinstance(raw, Mapping)
        or not required <= set(raw)
        or set(raw) - required - optional
    ):
        raise ValueError("Invalid local attribute fields")
    ident, group, name, kind = (raw[k] for k in ("id", "capability", "name", "type"))
    if not isinstance(ident, str) or not _ID.fullmatch(ident):
        raise ValueError("Use user.attribute.<identifier>")
    if not isinstance(group, str) or not _GROUP.fullmatch(group):
        raise ValueError("Invalid capability group")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 80
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("Invalid local attribute name")
    if kind not in ("number", "integer", "string", "boolean", "timestamp"):
        raise ValueError("Unsupported local attribute type")
    unit, device, state, precision = (
        raw.get(k) for k in ("unit", "device_class", "state_class", "precision")
    )
    stale = raw.get("display_last_known", False)
    if type(stale) is not bool:
        raise ValueError("Invalid freshness policy")
    if kind in ("number", "integer"):
        if device is None:
            if unit not in (None, "%"):
                raise ValueError("A unit requires an approved device class")
        elif (
            not isinstance(device, str)
            or not isinstance(unit, str)
            or device not in _UNITS
            or unit not in _UNITS[device]
        ):
            raise ValueError("Invalid device class/unit combination")
        if state not in (None, "measurement"):
            raise ValueError(
                "Only measurement statistics are supported for custom attributes"
            )
        if precision is not None and (
            type(precision) is not int or not 0 <= precision <= 6
        ):
            raise ValueError("Invalid precision")
    elif any(v is not None for v in (unit, device, state, precision)):
        raise ValueError("Non-numeric metadata is derived from the attribute type")
    if kind == "boolean" and stale:
        raise ValueError("Binary attributes must be fresh")
    return {
        "id": ident,
        "capability": group,
        "name": name.strip(),
        "type": kind,
        "unit": unit,
        "device_class": device,
        "state_class": state,
        "precision": precision,
        "display_last_known": stale,
    }


def descriptor(definition: Mapping[str, Any]) -> dict[str, Any]:
    slug = definition["id"].rsplit(".", 1)[-1]
    return {
        "id": definition["id"],
        "capability": definition["capability"],
        "entity_key": "v3_custom_" + slug,
        "platform": "binary_sensor" if definition["type"] == "boolean" else "sensor",
        "job": None,
        "paths": [],
        "local": True,
        "type": definition["type"],
        "contract": {
            "name": definition["name"],
            "unit": definition["unit"],
            "device_class": "timestamp"
            if definition["type"] == "timestamp"
            else definition["device_class"],
            "state_class": definition["state_class"],
            "precision": definition["precision"],
            "display_last_known": definition["display_last_known"],
        },
    }


def attributes_for(profile: Any) -> dict[str, dict[str, Any]]:
    return {
        **ATTRIBUTES,
        **{
            k: descriptor(v)
            for k, v in getattr(profile, "attribute_definitions", {}).items()
        },
    }


def normalize_local_value(value: Any, field: Mapping[str, Any]) -> Any:
    kind = field["type"]
    if kind == "boolean":
        return value if type(value) is bool else None
    if kind in ("number", "integer"):
        if (
            type(value) not in (int, float)
            or abs(value) > 1e100
            or not math.isfinite(value)
        ):
            return None
        return (
            int(value)
            if kind == "integer" and value == int(value)
            else (value if kind == "number" else None)
        )
    if not isinstance(value, str) or not value or len(value) > 255:
        return None
    if kind == "timestamp":
        try:
            if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                return None
        except ValueError:
            return None
    return value
