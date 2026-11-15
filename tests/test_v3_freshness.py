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


def test_invalid_climate_capture_does_not_report_current_climate_age():
    from custom_components.audiconnect.v3.vehicle import V3Vehicle

    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "", "", "BE")
    now = datetime.now(UTC)
    car.readings["climatisationState"] = {
        "value": None,
        "captured": now.isoformat(),
        "status": "invalid_value",
    }
    assert car.climate_captured == now
    assert car.capture_age_minutes is None


def test_vehicle_capture_order_is_independent_of_arrival():
    from itertools import permutations
    from types import SimpleNamespace

    from custom_components.audiconnect.v3.attribute_runtime import commit_observation

    now = datetime.now(UTC)
    for order in permutations((("charging", 3), ("off", 1), ("charging", 2))):
        car = SimpleNamespace(readings={}, family_readings={})
        for value, minutes in order:
            stamp = (now - timedelta(minutes=minutes)).isoformat()
            commit_observation(
                car,
                "chargingState",
                {
                    "value": value,
                    "captured": stamp,
                    "observed": now.isoformat(),
                    "family": "cariad",
                    "status": "verified",
                },
                None,
                now,
            )
        assert car.readings["chargingState"]["value"] == "off"


def test_same_capture_conflict_is_not_resolved_by_arrival_order():
    from types import SimpleNamespace

    from custom_components.audiconnect.v3.attribute_runtime import commit_observation

    now = datetime.now(UTC)
    for values in (("charging", "off", "charging"), ("off", "charging", "off")):
        car = SimpleNamespace(readings={}, family_readings={})
        for value in values:
            commit_observation(
                car,
                "chargingState",
                {
                    "value": value,
                    "captured": now.isoformat(),
                    "observed": now.isoformat(),
                    "family": "cariad",
                    "status": "verified",
                },
                None,
                now,
            )
        assert car.readings["chargingState"]["reason"] == "conflicting_source_values"
        assert car.readings["chargingState"]["value"] is None


def test_charge_mode_does_not_inherit_charging_capture():
    from custom_components.audiconnect.v3.historical_catalog import capture_time

    payload = {
        "charging": {
            "chargingStatus": {
                "value": {"carCapturedTimestamp": "2026-01-01T12:00:00Z"}
            },
            "chargeMode": {"value": {"availableChargeModes": ["manual", "timer"]}},
        }
    }
    assert (
        capture_time(payload, "charging.chargeMode.value.availableChargeModes") is None
    )


def test_undated_and_older_events_cannot_erase_a_vehicle_capture():
    from types import SimpleNamespace
    from custom_components.audiconnect.v3.attribute_runtime import (
        commit_observation,
        last_known_observation,
    )

    now = datetime.now(UTC)
    car = SimpleNamespace(readings={}, family_readings={})

    def write(value, captured, status="verified"):
        return commit_observation(
            car,
            "chargingState",
            {
                "value": value,
                "captured": captured,
                "observed": now.isoformat(),
                "family": "cariad",
                "status": status,
            },
            None,
            now,
        )

    assert write("charging", (now - timedelta(minutes=2)).isoformat())
    assert not write(None, None, "invalid_value")
    assert not write("off", (now - timedelta(minutes=3)).isoformat())
    assert car.readings["chargingState"]["value"] == "charging"
    assert write(None, now.isoformat(), "invalid_value")
    assert car.readings["chargingState"]["value"] is None
    assert last_known_observation(car.readings["chargingState"])["value"] == "charging"
    assert not write("off", (now - timedelta(minutes=1)).isoformat())
    assert last_known_observation(car.readings["chargingState"])["value"] == "off"
    assert car.readings["chargingState"]["value"] is None


def test_charge_mode_does_not_inherit_root_or_job_timestamp():
    from custom_components.audiconnect.v3.historical_catalog import capture_time

    payload = {
        "carCapturedTimestamp": "2026-01-01T00:00:00Z",
        "charging": {
            "carCapturedTimestamp": "2026-01-01T00:00:01Z",
            "chargeMode": {"value": {"preferredChargeMode": "manual"}},
        },
    }
    assert (
        capture_time(payload, "charging.chargeMode.value.preferredChargeMode") is None
    )


def test_late_history_and_conflict_have_same_projection_for_all_permutations():
    from itertools import permutations
    from types import SimpleNamespace
    from custom_components.audiconnect.v3.attribute_runtime import (
        commit_observation,
        last_known_observation,
    )

    now = datetime.now(UTC)
    older = (now - timedelta(minutes=3)).isoformat()
    middle = (now - timedelta(minutes=2)).isoformat()
    newest = (now - timedelta(minutes=1)).isoformat()
    events = [
        ("off", older, "verified"),
        ("charging", middle, "verified"),
        (None, newest, "invalid_value"),
    ]
    for order in permutations(events):
        car = SimpleNamespace(readings={}, family_readings={})
        for value, stamp, status in order:
            commit_observation(
                car,
                "chargingState",
                {
                    "value": value,
                    "captured": stamp,
                    "observed": now.isoformat(),
                    "status": status,
                    "family": "cariad",
                },
                None,
                now,
            )
        current = car.readings["chargingState"]
        assert current["captured"] == newest
        assert current["value"] is None
        assert last_known_observation(current)["value"] == "charging"
        assert last_known_observation(current)["captured"] == middle
