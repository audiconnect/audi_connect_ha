"""Bounded per-session response preview for the admin-only V3 Workbench.

This is NOT a public diagnostics or community-data export. Never store or
publish full OEM responses, auth headers, vehicle identifiers or coordinates.
"""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE = re.compile(
    r"vin|authorization|password|access.?token|refresh.?token|bearer|spin|s.?pin|"
    r"secret|token|credential|challenge|email|phone|location|latitude|longitude|position|account.?id|user.?id|"
    r"coordinates|street|address|request.?id|session.?id|user.?prompt.?proof|secured.?activation.?data|^lat$|^lon$|^lng$",
    re.IGNORECASE,
)
_VIN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


def safe_response_preview(
    payload: Any, *, vehicle_vin: str = "", depth_limit: int = 5
) -> Any:
    """Provide just a small recognizable redacted JSON shape and values."""

    def visit(value: Any, depth: int) -> Any:
        if depth >= depth_limit:
            return "[nested content omitted]"
        if isinstance(value, dict):
            clean = {}
            for index, (key, child) in enumerate(value.items()):
                if index >= 25:
                    clean["[more fields omitted]"] = True
                    break
                name = str(key)[:80]
                if (
                    _VIN.search(name)
                    or _EMAIL.search(name)
                    or (vehicle_vin and vehicle_vin.lower() in name.lower())
                ):
                    continue
                clean[name] = (
                    "[redacted]" if _SENSITIVE.search(name) else visit(child, depth + 1)
                )
            return clean
        if isinstance(value, list):
            result = [visit(item, depth + 1) for item in value[:8]]
            if len(value) > 8:
                result.append("[more items omitted]")
            return result
        if isinstance(value, str):
            if vehicle_vin:
                value = re.sub(re.escape(vehicle_vin), "[redacted]", value, flags=re.I)
            return _EMAIL.sub("[redacted]", _VIN.sub("[redacted]", value[:240]))
        if value is None or type(value) in (bool, int, float):
            return value
        return "[unsupported value type]"

    return visit(payload, 0)


MAX_SCHEMA_FIELDS = 128
MAX_SCHEMA_CHARS = 16000
_SCHEMA_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# The generic value-redaction VIN regex also matches 17-letter OEM field
# names (e.g. primaryEngineType). Schema keys need the numeric VIN suffix.
_SCHEMA_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{13}[0-9]{4}$", re.IGNORECASE)
_SCHEMA_PATH = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\[\])*(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\])*)*$"
)
_SCHEMA_TYPES = frozenset(
    ("object", "array", "boolean", "integer", "number", "string", "null")
)


def safe_schema_inventory(
    payload: Any,
    *,
    vehicle_vin: str = "",
    all_items: bool = False,
    field_limit: int = MAX_SCHEMA_FIELDS,
    char_limit: int = MAX_SCHEMA_CHARS,
    secrets: tuple = (),
) -> tuple[list[dict[str, str]], bool]:
    """Bounded structural inventory, with explicit sampling/truncation evidence."""
    from collections import deque
    from itertools import islice
    import json

    queue = deque([(payload, "", 0)])
    rows: dict[tuple[str, str], dict[str, str]] = {}
    budget = 20000 if all_items else 640
    truncated = False
    while queue and budget and len(rows) < field_limit:
        value, path, depth = queue.popleft()
        budget -= 1
        if depth > 12 or len(path) > 220:
            truncated = True
            continue
        kind = {
            dict: "object",
            list: "array",
            bool: "boolean",
            int: "integer",
            float: "number",
            str: "string",
            type(None): "null",
        }.get(type(value))
        if kind is None:
            continue
        if path:
            quality = "observed"
            if value is None:
                quality = "null"
            elif type(value) is str and value.strip().lower() in (
                "",
                "invalid",
                "unknown",
                "unsupported",
                "unavailable",
                "error",
            ):
                quality = "vendor_sentinel"
            elif (
                type(value) in (int, float)
                and value < 0
                and ("remaining" in path.lower() or "duration" in path.lower())
            ):
                quality = "negative_duration_candidate"
            # Preserve a detected issue even if another array member is valid.
            key = (path, kind)
            if key not in rows or quality != "observed":
                rows[key] = {"path": path, "type": kind, "quality": quality}
        if isinstance(value, dict):
            truncated |= len(value) > 40
            for key, child in islice(value.items(), 40):
                if (
                    not isinstance(key, str)
                    or not _SCHEMA_KEY.fullmatch(key)
                    or (_SENSITIVE.search(key) and key != "windowLocation")
                    or _SCHEMA_VIN.fullmatch(key)
                    or (vehicle_vin and vehicle_vin.lower() in key.lower())
                    or any(
                        isinstance(secret, str)
                        and len(secret) >= 4
                        and secret.casefold() in key.casefold()
                        for secret in secrets
                    )
                ):
                    continue
                queue.append((child, f"{path}.{key}" if path else key, depth + 1))
        elif isinstance(value, list) and path:
            limit = 256 if all_items else 4
            truncated |= len(value) > limit
            for child in value[:limit]:
                queue.append((child, path + "[]", depth + 1))
    truncated |= bool(queue)
    result = list(rows.values())
    while result and len(json.dumps(result, ensure_ascii=True)) > char_limit:
        result.pop()
        truncated = True
    return result, truncated


def merge_schema_evidence(previous, fields, truncated, *, status, source, at):
    """Bounded session union; latest empty/partial reply cannot erase known fields."""
    import json

    prior = previous or {}
    rows = {(row["path"], row["type"]): row for row in prior.get("fields", [])}
    union_truncated = bool(prior.get("union_truncated"))
    for row in fields:
        key = (row["path"], row["type"])
        if key not in rows and len(rows) >= 512:
            union_truncated = True
            continue
        if key not in rows or row["quality"] != "observed":
            rows[key] = row
    merged = list(rows.values())
    while merged and len(json.dumps(merged, ensure_ascii=True)) > 64000:
        merged.pop()
        union_truncated = True
    return {
        "fields": merged,
        "truncated": union_truncated or truncated,
        "union_truncated": union_truncated,
        "capture_truncated_seen": bool(prior.get("capture_truncated_seen"))
        or truncated,
        "latest_capture_truncated": truncated,
        "latest_field_count": len(fields),
        "http_status": status,
        "source": source,
        "observed_at": at,
        "scope": "session_union_structural_only",
    }


def safe_schema_fields(payload: Any, *, vehicle_vin: str = "") -> list[dict[str, str]]:
    """Compatibility accessor for callers requiring field rows only."""
    return safe_schema_inventory(payload, vehicle_vin=vehicle_vin)[0]


def validate_schema_fields(
    rows: Any, *, field_limit=MAX_SCHEMA_FIELDS, char_limit=MAX_SCHEMA_CHARS
) -> None:
    """Validate persisted structural evidence without trusting arbitrary paths."""
    import json

    if not isinstance(rows, list) or len(rows) > field_limit:
        raise ValueError("Invalid response schema inventory")
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"path", "type", "quality"}
            or not isinstance(row["path"], str)
            or len(row["path"]) > 220
            or not _SCHEMA_PATH.fullmatch(row["path"])
            or any(
                _SENSITIVE.search(part)
                for part in row["path"].split(".")
                if part.removesuffix("[]") != "windowLocation"
            )
            or any(
                _SCHEMA_VIN.fullmatch(part.removesuffix("[]"))
                for part in row["path"].split(".")
            )
            or not isinstance(row["type"], str)
            or row["type"] not in _SCHEMA_TYPES
            or row["quality"]
            not in (
                "observed",
                "null",
                "vendor_sentinel",
                "negative_duration_candidate",
            )
        ):
            raise ValueError("Invalid response schema field")
    if len(json.dumps(rows, ensure_ascii=True)) > char_limit:
        raise ValueError("Excessive response schema inventory")


# Engineering response cache is RAM-only and exposed through one admin WS
# route. Its larger limit must never be used for shareable diagnostics.
MAX_ENGINEERING_CHARS = 262144
MAX_ENGINEERING_ROUTES = 32
MAX_ENGINEERING_HISTORY = 24
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_AUTH_VALUE = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_SECRET_QUERY = re.compile(
    r"(?i)([?&](?:access_token|refresh_token|id_token|token|password|code|spin|s-pin|client_secret|authorization)=)[^&#\s]+"
)
_UUID = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
_ENGINEERING_VIN = re.compile(
    r"(?i)\b(?=[A-HJ-NPR-Z0-9]{0,16}[0-9])[A-HJ-NPR-Z0-9]{17}\b"
)
_SECRET_KEY = re.compile(
    r"(?i)authorization|password|token|credential|secret|challenge|bearer|cookie|api.?key|private.?key|security.?code|user.?prompt.?proof|secured.?activation.?data|^pin$|^s.?pin$|^spin$"
)
_LOCATION_KEY = re.compile(
    r"(?i)latitude|longitude|coordinates|^location$|^position$|street|address|^lat$|^lon$|^lng$"
)
_PERSON_KEY = re.compile(
    r"(?i)email|phone|account.?id|user.?id|username|nickname|first.?name|last.?name|full.?name|customer.?id|device.?id"
)
_IDENTIFIER_KEY = re.compile(
    r"(?i)request.?id|session.?id|correlation.?id|transaction.?id|command.?id"
)


def engineering_response(
    payload: Any,
    *,
    vehicle_vin: str = "",
    spin: Any = None,
    secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Preserve decoded JSON and actual values; mask secrets, never raw headers.

    No disk persistence. Budget is explicit; oversize content is not silently
    replaced by top-level keys. This is best-effort redaction, not a public export.
    """
    import json
    import math

    remaining = MAX_ENGINEERING_CHARS - 1024
    truncated = False
    replacements = [(str(s), "{SECRET}") for s in secrets if isinstance(s, str) and s]
    if isinstance(spin, (str, int)) and str(spin):
        replacements.append((str(spin), "{SPIN}"))
    replacements.sort(key=lambda item: len(item[0]), reverse=True)

    def redact_text(value: str) -> str:
        if vehicle_vin:
            value = re.sub(re.escape(vehicle_vin), "{VIN}", value, flags=re.I)
        value = _ENGINEERING_VIN.sub("{VIN}", value)
        for secret, marker in replacements:
            # Short PINs/credentials are matched only as a complete value or
            # a delimited token, not embedded in ordinary timestamps/numbers.
            if len(secret) >= 8:
                value = value.replace(secret, marker)
            elif value == secret:
                value = marker
            else:
                value = re.sub(
                    r"(?<![A-Za-z0-9])" + re.escape(secret) + r"(?![A-Za-z0-9])",
                    marker,
                    value,
                )
        value = _AUTH_VALUE.sub("{SECRET}", value)
        value = _JWT.sub("{SECRET}", value)
        value = _SECRET_QUERY.sub(lambda m: m.group(1) + "{SECRET}", value)
        value = _EMAIL.sub("{PERSONAL}", value)
        return _UUID.sub("{ID}", value)

    def mask_for(key: str) -> str | None:
        if re.search(r"(?i)^vin$|vehicle.?identification.?number|^vehicle.?id$", key):
            return "{VIN}"
        if re.search(r"(?i)^s.?pin$|^spin$|^pin$", key):
            return "{SPIN}"
        if _SECRET_KEY.search(key):
            return "{SECRET}"
        if _PERSON_KEY.search(key):
            return "{PERSONAL}"
        if _LOCATION_KEY.search(key):
            return "{LOCATION}"
        if _IDENTIFIER_KEY.search(key):
            return "{ID}"
        return None

    def consume(value: Any) -> bool:
        nonlocal remaining, truncated
        cost = len(json.dumps(value, ensure_ascii=True, allow_nan=False)) + 8
        if cost > remaining:
            truncated = True
            remaining = 0
            return False
        remaining -= cost
        return True

    def visit(value: Any, depth: int = 0) -> Any:
        nonlocal truncated
        if depth >= 40 or remaining < 64:
            truncated = True
            consume("[TRUNCATED]")
            return "[TRUNCATED]"
        if isinstance(value, dict):
            result = {}
            consume({})
            for key, child in value.items():
                original = str(key)
                name = redact_text(original)
                if not consume(name) or remaining < 64:
                    truncated = True
                    result["[TRUNCATED]"] = True
                    break
                marker = mask_for(original)
                if marker is not None:
                    if not consume(marker):
                        result["[TRUNCATED]"] = True
                        break
                    result[name] = marker
                else:
                    result[name] = visit(child, depth + 1)
            return result
        if isinstance(value, list):
            consume([])
            result = []
            for item in value:
                if remaining < 64:
                    truncated = True
                    result.append("[TRUNCATED]")
                    break
                result.append(visit(item, depth + 1))
            return result
        if isinstance(value, str):
            value = redact_text(value)
        elif type(value) is float and not math.isfinite(value):
            value = "[NON-FINITE]"
        elif value is not None and type(value) not in (bool, int, float):
            value = "[UNSUPPORTED VALUE TYPE]"
        if not consume(value):
            return "[TRUNCATED]"
        return value

    response = visit(payload)
    detail = {"payload": response, "truncated": truncated}
    # Defensive bound including markers and serialization overhead.
    if (
        len(json.dumps(detail, ensure_ascii=True, allow_nan=False))
        > MAX_ENGINEERING_CHARS
    ):
        return {
            "payload": "[TRUNCATED: response exceeds inspection limit]",
            "truncated": True,
        }
    return detail


def portable_definition(definition, *, vehicle_vin="", spin=None, secrets=()):
    """Refuse known private values in shared templates, including numeric PINs.

    This is deliberately stricter than evidence display: a numeric measurement
    can legitimately match a PIN, but exporting such a literal is unnecessary.
    """
    private_numbers = {
        str(value).lstrip("0") or "0"
        for value in (*secrets, spin)
        if isinstance(value, (str, int)) and str(value).isascii() and str(value).isdigit()
    }

    def contains_private_number(value):
        if isinstance(value, dict):
            return any(contains_private_number(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_private_number(item) for item in value)
        if type(value) is int:
            return str(value) in private_numbers
        if type(value) is float and value.is_integer():
            return str(int(value)) in private_numbers
        return False

    checked = engineering_response(
        definition, vehicle_vin=vehicle_vin, spin=spin, secrets=secrets
    )
    return (
        not checked["truncated"]
        and checked["payload"] == definition
        and not contains_private_number(definition)
    )
