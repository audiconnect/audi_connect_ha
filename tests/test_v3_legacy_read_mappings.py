"""Source-derived MBB legacy GET paths are explicit alternative variants."""

from datetime import UTC, datetime, timedelta

from custom_components.audiconnect.v3.attribute_routes import read_variants
from custom_components.audiconnect.v3.legacy_read_mappings import FIELDS, variant_for
from custom_components.audiconnect.v3.entities import _reading_available


def test_historical_mbb_charger_mappings_and_climater_share_normalized_attributes():
    assert len(FIELDS) >= 15
    assert variant_for("stateOfCharge")["family"] == "mbb"
    assert variant_for("chargingState")["path"] == variant_for("stateOfCharge")["path"]
    assert variant_for("climatisationState")["id"] == "mbb.climater.readonly"
    assert not any("position" in x.lower() for x in FIELDS)
    assert not any("lock_control" in x.lower() for x in FIELDS)


def test_read_variants_include_distinct_safe_mbb_executor_and_mappings():
    routes = read_variants("stateOfCharge", {})
    assert {x["family"] for x in routes} == {"mbb", "cariad"}
    mbb = next(x for x in routes if x["family"] == "mbb")
    assert mbb["response_paths"] == [
        "charger.status.batteryStatusData.stateOfCharge.content"
    ]


def test_legacy_unstamped_readings_never_claim_vehicle_freshness():
    now = datetime.now(UTC)
    item = {
        "family": "mbb",
        "status": "readable_but_stale",
        "observed": now.isoformat(),
        "captured": None,
        "value": 22,
    }
    assert _reading_available(item)
    item["observed"] = (now - timedelta(hours=2)).isoformat()
    assert not _reading_available(item)
    item["observed"] = now.isoformat()
    item["family"] = "cariad"
    assert not _reading_available(item)
