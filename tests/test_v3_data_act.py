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
    assert not client._last_file
    client.acknowledge(VIN, result[2])
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
    from custom_components.audiconnect.v3.data_act import DataActClient

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
        auth=SimpleNamespace(data_act_client=DataActClient(None)),
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
        return [(car, profile, payload, now, now.isoformat(), (now, "test.zip"))]

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
    assert {
        key: row["value"]
        for key, row in car.readings.items()
        if row["value"] is not None
    } == {
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
    for ident in ("remainingChargingTime", "remainingClimatisationTime"):
        assert car.readings[ident]["status"] == "invalid_value"
        assert car.readings[ident]["value"] is None
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
        assert (
            data_act_observations(payload, now, registry)[
                "UTC_TIME_AND_KILOMETER_STATUS"
            ]["value"]
            is None
        )


@pytest.mark.asyncio
async def test_slow_optional_family_does_not_delay_native_publish():
    from custom_components.audiconnect.v3.data_act import DataActClient

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
        auth=SimpleNamespace(data_act_client=DataActClient(None)),
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
                (now, "test.zip"),
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
    assert rows["right_front_window_open"]["value"] is None
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
    assert client.denied_vins == {VIN}
    assert client.delivery_states[VIN] == "vehicle_access_denied"
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
    result = await client.latest(VIN)
    assert result is not None
    client.acknowledge(VIN, result[2])
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


def test_data_act_account_status_is_derived_from_channel_state():
    from types import SimpleNamespace

    from custom_components.audiconnect.v3.data_act import DataActClient
    from custom_components.audiconnect.v3.status_engine import StatusEngine

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    client = DataActClient(None)
    status = StatusEngine(
        hass=None,
        entry=None,
        auth=SimpleNamespace(data_act_client=client),
        transport=None,
        storage=None,
        vehicles={VIN.lower(): car},
        profiles={},
        discover=None,
        known_inventory=None,
        operation_request=None,
        api_record=None,
    )
    assert status.data_act_poll_status()["result"] == "initializing"
    status._data_act_attempt_at = datetime.now(UTC)
    for delivery, expected in (
        ("dataset_received", "dataset_received"),
        ("vehicle_access_denied", "vehicle_access_denied"),
        ("subscription_unavailable", "subscription_unavailable"),
        ("unavailable", "unavailable"),
    ):
        client.delivery_states[VIN] = delivery
        report = status.data_act_poll_status()
        assert report["result"] == expected
        assert report["delivery_states"] == {delivery: 1}
    client.authorization_required = True
    assert status.data_act_poll_status()["result"] == "authorization_required"


@pytest.mark.asyncio
async def test_delivery_is_retried_until_status_acknowledges_it():
    from unittest.mock import AsyncMock

    from custom_components.audiconnect.v3.data_act import DataActClient

    now = datetime.now(UTC)
    listing = [{"name": "new.zip", "createdOn": now.isoformat()}]
    client = DataActClient(None)
    client._json = AsyncMock(
        side_effect=[{"Identifier": "existing"}, listing, listing, listing]
    )
    client._get = AsyncMock(return_value=archive({"vin": VIN, "Data": [sample("52")]}))
    first = await client.latest(VIN)
    second = await client.latest(VIN)
    assert first == second
    assert client._get.await_count == 2
    client.acknowledge(VIN, second[2])
    assert await client.latest(VIN) is None


@pytest.mark.asyncio
async def test_optional_status_only_update_is_published_without_registry_migration():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from custom_components.audiconnect.v3.data_act import DataActClient
    from custom_components.audiconnect.v3.status_engine import StatusEngine

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    client = DataActClient(None)
    notify = Mock()
    status = StatusEngine(
        hass=None,
        entry=None,
        auth=SimpleNamespace(data_act_client=client),
        transport=None,
        storage=None,
        vehicles={VIN.lower(): car},
        profiles={},
        discover=None,
        known_inventory=None,
        operation_request=None,
        api_record=None,
        notify=notify,
    )

    async def poll():
        client.delivery_states[VIN] = "subscription_unavailable"
        return []

    status._poll_data_act = poll
    await status._collect_data_act()
    notify.assert_called_once_with(reconcile_registry=False)
    await status._collect_data_act()
    notify.assert_called_once()


@pytest.mark.asyncio
async def test_portal_identity_only_enriches_owned_missing_fields():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from custom_components.audiconnect.v3.data_act import DataActClient
    from custom_components.audiconnect.v3.engine import V3Engine
    from custom_components.audiconnect.v3.identity_cache import capture_identity
    from custom_components.audiconnect.v3.status_engine import StatusEngine

    car = V3Vehicle(VIN, "Audi vehicle", "", "", "BE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    client = DataActClient(None)
    client._json = AsyncMock(
        return_value={
            "vehicles": [
                {
                    "vin": VIN,
                    "modelName": "Audi Q8",
                    "modelYear": 2021,
                    "vehicleNickname": "Not the model",
                },
                {"vin": "WAUZZZ4M0MD123457", "modelName": "Audi A8"},
            ]
        }
    )
    engine = SimpleNamespace(
        _rebind_identity_context=Mock(),
        health=SimpleNamespace(observe_inventory=Mock()),
    )
    storage = SimpleNamespace(async_save=AsyncMock())
    status = StatusEngine(
        hass=None,
        entry=None,
        auth=SimpleNamespace(data_act_client=client),
        transport=None,
        storage=storage,
        vehicles={VIN.lower(): car},
        profiles={VIN.lower(): profile},
        discover=None,
        known_inventory=None,
        operation_request=None,
        api_record=None,
        apply_identity=lambda *args, **kwargs: V3Engine._apply_identity_candidate(
            engine, *args, **kwargs
        ),
    )
    assert await status._enrich_data_act_identity(client)
    assert car.model == "Audi Q8"
    assert car.model_year == "2021"
    assert car.identity_operation == "eu_data_act.identity.vehicles"
    assert capture_identity(car)["operation"] == car.identity_operation
    assert profile.manufacturer_identity["source"] == "eu_data_act_modelName"
    schema = profile.job_schema["eu_data_act.identity.vehicles"]
    assert schema["outcome"] == "matched_vehicle"
    assert any(field["path"] == "modelName" for field in schema["fields"])
    assert VIN not in str(schema)
    assert "Audi Q8" not in str(schema)
    assert not await status._enrich_data_act_identity(client)
    client._json.assert_awaited_once()
    storage.async_save.assert_awaited_once()
    status._update_capture_projection()
    assert car.readings["model"]["family"] == "eu_data_act"


@pytest.mark.parametrize(
    "row",
    [
        {"vehicleNickname": "Audi Q8"},
        {"modelName": "vehicle"},
        {"modelName": "unknown"},
    ],
)
def test_portal_identity_does_not_promote_nickname_or_placeholder(row):
    candidate = V3Vehicle.from_data_act(
        {"vin": VIN, **row}, "BE", CapabilityRegistry.from_json_file(catalog_path())
    )
    assert not candidate.model
    assert not candidate.model_family


def test_data_act_discovery_reuses_schema_inventory_without_raw_values():
    from custom_components.audiconnect.v3.read_discovery import (
        data_act_discovery,
        record_data_act_fields,
    )

    now = datetime.now(UTC)
    registry = CapabilityRegistry.from_json_file(catalog_path())
    car = V3Vehicle(VIN, "Audi vehicle", "", "", "BE")
    profile = DevelopmentProfile(registry, car.context)
    unknown = {
        "key": "00000000-0000-0000-0000-000000000001",
        "dataFieldName": "unmapped_signal",
        "value": "private raw data",
        "timestampUtc": now.isoformat(),
    }
    payload = {"vin": VIN, "Data": [sample("52", now.isoformat()), unknown]}
    assert record_data_act_fields(profile, payload, now)
    assert observe_data_act(car, profile, payload, now, now.isoformat())
    report = data_act_discovery(car, profile, include_fields=True)
    assert report["fields_observed"] == 2
    assert report["fields_mapped"] == report["fields_normalized"] == 1
    assert report["fields_unmapped"] == 1
    assert report["fields"][1]["status"] == "mapping_missing"
    assert "private raw data" not in json.dumps(profile.job_schema)
    assert VIN not in json.dumps(profile.job_schema)
    assert not record_data_act_fields(profile, {"Data": []}, now)
    assert data_act_discovery(car, profile)["fields_observed"] == 2
    assert not profile.attribute_routes and not profile.attribute_evidence
    from custom_components.audiconnect.v3.capability_status import build_status_report

    sources = build_status_report(car, profile)["family_discovery"]
    source = next(item for item in sources if item["id"] == "eu_data_act")
    assert source["fields_observed"] == 2
    assert source["fields_mapped"] == source["normalized"] == source["selected"] == 1
    assert source["fresh"] == 1
    assert not source["read_scan"]
    assert "private raw data" not in str(source)


@pytest.mark.asyncio
async def test_missing_subscription_removes_only_optional_readings():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from custom_components.audiconnect.v3.data_act import DataActClient
    from custom_components.audiconnect.v3.status_engine import StatusEngine

    now = datetime.now(UTC)
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    earlier = now - timedelta(minutes=10)
    record_observation(
        car,
        profile,
        "stateOfCharge",
        80,
        earlier.isoformat(),
        now,
        "native",
        "charging",
        "cariad",
        fresh=True,
        operation="cariad.climate.status.batch",
        persist_evidence=False,
    )
    observe_data_act(
        car,
        profile,
        {"vin": VIN, "Data": [sample("52", now.isoformat())]},
        now,
        now.isoformat(),
    )
    client = DataActClient(None)
    status = StatusEngine(
        hass=None,
        entry=None,
        auth=SimpleNamespace(data_act_client=client),
        transport=None,
        storage=None,
        vehicles={VIN.lower(): car},
        profiles={VIN.lower(): profile},
        discover=None,
        known_inventory=None,
        operation_request=None,
        api_record=None,
        notify=Mock(),
    )

    async def poll():
        client.delivery_states[VIN] = "subscription_unavailable"
        return []

    status._poll_data_act = poll
    await status._collect_data_act()
    assert car.readings["stateOfCharge"]["value"] == 80
    assert "eu_data_act" not in car.family_readings["stateOfCharge"]
    assert status.data_act_poll_status()["result"] == "subscription_unavailable"


def test_data_act_duration_and_hood_enrichment_rejects_sentinels():
    from datetime import UTC, datetime
    from custom_components.audiconnect.v3.attribute_runtime import data_act_observations

    now = datetime.now(UTC)
    registry = CapabilityRegistry.from_json_file(catalog_path())
    payload = {
        "Data": [
            {
                "key": "cf28f7d9-6201-30b8-82e5-a461968d30dc",
                "dataFieldName": "remaining_charging_time",
                "value": "42",
                "timestampUtc": now.isoformat(),
            },
            {
                "key": "1c62bf0a-8088-332c-9399-3b8cb0573099",
                "dataFieldName": "remaining_climatisation_time",
                "value": "-1",
                "timestampUtc": now.isoformat(),
            },
            {
                "key": "d48ccd21-a39f-33eb-989b-d81bd23fa766",
                "dataFieldName": "state_of_hood",
                "value": "3",
                "timestampUtc": now.isoformat(),
            },
        ]
    }
    result = data_act_observations(payload, now, registry)
    assert result["remainingChargingTime"]["value"] == 42
    assert result["remainingClimatisationTime"]["value"] is None
    assert result["hood_open"]["value"] is False


def test_optional_identity_withdrawal_preserves_native_telemetry_and_history():
    from custom_components.audiconnect.v3.identity_cache import (
        capture_identity,
        withdraw_optional_identity,
        without_optional_identity,
    )

    now = datetime.now(UTC)
    car = V3Vehicle.from_data_act(
        {"vin": VIN, "modelName": "Audi Q8", "modelYear": 2021},
        "BE",
        CapabilityRegistry.from_json_file(catalog_path()),
    )
    car.identity_observed_at = now.isoformat()
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    profile.manufacturer_identity = capture_identity(car)
    assert profile.manufacturer_identity
    assert not without_optional_identity(profile.manufacturer_identity)
    car.readings["stateOfCharge"] = {"value": 80, "family": "cariad"}
    car.trip_history.append({"startMileage": 1, "overallMileage": 2})
    assert withdraw_optional_identity(car, profile)
    assert not car.model and not car.model_year and not profile.manufacturer_identity
    assert car.readings["stateOfCharge"]["value"] == 80
    assert len(car.trip_history) == 1
    assert not withdraw_optional_identity(car, profile)

    car = V3Vehicle(VIN, "Audi Q8", "Audi Q8", "q8", "BE")
    car.model_source = "audi_long_name"
    car.identity_operation = "graphql.inventory.vehicleList"
    car.identity_observed_at = now.isoformat()
    car.model_year = "2021"
    car.year_operation = "eu_data_act.identity.vehicles"
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    profile.manufacturer_identity = capture_identity(car)
    assert withdraw_optional_identity(car, profile)
    assert car.model == "Audi Q8" and not car.model_year
    assert profile.manufacturer_identity["model"] == "Audi Q8"
    assert not profile.manufacturer_identity["year"]


@pytest.mark.asyncio
async def test_native_and_portal_share_a_bounded_response_reader():
    from types import SimpleNamespace

    from custom_components.audiconnect.v3.data_act import read_bounded
    from custom_components.audiconnect.v3.transport import read_bounded_body

    async def chunks(_size):
        yield b"ab"
        yield b"cd"

    response = SimpleNamespace(
        content_length=None, content=SimpleNamespace(iter_chunked=chunks)
    )
    assert await read_bounded_body(response, 4) == b"abcd"
    with pytest.raises(ValueError, match="size limit"):
        await read_bounded_body(response, 3)
    with pytest.raises(DataActUnavailable, match="too large"):
        await read_bounded(response, 3)
    response.content_length = 10
    with pytest.raises(ValueError, match="size limit"):
        await read_bounded_body(response, 4)


def test_portal_duration_projects_eta_only_from_selected_source():
    from custom_components.audiconnect.v3.derived_values import project_charging_eta

    now = datetime.now(UTC)
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "BE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    payload = {
        "vin": VIN,
        "Data": [
            {
                "key": "cf28f7d9-6201-30b8-82e5-a461968d30dc",
                "dataFieldName": "remaining_charging_time",
                "value": "30",
                "timestampUtc": now.isoformat(),
            }
        ],
    }
    observe_data_act(car, profile, payload, now, now.isoformat())
    project_charging_eta(car, profile, now)
    assert (
        car.readings["charging_complete_time"]["value"]
        == (now + timedelta(minutes=30)).isoformat()
    )
    assert car.readings["charging_complete_time"]["family"] == "eu_data_act"
    assert "charging_complete_time" not in car.family_readings
    from custom_components.audiconnect.v3.attribute_runtime import (
        remove_family_observations,
    )

    remove_family_observations(car, profile, "eu_data_act", now)
    project_charging_eta(car, profile, now)
    assert "charging_complete_time" not in car.readings


def test_data_act_observed_charging_and_parking_fields_use_shared_contract():
    from custom_components.audiconnect.v3.attribute_runtime import data_act_observations

    now = datetime.now(UTC)
    registry = CapabilityRegistry.from_json_file(catalog_path())
    rows = [
        {
            "key": "9da735bb-c5d5-39f8-bf53-0fa2a367aa8f",
            "dataFieldName": "charging_state",
            "value": "charging",
            "timestampUtc": now.isoformat(),
        },
        {
            "key": "c17ead4f-09b8-357f-ac2b-38c448ab88c4",
            "dataFieldName": "parking_lights",
            "value": "2",
            "timestampUtc": now.isoformat(),
        },
    ]
    result = data_act_observations({"Data": rows}, now, registry)
    assert result["chargingState"]["value"] == "charging"
    assert result["parking_light"]["value"] is False
    rows[0]["value"] = "unsupported"
    rows[1]["value"] = "1"
    assert all(
        row["value"] is None
        for row in data_act_observations({"Data": rows}, now, registry).values()
    )


def test_portal_identity_uses_declared_paths_and_never_role_or_nickname():
    registry = CapabilityRegistry.from_json_file(catalog_path())
    registry.families["eu_data_act"]["identity_mappings"][
        "eu_data_act.identity.vehicles"
    ] = {
        "model": "oem.model",
        "model_year": "oem.year",
    }
    row = {"vin": VIN, "modelName": "Audi Q8", "role": "owner", "nickName": "Audi Q8"}
    car = V3Vehicle.from_data_act(row, "BE", registry)
    assert not car.model and not car.model_year
    row["oem"] = {"model": "Audi A6", "year": 2022}
    car = V3Vehicle.from_data_act(row, "BE", registry)
    assert car.model == "Audi A6"
    assert car.model_year == "2022"
    assert car.model_source == "eu_data_act_oem.model"
    from custom_components.audiconnect.v3.identity_cache import (
        capture_identity,
        apply_cached_identity,
        without_optional_identity,
    )

    car.identity_observed_at = datetime.now(UTC).isoformat()
    identity = capture_identity(car)
    assert identity["source"] == "eu_data_act_oem.model"
    restored = V3Vehicle(VIN, "Audi vehicle", "", "", "BE")
    apply_cached_identity(restored, identity)
    assert restored.model == "Audi A6" and restored.identity_restored
    assert not without_optional_identity(identity)


def test_observed_portal_inventory_has_exact_declared_destinations():
    """The 84 observed structural fields must never silently lose a mapping."""
    from pathlib import Path

    from custom_components.audiconnect.v3.historical_catalog import ATTRIBUTES

    registry = CapabilityRegistry.from_json_file(catalog_path())
    inventory = json.loads(
        (
            Path(__file__).parent / "fixtures/v3_data_act_observed_fields.json"
        ).read_text()
    )
    mappings = registry.families["eu_data_act"]["observations"]
    assert len(inventory) == 84
    for row in inventory:
        mapping = mappings[row["key"]]
        assert mapping["field"] == row["name"]
        assert mapping["attribute"] in ATTRIBUTES or (
            mapping.get("detail") and mapping["attribute"].endswith("_detail")
        )


def test_portal_read_only_details_use_existing_observation_lifecycle():
    from custom_components.audiconnect.v3.attribute_runtime import (
        remove_family_observations,
    )
    from custom_components.audiconnect.v3.capability_status import build_status_report

    now = datetime.now(UTC)
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "BE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    payload = {
        "vin": VIN,
        "Data": [
            {
                "key": "f8bbe94d-06e1-3311-bf8f-c0c99cc67d48",
                "dataFieldName": "parking_brake",
                "value": "1",
                "timestampUtc": now.isoformat(),
            },
            {
                "key": "c4a26fd6-c08f-3921-bb8c-23fab6751c54",
                "dataFieldName": "tyre_pressure_actual_front_left",
                "value": "2.8",
                "timestampUtc": now.isoformat(),
            },
            {
                "key": "0f43f2e7-3556-36a9-8271-a60bc54afad8",
                "dataFieldName": "echo",
                "value": "private-value",
                "timestampUtc": now.isoformat(),
            },
        ],
    }
    observe_data_act(car, profile, payload, now, now.isoformat())
    assert car.readings["parking_brake_detail"]["value"] is True
    assert car.readings["parking_brake_detail"]["detail"] is True
    assert car.readings["tyre_pressure_actual_front_left_detail"]["value"] == 2.8
    assert car.readings["echo_detail"]["value"] is True
    source = next(
        row
        for row in build_status_report(car, profile)["family_discovery"]
        if row["id"] == "eu_data_act"
    )
    assert source["normalized_details"] == 3
    assert source["normalized"] == 0
    assert any(
        row["attribute"] == "parking_brake_detail"
        and row["capability"] == "vehicle_status"
        for row in source["details"]
    )
    assert "private-value" not in str(source)
    remove_family_observations(car, profile, "eu_data_act", now)
    assert "parking_brake_detail" not in car.readings


def test_timestamped_data_act_rejection_withdraws_only_its_own_value():
    now = datetime.now(UTC)
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    earlier = (now - timedelta(minutes=10)).isoformat()
    record_observation(
        car,
        profile,
        "stateOfCharge",
        40,
        earlier,
        now,
        "native",
        "charging",
        "cariad",
        fresh=True,
        operation="cariad.climate.status.batch",
    )
    payload = {"vin": VIN, "Data": [sample("52", now.isoformat())]}
    observe_data_act(car, profile, payload, now, now.isoformat())
    assert car.readings["stateOfCharge"]["value"] == 52
    # Missing field is not invalidation; an older invalid value cannot replace it.
    for incoming in ([], [sample(None, now.isoformat())], [sample("-1", earlier)]):
        observe_data_act(
            car, profile, {"vin": VIN, "Data": incoming}, now, now.isoformat()
        )
        assert car.readings["stateOfCharge"]["value"] == 52
    payload["Data"].append(sample("53", now.isoformat()))
    observe_data_act(car, profile, payload, now, now.isoformat())
    assert car.readings["stateOfCharge"]["value"] == 40
    assert (
        car.family_readings["stateOfCharge"]["eu_data_act"]["status"] == "invalid_value"
    )
    from custom_components.audiconnect.v3.capability_status import build_status_report

    source = next(
        row
        for row in build_status_report(car, profile)["family_discovery"]
        if row["id"] == "eu_data_act"
    )
    assert source["priority"] == 30
    assert "stateOfCharge" in source["declared_attributes"]
    assert source["normalized"] == source["selected"] == 0
    observation = next(
        row for row in source["observations"] if row["attribute"] == "stateOfCharge"
    )
    assert observation["valid"] is False
    assert observation["status"] == "invalid_value"


def test_data_act_health_is_vehicle_scoped():
    from types import SimpleNamespace

    from custom_components.audiconnect.v3.data_act import DataActClient
    from custom_components.audiconnect.v3.status_engine import StatusEngine

    other = "WAUZZZ4M0MD123457"
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    denied = V3Vehicle(other, "Audi", "Q5", "q5", "DE")
    client = DataActClient(None)
    client.delivery_states.update(
        {VIN: "dataset_received", other: "vehicle_access_denied"}
    )
    status = StatusEngine(
        hass=None,
        entry=None,
        auth=SimpleNamespace(data_act_client=client),
        transport=None,
        storage=None,
        vehicles={VIN.lower(): car, other.lower(): denied},
        profiles={},
        discover=None,
        known_inventory=None,
        operation_request=None,
        api_record=None,
    )
    assert status.data_act_poll_status()["result"] == "dataset_received"
    assert status.data_act_poll_status(car)["result"] == "dataset_received"
    report = status.data_act_poll_status(denied)
    assert report["result"] == "vehicle_access_denied"
    assert report["delivery_states"] == {"vehicle_access_denied": 1}


@pytest.mark.parametrize(
    "change",
    [
        {"attribute": "nonexistent"},
        {"min": 100, "max": 0},
        {"values": {"x": True}},
        {"scale": 2},
        {"detail": True},
    ],
)
def test_registry_rejects_malformed_source_mappings(change):
    from custom_components.audiconnect.v3.registry import RegistryError

    raw = json.loads(catalog_path().read_text())
    raw["api_families"]["eu_data_act"]["observations"][SOC].update(change)
    with pytest.raises(RegistryError):
        CapabilityRegistry(raw)


def test_data_act_connection_state_distinguishes_delivery_from_configuration():
    from custom_components.audiconnect.v3.status_engine import data_act_connection_state

    cases = (
        ("not_configured", {}, "not_configured"),
        ("initializing", {}, "awaiting_data"),
        ("no_new_dataset", {"no_nonempty_dataset": 1}, "awaiting_data"),
        ("no_new_dataset", {"empty_dataset": 1}, "awaiting_data"),
        ("dataset_received", {"dataset_received": 1}, "connected"),
        ("no_new_dataset", {"no_new_dataset": 1}, "connected"),
        (
            "dataset_received",
            {"dataset_received": 1, "vehicle_access_denied": 1},
            "partial",
        ),
        (
            "authorization_required",
            {"dataset_received": 1},
            "authorization_required",
        ),
        ("rate_limited", {"dataset_received": 1}, "rate_limited"),
        (
            "subscription_unavailable",
            {"subscription_unavailable": 1},
            "subscription_unavailable",
        ),
    )
    for result, deliveries, expected in cases:
        assert data_act_connection_state(result, deliveries) == expected


def test_diagnostics_exposes_capture_sources_without_vehicle_values():
    from types import SimpleNamespace as NS

    from custom_components.audiconnect.v3.capability_status import (
        diagnostic_capability_summary,
    )

    now = datetime.now(UTC)
    registry = CapabilityRegistry.from_json_file(catalog_path())
    car = V3Vehicle(VIN, "Audi", "", "", "BE")
    profile = DevelopmentProfile(registry, car.context)
    captured = (now - timedelta(minutes=20)).isoformat()
    observe_data_act(
        car,
        profile,
        {"vin": VIN, "Data": [sample("52", captured)]},
        now,
        now.isoformat(),
    )
    report = diagnostic_capability_summary(car, profile, registry, NS(uses_auth0=True))
    row = next(
        row for row in report["capture_evidence"] if row["attribute"] == "stateOfCharge"
    )
    assert row["family"] == "eu_data_act"
    assert row["captured"] == captured
    assert row["selected"] and row["valid"]
    assert "value" not in row and "path" not in row


def test_newer_stopped_charging_suppresses_older_eta_without_erasing_duration():
    from custom_components.audiconnect.v3.derived_values import project_charging_eta

    now = datetime.now(UTC)
    registry = CapabilityRegistry.from_json_file(catalog_path())
    car = V3Vehicle(VIN, "Audi", "", "", "BE")
    profile = DevelopmentProfile(registry, car.context)
    duration = {
        "value": 30,
        "captured": (now - timedelta(minutes=10)).isoformat(),
        "family": "eu_data_act",
    }
    car.readings["remainingChargingTime"] = duration
    car.readings["chargingState"] = {
        "value": "charging",
        "captured": now.isoformat(),
    }
    project_charging_eta(car, profile, now)
    assert "charging_complete_time" in car.readings
    car.readings["chargingState"]["value"] = "readyForCharging"
    project_charging_eta(car, profile, now)
    assert "charging_complete_time" not in car.readings
    assert car.readings["remainingChargingTime"] == duration
    car.readings["chargingState"]["captured"] = (
        now - timedelta(minutes=20)
    ).isoformat()
    project_charging_eta(car, profile, now)
    assert "charging_complete_time" in car.readings


def test_data_act_adaptive_backoff_and_restart_checkpoint():
    from custom_components.audiconnect.v3.data_act import DataActClient

    now = datetime.now(UTC)
    quota = DataActClient(None).quota
    quota.observe(429, {}, now)
    assert quota.retry_at == now + timedelta(minutes=15)
    restored = DataActClient(None).quota
    restored.restore_rate_limit(quota.rate_limit_checkpoint())
    with pytest.raises(RuntimeError):
        restored.authorize(now + timedelta(minutes=14), read_only=True)
    due = restored.retry_at
    restored.authorize(due, read_only=True)
    restored.observe(429, {}, due)
    assert restored.retry_at == due + timedelta(minutes=30)
    due = restored.retry_at
    restored.authorize(due, read_only=True)
    restored.observe(429, {"Retry-After": "86400"}, due)
    assert restored.retry_at == due + timedelta(days=1)
    due = restored.retry_at
    restored.authorize(due, read_only=True)
    restored.observe(302, {}, due)
    assert restored.retry_at is None


@pytest.mark.asyncio
async def test_portal_rate_limit_keeps_delivery_and_avoids_false_unavailable():
    from unittest.mock import AsyncMock

    from custom_components.audiconnect.v3.data_act import DataActClient

    client = DataActClient(None)
    client.delivery_states[VIN] = "dataset_received"

    async def limited(_vin):
        client.quota.observe(429, {}, datetime.now(UTC))
        raise DataActUnavailable("Data Act read unavailable")

    client._latest = limited
    with pytest.raises(DataActUnavailable):
        await client.latest(VIN)
    assert client.delivery_states[VIN] == "dataset_received"
    assert client.quota.rate_limit_streak == 1
    client.quota.retry_at = None
    client._latest = AsyncMock(return_value=None)
    await client.latest(VIN)
    assert client.quota.rate_limit_streak == 0


def test_data_act_due_time_slows_when_no_new_data():
    from types import SimpleNamespace

    from custom_components.audiconnect.v3.data_act import DataActClient
    from custom_components.audiconnect.v3.status_engine import StatusEngine

    client = DataActClient(None)
    status = StatusEngine(
        hass=None,
        entry=None,
        auth=SimpleNamespace(data_act_client=client),
        transport=None,
        storage=None,
        vehicles={},
        profiles={},
        discover=None,
        known_inventory=None,
        operation_request=None,
        api_record=None,
    )
    now = datetime.now(UTC)
    status._data_act_attempt_at = now
    client.delivery_states[VIN] = "dataset_received"
    assert status._data_act_due_at(client) == now + timedelta(minutes=30)
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    status.vehicles[VIN.lower()] = car
    car.family_readings["stateOfCharge"] = {
        "eu_data_act": {
            "value": 52,
            "captured": (now - timedelta(days=1)).isoformat(),
        }
    }
    # An older capture in a newly delivered dataset does not imply idle delivery.
    assert status._data_act_due_at(client) == now + timedelta(minutes=30)
    car.family_readings["stateOfCharge"]["eu_data_act"]["captured"] = now.isoformat()
    assert status._data_act_due_at(client) == now + timedelta(minutes=30)
    client.delivery_states[VIN] = "no_new_dataset"
    assert status._data_act_due_at(client) == now + timedelta(hours=1)
    client.quota.observe(429, {}, now)
    assert status._data_act_due_at(client) == now + timedelta(minutes=15)
    client.quota.observe(429, {"Retry-After": "10800"}, now)
    assert status._data_act_due_at(client) == now + timedelta(hours=3)
    assert status.data_act_poll_status()["result"] == "rate_limited"
    client.quota.rate_limit_streak = 0
    client._reauth_path = "/expired"
    assert status.data_act_poll_status()["result"] == "session_refresh_pending"


@pytest.mark.asyncio
async def test_data_act_restored_cooldown_skips_portal_requests():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from custom_components.audiconnect.v3.data_act import DataActClient
    from custom_components.audiconnect.v3.status_engine import StatusEngine

    client = DataActClient(None)
    client.latest = AsyncMock()
    now = datetime.now(UTC)
    checkpoint = {
        "retry_at": (now + timedelta(hours=4)).isoformat(),
        "streak": 2,
    }
    storage = SimpleNamespace(
        async_load_data_act_backoff=AsyncMock(return_value=checkpoint),
        async_save_data_act_backoff=AsyncMock(),
    )
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    notify = Mock()
    status = StatusEngine(
        hass=None,
        entry=None,
        auth=SimpleNamespace(data_act_client=client),
        transport=None,
        storage=storage,
        vehicles={VIN.lower(): car},
        profiles={VIN.lower(): profile},
        discover=None,
        known_inventory=None,
        operation_request=None,
        api_record=None,
        notify=notify,
    )
    await status._collect_data_act()
    await status._collect_data_act()
    storage.async_load_data_act_backoff.assert_awaited_once()
    storage.async_save_data_act_backoff.assert_not_awaited()
    client.latest.assert_not_awaited()
    notify.assert_called_once_with(reconcile_registry=False)
    report = status.data_act_poll_status()
    assert report["result"] == "rate_limited"
    assert report["next_poll_at"] == checkpoint["retry_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["metadata", "list"])
async def test_empty_subscription_after_throttle_clears_recovery(resource):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from custom_components.audiconnect.v3.data_act import DataActClient

    session = MagicMock()
    session.get.return_value.__aenter__.return_value = SimpleNamespace(
        status=404, headers={}
    )
    client = DataActClient(session)
    if resource == "list":
        client._identifiers[VIN] = "existing"
    now = datetime.now(UTC)
    client.quota.observe(429, {"Retry-After": "0"}, now - timedelta(seconds=1))
    assert await client.latest(VIN) is None
    assert client.delivery_states[VIN] == "subscription_unavailable"
    assert client.quota.retry_at is None
    assert client.quota.rate_limit_streak == 0
    assert client.quota.rate_limit_checkpoint() == {}
    assert session.get.call_count == 1
