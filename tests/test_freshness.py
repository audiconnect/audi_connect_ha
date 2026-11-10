"""Vehicle telemetry freshness and cloud poll signals are not interchangeable."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from custom_components.audiconnect.freshness import (
    usable_vehicle_timestamp,
    vehicle_age_minutes,
    vehicle_freshness,
)
from custom_components.audiconnect.coordinator import AudiDataUpdateCoordinator
from custom_components.audiconnect.sensor import (
    AudiCloudLastPollSensor,
    AudiVehicleAgeSensor,
    AudiVehicleFreshnessSensor,
)

NOW = datetime(2026, 11, 10, 16, 0, tzinfo=UTC)
VIN = "NOT_A_REAL_VIN"


def test_vehicle_freshness_thresholds_and_ages():
    assert vehicle_age_minutes(NOW - timedelta(minutes=29), NOW) == 29
    assert vehicle_freshness(NOW - timedelta(minutes=30), NOW) == "fresh"
    assert vehicle_freshness(NOW - timedelta(minutes=31), NOW) == "delayed"
    assert vehicle_freshness(NOW - timedelta(minutes=120), NOW) == "delayed"
    assert vehicle_freshness(NOW - timedelta(minutes=121), NOW) == "stale"


def test_unknown_and_bad_timestamps_cannot_look_fresh():
    assert vehicle_freshness(None, NOW) == "unknown"
    assert vehicle_freshness(datetime(1970, 1, 1, tzinfo=UTC), NOW) == "unknown"
    assert vehicle_freshness(datetime(2026, 11, 10, 15, 0), NOW) == "unknown"
    assert vehicle_freshness(NOW + timedelta(minutes=6), NOW) == "unknown"
    assert vehicle_age_minutes(None, NOW) is None
    assert usable_vehicle_timestamp(NOW + timedelta(minutes=3), NOW) is not None
    assert vehicle_age_minutes(NOW + timedelta(minutes=3), NOW) == 0


def test_new_freshness_entities_use_stable_separate_unique_ids():
    telemetry_time = datetime.now(UTC) - timedelta(hours=3)
    car = NS(vin=VIN, last_update_time=telemetry_time)
    cloud_now = datetime.now(UTC)
    coordinator = NS(
        last_cloud_poll_success=cloud_now,
        last_cloud_poll_attempt=cloud_now,
        last_update_success=True,
    )
    freshness = AudiVehicleFreshnessSensor(coordinator, car)
    age = AudiVehicleAgeSensor(coordinator, car)
    cloud = AudiCloudLastPollSensor(coordinator, car)
    assert freshness.native_value == "stale"
    assert age.native_value >= 179
    assert cloud.native_value == cloud_now
    assert freshness.extra_state_attributes["last_cloud_poll_succeeded"] is True
    assert freshness.extra_state_attributes["vehicle_age_minutes"] >= 179
    assert len({freshness.unique_id, age.unique_id, cloud.unique_id}) == 3
    assert all(
        "sensor_" in x for x in (freshness.unique_id, age.unique_id, cloud.unique_id)
    )


def test_successful_cloud_poll_does_not_change_aged_vehicle_timestamp():
    car = NS(vin=VIN, last_update_time=datetime.now(UTC) - timedelta(hours=4))

    async def refreshed():
        return [car]

    coordinator = AudiDataUpdateCoordinator.__new__(AudiDataUpdateCoordinator)
    coordinator.account = NS(async_refresh_data=refreshed)
    coordinator.last_cloud_poll_attempt = None
    coordinator.last_cloud_poll_success = None
    result = asyncio.run(coordinator._async_update_data())
    assert result == [car]
    assert coordinator.last_cloud_poll_success is not None
    assert coordinator.last_cloud_poll_attempt is not None
    assert vehicle_freshness(car.last_update_time) == "stale"


def test_failed_cloud_poll_preserves_old_success_timestamp():
    previous = datetime.now(UTC) - timedelta(minutes=2)

    async def failed():
        raise RuntimeError("Audi temporarily offline")

    coordinator = AudiDataUpdateCoordinator.__new__(AudiDataUpdateCoordinator)
    coordinator.account = NS(async_refresh_data=failed)
    coordinator.last_cloud_poll_attempt = None
    coordinator.last_cloud_poll_success = previous
    try:
        asyncio.run(coordinator._async_update_data())
    except Exception:
        pass
    else:
        raise AssertionError("Poll should fail")
    assert coordinator.last_cloud_poll_success == previous
    assert coordinator.last_cloud_poll_attempt is not None
