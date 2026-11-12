from datetime import UTC,datetime
from types import SimpleNamespace as NS
from custom_components.audiconnect.v3.legacy_values import observe_legacy
from custom_components.audiconnect.v3.vehicle import V3Vehicle
VIN="WAUZZZ4M0MD123456"
def test_legacy_numeric_and_access_data_use_historical_ids():
    car=V3Vehicle(VIN,"Audi","A4","","DE",auth_family="legacy")
    p=NS(attribute_evidence={}); now=datetime.now(UTC); stamp=now.isoformat()
    fields=[{"id":"0x0101010002","value":"12345","tsCarCaptured":stamp},
            {"id":"0x0301040002","value":"2","tsCarCaptured":stamp}]
    observe_legacy(car,p,"vehicle_data",NS(data={"StoredVehicleDataResponse":{"vehicleData":{"data":[{"field":fields}]}}},observed_at=now))
    assert car.readings["UTC_TIME_AND_KILOMETER_STATUS"]["value"]==12345
    assert car.readings["left_front_door_open"]["value"] is True
    assert car.readings["any_door_open"]["value"] is True
    assert "any_door_unlocked" not in car.readings


def test_legacy_trip_units_and_reset_are_not_cariad_units():
    from custom_components.audiconnect.v3.trips import normalize_mbb_trips
    now=datetime.now(UTC).isoformat()
    out=normalize_mbb_trips({"tripDataList":{"tripData":[
        {"timestamp":now,"overallMileage":12345,"startMileage":12300,"averageFuelConsumption":"81"},
        {"timestamp":now,"overallMileage":12200,"startMileage":12000,"averageFuelConsumption":"73"}]}})
    assert out["current"]["averageFuelConsumption"]==8.1
    assert out["reset"]["averageFuelConsumption"]==7.3
