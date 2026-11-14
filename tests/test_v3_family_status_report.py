"""Workbench must not mislabel MBB evidence as CARIAD."""

from custom_components.audiconnect.v3.capability_status import build_status_report
from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
from custom_components.audiconnect.v3.registry import CapabilityRegistry
from custom_components.audiconnect.v3.runtime import catalog_path
from custom_components.audiconnect.v3.vehicle import V3Vehicle


def test_mbb_legacy_reading_has_correct_family_and_vehicle_scope():
    model = CapabilityRegistry.from_json_file(catalog_path())
    car = V3Vehicle(
        vin="WAUZZZ4M0MD123456",
        name="Audi",
        model="A4",
        model_family="",
        country="DE",
        auth_family="legacy",
    )
    profile = DevelopmentProfile(model, car.context)
    profile.attribute_evidence["stateOfCharge"] = {
        "status": "readable_but_stale",
        "source": "mbb.legacy",
        "path": "charger.status.batteryStatusData.stateOfCharge.content",
        "job": "charging",
        "timestamp_present": False,
    }
    report = build_status_report(car, profile)
    rows = [
        r
        for r in report["rows"]
        if r.get("attribute") == "stateOfCharge"
        and r.get("source") == "v3_historical_evidence"
    ]
    assert len(rows) == 1
    assert rows[0]["api_family"] == "mbb"
    assert rows[0]["status"] == "not_observed"
    assert not rows[0]["selected"]
