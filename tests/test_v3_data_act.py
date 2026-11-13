"""Source-format tests, not proof of a live authorized Q8 session."""

from datetime import UTC, datetime, timedelta
import io
import json
import zipfile

import pytest

from custom_components.audiconnect.v3.attribute_runtime import (
    data_act_observations,
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
    assert data_act_observations(decoded, now, registry).get("stateOfCharge") == {
        "value": 52,
        "captured": None,
        "path": SOC,
    }
    payload["Data"].append(sample("40"))
    assert not data_act_observations(payload, now, registry)


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
    client._get = AsyncMock(return_value=archive({"vin": VIN, "Data": [sample("52")]}))
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
    assert await client.latest(VIN) is None
    client._get.assert_not_awaited()


@pytest.mark.asyncio
async def test_data_act_rate_limit_is_independent_of_native_quota():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from custom_components.audiconnect.v3.data_act import DataActClient
    from custom_components.audiconnect.v3.quota import QuotaBudget

    native = QuotaBudget(remaining=50)
    session = MagicMock()
    response = SimpleNamespace(status=429, headers={"Retry-After": "7200"})
    session.get.return_value.__aenter__.return_value = response
    client = DataActClient(session)
    with pytest.raises(DataActUnavailable):
        await client._get("/test", limit=100)
    assert client.quota.retry_at > datetime.now(UTC) + timedelta(minutes=119)
    with pytest.raises(DataActUnavailable):
        await client._get("/test", limit=100)
    assert session.get.call_count == 1
    assert native.remaining == 50 and native.retry_at is None


@pytest.mark.asyncio
async def test_optional_family_uses_existing_status_cadence_and_auth():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from custom_components.audiconnect.v3.quota import QuotaBudget
    from custom_components.audiconnect.v3.status_engine import StatusEngine

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    auth = SimpleNamespace(data_act_client=None)
    status = StatusEngine(
        hass=None,
        entry=None,
        auth=auth,
        transport=lambda: None,
        storage=None,
        vehicles={VIN.lower(): car},
        profiles={VIN.lower(): profile},
        discover=None,
        known_inventory=None,
        operation_request=None,
        api_record=None,
    )
    now = datetime.now(UTC)
    await status._poll_data_act(now)
    assert status.data_act_poll_status()["result"] == "not_configured"
    client = SimpleNamespace(
        authorization_required=False,
        quota=QuotaBudget(),
        latest=AsyncMock(return_value=None),
    )
    auth.data_act_client = client
    await status._poll_data_act(now)
    await status._poll_data_act(now + timedelta(minutes=15))
    assert client.latest.await_count == 1
    await status._poll_data_act(now + timedelta(minutes=30))
    assert client.latest.await_count == 2
    client.quota.retry_at = now + timedelta(hours=3)
    await status._poll_data_act(now + timedelta(hours=1))
    assert status.data_act_poll_status()["result"] == "rate_limited"
    assert client.latest.await_count == 2
    client.authorization_required = True
    await status._poll_data_act(now + timedelta(hours=4))
    assert status.data_act_poll_status()["result"] == "authorization_required"
    assert client.latest.await_count == 2


@pytest.mark.asyncio
async def test_independent_family_reads_overlap_and_publish_through_shared_writer():
    import asyncio
    from types import SimpleNamespace

    from custom_components.audiconnect.v3.status_engine import StatusEngine

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    status = StatusEngine(
        hass=None,
        entry=None,
        auth=SimpleNamespace(data_act_client=object()),
        transport=lambda: SimpleNamespace(remaining_calls=50),
        storage=None,
        vehicles={VIN.lower(): car},
        profiles={VIN.lower(): profile},
        discover=None,
        known_inventory=lambda: True,
        operation_request=None,
        api_record=None,
    )
    native_started = asyncio.Event()
    optional_started = asyncio.Event()
    now = datetime.now(UTC)

    async def native():
        native_started.set()
        await optional_started.wait()
        record_observation(
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
        status.last_cloud_poll_succeeded = True

    async def optional():
        optional_started.set()
        await native_started.wait()
        payload = {"vin": VIN, "Data": [sample("52", now.isoformat())]}
        return [(car, profile, payload, now, now.isoformat())]

    status._poll_native_status = native
    status._poll_data_act = optional
    await asyncio.wait_for(status.poll(), timeout=2)
    await asyncio.wait_for(status._data_act_task, timeout=2)
    assert car.readings["stateOfCharge"]["family"] == "cariad"
    assert car.readings["stateOfCharge"]["value"] == 80
    assert status.last_cloud_poll_succeeded


def test_sparse_q8_shape_maps_known_information_only():
    """Synthetic values and VIN; field IDs are from the public dictionary."""
    now = datetime.now(UTC)
    stamp = (now - timedelta(hours=35)).isoformat()
    registry = CapabilityRegistry.from_json_file(catalog_path())
    fields = [
        ("ae0294b4-1286-3e98-a818-1485b8d88430", "state_of_charge", "64"),
        ("41c0805c-43e5-313e-9dfb-356cb8d20f7c", "mileage", "12345"),
        ("1503760b-5570-3001-8ffc-1bb6f464948e", "fuel_level_current_level", "80"),
        ("153e8c40-4c6c-3c17-a11b-0ecc35d55b81", "cruising_range_combined", "620"),
        (
            "55e0d40b-38ed-3cb5-9dcd-6193df6fc493",
            "cruising_range_primary_engine",
            "590",
        ),
        (
            "3dedefab-8ded-3f5a-907f-d5e9970720bf",
            "cruising_range_secondary_engine",
            "30",
        ),
        ("a3368611-8c63-3b7d-9d19-148a464c7a7b", "oil_level_actual_level", "95"),
        ("cf28f7d9-6201-30b8-82e5-a461968d30dc", "remaining_charging_time", "65535"),
        (
            "1c62bf0a-8088-332c-9399-3b8cb0573099",
            "remaining_climatisation_time",
            "-256",
        ),
        ("60bc0937-f5a7-3809-9535-9a7942e5dd94", "lock_state", "unlocked"),
    ]
    payload = {
        "vin": VIN,
        "Data": [
            {"key": key, "dataFieldName": field, "value": value, "timestampUtc": stamp}
            for key, field, value in fields
        ],
    }
    car = V3Vehicle(VIN, "Audi", "", "", "BE")
    profile = DevelopmentProfile(registry, car.context)
    assert observe_data_act(car, profile, payload, now, now.isoformat())
    assert {key: row["value"] for key, row in car.readings.items()} == {
        "stateOfCharge": 64,
        "UTC_TIME_AND_KILOMETER_STATUS": 12345,
        "TANK_LEVEL_IN_PERCENTAGE": 80,
        "TOTAL_RANGE": 620,
        "primaryEngineRange": 590,
        "secondaryEngineRange": 30,
        "OIL_LEVEL_DIPSTICKS_PERCENTAGE": 95,
    }
    assert all(row["captured"] == stamp for row in car.readings.values())
    assert not profile.attribute_evidence and not profile.attribute_routes
    payload["Data"][1]["value"] = "65535"
    assert (
        data_act_observations(payload, now, registry)["UTC_TIME_AND_KILOMETER_STATUS"][
            "value"
        ]
        == 65535
    )
    for invalid in ("4294967295", "2147483647", "-1", "123.5"):
        payload["Data"][1]["value"] = invalid
        assert "UTC_TIME_AND_KILOMETER_STATUS" not in data_act_observations(
            payload, now, registry
        )
