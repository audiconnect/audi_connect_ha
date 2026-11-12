"""Independent V3 historical command/payload parity; synthetic inputs only."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from custom_components.audiconnect.v3.command_payloads import build
from custom_components.audiconnect.v3.command_policy import eligible_operation
from custom_components.audiconnect.v3.service_commands import execute
from custom_components.audiconnect.v3.vehicle import V3Vehicle


def engine(payload=None):
    return NS(transport=NS(request=AsyncMock(return_value=NS(status=207, data=payload))),
              auth=NS(uses_auth0=True, service=NS(_spin="test-pin")), send_control=AsyncMock())


def car():
    return V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")


def test_global_soc_preserves_other_settings():
    obj = engine({"charging": {"chargingSettings": {"value": {
        "targetSOC_pct": 70, "maxChargeCurrentAC_A": 16,
        "autoUnlockPlugWhenChargedAC": False, "carCapturedTimestamp": "old",
    }}}})
    result = asyncio.run(build(obj, car(), "charging_settings_update", {"value": 85}))
    assert result == {"targetSOC_pct": 85, "maxChargeCurrentAC_A": 16,
                      "autoUnlockPlugWhenChargedAC": False}


def test_unknown_charging_setting_aborts_before_write():
    obj = engine({"charging": {"chargingSettings": {"value": {
        "targetSOC_pct": 70, "unknownFutureField": True,
    }}}})
    with pytest.raises(ValueError, match="Unrecognized"):
        asyncio.run(build(obj, car(), "charging_settings_update", {"value": 85}))
    assert obj.transport.request.await_count == 1


def test_profile_target_preserves_location_and_other_fields_on_wire():
    profile = {"id": 2, "position": {"lat": 0}, "targetSOC_pct": 70,
               "minSOC_pct": 20, "name": "synthetic"}
    obj = engine({"chargingProfiles": {"chargingProfilesStatus": {"value": {
        "profiles": [profile], "vehiclePositionedInProfileID": 2,
    }}}})
    body = asyncio.run(build(obj, car(), "charging_profile_update", {"value": 80}))
    assert body == {"profile": {**profile, "targetSOC_pct": 80}}


def test_parameterized_climate_preserves_stored_zones():
    obj = engine({"climatisation": {"climatisationSettings": {"value": {
        "targetTemperature_C": 20.5, "zoneFrontLeftEnabled": True,
        "windowHeatingEnabled": True, "heaterSource": "electric",
    }}}})
    body = asyncio.run(build(obj, car(), "climate_start_settings", {"temp_c": 22}))
    assert body["targetTemperature"] == 22
    assert body["zoneFrontLeftEnabled"] is True
    assert body["windowHeatingEnabled"] is True
    assert "zoneRearLeftEnabled" not in body


def test_historical_defaults_require_vehicle_evidence_and_pin():
    v = car()
    auth = engine().auth
    assert eligible_operation(v, auth, "access", "unlock") is None
    v.advertised_capabilities = {"access", "climatisation", "vehicleWakeUp"}
    assert eligible_operation(v, auth, "access", "unlock") == "cariad.access.unlock"
    assert eligible_operation(v, auth, "climate", "start") == "cariad.climate.start.stored"
    assert eligible_operation(v, auth, "remote", "wake") == "cariad.remote.wake"
    v.impaired_capabilities.add("access")
    assert eligible_operation(v, auth, "access", "unlock") is None


def test_timed_charge_is_mode_preference_not_start_post():
    obj = engine()
    asyncio.run(execute(obj, "VIN", "start_timed_charger"))
    obj.send_control.assert_awaited_once_with(
        "VIN", "set_charge_mode", "charging", params={"value": "timer"})


def test_shared_climate_patch_preserves_existing_fields_and_rejects_unreported_updates():
    obj = engine({"climatisation": {"climatisationSettings": {"value": {
        "targetTemperature_C": 20.5, "windowHeatingEnabled": False,
        "futureSetting": "preserve", "carCapturedTimestamp": "old",
    }}}})
    result = asyncio.run(build(obj, car(), "climate_settings_update",
                               {"windowHeatingEnabled": True}))
    assert result == {"targetTemperature_C": 20.5, "windowHeatingEnabled": True,
                      "futureSetting": "preserve"}
    with pytest.raises(ValueError, match="not reported"):
        asyncio.run(build(obj, car(), "climate_settings_update",
                          {"zoneFrontLeftEnabled": True}))
