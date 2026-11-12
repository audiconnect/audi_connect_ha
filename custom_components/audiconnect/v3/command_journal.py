"""Bounded persistent execution journal shared by HA and Workbench commands."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from uuid import uuid4


_UNRESOLVED = frozenset({"pending", "uncertain"})
_STATES = _UNRESOLVED | {
    "accepted_unconfirmed",
    "backend_completed",
    "verified",
    "rejected",
    "reviewed",
    "physical_failed",
}
HISTORY_LIMIT = 50
# Local anti-flood policy, not a claimed Audi server limit.
HA_COMMAND_COOLDOWN_SECONDS = 10
TEMPORARY_ERROR_COOLDOWN_SECONDS = 30
ENGINEERING_COMMAND_COOLDOWN_SECONDS = 90
_READBACKS = {
    "climate",
    "chargingState",
    "doorLockStatus",
    "targetstateOfCharge",
    "preferredChargeMode",
    "windowHeatingActive",
    "preheater_active",
    "climatisationWindowHeatingEnabled",
    "climatisationAtUnlock",
    "climatisationZoneFrontLeft",
    "climatisationZoneFrontRight",
    "climatisationZoneRearLeft",
    "climatisationZoneRearRight",
}


@dataclass
class CommandRecord:
    command_id: str
    capability: str
    action: str
    operation: str
    started_at: float
    state: str = "pending"
    request_id: str | None = None
    readback_attribute: str | None = None
    readback_values: list | None = None
    origin: str = "home_assistant"
    engineering_sequence: int | None = None
    operation_revision: str | None = None
    backend_result: str | None = None
    completed_at: float | None = None
    parent_command_id: str | None = None
    http_status: int | None = None

    @classmethod
    def begin(
        cls, capability: str, action: str, operation: str, now: float, **metadata
    ):
        return cls(uuid4().hex, capability, action, operation, now, **metadata)

    def observe_http(self, status: int | None) -> None:
        """Record the initial transport result, not proof of physical execution."""
        self.http_status = status
        self.state = (
            "accepted_unconfirmed"
            if status is not None and 200 <= status < 300
            else "uncertain"
            if status is None or status >= 500
            else "rejected"
        )
        self.backend_result = (
            "transport_uncertain" if self.state == "uncertain" else self.state
        )

    @property
    def unresolved(self) -> bool:
        return self.state in _UNRESOLVED or self.requires_review

    @property
    def requires_review(self) -> bool:
        """Security-sensitive acceptance without confirmation requires review."""
        return self.state == "pending" or (
            self.state in ("uncertain", "accepted_unconfirmed")
            and (
                self.capability == "access"
                or (
                    self.capability == "remote"
                    and self.action in ("engine_start", "engine_stop")
                )
            )
        )

    @property
    def is_wake(self) -> bool:
        """Only the reviewed CARIAD wake/refresh operations are preparatory."""
        return (
            self.capability == "remote"
            and self.action in ("wake", "refresh")
            and self.operation in ("cariad.remote.wake", "cariad.remote.refresh")
        )

    @property
    def wake_accepted(self) -> bool:
        return self.is_wake and self.state in (
            "accepted_unconfirmed",
            "backend_completed",
            "verified",
        )

    def check_next(
        self,
        now: float,
        cooldown: float = HA_COMMAND_COOLDOWN_SECONDS,
        *,
        capability=None,
        action=None,
    ) -> None:
        if self.requires_review:
            raise RuntimeError(
                "Previous vehicle command outcome uncertain; inspect and review it"
            )
        if self.state == "uncertain":
            until = (self.completed_at or self.started_at) + max(
                cooldown, TEMPORARY_ERROR_COOLDOWN_SECONDS
            )
            if now < until:
                raise RuntimeError(
                    f"Previous command outcome uncertain; try again in {math.ceil(until - now)}s"
                )
            return  # No automatic retry; a new explicit request is permitted.
        if self.wake_accepted and capability is not None and action is not None:
            return  # Wake has its own quota/cadence guard in CommandEngine.
        if now < self.started_at + cooldown:
            # A user can explicitly stop a just-accepted comfort/charging
            # operation. No bypass for repeated starts, locks, engine or
            # unresolved commands; a subsequent start still waits.
            reversible = {
                ("climate", "start"): "stop",
                ("climate", "start_with_settings"): "stop",
                ("climate", "window_heating_start"): "window_heating_stop",
                ("charging", "start"): "stop",
                ("climate", "preheater_start"): "preheater_stop",
            }
            if (
                self.origin == "home_assistant"
                and self.state
                in ("accepted_unconfirmed", "backend_completed", "verified")
                and capability == self.capability
                and reversible.get((self.capability, self.action)) == action
                and action is not None
            ):
                return
            remaining = math.ceil(self.started_at + cooldown - now)
            raise RuntimeError(
                f"Vehicle command cooldown active; try again in {remaining}s"
            )

    def snapshot(self) -> dict:
        return asdict(self)

    @classmethod
    def restore(cls, value: dict, *, recover_pending: bool = True):
        if not isinstance(value, dict):
            raise ValueError("Invalid stored command context")
        try:
            record = cls(**value)
        except TypeError as exc:
            raise ValueError("Invalid stored command fields") from exc
        if (
            not isinstance(record.command_id, str)
            or len(record.command_id) != 32
            or any(c not in "0123456789abcdef" for c in record.command_id)
            or any(
                not isinstance(s, str) or not s or len(s) > 160
                for s in (record.capability, record.action, record.operation)
            )
            or type(record.started_at) not in (int, float)
            or not math.isfinite(record.started_at)
            or record.started_at < 0
            or record.state not in _STATES
            or (
                record.http_status is not None
                and (
                    type(record.http_status) is not int
                    or not 100 <= record.http_status <= 599
                )
            )
            or record.origin not in ("home_assistant", "workbench")
            or (
                record.parent_command_id is not None
                and (
                    not isinstance(record.parent_command_id, str)
                    or not re.fullmatch(r"[a-f0-9]{32}", record.parent_command_id)
                    or record.parent_command_id == record.command_id
                    or record.capability != "remote"
                    or record.action != "refresh"
                    or record.origin != "home_assistant"
                )
            )
            or (
                record.engineering_sequence is not None
                and (
                    type(record.engineering_sequence) is not int
                    or record.engineering_sequence < 1
                )
            )
            or (record.origin == "workbench")
            != (record.engineering_sequence is not None)
            or (
                record.operation_revision is not None
                and (
                    not isinstance(record.operation_revision, str)
                    or not re.fullmatch(r"[a-f0-9]{64}", record.operation_revision)
                )
            )
            or (
                record.backend_result is not None
                and record.backend_result
                not in (
                    "accepted_unconfirmed",
                    "backend_completed",
                    "rejected",
                    "unknown",
                    "pending",
                    "quota_limited",
                    "transport_uncertain",
                )
            )
            or (
                record.completed_at is not None
                and (
                    type(record.completed_at) not in (int, float)
                    or not math.isfinite(record.completed_at)
                    or record.completed_at < record.started_at
                )
            )
            or (
                record.request_id is not None
                and (
                    not isinstance(record.request_id, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", record.request_id)
                )
            )
            or (
                record.readback_attribute is not None
                and record.readback_attribute not in _READBACKS
            )
            or (
                record.readback_values is not None
                and (
                    not isinstance(record.readback_values, list)
                    or len(record.readback_values) > 8
                    or any(
                        type(v) not in (str, int, bool) or len(str(v)) > 40
                        for v in record.readback_values
                    )
                )
            )
        ):
            raise ValueError("Invalid stored command context")
        if (
            recover_pending
            and record.state in ("pending", "accepted_unconfirmed")
            and not (
                record.is_wake
                and record.state == "accepted_unconfirmed"
                and record.backend_result == "accepted_unconfirmed"
            )
        ):
            record.state = "uncertain"  # Never replay an interrupted mutation.
        return record


def check_wake_budget(profile, now: float) -> None:
    """Count durable dispatch reservations, including failed and uncertain calls."""
    attempts = sorted(
        row.started_at
        for row in profile.command_journal
        if row.is_wake and now - row.started_at < 86400
    )
    if len(attempts) >= 4 or (attempts and now - attempts[-1] < 1800):
        raise RuntimeError(
            "Audi wake budget: 30 minutes and four attempts per 24 hours"
        )


def unresolved_normal_commands(profile):
    """All unresolved HA commands, not only the latest command pointer."""
    rows = list(getattr(profile, "command_journal", ()))
    latest = getattr(profile, "last_command", None)
    if latest is not None and latest not in rows:
        rows.append(latest)
    return [row for row in rows if row.origin == "home_assistant" and row.unresolved]


def blocking_normal_command(profile, capability):
    return next(
        (
            row
            for row in reversed(unresolved_normal_commands(profile))
            if row.capability == capability and row.requires_review
        ),
        None,
    )


def check_command_sequence(
    profile,
    now: float,
    *,
    capability: str,
    action: str,
    cooldown: float = HA_COMMAND_COOLDOWN_SECONDS,
) -> None:
    """Transient failures expire; security review and anti-flood limits remain."""
    blocker = blocking_normal_command(profile, capability)
    if blocker is not None:
        blocker.check_next(now, cooldown=cooldown, capability=capability, action=action)
    # Only the most recent action in this capability matters for a routine
    # transient failure. Keep older outcomes as history, not an interlock.
    rows = list(getattr(profile, "command_journal", ()))
    latest = profile.last_command
    if latest is not None and latest not in rows:
        rows.append(latest)
    previous = next(
        (
            row
            for row in reversed(rows)
            if row.origin == "home_assistant" and row.capability == capability
        ),
        None,
    )
    if previous is not None and previous.state == "uncertain":
        previous.check_next(
            now, cooldown=cooldown, capability=capability, action=action
        )
    if latest is None:
        return
    if latest.unresolved:
        # Its capability is already checked above. Never erase the journal.
        if now < latest.started_at + cooldown:
            raise RuntimeError(
                f"Vehicle command cooldown active; try again in {math.ceil(latest.started_at + cooldown - now)}s"
            )
        return
    latest.check_next(now, cooldown=cooldown, capability=capability, action=action)
    if not latest.wake_accepted:
        return
    prior = next(
        (
            record
            for record in reversed(profile.command_journal)
            if record.origin == "home_assistant"
            and not record.is_wake
            and not record.unresolved
        ),
        None,
    )
    if prior is not None:
        prior.check_next(now, cooldown=cooldown, capability=capability, action=action)


def restore_history(rows):
    """Validate bounded private history; restore unresolved commands per capability."""
    if not isinstance(rows, list) or len(rows) > HISTORY_LIMIT:
        raise ValueError("Invalid command journal length")
    records = [CommandRecord.restore(row, recover_pending=False) for row in rows]
    if len({record.command_id for record in records}) != len(records):
        raise ValueError("Duplicate command journal ID")
    normal = next(
        (record for record in reversed(records) if record.origin == "home_assistant"),
        None,
    )
    latest_by_capability = {}
    for record in records:
        if record.origin == "home_assistant":
            latest_by_capability[record.capability] = record
    for record in records:
        if record.origin == "home_assistant":
            if record.state == "pending" or (
                record.state == "accepted_unconfirmed"
                and latest_by_capability[record.capability] is record
                and not (
                    record.is_wake and record.backend_result == "accepted_unconfirmed"
                )
            ):
                record.state = "uncertain"
        elif record.state in ("pending", "accepted_unconfirmed"):
            record.state = "uncertain"
    return records, normal


def legacy_snapshot(record):
    """Original b8 last-command shape retained for older-reader compatibility."""
    keys = (
        "command_id",
        "capability",
        "action",
        "operation",
        "started_at",
        "state",
        "request_id",
        "readback_attribute",
        "readback_values",
    )
    return {key: getattr(record, key) for key in keys}
