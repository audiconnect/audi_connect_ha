"""Q8 Auth0 model metadata: do not show Unknown () when shortName exists."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from custom_components.audiconnect.audi_entity import AudiEntity
from custom_components.audiconnect.audi_models import Vehicle, VehiclesResponse
from custom_components.audiconnect.audi_connect_account import AudiConnectVehicle
from custom_components.audiconnect.sensor import _model_attrs, _park_time_attrs


@pytest.mark.parametrize(
    ("long_name", "short_name", "nickname", "expected", "source"),
    [
        ("Audi Q8 TFSI e", "Q8", "Family car", "Audi Q8 TFSI e", "audi_long_name"),
        (None, "Q8", "Family car", "Q8", "audi_short_name"),
        ("", "", "Q8 PHEV", "Q8 PHEV", "nickname_fallback"),
        (None, None, None, "", "unavailable"),
    ],
)
def test_model_fallbacks(long_name, short_name, nickname, expected, source):
    v = Vehicle()
    v.parse(
        {
            "vin": "NOT_A_REAL_VIN",
            "nickname": nickname,
            "vehicle": {
                "media": {"longName": long_name, "shortName": short_name},
                "core": {"modelYear": 2025},
            },
        }
    )
    assert v.model == expected
    assert v.model_source == source
    assert v.model_year == "2025"
    assert v.title
    assert _model_attrs(NS(model_source=v.model_source, model_year=v.model_year))["model_source"] == source


def test_auth0_missing_media_and_core_does_not_crash():
    v = Vehicle()
    v.parse({"vin": "NOT_A_REAL_VIN", "vehicle": {"media": None, "core": None}})
    assert v.model == ""
    assert v.model_year == ""
    assert v.title == "Audi vehicle"


def test_vehicle_list_enrichment_missing_does_not_drop_car():
    result = VehiclesResponse()
    result.parse({"userVehicles": [
        {"vin": "NOT_A_REAL_VIN", "vehicle": {"media": None, "core": None},
         "nickname": "Q8 PHEV"}
    ]})
    assert len(result.vehicles) == 1
    assert result.vehicles[0].model == "Q8 PHEV"
    assert result.vehicles[0].model_source == "nickname_fallback"


def test_device_model_does_not_have_empty_year_parentheses():
    class _Coordinator:
        last_update_success = True
        def async_add_listener(self, *args, **kwargs):
            return lambda: None

    car = NS(vin="NOT_A_REAL_VIN", model="", model_year="",
             title="Q8 PHEV")
    obj = AudiEntity(_Coordinator(), car)
    info = obj.device_info
    assert info["model"] == "Q8 PHEV"
    assert "()" not in info["model"]
    assert info["identifiers"] == {("audiconnect", "not_a_real_vin")}


def test_parking_clock_takes_priority_over_position_capture():
    from datetime import UTC, datetime
    legacy = datetime(2026, 11, 10, 11, tzinfo=UTC)
    observed = datetime(2026, 11, 10, 12, tzinfo=UTC)
    car = NS(vin="NOT_A_REAL_VIN", state={})
    wrapped = AudiConnectVehicle(None, car)
    wrapped._vehicle.state = {
        "vehicleParkingClock": legacy,
        "position": {"parktime": observed},
    }
    assert wrapped.park_time == legacy
    assert wrapped.park_time_source == "vehicle_parking_clock"
    assert _park_time_attrs(wrapped)["estimated"] is False


def test_modern_parking_time_is_labeled_estimate_not_engine_off():
    from datetime import UTC, datetime
    captured = datetime(2026, 11, 10, 12, tzinfo=UTC)
    car = NS(vin="NOT_A_REAL_VIN", state={})
    wrapped = AudiConnectVehicle(None, car)
    wrapped._vehicle.state["position"] = {"parktime": captured}
    assert wrapped.park_time == captured
    assert wrapped.park_time_supported
    attrs = _park_time_attrs(wrapped)
    assert attrs["estimated"] is True
    assert "not verified" in attrs["meaning"]


def test_no_parking_timestamp_remains_unsupported():
    car = NS(vin="NOT_A_REAL_VIN", state={})
    wrapped = AudiConnectVehicle(None, car)
    assert wrapped.park_time is None
    assert wrapped.park_time_supported is False
