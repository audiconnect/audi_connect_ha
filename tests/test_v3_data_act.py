"""Source-format tests, not proof of a live authorized Q8 session."""

from datetime import UTC, datetime, timedelta
import io
import json
import zipfile

import pytest

from custom_components.audiconnect.v3.attribute_runtime import (
    observe_data_act,
    record_observation,
)
from custom_components.audiconnect.v3.data_act import (
    DataActUnavailable,
    decode_dataset,
    soc_observation,
)
from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
from custom_components.audiconnect.v3.freshness import reading_freshness_attributes
from custom_components.audiconnect.v3.registry import CapabilityRegistry
from custom_components.audiconnect.v3.runtime import catalog_path
from custom_components.audiconnect.v3.vehicle import V3Vehicle

VIN = "WAUZZZ4M0MD123456"
SOC = "506cb83e-f99f-3af3-bbeb-0429b69a78d9"


def sample(value, timestamp=None, key=SOC):
    return {
        "key": key,
        "dataFieldName": "battery_state_report.soc",
        "value": value,
        "timestampUtc": timestamp,
    }


def archive(payload, name="vehicle.json"):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as output:
        output.writestr(name, json.dumps(payload))
    return raw.getvalue()


def test_exact_soc_field_and_no_inherited_capture_time():
    now = datetime.now(UTC)
    payload = {
        "vin": VIN,
        "Data": [
            sample("52"),
            sample("99", now.isoformat(), "7bddd5e7-43a4-3878-bd63-9502782f77a5"),
            {"dataFieldName": "car_captured_time", "value": now.isoformat()},
        ],
    }
    decoded = decode_dataset(archive(payload), VIN)
    assert soc_observation(decoded, now) == {
        "value": 52,
        "captured": None,
        "path": SOC,
    }
    payload["Data"].append(sample("40"))
    assert soc_observation(payload, now) is None


@pytest.mark.parametrize("name", ["../vehicle.json", "/vehicle.json", "vehicle.txt"])
def test_archive_rejects_unexpected_paths(name):
    with pytest.raises(DataActUnavailable):
        decode_dataset(archive({"vin": VIN, "Data": []}, name), VIN)


def test_archive_rejects_wrong_vehicle():
    with pytest.raises(DataActUnavailable):
        decode_dataset(archive({"vin": "WAUZZZ4M0MD123457", "Data": []}), VIN)


def test_data_act_fallback_reuses_same_vehicle_reading_and_freshness():
    now = datetime.now(UTC)
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    old = now - timedelta(days=2)
    payload = {"vin": VIN, "Data": [sample("52", old.isoformat())]}
    assert observe_data_act(car, profile, payload, now, now.isoformat())
    row = car.readings["stateOfCharge"]
    assert row["family"] == "eu_data_act" and row["value"] == 52
    attributes = reading_freshness_attributes(row, allow_last_known=True, now=now)
    assert attributes["vehicle_freshness"] == "stale_last_known"
    assert attributes["age_minutes"] == 2880
    assert attributes["delivered_at"] == now.isoformat()
    assert not profile.attribute_evidence and not profile.attribute_routes
    assert record_observation(
        car,
        profile,
        "stateOfCharge",
        80,
        now.isoformat(),
        now,
        "native",
        "charging",
        "cariad",
        fresh=True,
        operation="cariad.climate.status.batch",
        persist_evidence=False,
    )
    assert not observe_data_act(car, profile, payload, now, now.isoformat())
    assert car.readings["stateOfCharge"]["family"] == "cariad"
    assert car.readings["stateOfCharge"]["value"] == 80
