"""Explicit approval for protected and non-protected discovery."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import asyncio
import pytest
from custom_components.audiconnect.v3.action_discovery import approval_group, validate_approval, DiscoveryError
from custom_components.audiconnect.v3.engine import V3Engine
from custom_components.audiconnect.v3.registry import CapabilityRegistry
from custom_components.audiconnect.v3.runtime import catalog_path
from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
from custom_components.audiconnect.v3.vehicle import V3Vehicle

VIN="WAUZZZ4M0MD123456"

@pytest.mark.parametrize("cap,action,ident,group",[
    ("access","unlock","cariad.access.unlock","spin"),
    ("remote","engine_stop","cariad.remote.engine_stop","spin"),
    ("climate","preheater_start","cariad.climate.preheater_start","spin"),
    ("remote","wake","cariad.remote.wake","non_spin"),
    ("charging","set_target_soc","cariad.charging.settings","non_spin"),
])
def test_approval_scope_is_server_derived(cap,action,ident,group):
    registry=CapabilityRegistry.from_json_file(catalog_path())
    op=registry.operations[ident]
    assert approval_group(cap,action,op)==group
    with pytest.raises(DiscoveryError):
        validate_approval(cap,action,op,None,has_spin=True)
    with pytest.raises(DiscoveryError):
        validate_approval(cap,action,op,"spin" if group=="non_spin" else "non_spin",has_spin=True)
    if group=="spin":
        with pytest.raises(DiscoveryError):
            validate_approval(cap,action,op,group,has_spin=False)
    assert validate_approval(cap,action,op,group,has_spin=True)==group

def test_approved_discovery_rejects_missing_approval_before_any_command():
    registry=CapabilityRegistry.from_json_file(catalog_path())
    car=V3Vehicle(VIN,"Audi","Q8","q8","DE",auth_family="auth0")
    obj=NS(require_vehicle=lambda vin:car, profiles={VIN.lower():DevelopmentProfile(registry,car.context)},
           auth=NS(service=NS(_spin="test-pin")),test_action=AsyncMock(return_value={"sequence":1}))
    for wrong in (None,"non_spin",True):
        with pytest.raises(DiscoveryError):
            asyncio.run(V3Engine.approved_control_discovery(obj,VIN,"unlock","cariad.access.unlock",approval=wrong,capability="access"))
    obj.test_action.assert_not_awaited()
    result=asyncio.run(V3Engine.approved_control_discovery(obj,VIN,"unlock","cariad.access.unlock",approval="spin",capability="access"))
    assert result=={"sequence":1}
    obj.test_action.assert_awaited_once_with(VIN,"unlock","cariad.access.unlock",params=None,capability="access")

def test_public_websocket_paths_cannot_bypass_approval():
    from pathlib import Path
    code=(Path(__file__).resolve().parents[1]/"custom_components/audiconnect/v3/dashboard.py").read_text()
    assert ".test_action(" not in code
    assert code.count(".approved_control_discovery(")==1
    assert "audiconnect/v3/control_test" in code
    assert '"audiconnect/v3/test"' not in code
