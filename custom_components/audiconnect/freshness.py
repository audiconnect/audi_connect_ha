"""Freshness calculations for Audi Connect.

Cloud API success and vehicle telemetry age are independent signals.
The Audi timestamp is the newest reported vehicle reading, not evidence
that every vehicle field was updated at the same time.
"""
from __future__ import annotations

from datetime import UTC, datetime

FRESH_MAX_AGE_MINUTES = 30
DELAYED_MAX_AGE_MINUTES = 120


def usable_vehicle_timestamp(value: object, now: datetime | None = None) -> datetime | None:
    """Reject missing, naive, ancient sentinel and implausible future times."""
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    observed = value.astimezone(UTC)
    reference = (now or datetime.now(UTC)).astimezone(UTC)
    if observed.year < 2020 or (observed - reference).total_seconds() > 300:
        return None
    return observed


def vehicle_age_minutes(value: object, now: datetime | None = None) -> int | None:
    """Nonnegative age of the newest timestamp in the vehicle's data."""
    reference = (now or datetime.now(UTC)).astimezone(UTC)
    observed = usable_vehicle_timestamp(value, reference)
    if observed is None:
        return None
    return max(0, int((reference - observed).total_seconds() // 60))


def vehicle_freshness(value: object, now: datetime | None = None) -> str:
    """Fresh <=30m; delayed <=120m; stale >120m. Never assume a cloud poll refreshes telemetry."""
    age = vehicle_age_minutes(value, now)
    if age is None:
        return "unknown"
    if age <= FRESH_MAX_AGE_MINUTES:
        return "fresh"
    if age <= DELAYED_MAX_AGE_MINUTES:
        return "delayed"
    return "stale"
