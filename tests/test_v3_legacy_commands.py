from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import asyncio
import pytest
from custom_components.audiconnect.v3.family_executors import MBBLegacyExecutor
from custom_components.audiconnect.v3.legacy_commands import climate_body, security_token, confirm
from custom_components.audiconnect.v3.action_discovery import approval_group
from custom_components.audiconnect.v3.registry import CapabilityRegistry
from custom_components.audiconnect.v3.runtime import catalog_path
VIN="WAUZZZ4M0MD123456"
def test_legacy_commands_exact_paths_and_explicit_intent():
    e=MBBLegacyExecutor(); auth=NS(uses_auth0=False,access_token=lambda family:"fake")
    path=f"/fs-car/bs/climatisation/v1/Audi/DE/vehicles/{VIN}/climater/actions"
    body=climate_body("mbb_climate_start",{"temp_c":22})
    assert body["action"]["settings"]["targetTemperature"]==2951
    assert e.plan(auth,"POST",path,body,explicit_action=True).body==body
    with pytest.raises(ValueError): e.plan(auth,"POST",path,body)
    lock=f"/api/bs/rlu/v1/vehicles/{VIN}/lock"
    with pytest.raises(ValueError): e.plan(auth,"POST",lock,explicit_action=True)
    assert e.plan(auth,"POST",lock,explicit_action=True,security_token="temporary").headers["x-securityToken"]=="temporary"
    with pytest.raises(ValueError): e.plan(auth,"POST",lock,explicit_action=True,security_token="temporary",body={})
    catalog=CapabilityRegistry.from_json_file(catalog_path())
    assert approval_group("access","lock",catalog.operations["mbb.access.lock"])=="spin"

def test_security_challenge_and_status_never_retry_mutation():
    obj=NS(remaining_calls=100,request=AsyncMock(side_effect=[
        NS(status=200,data={"securityPinAuthInfo":{"securityToken":"first","securityPinTransmission":{"challenge":"ABCD"}}}),
        NS(status=200,data={"securityToken":"final"}),
        NS(status=200,data={"requestStatusResponse":{"status":"request_successful"}}),
    ]))
    assert asyncio.run(security_token(obj,VIN,"lock","1234"))=="final"
    assert asyncio.run(confirm(obj,f"/api/bs/rlu/v1/vehicles/{VIN}/lock",{"rluActionResponse":{"requestId":"abc"}},delay=0))=="backend_completed"
    assert [x.args[1] for x in obj.request.await_args_list]==["GET","POST","GET"]


def test_challenge_completion_uses_same_vehicle_region():
    e=MBBLegacyExecutor(); auth=NS(uses_auth0=False,access_token=lambda family:"fake")
    e.set_vehicle_home_region(VIN,"https://mal-3a.prd.eu.dp.vwg-connect.com")
    path="/api/rolesrights/authorization/v2/security-pin-auth-completed"
    body={"securityPinAuthentication":{}}
    with pytest.raises(ValueError):
        e.plan(auth,"POST",path,body,explicit_action=True)
    assert e.plan(auth,"POST",path,body,explicit_action=True,region_vin=VIN).url.startswith("https://mal-3a.prd.eu.dp.vwg-connect.com")
