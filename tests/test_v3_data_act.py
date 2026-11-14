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
        "plugLockState": "unlocked",
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


@pytest.mark.asyncio
async def test_slow_optional_family_does_not_delay_native_publish():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock

    from custom_components.audiconnect.v3.status_engine import StatusEngine

    car = V3Vehicle(VIN, "Audi", "", "", "BE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    started, finish = asyncio.Event(), asyncio.Event()
    notify = Mock()
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
        notify=notify,
    )

    async def optional():
        started.set()
        await finish.wait()
        now = datetime.now(UTC)
        return [
            (
                car,
                profile,
                {"vin": VIN, "Data": [sample("53", now.isoformat())]},
                now,
                now.isoformat(),
            )
        ]

    async def native():
        status.last_cloud_poll_succeeded = True

    status._poll_data_act = optional
    status._poll_native_status = native
    await asyncio.wait_for(status.poll(), timeout=1)
    await asyncio.wait_for(started.wait(), timeout=1)
    task = status._data_act_task
    assert not task.done()
    await status.poll()
    assert status._data_act_task is task
    assert status.last_cloud_poll_succeeded
    assert "stateOfCharge" not in car.readings
    finish.set()
    await asyncio.wait_for(task, timeout=1)
    assert car.readings["stateOfCharge"]["value"] == 53
    notify.assert_called_once()
    await status.async_stop_data_act()


@pytest.mark.asyncio
async def test_portal_auth_rejection_is_terminal_and_no_native_reauth():
    from unittest.mock import AsyncMock

    from custom_components.audiconnect.v3.data_act import (
        DataActAuthorizationRequired,
        DataActClient,
    )

    login = AsyncMock(side_effect=DataActAuthorizationRequired("denied"))
    client = DataActClient(None, login=login)
    for _ in range(2):
        with pytest.raises(DataActUnavailable):
            await client.latest(VIN)
    login.assert_awaited_once()
    assert client.authorization_required


@pytest.mark.parametrize(
    "action",
    [
        "https://untrusted.invalid/login/authenticate",
        "/signin-service/v1/oauth/consent",
        "https://eu-data-act.drivesomethinggreater.com/login",
    ],
)
def test_portal_credentials_never_submit_to_other_destinations(action):
    from custom_components.audiconnect.v3.data_act_auth import _form

    html = (
        f'<form action="{action}">'
        '<input type="hidden" name="hmac" value="fake">'
        '<input type="hidden" name="_csrf" value="fake">'
        "</form>"
    )
    with pytest.raises(DataActUnavailable):
        _form(
            html, "https://identity.vwgroup.io/signin-service/v1/login", "authenticate"
        )


def test_portal_password_form_uses_only_reviewed_fields():
    from custom_components.audiconnect.v3.data_act_auth import _form

    html = (
        '<form action="/signin-service/v1/audi/login/authenticate">'
        '<input type="hidden" name="hmac" value="example">'
        '<input type="hidden" name="_csrf" value="example">'
        '<input type="hidden" name="consent" value="accept">'
        "</form>"
    )
    target, fields = _form(
        html, "https://identity.vwgroup.io/signin-service/v1/login", "authenticate"
    )
    assert target.endswith("/login/authenticate")
    assert fields == {"hmac": "example", "_csrf": "example"}


def test_data_act_enum_and_temperature_mappings_do_not_invent_state():
    now = datetime.now(UTC)
    registry = CapabilityRegistry.from_json_file(catalog_path())
    stamp = (now - timedelta(hours=35)).isoformat()

    def item(key, name, value):
        return {
            "key": key,
            "dataFieldName": name,
            "value": value,
            "timestampUtc": stamp,
        }

    payload = {
        "vin": VIN,
        "Data": [
            item(
                "6810b781-e54a-35e8-af98-fcdefb54bac6",
                "outside_temperature",
                "2812",
            ),
            item(
                "60a4f436-5534-32f4-b4cc-b5a88a9d4b91",
                "state_front_left_door_window_lifter",
                "3",
            ),
            item(
                "5fcf7d27-6b76-3de0-9ce9-f207370cdaff",
                "state_front_right_door_window_lifter",
                "1",
            ),
            item(
                "60bc0937-f5a7-3809-9535-9a7942e5dd94",
                "lock_state",
                "locked",
            ),
        ],
    }
    rows = data_act_observations(payload, now, registry)
    assert rows["outdoor_temperature"]["value"] == 8.05
    assert rows["left_front_window_open"]["value"] is False
    assert "right_front_window_open" not in rows
    assert rows["plugLockState"]["value"] == "locked"
    assert "doorLockStatus" not in rows
    assert "any_door_unlocked" not in rows
    assert all(row["captured"] == stamp for row in rows.values())


@pytest.mark.asyncio
async def test_vehicle_denial_is_scoped_and_not_retried():
    from unittest.mock import AsyncMock

    from custom_components.audiconnect.v3.data_act import (
        DataActClient,
        DataActVehicleDenied,
    )

    client = DataActClient(None)
    client._json = AsyncMock(side_effect=DataActVehicleDenied("denied"))
    with pytest.raises(DataActVehicleDenied):
        await client.latest(VIN)
    assert await client.latest(VIN) is None
    client._json.assert_awaited_once()
    assert not client.authorization_required
    other = "WAUZZZ4M0MD123457"
    client._json = AsyncMock(return_value={})
    assert await client.latest(other) is None
    client._json.assert_awaited_once()


def test_revoked_family_restores_native_without_replaying_old_data():
    from custom_components.audiconnect.v3.attribute_runtime import (
        remove_family_observations,
    )

    now = datetime.now(UTC)
    car = V3Vehicle(VIN, "Audi", "", "", "BE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    earlier = now - timedelta(hours=3)
    assert record_observation(
        car,
        profile,
        "stateOfCharge",
        80,
        earlier.isoformat(),
        earlier,
        "native",
        "charging",
        "cariad",
        fresh=True,
        operation="cariad.climate.status.batch",
        persist_evidence=False,
    )
    assert observe_data_act(
        car,
        profile,
        {"vin": VIN, "Data": [sample("52", now.isoformat())]},
        now,
        now.isoformat(),
    )
    assert car.readings["stateOfCharge"]["family"] == "eu_data_act"
    assert remove_family_observations(car, profile, "eu_data_act", now)
    assert car.readings["stateOfCharge"]["family"] == "cariad"
    assert car.readings["stateOfCharge"]["value"] == 80
    assert "eu_data_act" not in car.family_readings["stateOfCharge"]


def test_data_act_vehicle_capture_provenance_uses_real_observation_clock():
    from custom_components.audiconnect.v3.freshness import vehicle_capture_summary

    now = datetime.now(UTC)
    captured = (now - timedelta(hours=35)).isoformat()
    delivered = (now - timedelta(minutes=10)).isoformat()
    car = V3Vehicle(VIN, "Audi", "", "", "BE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    assert observe_data_act(
        car, profile, {"vin": VIN, "Data": [sample("52", captured)]}, now, delivered
    )
    summary = vehicle_capture_summary(car, now)
    assert summary["source_family"] == "eu_data_act"
    assert summary["source_delivered_at"] == delivered
    assert summary["source_observed_at"] == now.isoformat()
    assert summary["vehicle_age_minutes"] == 2100
    assert summary["vehicle_freshness"] == "stale"


@pytest.mark.asyncio
async def test_intermediate_success_does_not_reset_portal_reauthentication_guard():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.audiconnect.v3.data_act import DataActClient

    session = MagicMock()
    response = SimpleNamespace(status=200, headers={}, content_length=2)
    response.content = MagicMock()

    async def chunks(_size):
        yield b"{}"

    response.content.iter_chunked = chunks
    session.get.return_value.__aenter__.return_value = response
    login = AsyncMock()
    client = DataActClient(session, login=login)
    client._logged_in = True
    other = "WAUZZZ4M0MD123457"
    client._identifiers = {VIN: "existing", other: "other"}

    async def listing(path, **kwargs):
        response.status = 200
        assert await client._get(path, limit=100) == b"{}"
        if other in path:
            return []
        response.status = 401
        return [{"name": "new.zip", "createdOn": datetime.now(UTC).isoformat()}]

    client._json = listing
    # The established session expires at the final delivery request.
    with pytest.raises(DataActUnavailable):
        await client.latest(VIN)
    assert not client.authorization_required
    assert not client._logged_in
    client.quota.retry_at = None
    # Renew once, even if another VIN happens to succeed before the failed VIN.
    assert await client.latest(other) is None
    with pytest.raises(DataActUnavailable):
        await client.latest(VIN)
    assert client.authorization_required
    login.assert_awaited_once()
    with pytest.raises(DataActUnavailable):
        await client.latest(VIN)
    login.assert_awaited_once()


@pytest.mark.asyncio
async def test_portal_delivery_states_and_future_delivery_guard():
    from unittest.mock import AsyncMock

    from custom_components.audiconnect.v3.data_act import DataActClient

    now = datetime.now(UTC)
    client = DataActClient(None)
    client._json = AsyncMock(
        side_effect=[
            None,
            {"Identifier": "existing"},
            [{"name": "future.zip", "createdOn": "2099-01-01T00:00:00+00:00"}],
            [{"name": "new_no_content_found.zip", "createdOn": now.isoformat()}],
            [{"name": "real.zip", "createdOn": now.isoformat()}],
            [{"name": "real.zip", "createdOn": now.isoformat()}],
        ]
    )
    client._get = AsyncMock(return_value=archive({"vin": VIN, "Data": [sample("52")]}))
    for expected in (
        "subscription_unavailable",
        "no_nonempty_dataset",
        "no_nonempty_dataset",
    ):
        assert await client.latest(VIN) is None
        assert client.delivery_states[VIN] == expected
    client._get.assert_not_awaited()
    assert await client.latest(VIN) is not None
    assert client.delivery_states[VIN] == "dataset_received"
    assert await client.latest(VIN) is None
    assert client.delivery_states[VIN] == "no_new_dataset"
    client._get.assert_awaited_once()


def test_data_act_status_counts_only_canonical_observations():
    from types import SimpleNamespace

    from custom_components.audiconnect.v3.status_engine import StatusEngine

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    row = {"family": "eu_data_act", "value": 52}
    car.family_readings["stateOfCharge"] = {"eu_data_act": row}
    car.readings["stateOfCharge"] = row
    car.readings["last_update_time"] = row
    status = StatusEngine(
        hass=None,
        entry=None,
        auth=SimpleNamespace(data_act_client=None),
        transport=None,
        storage=None,
        vehicles={VIN.lower(): car},
        profiles={},
        discover=None,
        known_inventory=None,
        operation_request=None,
        api_record=None,
    )
    result = status.data_act_poll_status()
    assert result["mapped_observations"] == result["selected_readings"] == 1
    car.readings["stateOfCharge"] = {"family": "cariad", "value": 53}
    result = status.data_act_poll_status()
    assert result["mapped_observations"] == 1
    assert result["selected_readings"] == 0
