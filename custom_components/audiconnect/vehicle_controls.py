"""Conservative command capability policy; unknown is never permission to actuate."""

from __future__ import annotations

from typing import Any

# Explicit vehicle-reported permission required. A fuel type or S-PIN alone
# does not prove this remote action is supported.
REMOTE_ENGINE_CAPABILITY = "remoteEngineStart"
_NON_REMOTE_ENGINE_TYPES = frozenset(
    {"electric", "hybrid", "phev", "plug-in hybrid", "plug_in_hybrid"}
)


def engine_start_stop_supported(vehicle: Any) -> bool:
    """Fail closed for engine start/stop, including the Q8 TFSI e.

    This does not infer remote-start support from combustion or S-PIN alone.
    """
    service = getattr(vehicle, "_audi_service", None)
    if not getattr(service, "_spin", None):
        return False

    model_terms = [
        getattr(vehicle, "model", None),
        getattr(vehicle, "model_family", None),
    ]
    if any(
        isinstance(term, str)
        and (
            term.strip().lower().startswith("q8")
            or term.strip().lower().startswith("audi q8")
        )
        for term in model_terms
    ):
        return False

    car_type = getattr(vehicle, "car_type", None)
    if (
        isinstance(car_type, str)
        and car_type.strip().lower() in _NON_REMOTE_ENGINE_TYPES
    ):
        return False

    impaired = getattr(vehicle, "impaired_capabilities", frozenset())
    if REMOTE_ENGINE_CAPABILITY in (impaired or frozenset()):
        return False
    check = getattr(vehicle, "has_capability", None)
    reported = check(REMOTE_ENGINE_CAPABILITY) if callable(check) else None
    if reported is True:
        return True
    if reported is False:
        # A reported denial is not permission, even on legacy vehicles.
        return False
    # Older, non-Auth0 vehicles did not necessarily publish userCapabilities.
    # Retain legacy engine-button eligibility when the capability is unknown,
    # but never extend that fallback to newer Auth0 sessions.
    service = getattr(vehicle, "_audi_service", None)
    uses_auth0 = getattr(service, "uses_auth0", None)
    if uses_auth0 is None:
        uses_auth0 = getattr(service, "_uses_auth0", None)
    return uses_auth0 is False
