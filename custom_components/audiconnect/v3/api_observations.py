"""Redacted, bounded last response evidence for each Audi API route.

Persisted in HA private .storage profiles and shared with the admin Workbench.
Never persist bearer tokens, PINs, VINs, GPS data or raw control responses.
"""

from __future__ import annotations
from datetime import UTC, datetime
import json
from typing import Any
from .response_preview import (
    safe_response_preview,
    safe_schema_inventory,
    validate_schema_fields,
)

MAX_ROUTES = 48
MAX_PREVIEW_CHARS = 3800
FAMILIES = frozenset(("cariad", "mbb", "graphql"))
METHODS = frozenset(("GET", "POST", "PUT"))
OUTCOMES = frozenset(
    (
        "http_ok",
        "http_error",
        "transport_uncertain",
        "verified",
        "readable_but_stale",
        "mapping_missing",
        "api_error",
    )
)


def record_for(
    *,
    family: str,
    method: str,
    http_status: int | None,
    payload: Any,
    vin: str,
    at: datetime | None = None,
    result: str | None = None,
) -> dict[str, Any]:
    if family not in FAMILIES or method not in METHODS:
        raise ValueError("Unsupported API family or method")
    stamp = (at or datetime.now(UTC)).astimezone(UTC).isoformat()
    outcome = result or (
        "transport_uncertain"
        if http_status is None
        else "http_ok"
        if 200 <= http_status < 300
        else "http_error"
    )
    if method == "GET":
        preview = safe_response_preview(payload, vehicle_vin=vin)
        try:
            encoded = json.dumps(preview, ensure_ascii=True)
            if len(encoded) > MAX_PREVIEW_CHARS:
                preview = {
                    "notice": "Preview truncated; inspect specific route mapping",
                    "top_level_keys": list(preview)[:12]
                    if isinstance(preview, dict)
                    else [],
                }
        except (ValueError, TypeError, RecursionError):
            preview = "[unreadable JSON response]"
    else:
        preview = "[control response withheld: security]"
    record = {
        "at": stamp,
        "family": family,
        "method": method,
        "http_status": http_status,
        "result": outcome,
        "preview": preview,
    }
    if method == "GET":
        record["fields"], record["fields_truncated"] = safe_schema_inventory(
            payload, vehicle_vin=vin
        )
    validate_record(record)
    return record


def validate_record(item: Any) -> None:
    required = {"at", "family", "method", "http_status", "result", "preview"}
    if (
        not isinstance(item, dict)
        or not required <= set(item)
        or set(item) - required - {"fields", "fields_truncated"}
    ):
        raise ValueError("Invalid API observation")
    if (
        item["family"] not in FAMILIES
        or item["method"] not in METHODS
        or item["result"] not in OUTCOMES
    ):
        raise ValueError("Invalid API observation enums")
    status = item["http_status"]
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        raise ValueError("Invalid HTTP status")
    try:
        dt = datetime.fromisoformat(item["at"])
        if dt.tzinfo is None:
            raise ValueError("Missing timezone")
        text = json.dumps(item["preview"], ensure_ascii=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid API record payload") from exc
    if len(text) > MAX_PREVIEW_CHARS:
        raise ValueError("Excessive response preview")
    if item["method"] != "GET" and (
        item["preview"] != "[control response withheld: security]"
        or "fields" in item
        or "fields_truncated" in item
    ):
        raise ValueError("Control responses must never be saved")
    if "fields" in item:
        validate_schema_fields(item["fields"])
    if "fields_truncated" in item and (
        "fields" not in item or type(item["fields_truncated"]) is not bool
    ):
        raise ValueError("Invalid schema truncation evidence")


def save_record(profile: Any, operation: str, record: dict[str, Any]) -> None:
    validate_record(record)
    if not isinstance(operation, str) or not 1 <= len(operation) <= 120:
        raise ValueError("Invalid route identifier")
    profile.api_observations.pop(operation, None)
    profile.api_observations[operation] = record
    while len(profile.api_observations) > MAX_ROUTES:
        profile.api_observations.pop(next(iter(profile.api_observations)))


def save_execution_review(profile: Any, review: dict[str, Any]) -> None:
    """Bounded private annotation of an execution, never runtime evidence."""
    if not isinstance(review, dict) or set(review) != {
        "operation",
        "at",
        "outcome",
        "comment",
    }:
        raise ValueError("Invalid execution review")
    operation, at, outcome, comment = (
        review[k] for k in ("operation", "at", "outcome", "comment")
    )
    if (
        not isinstance(operation, str)
        or not 1 <= len(operation) <= 120
        or not isinstance(at, str)
        or len(at) > 64
        or outcome not in ("unreviewed", "worked", "failed", "inconclusive")
        or not isinstance(comment, str)
        or len(comment) > 500
        or any(ord(c) < 32 and c not in "\n\t" for c in comment)
    ):
        raise ValueError("Invalid execution review fields")
    if datetime.fromisoformat(at).tzinfo is None:
        raise ValueError("Execution review requires timezone")
    rows = profile.execution_reviews
    rows[:] = [row for row in rows if (row["operation"], row["at"]) != (operation, at)]
    if outcome != "unreviewed" or comment:
        rows.append(dict(review))
    del rows[:-MAX_ROUTES]
