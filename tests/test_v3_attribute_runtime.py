"""Shared V3 status polling recovers source-derived V2 fields without guesses."""

from __future__ import annotations
from datetime import UTC, datetime, timedelta
from custom_components.audiconnect.v3.attribute_runtime import (
    observe_read_only,
    planned_jobs,
)
from custom_components.audiconnect.v3.vehicle import V3Vehicle


class Profile:
    attribute_routes = None
    attribute_evidence = None

    def __init__(self):
        self.attribute_routes, self.attribute_evidence = {}, {}
        self.job_discovery = {}


def car():
    return V3Vehicle(
        vin="TESTVIN0000000001",
        name="Audi",
        model="Q8",
        model_family="q8",
        country="DE",
    )


def test_single_selectivestatus_response_recovers_multiple_fields():
    car1, p, now = car(), Profile(), datetime.now(UTC)
    assert len(planned_jobs(car1, p)) >= 23
    sample = {
        "charging": {
            "batteryStatus": {
                "value": {"currentSOC_pct": 55, "carCapturedTimestamp": now.isoformat()}
            },
            "chargingStatus": {
                "value": {
                    "chargingState": "charging",
                    "carCapturedTimestamp": now.isoformat(),
                }
            },
        },
        "climatisation": {
            "climatisationStatus": {
                "value": {
                    "climatisationState": "off",
                    "carCapturedTimestamp": now.isoformat(),
                }
            }
        },
    }
    outcome = observe_read_only(car1, p, sample, now)
    assert outcome["fresh"] >= 3
    assert all(
        name in p.attribute_routes
        for name in ("stateOfCharge", "chargingState", "climatisationState")
    )
    assert set(planned_jobs(car1, p)) >= {
        "charging",
        "climatisation",
        "userCapabilities",
    }
    assert "tripStatistics" not in planned_jobs(car1, p)


def test_unknown_and_stale_values_are_not_promoted():
    car1, p, now = car(), Profile(), datetime.now(UTC)
    old = (now - timedelta(hours=3)).isoformat()
    observe_read_only(
        car1,
        p,
        {
            "charging": {
                "batteryStatus": {
                    "value": {"currentSOC_pct": 0, "carCapturedTimestamp": old}
                }
            }
        },
        now,
    )
    assert car1.readings["stateOfCharge"]["status"] == "readable_but_stale"
    assert p.attribute_routes["stateOfCharge"] == "cariad.selectivestatus.batch"
    assert "charging" in planned_jobs(car1, p)  # stale != unsupported; keep polling
    assert "plugState" not in car1.readings


def test_capability_advertisement_is_not_fresh_attribute_evidence():
    car1, p, now = car(), Profile(), datetime.now(UTC)
    observe_read_only(
        car1,
        p,
        {
            "userCapabilities": {
                "capabilitiesStatus": {
                    "value": [
                        {"id": "charging", "status": None},
                        {"id": "onlineLogBook", "status": "impaired"},
                    ]
                }
            }
        },
        now,
    )
    assert car1.advertised_capabilities == {"charging", "onlineLogBook"}
    assert car1.impaired_capabilities == {"onlineLogBook"}
    assert not p.attribute_routes


def test_stale_readable_v2_fields_are_active_after_first_discovery():
    """A sleeping Q8 still reports its last known SoC, range and service data."""
    vehicle, profile, now = car(), Profile(), datetime.now(UTC)
    captured = (now - timedelta(hours=4)).isoformat()
    payload = {
        "charging": {
            "batteryStatus": {
                "value": {
                    "currentSOC_pct": 52,
                    "carCapturedTimestamp": captured,
                }
            }
        },
        "fuelStatus": {
            "rangeStatus": {
                "value": {
                    "totalRange_km": 410,
                    "carCapturedTimestamp": captured,
                }
            }
        },
    }
    result = observe_read_only(vehicle, profile, payload, now)
    assert result["fresh"] == 0
    assert vehicle.readings["stateOfCharge"]["value"] == 52
    assert vehicle.readings["TOTAL_RANGE"]["value"] == 410
    assert profile.attribute_routes["stateOfCharge"] == "cariad.selectivestatus.batch"
    assert profile.attribute_routes["TOTAL_RANGE"] == "cariad.selectivestatus.batch"
    assert {"charging", "fuelStatus"} <= set(planned_jobs(vehicle, profile))


def test_observed_job_survives_pruning_when_no_fresh_attribute_exists():
    vehicle, profile = car(), Profile()
    vehicle.v2_initial_discovery_completed = True
    profile.job_discovery["vehicleHealthInspection"] = "observed"
    assert "vehicleHealthInspection" in planned_jobs(vehicle, profile)
    assert "tripStatistics" not in planned_jobs(vehicle, profile)


def test_older_cloud_cache_never_replaces_newer_captured_vehicle_value():
    vehicle, profile, now = car(), Profile(), datetime.now(UTC)

    def sample(value, capture):
        return {
            "charging": {
                "batteryStatus": {
                    "value": {
                        "currentSOC_pct": value,
                        "carCapturedTimestamp": capture.isoformat(),
                    }
                }
            }
        }

    observe_read_only(vehicle, profile, sample(70, now), now)
    observe_read_only(vehicle, profile, sample(49, now - timedelta(hours=3)), now)
    assert vehicle.readings["stateOfCharge"]["value"] == 70
    assert vehicle.readings["stateOfCharge"]["captured"] == now.isoformat()


def test_boolean_oil_never_becomes_numeric_and_existing_binary_is_used():
    vehicle, profile, now = car(), Profile(), datetime.now(UTC)

    def sample(value, stamp):
        return {
            "oilLevel": {
                "oilLevelStatus": {
                    "value": {
                        "value": value,
                        "carCapturedTimestamp": stamp.isoformat(),
                    }
                }
            }
        }

    observe_read_only(vehicle, profile, sample(48, now), now)
    assert vehicle.readings["OIL_LEVEL_DIPSTICKS_PERCENTAGE"]["value"] == 48
    later = now + timedelta(minutes=1)
    observe_read_only(vehicle, profile, sample(True, later), later)
    assert vehicle.readings["OIL_LEVEL_DIPSTICKS_PERCENTAGE"]["value"] is None
    assert (
        vehicle.readings["OIL_LEVEL_DIPSTICKS_PERCENTAGE"]["reason"]
        == "boolean_oil_level_use_binary"
    )
    assert vehicle.readings["oil_level_binary"]["value"] is False
    observe_read_only(vehicle, profile, sample(25, now), later)
    assert vehicle.readings["OIL_LEVEL_DIPSTICKS_PERCENTAGE"]["value"] is None
    latest = later + timedelta(minutes=1)
    observe_read_only(vehicle, profile, sample(False, latest), latest)
    assert vehicle.readings["oil_level_binary"]["value"] is True


def test_negative_duration_invalidates_newer_but_not_older_capture():
    vehicle, profile, now = car(), Profile(), datetime.now(UTC)

    def sample(value, stamp):
        return {
            "climatisation": {
                "climatisationStatus": {
                    "value": {
                        "remainingClimatisationTime_min": value,
                        "carCapturedTimestamp": stamp.isoformat(),
                    }
                }
            }
        }

    observe_read_only(vehicle, profile, sample(12, now), now)
    observe_read_only(vehicle, profile, sample(-256, now - timedelta(minutes=1)), now)
    assert vehicle.readings["remainingClimatisationTime"]["value"] == 12
    later = now + timedelta(minutes=1)
    observe_read_only(vehicle, profile, sample(-256, later), later)
    assert vehicle.readings["remainingClimatisationTime"]["value"] is None
    assert (
        vehicle.readings["remainingClimatisationTime"]["reason"] == "negative_duration"
    )


def test_charging_eta_follows_valid_and_invalid_source_capture():
    vehicle, profile, now = car(), Profile(), datetime.now(UTC)

    def sample(value, stamp):
        return {
            "charging": {
                "chargingStatus": {
                    "value": {
                        "remainingChargingTimeToComplete_min": value,
                        "carCapturedTimestamp": stamp.isoformat(),
                    }
                }
            }
        }

    observe_read_only(vehicle, profile, sample(45, now), now)
    assert (
        vehicle.readings["charging_complete_time"]["value"]
        == (now + timedelta(minutes=45)).isoformat()
    )
    later = now + timedelta(minutes=1)
    observe_read_only(vehicle, profile, sample(-256, later), later)
    eta = vehicle.readings["charging_complete_time"]
    assert eta["value"] is None
    assert eta["status"] == "invalid_value"
    assert eta["captured"] == later.isoformat()
    observe_read_only(vehicle, profile, sample(45, now), later)
    assert vehicle.readings["charging_complete_time"]["value"] is None
    newest = later + timedelta(minutes=1)
    observe_read_only(vehicle, profile, sample(30, newest), newest)
    assert (
        vehicle.readings["charging_complete_time"]["value"]
        == (newest + timedelta(minutes=30)).isoformat()
    )
    finished = newest + timedelta(minutes=1)
    observe_read_only(vehicle, profile, sample(0, finished), finished)
    assert vehicle.readings["remainingChargingTime"]["value"] == 0
    assert "charging_complete_time" not in vehicle.readings
    observe_read_only(vehicle, profile, sample(30, newest), finished)
    assert "charging_complete_time" not in vehicle.readings


def test_shared_scalar_mapping_preserves_meaningful_values_and_rejects_error_envelopes():
    from custom_components.audiconnect.v3.attribute_runtime import (
        normalize_attribute_value,
    )
    from custom_components.audiconnect.v3.historical_catalog import ATTRIBUTES

    assert normalize_attribute_value(ATTRIBUTES["stateOfCharge"], 0, None) == (0, None)
    assert normalize_attribute_value(
        ATTRIBUTES["externalPower"], "unavailable", None
    ) == ("unavailable", None)
    assert normalize_attribute_value(ATTRIBUTES["chargingState"], "unknown", None) == (
        None,
        "unknown_charging_state",
    )
    for bad in ({"error": {"code": 1}}, {}, [], "notavailable"):
        assert normalize_attribute_value(ATTRIBUTES["externalPower"], bad, None) == (
            None,
            None,
        )
