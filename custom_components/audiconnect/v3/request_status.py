"""Bounded CARIAD request-ID followup, independent of V2 command internals.

One mutating request is sent by V3Engine. This module never retries it:
only the reviewed read-only pendingrequests endpoint is checked. A completed
backend request is NOT inferred to mean a physically confirmed vehicle state.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_PENDING = frozenset({"in_progress", "pending", "queued", "accepted"})
_SUCCESS = frozenset({"successful", "succeeded", "completed"})
_REJECTED = frozenset({"failed", "rejected", "error", "cancelled", "canceled", "timeout"})


def request_id_of(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    value = data.get("requestID") if isinstance(data, dict) else None
    return value if isinstance(value, str) and _ID.fullmatch(value) else None


def status_of(payload: Any, request_id: str) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return "unknown"
    for request in payload["data"][:200]:
        if not isinstance(request, dict) or request.get("id") != request_id:
            continue
        status = request.get("status")
        if not isinstance(status, str):
            return "unknown"
        value = status.strip().lower()
        if value in _SUCCESS:
            return "backend_completed"
        if value in _REJECTED:
            return "rejected"
        if value in _PENDING:
            return "pending"
        return "unknown"
    return "unknown"


async def confirm(
    transport: Any, vin: str, request_id: str, *,
    max_reads: int = 3, delay_s: float = 4,
) -> str:
    """Check only the known VIN request; never POST/retry a physical command."""
    if not _ID.fullmatch(request_id):
        return "unknown"
    for attempt in range(max_reads):
        if transport.remaining_calls is not None and transport.remaining_calls <= 12:
            return "quota_limited"
        if attempt:
            await asyncio.sleep(delay_s)
        try:
            response = await transport.request(
                "cariad", "GET",
                f"/vehicle/v1/vehicles/{vin}/pendingrequests",
            )
        except (TimeoutError, OSError, RuntimeError, ValueError):
            return "unknown"
        if response.status in (401, 403, 429) or response.status >= 500:
            return "unknown"
        if response.status == 204:
            continue
        if not 200 <= response.status < 300:
            return "unknown"
        outcome = status_of(response.data, request_id)
        if outcome in ("rejected", "backend_completed"):
            return outcome
    return "accepted_unconfirmed"
