"""Sleeping-car display cache stays separate from current command evidence."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from custom_components.audiconnect.v3.attribute_runtime import observe_read_only
from custom_components.audiconnect.v3.entities import (
    V3ReadOnlyBinarySensor,
    V3ReadOnlySensor,
    V3StatusSensor,
    _reading_available,
)
from custom_components.audiconnect.v3.freshness import newest_vehicle_capture
from custom_components.audiconnect.v3.historical_catalog import ATTRIBUTES
from custom_components.audiconnect.v3.vehicle import V3Vehicle


def car():
    return V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")


def reading(value, stamp):
    return {
        "value": value,
        "captured": stamp.isoformat(),
        "observed": datetime.now(UTC).isoformat(),
        "status": "readable_but_stale",
        "family": "cariad",
    }


@pytest.mark.parametrize(
    "ident,value,expected",
    [
        ("left_front_door_open", False, False),
        ("right_rear_window_open", True, True),
        ("plugState", "connected", True),
        ("plugLockState", "locked", False),
    ],
)
def test_sleeping_binary_display_retains_actual_last_known(ident, value, expected):
    vehicle = car()
    row = reading(value, datetime.now(UTC) - timedelta(hours=7))
    vehicle.readings[ident] = row
    entity = V3ReadOnlyBinarySensor(
        NS(async_add_listener=lambda cb: None), vehicle, ATTRIBUTES[ident]
    )
    assert entity.available
    assert entity.is_on is expected
    assert entity.extra_state_attributes["vehicle_freshness"] == "stale_last_known"
    assert not _reading_available(row)
    row["status"] = "invalid_value"
    assert not entity.available


@pytest.mark.parametrize(
    "ident,value,available",
    [
        ("chargingState", "charging", True),
        ("chargingPower", 7.2, False),
        ("remainingChargingTime", 30, False),
        ("stateOfCharge", 80, True),
    ],
)
def test_charging_display_policy_is_not_command_policy(ident, value, available):
    vehicle = car()
    row = reading(value, datetime.now(UTC) - timedelta(hours=7))
    vehicle.readings[ident] = row
    entity = V3ReadOnlySensor(
        NS(async_add_listener=lambda cb: None), vehicle, ATTRIBUTES[ident]
    )
    assert entity.available is available
    assert not _reading_available(row)


def test_partial_access_does_not_discard_omitted_component_or_claim_safe():
    vehicle = car()
    profile = NS(attribute_routes={}, attribute_evidence={})
    now = datetime.now(UTC)
    old = now - timedelta(hours=7)
    vehicle.readings["left_front_door_open"] = reading(False, old)

    def observe(doors):
        observe_read_only(
            vehicle,
            profile,
            {
                "access": {
                    "accessStatus": {
                        "value": {
                            "carCapturedTimestamp": now.isoformat(),
                            "doors": doors,
                        }
                    }
                }
            },
            now,
        )

    observe([{"name": "frontRight", "status": ["closed", "locked"]}])
    assert vehicle.readings["left_front_door_open"]["captured"] == old.isoformat()
    assert vehicle.readings["left_front_door_open"]["value"] is False
    assert vehicle.readings["any_door_open"]["value"] is None
    observe([{"name": "frontLeft", "status": ["unknown"]}])
    assert vehicle.readings["left_front_door_open"]["status"] == "invalid_value"


def test_data_age_uses_capture_not_cloud_observation_or_invalid_future():
    vehicle = car()
    now = datetime.now(UTC)
    old = now - timedelta(hours=7, seconds=10)
    vehicle.readings["stateOfCharge"] = reading(80, old)
    vehicle.readings["chargingPower"] = reading(1, now + timedelta(hours=1))
    assert newest_vehicle_capture(vehicle, now) == old
    sensor = V3StatusSensor(NS(async_add_listener=lambda cb: None), vehicle, "age")
    assert sensor.native_value >= 420
    vehicle.readings["chargingState"] = reading("off", now)
    assert sensor.native_value == 0


def test_identity_refinement_retains_same_vehicle_measurements():
    from custom_components.audiconnect.v3.engine import V3Engine

    vehicle = car()
    vehicle.model_family = ""
    old_context = vehicle.context
    stamp = datetime.now(UTC) - timedelta(hours=7)
    vehicle.readings["stateOfCharge"] = reading(80, stamp)
    vehicle.model_family = "q8"
    seen = []
    profile = NS(rebind_context=seen.append)
    from custom_components.audiconnect.v3.status_engine import StatusEngine

    status = object.__new__(StatusEngine)
    status._trip_poll_at = {vehicle.vin.lower(): 10}
    engine = NS(status=status)
    V3Engine._rebind_identity_context(engine, vehicle, profile, old_context)
    assert seen == [vehicle.context]
    assert not status._trip_poll_at
    assert vehicle.readings["stateOfCharge"]["captured"] == stamp.isoformat()
    old_context = vehicle.context
    vehicle.country = "GB"
    V3Engine._rebind_identity_context(engine, vehicle, profile, old_context)
    assert not vehicle.readings


@pytest.mark.parametrize("initial", ["off", "heating"])
def test_climate_last_known_survives_sentinel_and_profile_reboot(initial):
    from pathlib import Path

    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    from custom_components.audiconnect.v3.entities import V3ClimateEntity
    from custom_components.audiconnect.v3.profile_store import restore_profile
    from custom_components.audiconnect.v3.registry import CapabilityRegistry

    vehicle = car()
    catalog = CapabilityRegistry.from_json_file(
        Path(__file__).resolve().parents[1]
        / "custom_components/audiconnect/v3/full_catalog.json"
    )
    profile = DevelopmentProfile(catalog, vehicle.context)
    now = datetime.now(UTC)

    def observe(state, captured):
        observe_read_only(
            vehicle,
            profile,
            {
                "climatisation": {
                    "climatisationStatus": {
                        "value": {
                            "carCapturedTimestamp": captured.isoformat(),
                            "climatisationState": state,
                        }
                    }
                }
            },
            now,
        )

    observe(initial, now - timedelta(hours=2))
    observe("unknown", now)
    saved = profile.snapshot()
    restored = restore_profile(catalog, vehicle.context, saved)
    rebooted = car()
    coordinator = NS(
        engine=NS(
            profiles={rebooted.vin.lower(): restored},
            control_enabled=lambda *args: True,
        ),
        last_update_success=True,
    )
    entity = V3ClimateEntity(coordinator, rebooted)
    assert entity.hvac_mode.value == ("off" if initial == "off" else "heat_cool")
    assert entity.hvac_action is None
    assert entity.extra_state_attributes["state_source"] == "last_known_vehicle"
    assert not entity.extra_state_attributes["state_is_current"]
    assert not rebooted.readings
    assert not restored.command_journal

    # A newer real observation supersedes the restored display.
    rebooted.set_climate(
        "off", now.isoformat(), route="test", observed_at=now, http_status=200
    )
    assert entity.hvac_mode.value == "off"
    assert entity.hvac_action.value == "off"
    assert entity.extra_state_attributes["state_is_current"]


def test_accepted_command_is_not_restored_as_verified_climate_state():
    from custom_components.audiconnect.v3.command_journal import CommandRecord
    from custom_components.audiconnect.v3.command_readback import (
        configure_readback,
        last_known_climate,
    )

    command = CommandRecord.begin(
        "climate", "start", "route", (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    )
    configure_readback(command, {})
    command.observe_http(200)
    profile = NS(command_journal=[command])
    assert last_known_climate(profile) == (None, None, "unknown")
    command.state = "verified"
    command.completed_at = command.started_at + 30
    value, _, source = last_known_climate(profile)
    assert value == "on" and source == "last_verified_command"
