"""Source-format tests, not proof of a live authorized Q8 session."""

from datetime import UTC, datetime, timedelta
import io
import json
import zipfile

import pytest

from custom_components.audiconnect.v3.attribute_runtime import (
    data_act_soc,
    observe_data_act,
    record_observation,
)
from custom_components.audiconnect.v3.data_act import (
    DataActUnavailable,
    decode_dataset,
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
    registry = CapabilityRegistry.from_json_file(catalog_path())
    assert data_act_soc(decoded, now, registry) == {
        "value": 52,
        "captured": None,
        "path": SOC,
    }
    payload["Data"].append(sample("40"))
    assert data_act_soc(payload, now, registry) is None


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
    from types import SimpleNamespace

    from custom_components.audiconnect.v3.entities import V3ReadOnlySensor
    from custom_components.audiconnect.v3.historical_catalog import ATTRIBUTES

    entity = V3ReadOnlySensor(SimpleNamespace(), car, ATTRIBUTES["stateOfCharge"])
    unique_id = entity.unique_id
    assert entity.native_value == 52
    assert entity.available
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
    assert entity.unique_id == unique_id
    assert entity.native_value == 80


@pytest.mark.asyncio
async def test_portal_reader_is_bounded_and_never_refetches_old_delivery():
    from unittest.mock import AsyncMock

    from custom_components.audiconnect.v3.data_act import DataActClient

    now = datetime.now(UTC)
    latest = {"name": "new.zip", "createdOn": now.isoformat()}
    older = {
        "name": "old.zip",
        "createdOn": (now - timedelta(days=1)).isoformat(),
    }
    empty = {"name": "new_no_content_found.zip", "createdOn": now.isoformat()}
    client = DataActClient(None)
    client._json = AsyncMock(
        side_effect=[
            {"Identifier": "existing"},
            [older, latest, empty],
            [older],
            [latest],
        ]
    )
    client._get = AsyncMock(
        return_value=archive({"vin": VIN, "Data": [sample("52")]})
    )
    result = await client.latest(VIN)
    assert result[1] == now.isoformat()
    assert client._get.await_count == 1
    assert client._get.call_args.kwargs["headers"]["filename"] == "new.zip"
    assert await client.latest(VIN) is None
    assert await client.latest(VIN) is None
    assert client._get.await_count == 1
    assert client._json.await_count == 4


@pytest.mark.asyncio
async def test_empty_or_unauthorized_subscription_does_not_download():
    from unittest.mock import AsyncMock

    from custom_components.audiconnect.v3.data_act import DataActClient

    client = DataActClient(None)
    client._json = AsyncMock(side_effect=[{"Identifier": "existing"}, []])
    client._get = AsyncMock()
    assert await client.latest(VIN) is None
    client._get.assert_not_awaited()
    client = DataActClient(None)
    client._json = AsyncMock(return_value={})
    client._get = AsyncMock()
    with pytest.raises(DataActUnavailable):
        await client.latest(VIN)
    client._get.assert_not_awaited()
