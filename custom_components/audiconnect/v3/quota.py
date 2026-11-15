"""Observed allowance and shared bounded server-recovery policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from collections.abc import Mapping


# Local headroom policy, not a claim about Audi account limits.
COMMAND_RESERVE = 8
OPTIONAL_HEADROOM = 4


def optional_budget_available(remaining, *, cost=1):
    """Conservative local headroom for optional remote actions only."""
    return remaining is None or remaining >= COMMAND_RESERVE + OPTIONAL_HEADROOM + cost


class QuotaUnavailable(RuntimeError):
    """Local quota refusal, before any request is sent."""


@dataclass
class RateLimit:
    """One observed server restriction; bounded recovery, no invented quota."""

    retry_at: datetime | None = None
    recovery_delay: timedelta = timedelta(minutes=15)
    max_recovery_delay: timedelta = timedelta(hours=2)
    clear_streak_on_success: bool = True
    rate_limit_streak: int = 0

    def read_deferred(self, now: datetime) -> bool:
        return self.retry_at is not None and now < self.retry_at

    def authorize(self, now: datetime) -> None:
        if self.read_deferred(now):
            raise QuotaUnavailable("Audi request budget suspended until cooldown")
        if self.retry_at is not None:
            # Reserve the next probe before I/O, including timeout/cancellation.
            self.retry_at = now + self.recovery_delay

    def observe(
        self,
        status: int,
        headers: Mapping[str, str],
        now: datetime,
        *,
        accepted_empty=False,
        allow_redirect=False,
    ) -> None:
        if 200 <= status < (400 if allow_redirect else 300) or (
            accepted_empty and status == 404
        ):
            self.retry_at = None
            if self.clear_streak_on_success:
                self.rate_limit_streak = 0
        if status == 429:
            recovery = min(
                self.recovery_delay * 2**self.rate_limit_streak,
                self.max_recovery_delay,
            )
            self.rate_limit_streak = min(self.rate_limit_streak + 1, 8)
            delay = now + recovery
            retry = headers.get("Retry-After")
            if retry:
                try:
                    delay = now + timedelta(seconds=max(0, int(retry)))
                except (ValueError, OverflowError):
                    try:
                        parsed = parsedate_to_datetime(retry)
                        if parsed.tzinfo is not None:
                            delay = max(now, parsed.astimezone(UTC))
                    except (ValueError, TypeError, OverflowError):
                        pass
            # A new server deadline supersedes a speculative probe reservation.
            self.retry_at = delay

    def rate_limit_checkpoint(self) -> dict:
        """Optional account backoff only; no credentials or response content."""
        if not self.rate_limit_streak or self.retry_at is None:
            return {}
        return {
            "retry_at": self.retry_at.isoformat(),
            "streak": self.rate_limit_streak,
        }

    def restore_rate_limit(self, checkpoint) -> None:
        if not isinstance(checkpoint, dict):
            return
        streak = checkpoint.get("streak")
        try:
            retry = datetime.fromisoformat(checkpoint.get("retry_at", ""))
        except (ValueError, TypeError):
            return
        if type(streak) is int and 1 <= streak <= 8 and retry.tzinfo is not None:
            self.rate_limit_streak = streak
            self.retry_at = retry.astimezone(UTC)


NATIVE_FAMILIES = ("cariad", "graphql", "mbb")


class NativeQuota:
    """Observed VCF allowance and actual restrictions, never invented read costs.

    Family/class identifies the origin of a restriction, not the OEM quota scope.
    No additive allowances across families, accounts, sessions or vehicles.
    """

    def __init__(self):
        self._limits = {}
        self._reports = {}
        self._requests = {}

    def _limit(self, family, kind):
        return self._limits.setdefault((family, kind), RateLimit())

    @property
    def remaining(self):
        return self._latest_report().get("reported")

    @property
    def observed_at(self):
        return self._latest_report().get("at")

    @property
    def request_count(self):
        return sum(self._requests.values())

    def _latest_report(self):
        return max(self._reports.values(), key=lambda row: row["at"], default={})

    def read_deferred(self, now, family):
        return any(
            limit.read_deferred(now)
            for (source, _), limit in self._limits.items()
            if source == family
        )

    def retry_for(self, family):
        return max(
            (
                limit.retry_at
                for (source, _), limit in self._limits.items()
                if source == family and limit.retry_at is not None
            ),
            default=None,
        )

    def planning_remaining(self, now, family):
        row = self._reports.get(family)
        if row is None or now - row["at"] >= timedelta(minutes=15):
            return None
        # Advisory conservative command cost, never a claimed server count.
        return max(0, row["reported"] - row["command_attempts"])

    def authorize(self, now, *, family, read_only, command_preparation=0):
        if family not in NATIVE_FAMILIES:
            raise ValueError("Unknown native API family")
        kind = "command" if command_preparation or not read_only else "read"
        if self.read_deferred(now, family):
            raise QuotaUnavailable("Audi API family rate limited")
        remaining = self.planning_remaining(now, family)
        if (
            command_preparation
            and remaining is not None
            and remaining <= command_preparation
        ):
            raise QuotaUnavailable(
                "Audi command preparation needs allowance for the write"
            )
        # After Retry-After a user-initiated command may try once. Ordinary reads
        # cannot clear a command restriction; no automatic mutation is generated.
        self._limit(family, kind).authorize(now)

    def reserve_request(self, *, family, read_only, command_preparation=0):
        kind = "command" if command_preparation or not read_only else "read"
        key = (family, kind)
        self._requests[key] = self._requests.get(key, 0) + 1
        row = self._reports.get(family)
        if row is not None:
            row["requests_since_header"] += 1
            if kind == "command":
                row["command_attempts"] += 1

    def observe(
        self, status, headers, now, *, family, read_only, command_preparation=0
    ):
        kind = "command" if command_preparation or not read_only else "read"
        # Use the same backoff primitive but never charge VCF allowance to reads.
        self._limit(family, kind).observe(status, headers, now)
        try:
            reported = int(headers.get("Vcf-Remaining-Calls"))
        except (ValueError, TypeError):
            return
        if reported >= 0:
            self._reports[family] = {
                "family": family,
                "kind": kind,
                "reported": reported,
                "at": now,
                "requests_since_header": 0,
                "command_attempts": 0,
            }
            return reported
        return None

    def rate_limit_checkpoint(self):
        return {
            f"{family}:{kind}": checkpoint
            for (family, kind), limit in self._limits.items()
            if (checkpoint := limit.rate_limit_checkpoint())
        }

    def restore_rate_limit(self, checkpoint):
        if not isinstance(checkpoint, dict):
            return
        for family in NATIVE_FAMILIES:
            for kind in ("read", "command"):
                self._limit(family, kind).restore_rate_limit(
                    checkpoint.get(f"{family}:{kind}")
                )

    def diagnostics(self):
        now = datetime.now(UTC)
        return {
            "remaining": self.remaining,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "scope": "unknown_remote_scope",
            "observations": {
                family: {
                    **row,
                    "at": row["at"].isoformat(),
                    "advisory_command_remaining": self.planning_remaining(now, family),
                }
                for family, row in self._reports.items()
            },
            "requests": {
                f"{family}:{kind}": count
                for (family, kind), count in self._requests.items()
            },
            "restrictions": self.rate_limit_checkpoint(),
        }
