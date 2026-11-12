from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3.derived_values import observe_derived
from custom_components.audiconnect.v3.attribute_runtime import _accept_observation
from custom_components.audiconnect.v3.product_contract import projection_reading, normalized_range_details
from custom_components.audiconnect.v3.historical_catalog import ATTRIBUTES

def test_explicit_alternative_range_soc_and_odometer_sources():
    car=V3Vehicle("WAUZZZ4M0MD123456","Audi","Q8","q8","DE")
    now=datetime.now(UTC)
    stamp=now.isoformat()
    old=(now-timedelta(hours=1)).isoformat()
    car.readings["TOTAL_RANGE"]={"value":300,"captured":old,"status":"verified"}
    car.readings["UTC_TIME_AND_KILOMETER_STATUS"]={"value":1000,"captured":old,"status":"verified"}
    payload={"measurements":{"rangeStatus":{"value":{"carCapturedTimestamp":stamp,
        "electricRange":40,"gasolineRange":600,"totalRange_km":640}},
        "fuelLevelStatus":{"value":{"carCapturedTimestamp":stamp,"carType":"hybrid","currentSOC_pct":72}}},
        "charging":{"batteryStatus":{"value":{"carCapturedTimestamp":old,"cruisingRangeElectric_km":30}}},
        "vehicleHealthInspection":{"maintenanceStatus":{"value":{"carCapturedTimestamp":stamp,"mileage_km":1020}}}}
    observe_derived(car,NS(),payload,now,_accept_observation)
    assert projection_reading(car,ATTRIBUTES["TOTAL_RANGE"])[1]["value"]==640
    assert projection_reading(car,ATTRIBUTES["UTC_TIME_AND_KILOMETER_STATUS"])[1]["value"]==1020
    assert projection_reading(car,ATTRIBUTES["stateOfCharge"])[1]["value"]==72
    assert normalized_range_details(car)["electric_range_km"]==40
    assert normalized_range_details(car)["fuel_range_km"]==600

def test_generic_soc_not_treated_as_electric_on_combustion():
    car=V3Vehicle("WAUZZZ4M0MD123456","Audi","A6","a6","DE",car_type="gasoline")
    car.readings["measuredElectricSOC"]={"value":72,"status":"verified"}
    assert projection_reading(car,ATTRIBUTES["stateOfCharge"])[1] is None


def test_engine_fuel_level_never_selects_electric_or_unknown_engine_by_order():
    car=V3Vehicle("WAUZZZ4M0MD123456","Audi","Q8","q8","DE",car_type="phev")
    now=datetime.now(UTC)
    stamp=now.isoformat()
    payload={"fuelStatus":{"rangeStatus":{"value":{"carCapturedTimestamp":stamp,
        "primaryEngine":{"currentFuelLevel_pct":61},
        "secondaryEngine":{"currentFuelLevel_pct":89}}}}}
    observe_derived(car,NS(),payload,now,_accept_observation)
    assert projection_reading(car,ATTRIBUTES["TANK_LEVEL_IN_PERCENTAGE"])[1] is None
    car.readings["primary_engine_type"]={"value":"gasoline","status":"verified"}
    car.readings["secondary_engine_type"]={"value":"electric","status":"verified"}
    assert projection_reading(car,ATTRIBUTES["TANK_LEVEL_IN_PERCENTAGE"])[1]["value"]==61
    car.readings["primary_engine_type"]["value"]="electric"
    car.readings["secondary_engine_type"]["value"]="gasoline"
    assert projection_reading(car,ATTRIBUTES["TANK_LEVEL_IN_PERCENTAGE"])[1]["value"]==89
