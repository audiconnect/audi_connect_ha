"""#793: an all-error selectivestatus payload has to be detectable, so the caller
can keep the last known values instead of quietly pruning every entity.

Composes with the pytest harness from #815 (no network). On its own it just needs
the package importable.
"""

from __future__ import annotations

from custom_components.audiconnect.audi_models import (
    VehicleDataResponse,
    _count_error_objects,
)

# HTTP 200 payload where every job carried an error object (a CARIAD outage).
_OUTAGE = {
    "access": {"accessStatus": {"error": {"message": "Bad Gateway", "retry": True}}},
    "charging": {
        "batteryStatus": {"error": {"message": "Bad Gateway"}},
        "chargingStatus": {"error": {"message": "Bad Gateway"}},
    },
    "measurements": {
        "odometerStatus": {"error": {"message": "Bad Gateway"}},
        "rangeStatus": {"error": {"message": "Bad Gateway"}},
    },
}

# A normal payload with real values and no error object.
_NORMAL = {
    "measurements": {
        "odometerStatus": {"value": {"odometer": 42000}},
        "fuelLevelStatus": {"value": {"currentFuelLevel_pct": 70}},
    },
    "fuelStatus": {"rangeStatus": {"value": {"totalRange_km": 480}}},
}

# A car that simply lacks a feature: no error, just fewer jobs.
_FEATURELESS = {"access": {"accessStatus": {"value": {"doorLockStatus": "locked"}}}}


def test_count_error_objects_counts_every_error() -> None:
    assert _count_error_objects(_OUTAGE) == 5
    assert _count_error_objects(_NORMAL) == 0
    assert _count_error_objects(_FEATURELESS) == 0


def test_all_jobs_errored_true_on_outage() -> None:
    assert VehicleDataResponse(_OUTAGE).all_jobs_errored is True


def test_all_jobs_errored_false_on_real_data() -> None:
    assert VehicleDataResponse(_NORMAL).all_jobs_errored is False


def test_featureless_car_is_not_flagged_as_an_outage() -> None:
    # No error object here, so the "keep last known values" guard must not fire.
    # A feature the car doesn't have is a real absence, not an outage.
    assert VehicleDataResponse(_FEATURELESS).all_jobs_errored is False
