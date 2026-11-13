"""Pure fast control-route resolution; discovery never sends vehicle actions.

Catalog matches are not local physical proof. A cached binding is diagnostic
evidence only; the current context and policy are evaluated on every use.
"""

from __future__ import annotations

from .action_discovery import approval_group
from .auth import configured_spin
from .command_policy import eligible_operation
from .operation_revision import operation_revision
from .command_parameters import runtime_ready


def reviewed_alternative(capability, action, operation):
    """The only equivalent built-in fixed-parameter route pairs reviewed so far."""
    if (
        capability == "charging"
        and action in ("start", "stop")
        and operation == f"cariad.charging.{action}"
    ):
        return operation + ".combined"
    return None


def control_decision(
    car, profile, auth, capability: str, aspect: str, *, for_discovery=False
) -> dict:
    key = f"{capability}.{aspect}"

    def decision(status, operation=None, reason=None):
        return {
            "status": status,
            "reason": reason,
            "operation": operation,
            "revision": operation_revision(profile.registry.operations[operation])
            if operation
            else None,
        }

    if key in profile.discovery.disabled:
        return decision("user_disabled")
    from .command_journal import blocking_normal_command

    active = profile.discovery._active
    if active is not None and active.capability == capability:
        return decision("pending_review", reason="engineering_command_awaiting_review")
    blocker = blocking_normal_command(profile, capability)
    if blocker is not None:
        return decision(
            "pending_review",
            reason="previous_vehicle_command_uncertain"
            if blocker.state == "uncertain"
            else "vehicle_command_in_progress",
        )
    restricted = capability == "remote" and aspect in ("engine_start", "engine_stop")
    allowed = eligible_operation(car, auth, capability, aspect) if restricted else None
    if restricted and not allowed:
        return decision("ineligible")
    try:
        available = profile.registry.resolve(capability, aspect, car.context)[
            "available_operations"
        ]
    except ValueError:
        return decision("unknown")

    if capability == "remote" and aspect == "flash":
        # A supported command may be temporarily blocked by a missing
        # prerequisite. Never confuse this with unsupported hardware.
        if "honkAndFlash" in car.impaired_capabilities:
            return decision("temporarily_blocked", reason="capability_impaired")
        if "honkAndFlash" in car.advertised_capabilities and car.position is None:
            return decision("temporarily_blocked", reason="parking_position_missing")

    def currently_safe(ident):
        if ident not in available:
            return False
        op = profile.registry.operations[ident]
        group = approval_group(capability, aspect, op)
        if group not in ("non_spin", "spin"):
            return False
        if group == "spin" and not configured_spin(auth):
            return False
        impaired = car.impaired_capabilities
        relevant = {
            "access": {"access", "remoteLockUnlock"},
            "charging": {"charging"},
            "climate": {"climatisation"},
        }.get(capability, set())
        if capability == "remote" and aspect == "flash":
            relevant = {"honkAndFlash"}
            if car.position is None:
                return False
        if capability == "climate" and aspect.startswith("preheater_"):
            relevant = {"auxiliaryHeating", "hybridCarAuxiliaryHeating"}
        return not (relevant and relevant & impaired)

    ident = profile.active.get(key)
    if (
        ident
        and profile.control_results.get(ident) == "worked"
        and runtime_ready(profile.custom.get(ident, {}))
        and (
            not profile.custom.get(ident, {}).get("parameter_bindings")
            or eligible_operation(car, auth, capability, aspect) is not None
        )
        and (
            not profile.custom.get(ident, {}).get("handler")
            or eligible_operation(car, auth, capability, aspect)
            == profile.custom[ident]["handler"]
        )
        and (not restricted or ident == allowed)
        and currently_safe(ident)
    ):
        revision = profile.active_revisions.get(key)
        if revision == operation_revision(profile.registry.operations[ident]):
            return decision("local_verified", ident)
    if len(profile.registry.capabilities) <= 1:
        return decision("unknown")
    ident = eligible_operation(car, auth, capability, aspect)
    if ident and currently_safe(ident):
        if profile.control_results.get(ident) != "failed":
            return decision("catalog_matched", ident)
        alternative = reviewed_alternative(capability, aspect, ident)
        if (
            alternative
            and currently_safe(alternative)
            and alternative not in profile.custom
            and profile.control_results.get(alternative) != "failed"
        ):
            # A candidate is not a normal HA binding until locally verified.
            return decision(
                "candidate_unverified",
                alternative if for_discovery else None,
                "alternative_requires_verification",
            )
        return decision("no_working_route", reason="reviewed_candidates_failed")
    return decision("unknown")


def resolve_control(car, profile, auth, capability: str, aspect: str) -> str | None:
    return control_decision(car, profile, auth, capability, aspect)["operation"]
