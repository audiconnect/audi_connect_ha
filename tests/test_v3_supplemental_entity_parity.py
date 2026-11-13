"""Independent historical diagnostics, local service and stale-state controls."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import asyncio

from custom_components.audiconnect.v3.entities import (
    V3StatusSensor,
    V3ApiQuotaSensor,
    V3LocalServiceSensor,
    V3LockEntity,
    V3ClimateQuickSwitch,
)
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3.attribute_runtime import _accept_observation
from custom_components.audiconnect.v3.derived_values import observe_derived

VIN = "WAUZZZ4M0MD123456"


def context():
    car = V3Vehicle(VIN, "Audi", "Audi Q8", "q8", "DE")
    now = datetime.now(UTC)
    engine = NS(
        last_cloud_poll_success=now,
        last_cloud_poll_attempt=now,
        auth=NS(service=NS(_spin="test-pin")),
        entry=NS(
            options={
                "local_dealers": {
                    VIN.lower(): {
                        "dealer_name": "Dealer",
                        "next_service_date": "2027-01-01",
                    }
                }
            }
        ),
        transport=NS(remaining_calls=44, remaining_calls_observed_at=now),
        control_enabled=lambda *a: True,
        send_control=AsyncMock(),
    )
    coord = NS(
        engine=engine, last_update_success=True, async_add_listener=lambda cb: None
    )
    return car, coord, now


def test_historical_freshness_age_and_quota_are_distinct():
    car, co, now = context()
    car.readings["stateOfCharge"] = {
        "value": 80,
        "captured": (now - timedelta(hours=4)).isoformat(),
        "status": "readable_but_stale",
    }
    car.readings["invalid"] = {
        "value": 1,
        "captured": (now + timedelta(hours=4)).isoformat(),
        "status": "invalid_value",
    }
    fresh = V3StatusSensor(co, car, "freshness")
    age = V3StatusSensor(co, car, "age")
    quota = V3ApiQuotaSensor(co, car, "entry")
    assert fresh.unique_id == VIN.lower() + "_sensor_vehicle_data_freshness"
    assert fresh.native_value == "stale"
    assert age.native_value >= 240
    assert (
        quota.unique_id == "entry_api_requests_remaining" and quota.native_value == 44
    )
    assert fresh.extra_state_attributes["last_cloud_poll_succeeded"] is True
    car.readings["chargingState"] = {
        "value": "off",
        "captured": now.isoformat(),
        "status": "verified",
        "job": "charging",
    }
    assert age.native_value == 0
    assert fresh.native_value == "fresh"
    coverage = fresh.extra_state_attributes["job_capture_coverage"]
    assert coverage["unclassified"]["oldest_minutes"] >= 240


def test_service_overview_and_dealer_are_vehicle_local_data():
    car, co, now = context()
    dealer = V3LocalServiceSensor(co, car, "local_dealer")
    service = V3LocalServiceSensor(co, car, "service_overview")
    assert dealer.native_value == "Dealer"
    assert service.native_value == "appointment_recorded"
    car.readings["MAINTENANCE_INTERVAL_TIME_TO_INSPECTION"] = {
        "value": 12,
        "captured": now.isoformat(),
        "status": "verified",
    }
    assert service.native_value == "due_soon"
    assert service.extra_state_attributes["inspection_due_days"] == 12


def test_parked_state_unknown_does_not_hide_authorized_control():
    car, co, now = context()
    stamp = (now - timedelta(hours=4)).isoformat()
    car.readings["doorLockStatus"] = {
        "value": "locked",
        "captured": stamp,
        "status": "readable_but_stale",
    }
    car.set_climate("off", stamp, route="test", observed_at=now, http_status=200)
    lock = V3LockEntity(co, car)
    quick = V3ClimateQuickSwitch(co, car)
    assert lock.available and lock.is_locked is None
    assert quick.available and quick.is_on is None
    lock.async_write_ha_state = lambda: None
    quick.async_write_ha_state = lambda: None
    asyncio.run(lock.async_lock())
    asyncio.run(quick.async_turn_on())
    assert co.engine.send_control.await_count == 2


def test_aliases_and_completion_keep_source_capture():
    car, co, now = context()
    stamp = now.isoformat()
    for key, value in (
        ("chargeType", "ac"),
        ("plugledColor", "green"),
        ("engineTypeFirstEngine", "gasoline"),
        ("chargingCurrentLimitA", 16),
        ("remainingChargingTime", 45),
    ):
        car.readings[key] = {
            "value": value,
            "captured": stamp,
            "job": "charging",
            "path": "test",
        }
    observe_derived(car, NS(), {}, now, _accept_observation)
    assert car.readings["charging_type"]["value"] == "ac"
    assert car.readings["max_charge_current"]["value"] == 16
    assert (
        car.readings["charging_complete_time"]["value"]
        == (now + timedelta(minutes=45)).isoformat()
    )
    assert car.readings["charging_complete_time"]["captured"] == stamp


def test_newest_vehicle_capture_keeps_older_climate_age_visible():
    car, co, now = context()
    car.readings.update(
        stateOfCharge={"value": 77, "job": "charging", "captured": now.isoformat()},
        climatisationState={
            "value": "off",
            "job": "climatisation",
            "captured": (now - timedelta(hours=3)).isoformat(),
        },
    )
    assert V3StatusSensor(co, car, "age").native_value == 0
    sensor = V3StatusSensor(co, car, "freshness")
    assert sensor.native_value == "fresh"
    assert (
        sensor.extra_state_attributes["job_capture_coverage"]["climatisation"][
            "oldest_minutes"
        ]
        >= 180
    )


def test_age_sensor_explains_source_and_partial_freshness():
    car, co, now = context()
    car.readings["stateOfCharge"] = {
        "value": 80,
        "captured": (now - timedelta(hours=4)).isoformat(),
        "job": "charging",
    }
    car.readings["climatisationState"] = {
        "value": "off",
        "captured": now.isoformat(),
        "observed": now.isoformat(),
        "job": "climatisation",
    }
    age = V3StatusSensor(co, car, "age")
    attrs = age.extra_state_attributes
    assert age.native_value == attrs["vehicle_age_minutes"] == 0
    assert attrs["source_attribute"] == "climatisationState"
    assert attrs["source_job"] == "climatisation"
    assert attrs["vehicle_last_update"] == now.isoformat()
    assert attrs["source_observed_at"] == now.isoformat()
    assert attrs["oldest_observed_age_minutes"] >= 240
    assert attrs["job_capture_coverage"]["charging"]["oldest_minutes"] >= 240
    assert attrs["cloud_last_successful_poll"] == now.isoformat()
    car.readings.clear()
    assert age.native_value is None
    assert age.extra_state_attributes["source_attribute"] is None


def test_native_controls_share_reported_capture_attributes():
    from custom_components.audiconnect.v3.entities import (
        V3ChargeModeSelect,
        V3ChargeTargetNumber,
        V3ClimateSettingSwitch,
        V3PreheaterSwitch,
    )

    car, co, now = context()
    captured = (now - timedelta(hours=2)).isoformat()
    row = {
        "value": True,
        "captured": captured,
        "observed": now.isoformat(),
        "status": "readable_but_stale",
    }
    car.readings.update(
        climatisationState={**row, "value": "off"},
        doorLockStatus={**row, "value": "locked"},
        preferredChargeMode={**row, "value": "manual"},
        targetstateOfCharge={**row, "value": 80},
        preheater_active=row,
        climatisationWithoutExternalPower=row,
    )
    entities = (
        V3ClimateQuickSwitch(co, car),
        V3LockEntity(co, car),
        V3ChargeModeSelect(co, car),
        V3ChargeTargetNumber(co, car),
        V3PreheaterSwitch(co, car),
        V3ClimateSettingSwitch(
            co,
            car,
            (
                "climatisation_without_external_power",
                "climatisationWithoutExternalPower",
                "climatisationWithoutExternalPower",
            ),
        ),
    )
    for entity in entities:
        attrs = entity.extra_state_attributes
        assert attrs["vehicle_captured"] == captured
        assert attrs["cloud_observed"] == now.isoformat()
        assert attrs["age_minutes"] >= 120
        assert attrs["vehicle_freshness"] in ("stale", "stale_last_known")
        assert attrs["verification"] == "readable_but_stale"
