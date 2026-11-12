"""Reserved system variables in V3 command templates.

VIN is a standard vehicle placeholder. SPIN is never user-supplied/persisted
and is only resolved inside approved CARIAD door-control JSON requests.
"""
from types import SimpleNamespace
import json
import pytest
from custom_components.audiconnect.v3.engine import V3Engine
from custom_components.audiconnect.v3.development_profiles import (
    DevelopmentProfile, DevelopmentProfileError,
)
from custom_components.audiconnect.v3.registry import CapabilityRegistry
from custom_components.audiconnect.v3.runtime import catalog_path
from custom_components.audiconnect.v3.vehicle import V3Vehicle


VIN="WAUZZZ4M0MD123456"
SECRET="9876"


def setup():
    model=CapabilityRegistry.from_json_file(catalog_path())
    car=V3Vehicle(vin=VIN,name="Audi",model="Q8",model_family="",country="DE")
    auth=SimpleNamespace(service=SimpleNamespace(_spin=SECRET),country="DE",uses_auth0=True)
    engine=V3Engine(None,SimpleNamespace(entry_id="test",data={},options={}),
                    model,auth=auth,transport=object(),storage=object())
    engine.vehicles[VIN.lower()]=car
    profile=DevelopmentProfile(model,car.context)
    engine.profiles[VIN.lower()]=profile
    return engine,car,profile


def custom_access(action="unlock", **overrides):
    data={
        "id":f"user.access.{action}.secure_alternative",
        "capability":"access", "aspect":action,
        "family":"cariad", "method":"POST",
        "path":f"/vehicle/v1/vehicles/{{VIN}}/access/{action}",
        "body":{"spin":"{SPIN}"},
        "variables":{}, "response_paths":[],
        "description":"Secure reviewed alternative",
    }
    data.update(overrides)
    return data


def test_built_in_access_lock_and_unlock_use_same_system_template():
    engine,car,_=setup()
    for action in ("lock","unlock"):
        family,method,path,body=engine._operation_request(car,f"cariad.access.{action}")
        assert family=="cariad" and method=="POST"
        assert path==f"/vehicle/v1/vehicles/{VIN}/access/{action}"
        assert body=={"spin":SECRET}


def test_custom_access_route_is_secure_and_saved_only_as_marker():
    engine,car,profile=setup()
    operation=profile.add(custom_access())
    preview=profile.preview_request(operation,vehicle_values={"VIN":VIN})
    assert preview["json_body"]=={"spin":"{SPIN}"}
    assert "9876" not in json.dumps(preview)
    assert engine._operation_request(car,operation)[3]=={"spin":SECRET}
    data=json.dumps(profile.snapshot())
    assert SECRET not in data
    assert "{SPIN}" in data
    assert "{VIN}" in data


@pytest.mark.parametrize("bad",[
    {"path":"/vehicle/v1/vehicles/{VIN}/{SPIN}/access/unlock"},
    {"body":{"password":"{SPIN}"}},
    {"body":{"spin":"9876"}},
    {"body":{"spin":"{SPIN}","extra":"{VIN}"}},
    {"family":"mbb"},
    {"method":"GET"},
    {"path":"/vehicle/v1/vehicles/{VIN}/charging/start"},
    {"aspect":"lock"},  # Mismatched namespace
])
def test_unsafe_spin_custom_routes_are_rejected_without_storage(bad):
    _,_,profile=setup()
    with pytest.raises(DevelopmentProfileError):
        profile.add(custom_access(**bad))
    assert not profile.custom


def test_spin_missing_is_a_safe_error_without_exposing_account_secret():
    engine,car,_=setup()
    engine.auth.service._spin=None
    with pytest.raises(ValueError, match="Configure an Audi S-PIN"):
        engine._operation_request(car,"cariad.access.lock")


def test_user_cannot_declare_spin_or_send_it_as_a_manual_variable():
    _,_,profile=setup()
    with pytest.raises(DevelopmentProfileError):
        profile.add(custom_access(variables={"SPIN":"string"}))


def test_vin_is_available_in_normal_non_security_command_body():
    engine,car,profile=setup()
    operation=profile.add({
        "id":"user.remote.wake.with_vin",
        "capability":"remote","aspect":"wake",
        "family":"cariad","method":"POST",
        "path":"/vehicle/v1/vehicles/{VIN}/vehiclewakeuptrigger",
        "body":{"vehicle":"{VIN}"},
        "variables":{},
    })
    f,m,path,body=engine._operation_request(car,operation)
    assert (f,m)==("cariad","POST")
    assert VIN in path
    assert body=={"vehicle":VIN}


def test_builtin_preview_uses_registry_renderer_without_resolving_spin():
    engine, car, profile = setup()
    values = {"VIN": car.vin, "COUNTRY": car.country, "TYPE": "Audi",
              "JOBS": "access,charging"}
    lock = profile.preview_request("cariad.access.lock", vehicle_values=values)
    assert lock["json_body"] == {"spin": "{SPIN}"}
    assert lock["experimental_only"] is False
    batch = profile.preview_request("cariad.climate.status.batch", vehicle_values=values)
    assert batch["relative_path"].endswith("?jobs=access,charging")
    assert batch["json_body"] is None
    combined = profile.preview_request("cariad.charging.start.combined", vehicle_values=values)
    assert combined["json_body"] == {"action": "start"}


def test_shared_renderer_accepts_reviewed_attribute_read_route():
    from custom_components.audiconnect.v3.development_profiles import render_request
    route = {"family": "cariad", "method": "GET",
             "path": "/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs={JOBS}"}
    plan = render_request(route, vehicle_values={"VIN": VIN, "JOBS": "access,charging"})
    assert plan["relative_path"] == f"/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=access,charging"
    assert plan["json_body"] is None
