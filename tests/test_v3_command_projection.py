"""Shared command projection, not fabricated physical state."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
import pytest
from custom_components.audiconnect.v3.command_journal import CommandRecord
from custom_components.audiconnect.v3.command_readback import (
    configure_readback,
)
from custom_components.audiconnect.v3.entities import _reading_projection

NOW = datetime.now(UTC)
OLD = NOW - timedelta(minutes=2)
NEW = NOW + timedelta(seconds=1)


def projected_state(profile, attribute, reported, captured, **_):
    key = "climatisationState" if attribute == "climate" else attribute
    vin = "test"
    vehicle = NS(
        vin=vin,
        readings={
            key: {
                "value": reported,
                "captured": captured.isoformat(),
                "status": "verified",
                "family": "cariad",
            }
        },
    )
    return _reading_projection(NS(engine=NS(profiles={vin: profile})), vehicle, key)


def record(cap, action, params=None, state="accepted_unconfirmed"):
    row = CommandRecord.begin(
        cap, action, "route", (NOW - timedelta(seconds=1)).timestamp()
    )
    row.state = state
    configure_readback(row, params or {})
    return row


@pytest.mark.parametrize(
    "cap,action,params,attribute,reported",
    [
        ("climate", "start", {}, "climate", "off"),
        ("climate", "stop", {}, "climate", "heating"),
        ("charging", "start", {}, "chargingState", "off"),
        ("climate", "window_heating_start", {}, "windowHeatingActive", False),
        ("climate", "preheater_stop", {}, "preheater_active", True),
        (
            "climate",
            "set_settings",
            {"windowHeatingEnabled": True},
            "climatisationWindowHeatingEnabled",
            False,
        ),
        ("charging", "set_target_soc", {"value": 80}, "targetstateOfCharge", 70),
        (
            "charging",
            "set_charge_mode",
            {"value": "timer"},
            "preferredChargeMode",
            "manual",
        ),
        ("access", "lock", {}, "doorLockStatus", "unlocked"),
    ],
)
def test_command_outcome_never_changes_vehicle_projection(
    cap, action, params, attribute, reported
):
    row = record(cap, action, params)
    profile = NS(command_journal=[row])
    for outcome in (
        "pending",
        "accepted_unconfirmed",
        "backend_completed",
        "uncertain",
        "rejected",
        "verified",
    ):
        row.state = outcome
        for stamp in (OLD, NEW):
            assert projected_state(profile, attribute, reported, stamp, now=NOW) == (
                reported,
                "vehicle",
            )
        assert projected_state(profile, attribute, None, OLD, now=NOW) == (
            None,
            "unknown",
        )


def test_stop_supersedes_start_but_other_cooldowns_remain():
    start = record("climate", "start")
    start.check_next(NOW.timestamp(), capability="climate", action="stop")
    for cap, action in [
        ("climate", "start"),
        ("charging", "stop"),
        ("access", "unlock"),
    ]:
        with pytest.raises(RuntimeError, match="cooldown"):
            start.check_next(NOW.timestamp(), capability=cap, action=action)
    start.state = "uncertain"
    with pytest.raises(RuntimeError, match="uncertain"):
        start.check_next(NOW.timestamp(), capability="climate", action="stop")
    start.state = "accepted_unconfirmed"
    stop = record("climate", "stop")
    profile = NS(command_journal=[start, stop])
    assert projected_state(profile, "climate", "heating", OLD, now=NOW) == (
        "heating",
        "vehicle",
    )
    with pytest.raises(RuntimeError, match="cooldown"):
        stop.check_next(NOW.timestamp(), capability="climate", action="start")


def test_restart_and_unrelated_commands_never_replay_or_replace_projection():
    start = record("climate", "start")
    charge = record("charging", "start")
    assert projected_state(
        NS(command_journal=[start, charge]), "climate", "off", OLD, now=NOW
    ) == ("off", "vehicle")
    restored = CommandRecord.restore(start.snapshot())
    assert projected_state(
        NS(command_journal=[restored]), "climate", "off", OLD, now=NOW
    ) == ("off", "vehicle")


def test_rejected_stop_does_not_revive_preceding_accepted_start():
    start = record("climate", "start")
    stop = record("climate", "stop", state="rejected")
    assert projected_state(
        NS(command_journal=[start, stop]), "climate", "off", OLD, now=NOW
    ) == ("off", "vehicle")


@pytest.mark.parametrize(
    "cap,action", [("climate", "start"), ("charging", "start"), ("access", "lock")]
)
def test_normal_command_cooldown_expires_after_ten_seconds(cap, action):
    from custom_components.audiconnect.v3.command_journal import check_command_sequence

    start = CommandRecord.begin("climate", "start", "cariad.climate.start.stored", 1000)
    start.state = "backend_completed"
    profile = NS(last_command=start, command_journal=[start])
    with pytest.raises(RuntimeError, match="try again in 1s"):
        check_command_sequence(profile, 1009, capability=cap, action=action)
    check_command_sequence(profile, 1010, capability=cap, action=action)
    start.state = "uncertain"
    if cap == "climate":
        with pytest.raises(RuntimeError, match="uncertain"):
            check_command_sequence(profile, 1020, capability=cap, action=action)
    check_command_sequence(profile, 1100, capability=cap, action=action)


def test_readback_selection_does_not_revive_rejected_predecessor():
    from custom_components.audiconnect.v3.command_readback import (
        latest_readback_command,
    )

    start = record("climate", "start")
    engineering = record("climate", "stop")
    engineering.origin = "workbench"
    rejected = record("climate", "stop", state="rejected")
    profile = NS(command_journal=[start, engineering, rejected])
    assert latest_readback_command(profile, "climate") is rejected
    assert projected_state(profile, "climate", "off", OLD, now=NOW) == (
        "off",
        "vehicle",
    )


@pytest.mark.parametrize(
    "value,expected",
    [("off", True), ("unknown", False), ("heating", False), (None, False)],
)
def test_guided_readback_only_uses_known_changed_comfort_state(value, expected):
    from custom_components.audiconnect.v3.command_readback import (
        configure_discovery_readback,
    )

    car = NS(
        readings={
            "climatisationState": {
                "value": value,
                "captured": NOW.isoformat(),
                "observed": NOW.isoformat(),
                "family": "cariad",
            }
        }
    )
    row = CommandRecord.begin("climate", "start", "route", NOW.timestamp())
    configure_discovery_readback(row, car, {})
    assert bool(row.readback_attribute) is expected


def test_access_mismatch_releases_only_accepted_command_with_new_evidence():
    from custom_components.audiconnect.v3.command_readback import (
        reconcile_access_mismatch,
        reconcile_readback,
    )

    row = record("access", "lock")
    row.started_at = (NOW - timedelta(minutes=3)).timestamp()
    row.observe_http(200)
    car = NS(
        readings={
            "doorLockStatus": {
                "value": "unlocked",
                "captured": (NOW - timedelta(minutes=4)).isoformat(),
                "observed": NOW.isoformat(),
            }
        }
    )
    assert not row.requires_review
    assert not reconcile_access_mismatch(row, car, NOW)
    car.readings["doorLockStatus"]["captured"] = NOW.isoformat()
    assert not reconcile_readback(row, car, NOW)
    row.backend_result = "transport_uncertain"
    assert not reconcile_access_mismatch(row, car, NOW)
    row.backend_result = "accepted_unconfirmed"
    assert reconcile_access_mismatch(row, car, NOW)
    assert row.state == "accepted_unconfirmed"
    assert row.readback_mismatch_at == NOW.timestamp()
    assert not row.requires_review
    restored = CommandRecord.restore(row.snapshot())
    assert restored.state == "accepted_unconfirmed"
    assert restored.readback_mismatch_at == NOW.timestamp()
    assert projected_state(
        NS(command_journal=[row]),
        "doorLockStatus",
        "unlocked",
        NOW,
        now=NOW,
        optimistic=False,
    ) == ("unlocked", "vehicle")


def test_lock_transition_expires_without_fabricating_physical_state():
    row = record("access", "unlock")
    row.observe_http(200)
    profile = NS(command_journal=[row])
    from custom_components.audiconnect.v3.product_contract import control_projection

    reading = {"value": "locked", "captured": OLD.isoformat()}
    assert control_projection(profile, "doorLockStatus", reading, now=NOW) == (
        "unlocked",
        "optimistic",
    )
    assert control_projection(
        profile, "doorLockStatus", {**reading, "captured": NEW.isoformat()}, now=NEW
    ) == ("locked", "vehicle")
    assert control_projection(
        profile, "doorLockStatus", reading, now=NOW + timedelta(minutes=30)
    ) == ("locked", "vehicle")
    assert projected_state(profile, "doorLockStatus", "locked", OLD, now=NOW) == (
        "unlocked",
        "optimistic",
    )


@pytest.mark.parametrize(
    "cap,action,attribute,value",
    [
        ("charging", "start", "chargingState", "charging"),
        ("access", "lock", "doorLockStatus", "locked"),
        ("climate", "start", "climatisationState", "heating"),
    ],
)
def test_data_act_never_verifies_command_even_with_fresh_capture(
    cap, action, attribute, value
):
    from custom_components.audiconnect.v3.command_readback import reconcile_readback

    row = record(cap, action)
    car = NS(
        readings={
            attribute: {
                "value": value,
                "captured": NOW.isoformat(),
                "observed": NOW.isoformat(),
                "family": "eu_data_act",
            }
        },
        climate_state=value,
        climate_captured=NOW,
    )
    assert not reconcile_readback(row, car, NOW)
    assert row.state == "accepted_unconfirmed"
    car.readings[attribute]["family"] = "cariad"
    assert reconcile_readback(row, car, NOW)


def test_display_source_does_not_hide_native_command_evidence():
    from custom_components.audiconnect.v3.command_readback import reconcile_readback

    row = record("charging", "start")
    native = {
        "value": "charging",
        "family": "cariad",
        "captured": NOW.isoformat(),
        "observed": NOW.isoformat(),
    }
    display = {
        "value": "off",
        "family": "eu_data_act",
        "captured": (NOW + timedelta(seconds=1)).isoformat(),
    }
    car = NS(
        readings={"chargingState": display},
        family_readings={"chargingState": {"cariad": native, "eu_data_act": display}},
    )
    assert reconcile_readback(row, car, NOW)
    assert car.readings["chargingState"] is display


@pytest.mark.parametrize("receipt", [None, OLD.isoformat()])
def test_command_requires_post_dispatch_receipt(receipt):
    from custom_components.audiconnect.v3.command_readback import reconcile_readback

    row = record("access", "lock")
    car = NS(
        readings={
            "doorLockStatus": {
                "value": "locked",
                "family": "cariad",
                "captured": NOW.isoformat(),
                "observed": receipt,
            }
        }
    )
    assert not reconcile_readback(row, car, NOW)
    car.readings["doorLockStatus"]["observed"] = NOW.isoformat()
    assert reconcile_readback(row, car, NOW)


def test_command_response_publishes_real_capture_without_poll_or_request_echo():
    from custom_components.audiconnect.v3.command_readback import (
        observe_command_response,
    )
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    from custom_components.audiconnect.v3.freshness import (
        reading_freshness_attributes,
        vehicle_capture_summary,
    )
    from custom_components.audiconnect.v3.registry import CapabilityRegistry
    from custom_components.audiconnect.v3.runtime import catalog_path
    from custom_components.audiconnect.v3.vehicle import V3Vehicle

    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "", "", "BE")
    profile = DevelopmentProfile(
        CapabilityRegistry.from_json_file(catalog_path()), car.context
    )
    row = record("access", "unlock")
    row.operation = "cariad.access.unlock"
    response = NS(
        status=200,
        observed_at=NEW,
        data={
            "access": {
                "accessStatus": {
                    "value": {
                        "doorLockStatus": "unlocked",
                        "carCapturedTimestamp": NEW.isoformat(),
                    }
                }
            },
            "charging": {
                "batteryStatus": {
                    "value": {
                        "currentSOC_pct": 95,
                        "carCapturedTimestamp": NEW.isoformat(),
                    }
                },
                "chargingStatus": {
                    "value": {"chargingState": "charging"},
                    "requests": [{"status": "successful"}],
                },
            },
            "climatisation": {
                "climatisationStatus": {
                    "value": {
                        "climatisationState": "heating",
                        "carCapturedTimestamp": OLD.isoformat(),
                    }
                }
            },
        },
    )
    assert observe_command_response(row, car, profile, "cariad", response)
    assert row.state == "accepted_unconfirmed"
    assert row.readback_observed_at == NEW.timestamp()
    assert car.readings["doorLockStatus"]["value"] == "unlocked"
    assert car.readings["stateOfCharge"]["value"] == 95
    assert "chargingState" not in car.readings
    # A genuine earlier vehicle capture is still telemetry, not proof of
    # the just-issued command. The canonical writer rejects older duplicates.
    assert car.readings["climatisationState"]["captured"] == OLD.isoformat()
    assert car.readings["climatisationState"]["value"] == "heating"
    assert car.readings["last_update_time"]["value"] == NEW.isoformat()
    assert not car.v2_initial_discovery_completed
    attrs = reading_freshness_attributes(car.readings["stateOfCharge"], now=NEW)
    assert attrs["source_operation"] == "cariad.access.unlock"
    assert attrs["vehicle_captured"] == NEW.isoformat()
    assert attrs["vehicle_freshness"] == "fresh"
    summary = vehicle_capture_summary(car, NEW)
    assert summary["vehicle_age_minutes"] == 0
    assert summary["source_operation"] == "cariad.access.unlock"
    response.data = {
        "access": {"accessStatus": {"requests": [{"status": "successful"}]}}
    }
    response.observed_at = NEW + timedelta(minutes=2)
    assert not observe_command_response(row, car, profile, "cariad", response)
    assert car.readings["last_update_time"]["value"] == NEW.isoformat()


def test_manual_stop_after_failed_remote_stop_is_not_command_success():
    from custom_components.audiconnect.v3.command_readback import reconcile_readback

    row = record("charging", "stop")
    row.observe_http(200)
    car = NS(
        readings={
            "chargingState": {
                "value": "readyForCharging",
                "captured": NEW.isoformat(),
                "observed": NEW.isoformat(),
                "family": "cariad",
            }
        }
    )
    assert reconcile_readback(row, car, NEW)
    assert row.state == "accepted_unconfirmed"
    assert row.readback_observed_at == NEW.timestamp()
    row.observe_backend("rejected", NEW.timestamp())
    assert row.state == "rejected"
    assert row.backend_result == "rejected"
    assert not reconcile_readback(row, car, NEW)
    assert CommandRecord.restore(row.snapshot()).state == "rejected"
    # Reversing delivery order preserves the same terminal outcome and evidence.
    other = record("charging", "stop")
    other.observe_http(200)
    other.observe_backend("rejected", NEW.timestamp())
    assert reconcile_readback(other, car, NEW)
    assert other.state == row.state
    assert other.backend_result == row.backend_result
    assert other.readback_observed_at == row.readback_observed_at


@pytest.mark.parametrize(
    "cap,action,params,attribute,reported,requested",
    [
        ("access", "unlock", {}, "doorLockStatus", "locked", "unlocked"),
        ("access", "lock", {}, "doorLockStatus", "unlocked", "locked"),
        ("climate", "start", {}, "climate", "off", "on"),
        ("climate", "preheater_stop", {}, "preheater_active", True, False),
        ("charging", "set_target_soc", {"value": 80}, "targetstateOfCharge", 70, 80),
        (
            "charging",
            "set_charge_mode",
            {"value": "timer"},
            "preferredChargeMode",
            "manual",
            "timer",
        ),
        (
            "climate",
            "set_settings",
            {"windowHeatingEnabled": True},
            "climatisationWindowHeatingEnabled",
            False,
            True,
        ),
    ],
)
def test_accepted_control_projection_expires_and_newer_observation_wins(
    cap, action, params, attribute, reported, requested
):
    from custom_components.audiconnect.v3.command_readback import OPTIMISTIC_TTL_SECONDS
    from custom_components.audiconnect.v3.product_contract import control_projection

    command = record(cap, action, params)
    command.observe_http(200)
    profile = NS(command_journal=[command])
    reading = {
        "value": reported,
        "captured": OLD.isoformat(),
        "status": "verified",
    }
    assert control_projection(profile, attribute, reading, now=NOW) == (
        requested,
        "optimistic",
    )
    assert control_projection(
        profile, attribute, {**reading, "captured": NEW.isoformat()}, now=NEW
    ) == (reported, "vehicle")
    expiry = datetime.fromtimestamp(command.started_at + OPTIMISTIC_TTL_SECONDS, UTC)
    assert control_projection(profile, attribute, reading, now=expiry) == (
        reported,
        "vehicle",
    )
    command.observe_backend("rejected", NOW.timestamp())
    assert control_projection(profile, attribute, reading, now=NOW) == (
        reported,
        "vehicle",
    )


@pytest.mark.parametrize(
    "action,reported,new_state",
    [("stop", "charging", "off"), ("start", "off", "charging")],
)
def test_charging_intent_never_replaces_reported_state(action, reported, new_state):
    from custom_components.audiconnect.v3.product_contract import control_projection

    command = record("charging", action)
    command.observe_http(200)
    profile = NS(command_journal=[command])
    reading = {
        "value": reported,
        "captured": OLD.isoformat(),
        "status": "verified",
    }
    assert control_projection(profile, "chargingState", reading, now=NOW) == (
        reported,
        "last_known_vehicle",
    )
    assert control_projection(profile, "chargingState", {}, now=NOW) == (
        None,
        "unknown",
    )
    assert control_projection(
        profile,
        "chargingState",
        {**reading, "value": new_state, "captured": NEW.isoformat()},
        now=NEW,
    ) == (new_state, "vehicle")


def test_sleeping_lock_retains_last_observation_and_explicit_reverse_dispatch():
    import asyncio
    from unittest.mock import AsyncMock

    from custom_components.audiconnect.v3.entities import V3LockEntity

    vehicle = NS(
        vin="test",
        inventory_present=True,
        readings={
            "doorLockStatus": {
                "value": "locked",
                "captured": (NOW - timedelta(minutes=142)).isoformat(),
                "status": "readable_but_stale",
            }
        },
    )
    command = record("access", "unlock")
    command.observe_http(200)
    engine = NS(
        profiles={"test": NS(command_journal=[command])},
        control_enabled=lambda *args: True,
        auth=NS(spin="1234"),
        send_control=AsyncMock(),
    )
    entity = V3LockEntity(NS(engine=engine, last_update_success=True), vehicle)
    assert entity.is_locked is False
    entity._send_access = AsyncMock()
    asyncio.run(entity.async_lock())
    entity._send_access.assert_awaited_once_with("lock")
    command.state = "rejected"
    assert entity.is_locked is True
    assert entity.extra_state_attributes["state_source"] == "last_known_vehicle"
    assert entity.extra_state_attributes["last_reported_state"] == "locked"


def test_restart_never_reactivates_optimistic_state():
    from custom_components.audiconnect.v3.product_contract import control_projection

    command = record("access", "unlock")
    command.observe_http(200)
    restored = CommandRecord.restore(command.snapshot())
    reading = {
        "value": "locked",
        "captured": OLD.isoformat(),
        "status": "verified",
    }
    assert control_projection(
        NS(command_journal=[restored]), "doorLockStatus", reading, now=NOW
    ) == ("locked", "vehicle")
