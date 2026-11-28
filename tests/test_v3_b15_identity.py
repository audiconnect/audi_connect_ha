from types import SimpleNamespace as NS

import pytest
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3.identity_cache import (
    capture_identity,
    apply_cached_identity,
)
from custom_components.audiconnect.v3.command_policy import eligible_operation


def test_cached_identity_is_private_last_known_not_new_drivetrain():
    car = V3Vehicle(
        "wauzzz4m0md123456",
        "Audi Q8",
        "Audi Q8",
        "q8",
        "DE",
        model_year="2022",
        model_source="audi_long_name",
        car_type="phev",
        identity_observed_at="2026-11-12T14:00:00+00:00",
    )
    row = capture_identity(car)
    new = V3Vehicle(car.vin, "Audi vehicle", "", "", "DE")
    apply_cached_identity(new, row)
    assert new.model == "Audi Q8" and new.model_year == "2022" and new.identity_restored
    assert new.car_type == "" and not capture_identity(new)
    other = V3Vehicle(car.vin, "Audi vehicle", "", "", "BE")
    apply_cached_identity(other, row)
    assert not other.model


def test_cached_identity_cannot_authorize_remote_engine():
    car = V3Vehicle(
        "wauzzz4m0md123456",
        "Audi A4",
        "Audi A4",
        "a4",
        "DE",
        car_type="combustion",
        identity_restored=True,
    )
    car.advertised_capabilities.add("remoteEngineStart")
    assert (
        eligible_operation(
            car, NS(uses_auth0=True, service=NS(_spin="1234")), "remote", "engine_start"
        )
        is None
    )


@pytest.mark.parametrize(
    "label", ["Audi", "Audi vehicle", "unknown", "WAUZZZ4M0MD123456"]
)
def test_cached_identity_rejects_labels_invalid_for_live_inventory(label):
    from custom_components.audiconnect.v3.identity_cache import validate_identity

    vin = "WAUZZZ4M0MD123456"
    row = {
        "model": label,
        "source": "audi_long_name",
        "region": "DE",
        "observed_at": "2026-11-12T14:00:00+00:00",
    }
    assert not validate_identity(row, "DE", vin)
    assert not V3Vehicle.from_graphql(
        {"vin": vin, "vehicle": {"media": {"longName": label}}}, "DE"
    ).model


def test_cached_identity_fills_only_missing_fields_of_matching_model():
    from custom_components.audiconnect.v3.transport import GARAGE_OPERATION

    vin = "WAUZZZ4M0MD123456"
    row = {
        "model": "Audi Q8",
        "source": "audi_long_name",
        "region": "DE",
        "observed_at": "2026-11-12T14:00:00+00:00",
        "year": "2022",
        "year_operation": GARAGE_OPERATION,
    }
    fresh = V3Vehicle(vin, "Audi Q8", "Audi Q8", "q8", "DE")
    apply_cached_identity(fresh, row)
    assert fresh.model_year == "2022" and fresh.year_operation == GARAGE_OPERATION
    assert not fresh.identity_restored and fresh.identity_observed_at is None
    fresh.model_year = "2025"
    apply_cached_identity(fresh, row)
    assert fresh.model_year == "2025"
    conflicting = V3Vehicle(vin, "Audi Q5", "Audi Q5", "q5", "DE")
    apply_cached_identity(conflicting, row)
    assert not conflicting.model_year


def test_malformed_retained_identity_operation_does_not_break_restore():
    from custom_components.audiconnect.v3.identity_cache import validate_identity
    from custom_components.audiconnect.v3.transport import INVENTORY_OPERATION

    row = {
        "model": "Audi Q8",
        "source": "audi_long_name",
        "region": "DE",
        "observed_at": "2026-11-12T14:00:00+00:00",
        "year": "2022",
        "operation": [],
        "year_operation": {},
    }
    result = validate_identity(row, "DE")
    assert result["operation"] == INVENTORY_OPERATION
    assert result["year_operation"] == INVENTORY_OPERATION


def test_legacy_year_provenance_is_not_invented():
    from custom_components.audiconnect.v3.identity_cache import validate_identity

    row = {
        "model": "Audi Q8",
        "source": "audi_long_name",
        "region": "DE",
        "observed_at": "2026-11-12T14:00:00+00:00",
        "year": "2022",
    }
    assert "year_observed_at" not in validate_identity(row, "DE")
    row["year_observed_at"] = "2026-11-13T14:00:00"
    assert "year_observed_at" not in validate_identity(row, "DE")
