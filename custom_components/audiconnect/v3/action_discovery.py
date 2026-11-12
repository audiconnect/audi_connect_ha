"""V3 guided action discovery, independent from HA, V2 and HTTP.

Never dispatches a vehicle command. An authenticated user-facing controller
must explicitly request one reviewed operation per experiment and obtain the
physical outcome before moving to a different implementation. Evidence is
vehicle-scoped by the OWNER; exported snapshots contain no VIN or payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .registry import CapabilityRegistry, RegistryError, VehicleContext

Result = Literal["worked", "failed", "uncertain"]


def approval_group(capability: str, action: str, operation: dict) -> str:
    """Classify the actual command, not a UI-provided security label.

    Engine stop and auxiliary stop share the protected discovery group even
    when the OEM stop endpoint itself does not transmit a PIN. Unknown
    legacy adapters and arbitrary custom secure bodies cannot be tested here.
    """
    if operation.get("method") == "GET":
        return "read_only"
    if operation.get("family") == "mbb":
        if operation.get("request_mode") == "mbb_rlu":
            return "spin"
        if operation.get("request_mode") in ("mbb_climate_start", "mbb_climate_stop"):
            return "non_spin"
        return "unsupported"
    if operation.get("family") != "cariad":
        return "unsupported"
    if operation.get("method") not in ("POST", "PUT"):
        return "unsupported"
    if (capability == "access" or "/access/" in operation.get("path", "")
            or "/engine/" in operation.get("path", "")
            or "/auxiliaryheating/" in operation.get("path", "")
            or action in (
            "engine_start", "engine_stop", "preheater_start", "preheater_stop"
        ) or operation.get("request_mode") in ("secure_spin", "engine_start", "auxiliary_start")):
        return "spin"
    return "non_spin"


def validate_approval(capability: str, action: str, operation: dict,
                      approval: object, *, has_spin: bool) -> str:
    group = approval_group(capability, action, operation)
    if group not in ("non_spin", "spin") or approval != group:
        raise DiscoveryError("Explicit approval for this control security group is required")
    if group == "spin" and not has_spin:
        raise DiscoveryError("S-PIN must already be configured for protected discovery")
    return group


class DiscoveryError(ValueError):
    """Guided discovery cannot safely advance in its current state."""


@dataclass
class ActionAttempt:
    """One deliberately initiated action, with independent network/real outcome."""

    sequence: int
    capability: str
    action: str
    operation: str
    started_at: float
    http_status: int | None = None
    transport: str = "not_observed"
    result: str = "awaiting_user_feedback"
    closed_at: float | None = None

    def public(self) -> dict[str, str | int | float | None]:
        return {
            "sequence": self.sequence,
            "capability": self.capability,
            "action": self.action,
            "operation": self.operation,
            "transport": self.transport,
            "http_status": self.http_status,
            "result": self.result,
            "started_at": self.started_at,
            "closed_at": self.closed_at,
        }


class GuidedActionDiscovery:
    """A small per-vehicle state machine; no network calls or HA dependencies.

    - Only *explicit* user intent starts an experiment.
    - One unresolved attempt blocks all other action experiments on the car.
    - HTTP 2xx != physical success, and HTTP failure alone != physical failure.
    - The person testing the vehicle verifies what happened.
    - Disabled capabilities stay disabled, regardless of advertised support.
    - Worked routes are preferred for this vehicle only, never globally.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        context: VehicleContext,
        *,
        cooldown_seconds: float = 15,
        history_limit: int = 30,
    ) -> None:
        if cooldown_seconds < 0 or not 1 <= history_limit <= 100:
            raise DiscoveryError("Invalid discovery safety limits")
        self.registry = registry
        self.context = context
        self.cooldown_seconds = cooldown_seconds
        self.history_limit = history_limit
        self.history: list[ActionAttempt] = []
        self.preferred: dict[str, str] = {}
        self.disabled: set[str] = set()
        self._active: ActionAttempt | None = None
        self._sequence = 0

    def candidates(self, capability: str, action: str) -> list[dict[str, str]]:
        """Show alternatives ordered by evidence, but never send a request."""
        if not self.registry.operations_for(capability, action):
            raise DiscoveryError("No reviewed control routes are available")
        refs = self.registry.resolve(capability, action, self.context)
        works = self.preferred.get(f"{capability}.{action}")
        previously_failed = {
            row.operation for row in self.history
            if row.capability == capability
            and row.action == action
            and row.result == "failed"
        }
        ids = list(refs["available_operations"])
        ids.sort(key=lambda ident: (
            0 if ident == works else 1 if ident not in previously_failed else 2,
            self.registry.operations[ident].get("priority", 100),
        ))
        return [
            {
                "operation": ident,
                "evidence": "worked_for_this_vehicle" if ident == works
                else "previously_failed" if ident in previously_failed
                else "untested",
                "selection_only": "true",
            }
            for ident in ids
        ]

    def begin(
        self,
        capability: str,
        action: str,
        operation: str,
        *,
        user_initiated: bool,
        now: float,
    ) -> ActionAttempt:
        """Begin one user-authorized experiment; DOES NOT invoke an API."""
        if user_initiated is not True:
            raise DiscoveryError("Physical action tests require a user gesture")
        key = f"{capability}.{action}"
        if key in self.disabled:
            raise DiscoveryError("This action has been disabled by the user")
        if self._active is not None:
            raise DiscoveryError("Review the previous action before trying another")
        if self.history and now < self.history[-1].started_at + self.cooldown_seconds:
            raise DiscoveryError("Vehicle command cooldown still active")
        try:
            applicable = self.registry.resolve(
                capability, action, self.context, preferred=operation
            )["available_operations"]
        except RegistryError as exc:
            raise DiscoveryError("Invalid or context-incompatible API variant") from exc
        if operation not in applicable:
            raise DiscoveryError("Variant not applicable to this vehicle")
        self._sequence += 1
        record = ActionAttempt(
            sequence=self._sequence,
            capability=capability,
            action=action,
            operation=operation,
            started_at=now,
        )
        self._active = record
        self.history.append(record)
        self.history[:] = self.history[-self.history_limit:]
        return record

    def observe_transport(self, sequence: int, *, http_status: int | None) -> None:
        """Transport is evidence, not an actuator completion assertion."""
        record = self._require_active(sequence)
        if record.transport != "not_observed":
            raise DiscoveryError("Transport result already recorded")
        if http_status is not None and not 100 <= http_status <= 599:
            raise DiscoveryError("Invalid HTTP status")
        record.http_status = http_status
        record.transport = (
            "timeout_or_unknown" if http_status is None
            else "accepted_unconfirmed" if 200 <= http_status < 300
            else "http_rejected_or_error"
        )

    def review(
        self,
        sequence: int,
        *,
        result: Result,
        inspected_vehicle: bool,
        now: float,
        readback_verified: bool = False,
    ) -> ActionAttempt:
        """User can record worked/failed only after reviewing real vehicle.

        If unsure, retain an unresolved attempt; a different POST is blocked
        until the operator checks what the car actually did and resolves it.
        """
        record = self._require_active(sequence)
        if result not in ("worked", "failed", "uncertain"):
            raise DiscoveryError("Unknown physical-action outcome")
        if result in ("worked", "failed") and inspected_vehicle is not True and not (
                result == "worked" and readback_verified is True):
            raise DiscoveryError("Physical outcome requires vehicle confirmation")
        if now < record.started_at:
            raise DiscoveryError("Feedback timestamp precedes request")
        if result == "uncertain":
            record.result = "uncertain_pending_review"
            return record

        record.result = result
        record.closed_at = now
        key = f"{record.capability}.{record.action}"
        if result == "worked":
            self.preferred[key] = record.operation
        elif self.preferred.get(key) == record.operation:
            self.preferred.pop(key)
        self._active = None
        return record

    def reject_nonexecution(self, sequence: int, *, now: float) -> ActionAttempt:
        """Close a definitive pre-execution rejection without inventing physical feedback."""
        record = self._require_active(sequence)
        if record.http_status not in (405, 410) or record.transport != "http_rejected_or_error" or now < record.started_at:
            raise DiscoveryError("No definitive route rejection")
        record.result = "rejected"
        record.closed_at = now
        key = f"{record.capability}.{record.action}"
        if self.preferred.get(key) == record.operation:
            self.preferred.pop(key)
        self._active = None
        return record

    def disable(self, capability: str, action: str) -> None:
        """A user may disable an unwanted action independently of status."""
        if not self.registry.operations_for(capability, action):
            raise DiscoveryError("Only defined controls may be disabled")
        if self._active is not None:
            raise DiscoveryError("Resolve in-flight test before disabling controls")
        self.registry.operations_for(capability, action)
        self.disabled.add(f"{capability}.{action}")

    def enable(self, capability: str, action: str) -> None:
        """Re-enable a control without inventing positive evidence."""
        self.disabled.discard(f"{capability}.{action}")

    def _require_active(self, sequence: int) -> ActionAttempt:
        if self._active is None or self._active.sequence != sequence:
            raise DiscoveryError("No matching active vehicle experiment")
        return self._active

    def snapshot(self) -> dict[str, object]:
        """No VIN, auth token, request body, vehicle location or URL."""
        return {
            "disabled_controls": sorted(self.disabled),
            "preferred": dict(self.preferred),
            "active_sequence": self._active.sequence if self._active else None,
            "attempts": [attempt.public() for attempt in self.history],
        }
