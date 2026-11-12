"""V3 sensor metadata and API normalization follow Home Assistant standards."""
from types import SimpleNamespace
import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.util.unit_conversion import DistanceConverter, PowerConverter
from custom_components.audiconnect.v3.attribute_contracts import attribute_contracts
from custom_components.audiconnect.v3.api_value_mappings import (
    normalize_api_value, validate_transform, validate_attribute_transform,
)
from custom_components.audiconnect.v3.entities import V3ReadOnlySensor
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3.attribute_routes import (
    validate_custom_read_route, read_variants,
)


def test_v2_metadata_is_declarative_and_correct():
    contracts=attribute_contracts()
    assert contracts["state_of_charge"]["unit"] == "%"
    assert contracts["state_of_charge"]["device_class"] == "battery"
    assert contracts["range"]["unit"] == "km"
    assert contracts["mileage"]["state_class"] == "total_increasing"
    assert contracts["charging_power"]["unit"] == "kW"
    assert contracts["charging_power"]["device_class"] == "power"
    assert contracts["remaining_charging_time"]["unit"] is None
    assert contracts["remaining_charging_time"]["unit_resolution"] == "api_route"


def test_entity_uses_contract_only_and_keeps_historical_id():
    car=V3Vehicle(vin="WAUZZZ4M0MD123456",name="Audi",model="Q8",model_family="",country="DE")
    dummy=SimpleNamespace(async_add_listener=lambda cb: None)
    entity=V3ReadOnlySensor(dummy,car,{
        "id":"stateOfCharge","entity_key":"state_of_charge","capability":"charging"
    })
    assert entity.unique_id == car.vin.lower()+"_sensor_state_of_charge"
    assert entity.native_unit_of_measurement == "%"
    assert entity.device_class == SensorDeviceClass.BATTERY
    car.readings["stateOfCharge"]={"value":55}
    assert entity.native_value == 55


def test_api_route_uses_standard_home_assistant_converters():
    miles={"unit_class":"distance","from":"mi","to":"km"}
    watts={"unit_class":"power","from":"W","to":"kW"}
    assert normalize_api_value(5,miles)==pytest.approx(DistanceConverter.convert(5,"mi","km"))
    assert normalize_api_value(1000,watts)==pytest.approx(PowerConverter.convert(1000,"W","kW"))
    assert normalize_api_value(0,miles)==0
    assert normalize_api_value(False,None) is False
    with pytest.raises(ValueError):
        normalize_api_value(True,miles)


def test_custom_route_supports_declarative_conversions_without_executable_code():
    inp={"id":"user.read.distance","attribute":"TOTAL_RANGE",
         "family":"cariad","method":"GET",
         "path":"/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=fuelStatus",
         "response_path":"/fuelStatus/rangeStatus/value/totalRange_mi",
         "conversion":{"unit_class":"distance","from":"mi","to":"km"}}
    assert validate_custom_read_route(inp)==inp
    assert read_variants("TOTAL_RANGE",{inp["id"]:inp})[-1]["conversion"]==inp["conversion"]
    with pytest.raises(ValueError):
        validate_custom_read_route({**inp,"conversion":{"type":"python","expression":"eval(...)"}})



def test_api_conversions_cannot_reinterpret_percentage_as_distance():
    with pytest.raises(ValueError, match="destination unit"):
        validate_attribute_transform("stateOfCharge",{
            "unit_class":"distance","from":"mi","to":"km"
        })


def test_json_pointer_rfc6901_extraction_preserves_false_and_zero():
    from custom_components.audiconnect.v3.historical_catalog import read_path
    payload={"data":{"foo/bar":[{"soc":0},{"enabled":False}],"~key":75}}
    assert read_path(payload,"/data/foo~1bar/0/soc")==0
    assert read_path(payload,"/data/foo~1bar/1/enabled") is False
    assert read_path(payload,"/data/~0key")==75
    assert read_path(payload,"/data/foo~1bar/9/soc") is None
    assert read_path(payload,"data.foo/bar") == payload["data"]["foo/bar"]


def test_legacy_dotted_and_standard_pointer_both_allowed_for_get_routes():
    base={"id":"user.read.pointer","attribute":"TOTAL_RANGE","family":"cariad",
          "method":"GET","path":"/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=fuelStatus",
          "response_path":"/fuelStatus/rangeStatus/value/totalRange_km"}
    assert validate_custom_read_route(base)==base
