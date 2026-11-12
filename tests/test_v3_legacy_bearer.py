"""Legacy IDK can use explicitly reviewed CARIAD routes without weakening RLU isolation."""
from types import SimpleNamespace as NS
import pytest
from custom_components.audiconnect.v3.registry import CapabilityRegistry,VehicleContext
from custom_components.audiconnect.v3.runtime import catalog_path
from custom_components.audiconnect.v3.family_executors import CARIADExecutor
from custom_components.audiconnect.v3.command_policy import eligible_operation
from custom_components.audiconnect.v3.vehicle import V3Vehicle
VIN="WAUZZZ4M0MD123456"
def test_legacy_bearer_routes_are_explicit_and_api_level_scoped():
    reg=CapabilityRegistry.from_json_file(catalog_path())
    ctx=VehicleContext(auth="legacy",legacy_cariad=True,legacy_api_level=1)
    assert "cariad.charging.start" in reg.resolve("charging","start",ctx)["available_operations"]
    assert reg.resolve("access","lock",ctx)["available_operations"]==["mbb.access.lock"]
    assert reg.resolve("remote","wake",ctx)["available_operations"]==[]
    assert reg.resolve("climate","start",ctx)["available_operations"]==["cariad.climate.start.stored"]
    assert reg.resolve("climate","start",VehicleContext(auth="legacy",legacy_cariad=True,legacy_api_level=0))["available_operations"]==["mbb.climate.start"]
def test_legacy_bearer_transport_only_accepts_reviewed_paths():
    e=CARIADExecutor(); a=NS(uses_auth0=False,has_cariad_bearer=True,country="DE",access_token=lambda family:"fake")
    path=f"/vehicle/v1/vehicles/{VIN}/"
    assert e.plan(a,"GET",path+"selectivestatus?jobs=charging").method=="GET"
    for suffix in ("access/unlock","vehiclewakeuptrigger","unknown"):
        with pytest.raises(ValueError):
            e.plan(a,"POST",path+suffix,{},explicit_action=True)
def test_legacy_charging_not_lost_while_lock_remains_mbb():
    car=V3Vehicle(VIN,"Audi","A4","","DE",auth_family="legacy",legacy_cariad=True)
    car.advertised_capabilities={"charging","access"}
    car.readings["doorLockStatus"]={"value":"locked"}
    auth=NS(uses_auth0=False,service=NS(_spin="test"))
    assert eligible_operation(car,auth,"charging","start")=="cariad.charging.start"
    assert eligible_operation(car,auth,"access","unlock")=="mbb.access.unlock"
