"""Account request budget: bounded read-only recovery, no automatic mutations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from collections.abc import Mapping


@dataclass
class QuotaBudget:
    remaining: int | None = None
    observed_at: datetime | None = None
    retry_at: datetime | None = None
    reserve: int = 8
    recovery_delay: timedelta = timedelta(hours=1)
    max_recovery_delay: timedelta | None = None
    rate_limit_streak: int = 0

    def authorize(self, now: datetime, *, read_only: bool) -> None:
        """Reserve a single recovery probe before network I/O under transport lock."""
        exhausted = self.remaining is not None and self.remaining <= self.reserve
        if self.retry_at is not None and now < self.retry_at:
            raise RuntimeError("Audi request budget suspended until cooldown")
        if not exhausted and self.retry_at is None:
            return
        eligible_at = self.retry_at or ((self.observed_at or now) + self.recovery_delay)
        if not read_only or now < eligible_at:
            raise RuntimeError("Audi request budget too low; recovery read required")
        # Reserve before sending: timeout/cancellation cannot cause a probe storm.
        self.retry_at = now + self.recovery_delay

    def reserve_request(self) -> None:
        """Debit known quota before dispatch; a response header replaces the estimate."""
        if self.remaining is not None:
            self.remaining = max(0, self.remaining - 1)

    def observe(self, status: int, headers: Mapping[str, str], now: datetime) -> None:
        success = 200 <= status < (400 if self.max_recovery_delay else 300)
        raw = headers.get("Vcf-Remaining-Calls")
        try:
            count = int(raw) if raw is not None else None
        except (ValueError, TypeError):
            count = None
        if count is not None and count >= 0:
            self.remaining = count
            self.observed_at = now
            if count <= self.reserve:
                self.retry_at = max(self.retry_at or now, now + self.recovery_delay)
            elif success:
                self.retry_at = None
        if count is None and self.remaining is None and success:
            self.retry_at = None
        if status == 429:
            recovery = self.recovery_delay
            if self.max_recovery_delay is not None:
                recovery = min(
                    recovery * 2**self.rate_limit_streak, self.max_recovery_delay
                )
                self.rate_limit_streak = min(self.rate_limit_streak + 1, 8)
            delay = now + recovery
            retry = headers.get("Retry-After")
            if retry:
                try:
                    delay = max(delay, now + timedelta(seconds=max(0, int(retry))))
                except (ValueError, OverflowError):
                    try:
                        parsed = parsedate_to_datetime(retry)
                        if parsed.tzinfo is not None:
                            delay = max(delay, parsed.astimezone(UTC))
                    except (ValueError, TypeError, OverflowError):
                        pass
            self.retry_at = max(self.retry_at or now, delay)


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
