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
    return NS(
        transport=NS(request=AsyncMock(return_value=NS(status=207, data=payload))),
        auth=NS(uses_auth0=True, service=NS(_spin="test-pin")),
        send_control=AsyncMock(),
    )


def car():
    return V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")


def test_global_soc_preserves_other_settings():
    obj = engine(
        {
            "charging": {
                "chargingSettings": {
                    "value": {
                        "targetSOC_pct": 70,
                        "maxChargeCurrentAC_A": 16,
                        "autoUnlockPlugWhenChargedAC": False,
                        "carCapturedTimestamp": "old",
                    }
                }
            }
        }
    )
    result = asyncio.run(build(obj, car(), "charging_settings_update", {"value": 85}))
    assert obj.transport.request.await_args.kwargs["command_preparation"] == 1
    assert result == {
        "targetSOC_pct": 85,
        "maxChargeCurrentAC_A": 16,
        "autoUnlockPlugWhenChargedAC": False,
    }


def test_unknown_charging_setting_aborts_before_write():
    obj = engine(
        {
            "charging": {
                "chargingSettings": {
                    "value": {
                        "targetSOC_pct": 70,
                        "unknownFutureField": True,
                    }
                }
            }
        }
    )
    with pytest.raises(ValueError, match="Unrecognized"):
        asyncio.run(build(obj, car(), "charging_settings_update", {"value": 85}))
    assert obj.transport.request.await_count == 1


def test_profile_target_preserves_location_and_other_fields_on_wire():
    profile = {
        "id": 2,
        "position": {"lat": 0},
        "targetSOC_pct": 70,
        "minSOC_pct": 20,
        "name": "synthetic",
    }
    obj = engine(
        {
            "chargingProfiles": {
                "chargingProfilesStatus": {
                    "value": {
                        "profiles": [profile],
                        "vehiclePositionedInProfileID": 2,
                    }
                }
            }
        }
    )
    body = asyncio.run(build(obj, car(), "charging_profile_update", {"value": 80}))
    assert body == {"profile": {**profile, "targetSOC_pct": 80}}


def test_parameterized_climate_preserves_stored_zones():
    obj = engine(
        {
            "climatisation": {
                "climatisationSettings": {
                    "value": {
                        "targetTemperature_C": 20.5,
                        "zoneFrontLeftEnabled": True,
                        "windowHeatingEnabled": True,
                        "heaterSource": "electric",
                    }
                }
            }
        }
    )
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
    assert (
        eligible_operation(v, auth, "climate", "start") == "cariad.climate.start.stored"
    )
    assert eligible_operation(v, auth, "remote", "wake") == "cariad.remote.wake"
    v.impaired_capabilities.add("access")
    assert eligible_operation(v, auth, "access", "unlock") is None


def test_timed_charge_is_mode_preference_not_start_post():
    obj = engine()
    asyncio.run(execute(obj, "VIN", "start_timed_charger"))
    obj.send_control.assert_awaited_once_with(
        "VIN", "set_charge_mode", "charging", params={"value": "timer"}
    )


def test_shared_climate_patch_preserves_existing_fields_and_rejects_unreported_updates():
    obj = engine(
        {
            "climatisation": {
                "climatisationSettings": {
                    "value": {
                        "targetTemperature_C": 20.5,
                        "windowHeatingEnabled": False,
                        "futureSetting": "preserve",
                        "carCapturedTimestamp": "old",
                    }
                }
            }
        }
    )
    result = asyncio.run(
        build(obj, car(), "climate_settings_update", {"windowHeatingEnabled": True})
    )
    assert result == {
        "targetTemperature_C": 20.5,
        "windowHeatingEnabled": True,
        "futureSetting": "preserve",
    }
    with pytest.raises(ValueError, match="not reported"):
        asyncio.run(
            build(obj, car(), "climate_settings_update", {"zoneFrontLeftEnabled": True})
        )


@pytest.mark.parametrize(
    "params",
    [
        {"windowHeatingEnabled": "false"},
        {"zoneFrontLeftEnabled": 1},
        {"targetTemperature_C": 99},
        {"unreviewed": True},
    ],
)
def test_invalid_climate_patch_rejected_before_any_request(params):
    obj = engine()
    with pytest.raises(ValueError):
        asyncio.run(build(obj, car(), "climate_settings_update", params))
    obj.transport.request.assert_not_awaited()


def test_q8_sparse_climate_settings_use_observed_fields_only():
    obj = engine(
        {
            "climatisation": {
                "climatisationSettings": {
                    "value": {
                        "targetTemperature_C": 20,
                        "targetTemperature_F": 68,
                        "climatisationWithoutExternalPower": True,
                        "carCapturedTimestamp": "old",
                    }
                }
            }
        }
    )
    body = asyncio.run(build(obj, car(), "climate_settings_update", {"temp_c": 22}))
    assert body == {
        "targetTemperature_C": 22,
        "targetTemperature_F": 72,
        "climatisationWithoutExternalPower": True,
    }
    obj.transport.request.assert_awaited_once()


def test_climate_start_readback_requires_requested_temperature_not_only_on():
    from datetime import UTC, datetime, timedelta
    from custom_components.audiconnect.v3.command_journal import CommandRecord
    from custom_components.audiconnect.v3.command_readback import (
        configure_readback,
        reconcile_readback,
    )

    vehicle = car()
    now = datetime.now(UTC)
    record = CommandRecord.begin(
        "climate",
        "start_with_settings",
        "route",
        (now - timedelta(minutes=1)).timestamp(),
    )
    configure_readback(record, {"temp_c": 22.5})
    record.observe_http(200)
    vehicle.set_climate(
        "heating", now.isoformat(), route="test", observed_at=now, http_status=200
    )
    vehicle.readings["climatisationTargetTemperatureC"] = {
        "value": 20,
        "captured": now.isoformat(),
        "observed": now.isoformat(),
    }
    assert not reconcile_readback(record, vehicle, now)
    vehicle.readings["climatisationTargetTemperatureC"]["value"] = 22.5
    assert reconcile_readback(record, vehicle, now)
    assert CommandRecord.restore(record.snapshot()).readback_values == [22.5]


@pytest.mark.parametrize(
    "mode,params",
    [
        ("climate_start_settings", {"temp_c": 20, "temp_f": 68}),
        ("climate_settings_update", {"temp_c": 20, "temp_f": 68}),
        ("climate_settings_update", {"temp_c": 20, "targetTemperature_C": 21}),
    ],
)
def test_conflicting_temperature_inputs_rejected_before_settings_request(mode, params):
    obj = engine()
    with pytest.raises(ValueError, match="Supply"):
        asyncio.run(build(obj, car(), mode, params))
    obj.transport.request.assert_not_awaited()


def test_vehicle_specific_climate_discovery_schema_and_payload():
    from datetime import UTC, datetime
    from custom_components.audiconnect.v3.attribute_runtime import observe_read_only
    from custom_components.audiconnect.v3.command_parameters import (
        native_climate_parameter_schema,
    )
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    from custom_components.audiconnect.v3.registry import CapabilityRegistry
    from custom_components.audiconnect.v3.runtime import catalog_path

    registry = CapabilityRegistry.from_json_file(catalog_path())
    route = registry.operations["cariad.climate.start.vehicle_settings"]
    now = datetime.now(UTC)
    vehicle = car()
    profile = DevelopmentProfile(registry, vehicle.context)
    payload = {
        "climatisation": {
            "climatisationSettings": {
                "value": {
                    "targetTemperature_C": 20,
                    "zoneFrontLeftEnabled": False,
                    "zoneRearLeftEnabled": None,
                    "climatisationMode": "comfort",
                    "carCapturedTimestamp": now.isoformat(),
                }
            }
        }
    }
    observe_read_only(vehicle, profile, payload, now)
    schema = native_climate_parameter_schema(route, {}, vehicle)
    assert "seat_fl" in schema
    assert "seat_rl" not in schema
    assert schema["climatisation_mode"]["enum"] == ["comfort"]

    from custom_components.audiconnect.v3.read_discovery import user_test_candidates

    vehicle.advertised_capabilities.add("climatisation")
    obj = engine(payload)
    from types import SimpleNamespace

    obj.auth = SimpleNamespace(uses_auth0=True, service=SimpleNamespace(_spin=""))
    guided = user_test_candidates(obj, vehicle, profile)
    selective = user_test_candidates(obj, vehicle, profile, include_verified=True)
    key = "climate.start_with_settings"
    assert guided[key]["parameter_schema"] == selective[key]["parameter_schema"]
    assert set(guided[key]["parameter_schema"]) == {
        "temp_c",
        "seat_fl",
        "climatisation_mode",
    }
    assert "seat_fl" in selective[key]["parameter_schema"]
    assert "seat_rl" not in selective[key]["parameter_schema"]
    assert not selective[key]["parameter_schema"]["temp_c"].get("required")
    assert set(native_climate_parameter_schema(route, {}, car())) == {
        "temp_c",
        "temp_f",
    }
    obj = engine(payload)
    body = asyncio.run(
        build(obj, vehicle, "climate_start_settings", {"temp_c": 22, "seat_fl": True})
    )
    assert body["zoneFrontLeftEnabled"] is True
    assert "zoneRearLeftEnabled" not in body
    for params in ({"seat_rl": True}, {"climatisation_mode": "economy"}):
        with pytest.raises(ValueError):
            asyncio.run(build(obj, vehicle, "climate_start_settings", params))


def test_null_optional_fahrenheit_does_not_block_celsius_update():
    obj = engine(
        {
            "climatisation": {
                "climatisationSettings": {
                    "value": {
                        "targetTemperature_C": 20,
                        "targetTemperature_F": None,
                        "windowHeatingEnabled": False,
                    }
                }
            }
        }
    )
    body = asyncio.run(build(obj, car(), "climate_settings_update", {"temp_c": 22}))
    assert body == {
        "targetTemperature_C": 22,
        "targetTemperature_F": None,
        "windowHeatingEnabled": False,
    }
    obj.transport.request.assert_awaited_once()
