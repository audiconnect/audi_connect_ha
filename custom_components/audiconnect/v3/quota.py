"""Account request budget: bounded read-only recovery, no automatic mutations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Mapping


@dataclass
class QuotaBudget:
    remaining: int | None = None
    observed_at: datetime | None = None
    retry_at: datetime | None = None
    reserve: int = 8
    recovery_delay: timedelta = timedelta(hours=1)

    def authorize(self, now: datetime, *, read_only: bool) -> None:
        """Reserve a single recovery probe before network I/O under transport lock."""
        exhausted = self.remaining is not None and self.remaining <= self.reserve
        if self.retry_at is not None and now < self.retry_at:
            raise RuntimeError("Audi request budget suspended until cooldown")
        if not exhausted and self.retry_at is None:
            return
        eligible_at = self.retry_at or (
            (self.observed_at or now) + self.recovery_delay
        )
        if not read_only or now < eligible_at:
            raise RuntimeError("Audi request budget too low; recovery read required")
        # Reserve before sending: timeout/cancellation cannot cause a probe storm.
        self.retry_at = now + self.recovery_delay

    def reserve_request(self) -> None:
        """Debit known quota before dispatch; a response header replaces the estimate."""
        if self.remaining is not None:
            self.remaining = max(0, self.remaining - 1)

    def observe(self, status: int, headers: Mapping[str, str], now: datetime) -> None:
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
            elif 200 <= status < 300:
                self.retry_at = None
        if count is None and self.remaining is None and 200 <= status < 300:
            self.retry_at = None
        if status == 429:
            delay = now + self.recovery_delay
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
