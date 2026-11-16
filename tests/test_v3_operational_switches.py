"""Stateful controls: actual evidence and bounded command projection."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import asyncio
import pytest

from custom_components.audiconnect.v3.vehicle import (
    V3Vehicle,
    charging_active,
    window_heating_active,
)
from custom_components.audiconnect.v3.derived_values import observe_derived
from custom_components.audiconnect.v3.attribute_runtime import _accept_observation
from custom_components.audiconnect.v3.entities import V3OperationalSwitch, V3ModelSensor
from custom_components.audiconnect.v3.product_contract import (
    stateful_control_supported,
    superseded_control_button,
)
from custom_components.audiconnect.v3.command_readback import (
    configure_readback,
    reconcile_readback,
)

VIN = "WAUZZZ4M0MD123456"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("charging", True),
        ("notReadyForCharging", False),
        ("readyForCharging", False),
        ("off", False),
        ("invalid", None),
        ("unsupported", None),
        ("error", None),
        (True, None),
    ],
)
def test_charging_normalization(raw, expected):
    assert charging_active(raw) is expected


def windows(front, rear):
    return [
        {"windowLocation": "front", "windowHeatingState": front},
        {"windowLocation": "rear", "windowHeatingState": rear},
    ]


def test_window_settings_do_not_define_operational_state():
    assert window_heating_active(windows("off", "off")) is False
    assert window_heating_active(windows("on", "invalid")) is True
    assert window_heating_active(windows("off", "invalid")) is None
    assert window_heating_active(windows("invalid", "invalid")) is None
    assert window_heating_active(windows("off", "off")[:1]) is None
    assert (
        window_heating_active(
            [{"windowLocation": "front", "windowHeatingState": "off"}] * 2
        )
        is None
    )
    car = V3Vehicle(VIN, "Audi", "Audi Q8", "q8", "DE")
    now = datetime.now(UTC)

    def observe(rows, stamp):
        observe_derived(
            car,
            NS(),
            {
                "climatisation": {
                    "climatisationSettings": {"value": {"windowHeatingEnabled": True}},
                    "windowHeatingStatus": {
                        "value": {
                            "carCapturedTimestamp": stamp.isoformat(),
                            "windowHeatingStatus": rows,
                        }
                    },
                }
            },
            now,
            _accept_observation,
        )

    observe(windows("off", "off"), now)
    assert car.readings["windowHeatingActive"]["value"] is False
    observe(windows("invalid", "invalid"), now + timedelta(seconds=1))
    assert car.readings["windowHeatingActive"]["value"] is None
    observe(windows("on", "off"), now - timedelta(minutes=1))
    assert car.readings["windowHeatingActive"]["value"] is None


@pytest.mark.parametrize(
    "key,reading,capability,on,off,button,raw",
    [
        (
            "charging",
            "chargingState",
            "charging",
            "start",
            "stop",
            "start_charging_modern",
            "notReadyForCharging",
        ),
        (
            "window_heating",
            "windowHeatingActive",
            "climate",
            "window_heating_start",
            "window_heating_stop",
            "start_window_heating_modern",
            False,
        ),
    ],
)
def test_switch_projection_and_actions(key, reading, capability, on, off, button, raw):
    car = V3Vehicle(VIN, "Audi", "Audi Q8", "q8", "DE")
    enabled = {on, off}
    engine = NS(
        control_enabled=lambda vin, action, cap: (
            cap == capability and action in enabled
        ),
        send_control=AsyncMock(),
        profiles={},
    )
    co = NS(engine=engine, last_update_success=True, async_add_listener=lambda cb: None)
    assert not stateful_control_supported(engine, car, key)
    now = datetime.now(UTC)
    car.readings[reading] = {
        "value": raw,
        "status": "verified",
        "captured": now.isoformat(),
    }
    assert stateful_control_supported(engine, car, key)
    assert superseded_control_button(engine, car, "button." + button)
    switch = V3OperationalSwitch(co, car, key)
    switch.async_write_ha_state = lambda: None
    assert switch.is_on is False and switch.available
    asyncio.run(switch.async_turn_on())
    engine.send_control.assert_awaited_once_with(VIN, on, capability)
    assert switch.is_on is False  # no optimistic mutation of actual status
    from custom_components.audiconnect.v3.command_journal import CommandRecord

    car.readings[reading]["captured"] = (now - timedelta(seconds=2)).isoformat()
    command = CommandRecord.begin(capability, on, "route", now.timestamp() - 1)
    command.state = "accepted_unconfirmed"
    configure_readback(command, {})
    engine.profiles[VIN.lower()] = NS(command_journal=[command])
    assert switch.is_on is False
    assert switch.extra_state_attributes["state_source"] == "vehicle"
    assert switch.extra_state_attributes["state_is_optimistic"] is False
    assert switch.extra_state_attributes["last_reported_state"] is False
    enabled.remove(on)
    assert not stateful_control_supported(engine, car, key)
    assert not switch.available
    assert not superseded_control_button(engine, car, "button." + button)
    for action in (switch.async_turn_on, switch.async_turn_off):
        with pytest.raises(Exception, match="Vehicle action unavailable"):
            asyncio.run(action())
    # A single eligible direction belongs to its independent command button.
    assert engine.control_enabled(VIN, off, capability)


def test_window_command_readback_rejects_precommand_and_numeric_values():
    car = V3Vehicle(VIN, "Audi", "Audi Q8", "q8", "DE")
    now = datetime.now(UTC)
    rec = NS(
        capability="climate",
        action="window_heating_stop",
        state="accepted_unconfirmed",
        started_at=(now - timedelta(seconds=5)).timestamp(),
        readback_attribute=None,
        readback_values=[],
    )
    configure_readback(rec, {})
    car.readings["windowHeatingActive"] = {
        "value": False,
        "captured": (now - timedelta(seconds=10)).isoformat(),
    }
    assert not reconcile_readback(rec, car, now)
    car.readings["windowHeatingActive"] = {
        "value": 0,
        "captured": now.isoformat(),
        "observed": now.isoformat(),
    }
    assert not reconcile_readback(rec, car, now)
    car.readings["windowHeatingActive"]["value"] = False
    assert reconcile_readback(rec, car, now)


@pytest.mark.parametrize(
    "media,expected,family,source",
    [
        (
            {"longName": "Audi Q8 TFSI e", "shortName": "Q8"},
            "Audi Q8 TFSI e",
            "q8",
            "audi_long_name",
        ),
        (
            {"longName": 123, "shortName": "Q4 e-tron"},
            "Q4 e-tron",
            "q4",
            "audi_short_name",
        ),
        ({"longName": "Audi A6 Avant"}, "Audi A6 Avant", "a6", "audi_long_name"),
        ({}, "", "", ""),
    ],
)
def test_model_inventory_not_nickname(media, expected, family, source):
    car = V3Vehicle.from_graphql(
        {
            "vin": VIN,
            "nickname": "Q8",
            "vehicle": {
                "media": media,
                "core": {"modelYear": 2025},
                "classification": {"driveTrain": "hybrid"},
            },
        },
        "DE",
    )
    assert (car.model, car.model_family, car.model_source) == (expected, family, source)
    assert car.name == "Q8" and car.model_year == "2025"
    entity = V3ModelSensor(NS(async_add_listener=lambda cb: None), car)
    assert entity.native_value == (expected or None)
    assert entity.available is bool(expected)


def test_window_readback_survives_journal_restore():
    from custom_components.audiconnect.v3.command_journal import CommandRecord

    rec = CommandRecord.begin(
        "climate",
        "window_heating_stop",
        "cariad.climate.window_heating_stop",
        datetime.now(UTC).timestamp(),
    )
    configure_readback(rec, {})
    restored = CommandRecord.restore(rec.snapshot())
    assert restored.readback_attribute == "windowHeatingActive"
    assert restored.readback_values == [False]
    assert restored.state == "uncertain"


def test_platform_discovers_switch_after_state_and_both_commands_are_observed():
    from custom_components.audiconnect.v3.ha_platforms import setup

    car = V3Vehicle(VIN, "Audi", "Audi Q8", "q8", "DE")
    enabled = set()
    engine = NS(
        vehicles={VIN.lower(): car},
        profiles={},
        control_enabled=lambda vin, action, cap="climate": (cap, action) in enabled,
    )
    offered, listeners = [], []
    co = NS(
        engine=engine,
        last_update_success=True,
        async_add_listener=lambda cb: listeners.append(cb),
    )
    entry = NS(
        entry_id="entry",
        runtime_data=NS(v3=engine, coordinator=co),
        async_on_unload=lambda cb: None,
    )
    setup("switch", entry, offered.extend)
    assert not offered
    enabled.update({("charging", "start"), ("charging", "stop")})
    listeners[0]()
    assert not offered
    car.readings["chargingState"] = {
        "value": "charging",
        "status": "verified",
        "captured": datetime.now(UTC).isoformat(),
    }
    listeners[0]()
    listeners[0]()
    assert [entity.unique_id for entity in offered] == [
        VIN.lower() + "_switch_charging"
    ]
    assert offered[0].is_on is True
    offered[0].platform_data = NS(
        platform_name="audiconnect",
        domain="switch",
        component_translations={},
        platform_translations={
            "component.audiconnect.entity.switch.v3_charging.name": "Laden"
        },
    )
    assert offered[0].entity_description.name == "Charging"
    assert offered[0].name == "Laden"


def test_charging_stop_projects_temporary_intent_and_retains_reported_state():
    from custom_components.audiconnect.v3.command_journal import CommandRecord

    car = V3Vehicle(VIN, "Audi", "", "", "DE")
    now = datetime.now(UTC)
    command = CommandRecord.begin(
        "charging", "stop", "cariad.charging.stop", now.timestamp() - 5
    )
    command.observe_http(200)
    configure_readback(command, {})
    engine = NS(
        control_enabled=lambda *args: True,
        profiles={VIN.lower(): NS(command_journal=[command])},
    )
    co = NS(engine=engine, last_update_success=True, async_add_listener=lambda cb: None)
    row = {
        "value": "charging",
        "status": "verified",
        "family": "cariad",
        "captured": (now - timedelta(seconds=10)).isoformat(),
        "observed": now.isoformat(),
    }
    car.readings["chargingState"] = row
    switch = V3OperationalSwitch(co, car, "charging")
    assert switch.available
    assert switch.is_on is False
    assert switch.assumed_state
    attrs = switch.extra_state_attributes
    assert attrs["last_reported_state"] is True
    assert attrs["command_status"] == "accepted_unconfirmed"
    assert attrs["command_requested_state"] == "off"
    assert attrs["state_source"] == "optimistic"
    assert attrs["state_is_optimistic"] is True
    row["captured"] = now.isoformat()
    assert switch.is_on is True
    assert not reconcile_readback(command, car, now)
    row["value"] = "readyForCharging"
    assert reconcile_readback(command, car, now)
    assert command.state == "accepted_unconfirmed"
    assert command.readback_observed_at == now.timestamp()
    assert switch.is_on is False
    # An invalid current reading must preserve the real post-command capture.
    car.readings["chargingState"] = {
        "value": None,
        "status": "invalid_value",
        "family": "cariad",
        "last_known": dict(row),
    }
    assert switch.is_on is False
    assert switch.extra_state_attributes["last_reported_state"] is False


def test_charging_request_feedback_is_informational_not_vehicle_capture():
    from custom_components.audiconnect.v3.structured_details import observe_structured
    from custom_components.audiconnect.v3.command_journal import CommandRecord

    car = V3Vehicle(VIN, "Audi", "", "", "DE")
    now = datetime.now(UTC)
    command = CommandRecord.begin(
        "charging", "stop", "cariad.charging.stop", now.timestamp() - 5
    )
    command.observe_http(200)
    configure_readback(command, {})
    engine = NS(
        control_enabled=lambda *args: True,
        profiles={VIN.lower(): NS(command_journal=[command])},
    )
    co = NS(engine=engine, last_update_success=True, async_add_listener=lambda cb: None)
    car.readings["chargingState"] = {
        "value": "charging",
        "status": "verified",
        "family": "cariad",
        "captured": (now - timedelta(seconds=10)).isoformat(),
        "observed": now.isoformat(),
    }
    observe_structured(
        car,
        {
            "charging": {
                "chargingStatus": {
                    "requests": [
                        {
                            "operation": "stop",
                            "status": "failed",
                            "private": "not-retained",
                        }
                    ]
                }
            }
        },
        now,
        _accept_observation,
    )
    switch = V3OperationalSwitch(co, car, "charging")
    detail = switch.extra_state_attributes["charging_requests"]
    assert detail["data"]["items"] == [{"operation": "stop", "status": "failed"}]
    assert car.readings["charging_requests_detail"]["captured"] is None
    assert command.state == "accepted_unconfirmed"
    assert switch.is_on is False
    assert switch.extra_state_attributes["state_source"] == "optimistic"
    assert switch.extra_state_attributes["last_reported_state"] is True
    assert not reconcile_readback(command, car, now)


def test_switch_display_and_metadata_share_retained_source_selection():
    car = V3Vehicle(VIN, "Audi", "Audi Q8", "q8", "DE")
    now = datetime.now(UTC)
    old = (now - timedelta(hours=2)).isoformat()
    recent = (now - timedelta(minutes=2)).isoformat()
    current = {
        "value": "off",
        "captured": old,
        "family": "eu_data_act",
        "status": "readable_but_stale",
    }
    native = {
        "value": None,
        "captured": now.isoformat(),
        "family": "cariad",
        "status": "invalid_value",
        "last_known": {
            "value": "charging",
            "captured": recent,
            "family": "cariad",
            "status": "verified",
        },
    }
    car.readings["chargingState"] = current
    car.family_readings["chargingState"] = {"cariad": native, "eu_data_act": current}
    engine = NS(control_enabled=lambda *args: True, profiles={})
    co = NS(engine=engine, last_update_success=True)
    switch = V3OperationalSwitch(co, car, "charging")
    assert switch.is_on is True
    attrs = switch.extra_state_attributes
    assert attrs["last_reported_state"] is True
    assert attrs["vehicle_captured"] == recent
    assert attrs["state_source"] == "last_known_vehicle"
    assert car.readings["chargingState"] is current


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["setting", "target"])
async def test_expired_setting_remains_explicitly_writable(kind):
    from custom_components.audiconnect.v3.command_journal import CommandRecord
    from custom_components.audiconnect.v3.entities import (
        V3ChargeTargetNumber,
        V3ClimateSettingSwitch,
    )

    car = V3Vehicle(VIN, "Audi", "", "", "DE")
    now = datetime.now(UTC)
    if kind == "setting":
        capability, action = "climate", "set_settings"
        ident, old, params = (
            "climatisationWindowHeatingEnabled",
            False,
            {"windowHeatingEnabled": True},
        )
    else:
        capability, action = "charging", "set_target_soc"
        ident, old, params = "targetstateOfCharge", 70, {"value": 80}
    command = CommandRecord.begin(capability, action, "route", now.timestamp() - 600)
    configure_readback(command, params)
    command.observe_http(200)
    car.readings[ident] = {
        "value": old,
        "family": "cariad",
        "captured": (now - timedelta(minutes=20)).isoformat(),
        "status": "verified",
    }
    engine = NS(
        control_enabled=lambda *args, params=None: (
            params is None
            or params
            in (
                {"windowHeatingEnabled": False},
                {"windowHeatingEnabled": True},
            )
        ),
        profiles={VIN.lower(): NS(command_journal=[command])},
        send_control=AsyncMock(),
        send_setting=AsyncMock(),
    )
    co = NS(engine=engine, last_update_success=True, async_add_listener=lambda cb: None)
    if kind == "setting":
        entity = V3ClimateSettingSwitch(
            co, car, ("climatisation_window_heating", ident, "windowHeatingEnabled")
        )
        assert entity.is_on is None
        assert entity.available
        proven = engine.control_enabled
        engine.control_enabled = lambda *args, params=None: params is None
        assert not entity.available
        assert not entity.extra_state_attributes["control_actions"]["set_settings"]
        engine.control_enabled = proven
        assert entity.available
        entity.async_write_ha_state = lambda: None
        await entity.async_turn_off()
        engine.send_control.assert_awaited_once_with(
            VIN, "set_settings", "climate", params={"windowHeatingEnabled": False}
        )
    else:
        entity = V3ChargeTargetNumber(co, car)
        assert entity.native_value is None
        assert entity.available
        entity.async_write_ha_state = lambda: None
        await entity.async_set_native_value(75)
        engine.send_setting.assert_awaited_once_with(VIN, "set_target_soc", 75)
    car.readings.clear()
    assert not entity.available
