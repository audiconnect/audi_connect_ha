"""V3 cached data must not be promoted to live Climate capability."""

from datetime import UTC, datetime, timedelta
from custom_components.audiconnect.v3.freshness import timestamp_is_fresh
from custom_components.audiconnect.v3.vehicle import V3Vehicle


def test_four_hour_old_capture_is_not_fresh():
    now = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
    assert not timestamp_is_fresh((now - timedelta(minutes=257)).isoformat(), now)
    assert timestamp_is_fresh((now - timedelta(minutes=15)).isoformat(), now)


def test_no_or_invalid_timestamp_cannot_confirm_state():
    now = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
    assert not timestamp_is_fresh(None, now)
    assert not timestamp_is_fresh("yesterday", now)
    assert not timestamp_is_fresh("2026-11-11T15:00:00", now)
    assert not timestamp_is_fresh((now + timedelta(minutes=6)).isoformat(), now)


def test_new_sample_without_capture_does_not_inherit_timestamp():
    now = datetime.now(UTC)
    car = V3Vehicle(
        vin="WAUZZZ4M0MD123456",
        name="Test",
        model="Audi Q8",
        model_family="q8",
        country="DE",
    )
    assert car.set_climate(
        "off", now.isoformat(), route="a", observed_at=now, http_status=200
    )
    assert car.climate_captured == now
    assert not car.set_climate(
        "heating", None, route="b", observed_at=now, http_status=200
    )
    assert car.climate_captured == now
    assert car.climate_state == "off"
    assert not car.set_climate(
        "heating", "not-a-timestamp", route="c", observed_at=now, http_status=200
    )
    assert car.climate_captured == now


def test_newest_capture_ignores_derived_summary_and_invalid_readings():
    from types import SimpleNamespace
    from custom_components.audiconnect.v3.freshness import (
        newest_vehicle_capture,
        newest_vehicle_reading,
        vehicle_capture_summary,
    )

    now = datetime.now(UTC)
    older = now - timedelta(hours=2)
    car = SimpleNamespace(
        readings={
            "last_update_time": {"value": now.isoformat(), "captured": now.isoformat()},
            "stateOfCharge": {"value": 80, "captured": older.isoformat()},
            "climatisationState": {
                "value": None,
                "captured": now.isoformat(),
                "status": "invalid_value",
            },
        }
    )
    assert newest_vehicle_capture(car, now) == older
    assert newest_vehicle_reading(car, now)[1] == "stateOfCharge"
    summary = vehicle_capture_summary(car, now)
    assert summary["source_attribute"] == "stateOfCharge"
    assert summary["vehicle_age_minutes"] == 120
    assert summary["vehicle_last_update"] == older.isoformat()
    car.readings.pop("stateOfCharge")
    assert newest_vehicle_capture(car, now) is None


def test_reading_attributes_distinguish_vehicle_capture_from_cloud_refresh():
    from custom_components.audiconnect.v3.freshness import reading_freshness_attributes

    now = datetime.now(UTC)
    captured = (now - timedelta(hours=2)).isoformat()
    reading = {
        "value": 80,
        "captured": captured,
        "observed": now.isoformat(),
        "status": "readable_but_stale",
    }
    attrs = reading_freshness_attributes(reading, allow_last_known=True, now=now)
    assert attrs["vehicle_captured"] == captured
    assert attrs["age_minutes"] == 120
    assert attrs["cloud_observed"] == now.isoformat()
    assert attrs["cloud_age_minutes"] == 0
    assert attrs["vehicle_freshness"] == "stale_last_known"
    reading.update(value=None, status="invalid_value")
    assert (
        reading_freshness_attributes(reading, now=now)["vehicle_freshness"] == "unknown"
    )
    reading.update(value=80, captured=None)
    assert reading_freshness_attributes(reading, now=now)["age_minutes"] is None


def test_b28_window_envelope_cannot_make_older_vehicle_data_fresh():
    from custom_components.audiconnect.v3.freshness import (
        capture_coverage,
        vehicle_capture_summary,
    )

    now = datetime.now(UTC)
    old = (now - timedelta(minutes=69)).isoformat()
    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")
    car.readings.update(
        stateOfCharge={"value": 80, "captured": old, "job": "charging"},
        window_heating_detail={
            "value": {"items": [{"location": "front", "state": "unsupported"}]},
            "captured": now.isoformat(),
            "status": "verified",
            "job": "climatisation",
        },
        windowHeatingActive={
            "value": None,
            "captured": now.isoformat(),
            "status": "invalid_value",
            "job": "climatisation",
        },
    )
    summary = vehicle_capture_summary(car, now)
    assert summary["vehicle_age_minutes"] == 69
    assert summary["vehicle_freshness"] == "delayed"
    assert summary["source_attribute"] == "stateOfCharge"
    assert capture_coverage(car, now)["climatisation"]["newest_minutes"] is None
    car.readings["climatisationState"] = {
        "value": "off",
        "captured": now.isoformat(),
        "job": "climatisation",
    }
    assert vehicle_capture_summary(car, now)["vehicle_freshness"] == "partial"
