"""Account request budget: bounded read-only recovery, no automatic mutations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from collections.abc import Mapping


# Local headroom policy, not a claim about Audi account limits.
COMMAND_RESERVE = 8
OPTIONAL_HEADROOM = 4


def optional_budget_available(remaining, *, cost=1):
    """Preserve command and primary status headroom for optional work."""
    return remaining is None or remaining >= COMMAND_RESERVE + OPTIONAL_HEADROOM + cost


class QuotaUnavailable(RuntimeError):
    """Local quota refusal, before any request is sent."""


@dataclass
class QuotaBudget:
    remaining: int | None = None
    observed_at: datetime | None = None
    retry_at: datetime | None = None
    reserve: int = COMMAND_RESERVE
    recovery_delay: timedelta = timedelta(minutes=15)
    max_recovery_delay: timedelta | None = None
    rate_limit_streak: int = 0

    def read_deferred(self, now: datetime) -> bool:
        """A scheduled read would be refused before I/O by this budget."""
        if self.retry_at is not None:
            return now < self.retry_at
        if self.remaining is None or self.remaining > self.reserve:
            return False
        return now < (self.observed_at or now) + self.recovery_delay

    def authorize(
        self, now: datetime, *, read_only: bool, command_preparation: int = 0
    ) -> None:
        """Reserve a single recovery probe before network I/O under transport lock."""
        # Preparation specifies how many required requests must still follow.
        if command_preparation and (
            self.remaining is not None and self.remaining <= command_preparation
        ):
            raise QuotaUnavailable(
                "Audi command preparation needs allowance for the write"
            )
        if command_preparation and self.rate_limit_streak:
            raise QuotaUnavailable("Audi request budget requires recovery read")
        # A positive reserve is for explicit commands, not a hard server limit.
        if (
            (not read_only or command_preparation)
            and self.remaining is not None
            and 0 < self.remaining <= self.reserve
            and not self.rate_limit_streak
        ):
            return
        exhausted = self.remaining is not None and self.remaining <= self.reserve
        if self.read_deferred(now):
            raise QuotaUnavailable("Audi request budget suspended until cooldown")
        if not exhausted and self.retry_at is None:
            return
        eligible_at = self.retry_at or ((self.observed_at or now) + self.recovery_delay)
        if not read_only or now < eligible_at:
            raise QuotaUnavailable(
                "Audi request budget too low; recovery read required"
            )
        # Reserve before sending: timeout/cancellation cannot cause a probe storm.
        self.retry_at = now + self.recovery_delay

    def reserve_request(self) -> None:
        """Debit known quota before dispatch; a response header replaces the estimate."""
        if self.remaining is not None:
            self.remaining = max(0, self.remaining - 1)

    def observe(
        self,
        status: int,
        headers: Mapping[str, str],
        now: datetime,
        *,
        accepted_empty=False,
    ) -> None:
        success = 200 <= status < (400 if self.max_recovery_delay else 300) or (
            accepted_empty and status == 404
        )
        raw = headers.get("Vcf-Remaining-Calls")
        try:
            count = int(raw) if raw is not None else None
        except (ValueError, TypeError):
            count = None
        if count is not None and count >= 0:
            self.remaining = count
            self.observed_at = now
            if status != 429 and count <= self.reserve:
                self.retry_at = max(self.retry_at or now, now + self.recovery_delay)
            elif success:
                self.retry_at = None
        if success and self.max_recovery_delay is None:
            self.rate_limit_streak = 0
        if (
            count is None
            and success
            and (self.remaining is None or self.remaining > self.reserve)
        ):
            self.retry_at = None
        if status == 429:
            recovery = min(
                self.recovery_delay * 2**self.rate_limit_streak,
                self.max_recovery_delay or timedelta(hours=2),
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

    def diagnostics(self) -> dict:
        """Current local budget evidence; remote scope is not assumed."""
        return {
            "remaining": self.remaining,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "retry_at": self.retry_at.isoformat() if self.retry_at else None,
            "rate_limit_streak": self.rate_limit_streak,
            "command_reserve": self.reserve,
            "optional_headroom_available": optional_budget_available(self.remaining),
        }

    def rate_limit_checkpoint(self) -> dict:
        """Optional account backoff only; no credentials or response content."""
        if not self.rate_limit_streak or self.retry_at is None:
            return {}
        return {
            "retry_at": self.retry_at.isoformat(),
            "streak": self.rate_limit_streak,
        }

    def restore_rate_limit(self, checkpoint) -> None:
        if not self.max_recovery_delay or not isinstance(checkpoint, dict):
            return
        streak = checkpoint.get("streak")
        try:
            retry = datetime.fromisoformat(checkpoint.get("retry_at", ""))
        except (ValueError, TypeError):
            return
        if type(streak) is int and 1 <= streak <= 8 and retry.tzinfo is not None:
            self.rate_limit_streak = streak
            self.retry_at = retry.astimezone(UTC)
