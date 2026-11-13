"""Shared command projection, not fabricated physical state."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
import pytest
from custom_components.audiconnect.v3.command_journal import CommandRecord
from custom_components.audiconnect.v3.command_readback import (
    configure_readback,
    projected_state,
)

NOW = datetime.now(UTC)
OLD = NOW - timedelta(minutes=2)
NEW = NOW + timedelta(seconds=1)


def record(cap, action, params=None, state="accepted_unconfirmed"):
    row = CommandRecord.begin(
        cap, action, "route", (NOW - timedelta(seconds=1)).timestamp()
    )
    row.state = state
    configure_readback(row, params or {})
    return row


@pytest.mark.parametrize(
    "cap,action,params,attribute,reported,expected",
    [
        ("climate", "start", {}, "climate", "off", "on"),
        ("climate", "stop", {}, "climate", "heating", "off"),
        ("charging", "start", {}, "chargingState", "off", "charging"),
        ("climate", "window_heating_start", {}, "windowHeatingActive", False, True),
        ("climate", "preheater_stop", {}, "preheater_active", True, False),
        (
            "climate",
            "set_settings",
            {"windowHeatingEnabled": True},
            "climatisationWindowHeatingEnabled",
            False,
            True,
        ),
        ("charging", "set_target_soc", {"value": 80}, "targetstateOfCharge", 70, 80),
        (
            "charging",
            "set_charge_mode",
            {"value": "timer"},
            "preferredChargeMode",
            "manual",
            "timer",
        ),
    ],
)
def test_accepted_projection_reconciles_even_contradictory_new_data(
    cap, action, params, attribute, reported, expected
):
    row = record(cap, action, params)
    profile = NS(command_journal=[row])
    assert projected_state(profile, attribute, reported, OLD, now=NOW) == (
        expected,
        "command_pending",
    )
    assert projected_state(profile, attribute, reported, NEW, now=NEW) == (
        reported,
        "vehicle",
    )
    assert row.state == "accepted_unconfirmed"
    assert projected_state(
        profile, attribute, reported, OLD, now=NOW + timedelta(minutes=31)
    ) == (None, "unknown")
    row.state = "uncertain"
    assert projected_state(profile, attribute, reported, OLD, now=NOW) == (
        None,
        "unknown",
    )
    row.state = "rejected"
    assert projected_state(profile, attribute, reported, OLD, now=NOW) == (
        reported,
        "vehicle",
    )


def test_security_sensitive_lock_does_not_claim_locked():
    row = record("access", "lock")
    profile = NS(command_journal=[row])
    assert projected_state(
        profile, "doorLockStatus", "unlocked", OLD, now=NOW, optimistic=False
    ) == (None, "command_pending")
    assert projected_state(
        profile, "doorLockStatus", "unlocked", NEW, now=NEW, optimistic=False
    ) == ("unlocked", "vehicle")


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
        "off",
        "command_pending",
    )
    with pytest.raises(RuntimeError, match="cooldown"):
        stop.check_next(NOW.timestamp(), capability="climate", action="start")


def test_restart_and_unrelated_commands_never_replay_or_replace_projection():
    start = record("climate", "start")
    charge = record("charging", "start")
    assert projected_state(
        NS(command_journal=[start, charge]), "climate", "off", OLD, now=NOW
    ) == ("on", "command_pending")
    restored = CommandRecord.restore(start.snapshot())
    assert projected_state(
        NS(command_journal=[restored]), "climate", "off", OLD, now=NOW
    ) == (None, "unknown")


def test_rejected_stop_preserves_preceding_accepted_start():
    start = record("climate", "start")
    stop = record("climate", "stop", state="rejected")
    assert projected_state(
        NS(command_journal=[start, stop]), "climate", "off", OLD, now=NOW
    ) == ("on", "command_pending")


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


def test_readback_selection_ignores_workbench_and_rejected_actions():
    from custom_components.audiconnect.v3.command_readback import (
        latest_readback_command,
    )

    start = record("climate", "start")
    engineering = record("climate", "stop")
    engineering.origin = "workbench"
    rejected = record("climate", "stop", state="rejected")
    profile = NS(command_journal=[start, engineering, rejected])
    assert latest_readback_command(profile, "climate") is start
    assert projected_state(profile, "climate", "off", OLD, now=NOW) == (
        "on",
        "command_pending",
    )


@pytest.mark.parametrize(
    "value,expected",
    [("off", True), ("unknown", False), ("heating", False), (None, False)],
)
def test_guided_readback_only_uses_known_changed_comfort_state(value, expected):
    from custom_components.audiconnect.v3.command_readback import (
        configure_discovery_readback,
    )

    car = NS(climate_state=value, climate_captured=NOW, readings={})
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
            }
        }
    )
    assert row.requires_review
    assert not reconcile_access_mismatch(row, car, NOW)
    car.readings["doorLockStatus"]["captured"] = NOW.isoformat()
    assert not reconcile_readback(row, car, NOW)
    row.backend_result = "transport_uncertain"
    assert not reconcile_access_mismatch(row, car, NOW)
    row.backend_result = "accepted_unconfirmed"
    assert reconcile_access_mismatch(row, car, NOW)
    assert row.state == "readback_mismatch"
    assert not row.requires_review
    assert CommandRecord.restore(row.snapshot()).state == "readback_mismatch"
    assert projected_state(
        NS(command_journal=[row]),
        "doorLockStatus",
        "unlocked",
        NOW,
        now=NOW,
        optimistic=False,
    ) == ("unlocked", "vehicle")
