"""Bounded CARIAD request-ID followup, independent of V2 command internals.

One mutating request is sent by V3Engine. This module never retries it:
only read-only pendingrequests and already-fetched native status are checked.
A completed backend request is NOT inferred to mean a physically confirmed vehicle state.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from .quota import QuotaUnavailable


_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
PENDING_RESULTS = frozenset({"in_progress", "pending", "queued", "accepted"})
_SUCCESS = frozenset({"successful", "succeeded", "completed"})
_REJECTED = frozenset(
    {"failed", "rejected", "error", "cancelled", "canceled", "timeout"}
)


def request_id_of(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    value = data.get("requestID") if isinstance(data, dict) else None
    return value if isinstance(value, str) and _ID.fullmatch(value) else None


def _backend_status(status):
    if not isinstance(status, str):
        return "unknown"
    value = status.strip().lower()
    if value in _SUCCESS:
        return "backend_completed"
    if value in _REJECTED:
        return "rejected"
    if value in PENDING_RESULTS:
        return value
    return "unknown"


def status_of(payload: Any, request_id: str) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return "unknown"
    rows = payload["data"]
    if len(rows) > 200:
        return "unknown"
    matches = [
        row for row in rows if isinstance(row, dict) and row.get("id") == request_id
    ]
    if len(matches) != 1:
        return "unknown" if matches else "not_listed"
    return _backend_status(matches[0].get("status"))


async def confirm(
    transport: Any,
    vin: str,
    request_id: str,
    *,
    max_reads: int = 3,
    delay_s: float = 4,
) -> str:
    """Check only the known VIN request; never POST/retry a physical command."""
    if not _ID.fullmatch(request_id):
        return "unknown"
    last_pending = None
    missing = False
    for attempt in range(max_reads):
        if attempt:
            await asyncio.sleep(delay_s)
        try:
            response = await transport.request(
                "cariad",
                "GET",
                f"/vehicle/v1/vehicles/{vin}/pendingrequests",
            )
        except QuotaUnavailable:
            return "quota_limited"
        except (TimeoutError, OSError, RuntimeError, ValueError):
            return "unknown"
        if response.status == 429:
            return "quota_limited"
        if response.status in (401, 403) or response.status >= 500:
            return "unknown"
        if response.status == 204:
            missing = True
            continue
        if not 200 <= response.status < 300:
            return "unknown"
        outcome = status_of(response.data, request_id)
        if outcome in ("rejected", "backend_completed"):
            return outcome
        if outcome in PENDING_RESULTS:
            last_pending = outcome
        elif outcome == "not_listed":
            missing = True
    # Disappearance is not completion. Preserve the last explicit queue
    # evidence instead of treating an empty response as success.
    return last_pending or ("not_listed" if missing else "accepted_unconfirmed")


# Exact reviewed route/queue pairs only. vcfRequestId is a different field;
# never guess that it is interchangeable with the mutation receipt ID.
_QUEUE_ROUTES = {
    "cariad.climate.start.stored": (
        "climatisation.climatisationStatus.requests",
        "start",
    ),
    "cariad.climate.start.vehicle_settings": (
        "climatisation.climatisationStatus.requests",
        "start",
    ),
    "cariad.climate.stop": ("climatisation.climatisationStatus.requests", "stop"),
    "cariad.climate.settings": (
        "climatisation.climatisationSettings.requests",
        "settings",
    ),
    "cariad.charging.start": ("charging.chargingStatus.requests", "start"),
    "cariad.charging.stop": ("charging.chargingStatus.requests", "stop"),
    "cariad.access.lock": ("access.accessStatus.requests", "lock"),
    "cariad.access.unlock": ("access.accessStatus.requests", "unlock"),
}


def reconcile_native_queue(profile, payload, observed_at):
    """Correlate exact current-session receipts, not foreign commands or telemetry."""
    from .registry import read_json_path
    from .operation_revision import operation_revision

    stamp = observed_at.timestamp()
    changed = []
    history = profile.command_journal
    for record in history:
        route = _QUEUE_ROUTES.get(record.operation)
        if (
            route is None
            or record.origin != "home_assistant"
            or record.http_status is None
            or not 200 <= record.http_status < 300
            or not record.request_id
            or getattr(record, "request_context", None) is not profile.discovery.context
            or stamp < record.started_at
            or stamp < getattr(record, "backend_observed_at", record.started_at)
            or sum(other.request_id == record.request_id for other in history) != 1
        ):
            continue
        operation = profile.registry.operations.get(record.operation)
        if operation is None or record.operation_revision != operation_revision(
            operation
        ):
            continue
        path, expected = route
        rows = read_json_path(payload, path)
        if not isinstance(rows, list) or len(rows) > 200:
            continue
        matches = [
            item
            for item in rows
            if isinstance(item, dict) and item.get("requestId") == record.request_id
        ]
        if len(matches) != 1 or matches[0].get("operation") != expected:
            continue
        outcome = _backend_status(matches[0].get("status"))
        if outcome == "unknown":
            continue
        before = (record.state, record.backend_result)
        record.observe_backend(outcome, stamp)
        if before != (record.state, record.backend_result):
            changed.append(record)
    return changed
