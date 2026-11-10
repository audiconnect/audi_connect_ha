"""Conservative CARIAD selective-status job planning.

Capability IDs and selective-status job names are different contracts. A
capability can be absent or impaired while a previously observed job still
returns valid data. Keep only allowlisted, actually useful jobs from previous
polls; never infer authorization for remote commands or add HTTP requests.
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


# Explicitly verified alias: Audi announces oilLevelStatus but the
# selectivestatus job is oilLevel. Do not add undocumented guesses here.
JOB_CAPABILITY_ALIASES: dict[str, frozenset[str]] = {
    "oilLevel": frozenset({"oilLevelStatus"}),
}


def observed_readable_jobs(
    payload: Any, requested: tuple[str, ...]
) -> frozenset[str]:
    """Track only a job that actually carried a non-empty, non-error value.

    Supports mixed HTTP 207-style payloads. Never retain response values,
    identifiers or arbitrary job names. Reject error-only/empty fragments.
    """
    if not isinstance(payload, dict):
        return frozenset()
    allowed = frozenset(BASE_SELECTIVE_JOBS)
    found: set[str] = set()
    for job in requested:
        if job not in allowed:
            continue
        data = payload.get(job)
        if not isinstance(data, dict) or data.get("error") is not None:
            continue
        stack: list[Any] = [data]
        budget = 64
        while stack and budget > 0:
            budget -= 1
            item = stack.pop()
            if isinstance(item, dict):
                if item.get("error") is not None:
                    continue
                if "value" in item:
                    value = item["value"]
                    if value is not None and value != {} and value != []:
                        found.add(job)
                        break
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item[:16])
    return frozenset(found)


def _job_capabilities(job: str) -> frozenset[str]:
    return frozenset({job}) | JOB_CAPABILITY_ALIASES.get(job, frozenset())


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
    observed: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """Plan one selectivestatus request without dropping proven job data.

    Missing capabilities on first poll means unknown, not unsupported. A
    previously readable job is preserved even if its capability was omitted
    in a later snapshot. Impaired, never-observed jobs stay excluded.
    """
    if not capabilities:
        return BASE_SELECTIVE_JOBS
    ignored = impaired or frozenset()
    confirmed = observed or frozenset()
    return tuple(
        job for job in BASE_SELECTIVE_JOBS
        if (
            job == "userCapabilities"
            or job in confirmed
            or bool((_job_capabilities(job) & capabilities) - ignored)
        )
    )
