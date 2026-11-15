"""Remote allowance observations are not native read counters."""

from datetime import UTC, datetime, timedelta
from custom_components.audiconnect.v3.quota import NativeQuota


def test_missing_header_keeps_observation_not_invented_remaining():
    now = datetime.now(UTC)
    budget = NativeQuota()
    budget.observe(
        200, {"Vcf-Remaining-Calls": "10"}, now, family="cariad", read_only=False
    )
    budget.authorize(now, family="cariad", read_only=True)
    budget.reserve_request(family="cariad", read_only=True)
    assert budget.observe(200, {}, now, family="cariad", read_only=True) is None
    assert budget.request_count == 1
    assert budget.remaining == 10
    assert budget.planning_remaining(now, "cariad") == 10
    assert budget.observed_at == now
    later = now + timedelta(seconds=1)
    assert (
        budget.observe(
            200, {"Vcf-Remaining-Calls": "20"}, later, family="cariad", read_only=True
        )
        == 20
    )
    assert budget.remaining == 20
    assert budget.observed_at == later
