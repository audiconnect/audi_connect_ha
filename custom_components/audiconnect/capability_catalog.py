"""Fixed, privacy-safe capability catalogue, inspired by observed myAudi identifiers.

The presence of a capability is not proof that a remote command is authorized
or functional. Raw myAudi HAR data is never imported or persisted.
"""

from __future__ import annotations

from typing import Any

CAPABILITY_GROUPS: dict[str, tuple[str, ...]] = {
    "charging": ("charging", "chargingTimers", "chargingProfiles"),
    "climate": ("climatisation", "climatisationTimers", "auxiliaryHeating"),
    "vehicle_status": (
        "measurements",
        "fuelStatus",
        "vehicleHealthInspection",
        "vehicleHealthWarnings",
        "oilLevelStatus",
    ),
    "mobility": ("tripStatistics", "parkingPosition", "b2bVDATrip"),
    "service": ("dealerAppointment", "onlineCarCare", "onlineLogBook"),
    "remote": ("access", "honkAndFlash", "vehicleWakeUp", "vehicleWakeUpTrigger"),
}


def snapshot_capabilities(vehicle: Any) -> dict[str, Any]:
    """Return only predeclared identifiers and a conservative tri-state verdict."""
    checker = getattr(vehicle, "has_capability", None)
    impaired = getattr(vehicle, "impaired_capabilities", frozenset()) or frozenset()
    groups: dict[str, dict[str, str]] = {}
    for family, names in CAPABILITY_GROUPS.items():
        statuses = {}
        for name in names:
            result = checker(name) if callable(checker) else None
            if result is True:
                statuses[name] = "reported_impaired" if name in impaired else "reported"
            elif result is False:
                statuses[name] = "not_reported_for_this_vehicle"
            else:
                statuses[name] = "unknown"
        groups[family] = statuses
    count = getattr(vehicle, "capabilities", None)
    return {
        "source": "vehicle_poll_not_browser_session",
        "advertised_capability_count": len(count)
        if isinstance(count, (set, frozenset, list, tuple))
        else None,
        "groups": groups,
        "command_authorization_confirmed": False,
    }
