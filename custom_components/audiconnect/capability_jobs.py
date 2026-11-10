"""Conservative CARIAD selective-status job planning.

Only use the capabilities that Audi itself reported. An absent list means
UNKNOWN, not an unsupported car: preserve the legacy full query.
No extra network requests are made and order is deterministic.
"""

from __future__ import annotations

from typing import Any

BASE_SELECTIVE_JOBS = (
    "access",
    "activeVentilation",
    "auxiliaryHeating",
    "batteryChargingCare",
    "batterySupport",
    "charging",
    "chargingProfiles",
    "chargingTimers",
    "climatisation",
    "climatisationTimers",
    "departureProfiles",
    "departureTimers",
    "fuelStatus",
    "honkAndFlash",
    "hybridCarAuxiliaryHeating",
    "lvBattery",
    "measurements",
    "oilLevel",
    "readiness",
    "userCapabilities",
    "vehicleHealthInspection",
    "vehicleHealthWarnings",
    "vehicleLights",
)


def capability_snapshot(raw: Any) -> tuple[frozenset[str], frozenset[str]] | None:
    """Parse only the public capability IDs/statuses, not VIN or personal data."""
    if not isinstance(raw, dict):
        return None
    cap = raw.get("userCapabilities")
    if not isinstance(cap, dict):
        return None
    status = cap.get("capabilitiesStatus")
    if not isinstance(status, dict) or not isinstance(status.get("value"), list):
        return None
    all_capabilities = status["value"]
    reported: set[str] = set()
    impaired: set[str] = set()
    for entry in all_capabilities:
        if not isinstance(entry, dict):
            continue
        name = entry.get("id")
        if not isinstance(name, str) or not name:
            continue
        reported.add(name)
        # Non-empty status means the service is not unconditionally usable.
        if entry.get("status"):
            impaired.add(name)
    # Zero IDs may be a transient/incomplete capabilities payload. Do not
    # switch to an empty job plan, preserving legacy fallback.
    if not reported:
        return None
    return frozenset(reported), frozenset(impaired)


def select_jobs(
    capabilities: frozenset[str] | None = None,
    impaired: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """Select only supported healthy jobs; always refresh capabilities.

    Caller may pass None for a missing snapshot. An unknown capability must
    not disable the first poll, nor trigger hidden control changes.
    """
    if not capabilities:
        return BASE_SELECTIVE_JOBS
    ignored = impaired or frozenset()
    return tuple(
        job
        for job in BASE_SELECTIVE_JOBS
        if job == "userCapabilities" or (job in capabilities and job not in ignored)
    )
