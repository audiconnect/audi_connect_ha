"""Known quota is debited even if a response omits the quota header."""

from datetime import UTC, datetime
from custom_components.audiconnect.v3.quota import QuotaBudget


def test_missing_header_does_not_restore_budget():
    now = datetime.now(UTC)
    budget = QuotaBudget(remaining=10, observed_at=now)
    budget.authorize(now, read_only=True)
    budget.reserve_request()
    budget.observe(200, {}, now)
    assert budget.remaining == 9
    budget.authorize(now, read_only=True)
    budget.reserve_request()
    budget.observe(200, {"Vcf-Remaining-Calls": "20"}, now)
    assert budget.remaining == 20
