from types import SimpleNamespace as NS
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3.identity_cache import capture_identity, apply_cached_identity
from custom_components.audiconnect.v3.command_policy import eligible_operation

def test_cached_identity_is_private_last_known_not_new_drivetrain():
    car = V3Vehicle("wauzzz4m0md123456", "Audi Q8", "Audi Q8", "q8", "DE",
                    model_year="2022", model_source="audi_long_name", car_type="phev",
                    identity_observed_at="2026-11-12T14:00:00+00:00")
    row = capture_identity(car)
    new = V3Vehicle(car.vin, "Audi vehicle", "", "", "DE")
    apply_cached_identity(new, row)
    assert new.model == "Audi Q8" and new.model_year == "2022" and new.identity_restored
    assert new.car_type == "" and not capture_identity(new)
    other = V3Vehicle(car.vin, "Audi vehicle", "", "", "BE")
    apply_cached_identity(other, row)
    assert not other.model

def test_cached_identity_cannot_authorize_remote_engine():
    car = V3Vehicle("wauzzz4m0md123456", "Audi A4", "Audi A4", "a4", "DE",
                    car_type="combustion", identity_restored=True)
    car.advertised_capabilities.add("remoteEngineStart")
    assert eligible_operation(car, NS(uses_auth0=True, service=NS(_spin="1234")), "remote", "engine_start") is None
