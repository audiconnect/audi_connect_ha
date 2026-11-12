"""One command execution history for both normal and engineering actions."""

from pathlib import Path

from custom_components.audiconnect.v3.command_journal import (
    CommandRecord,
    HISTORY_LIMIT,
)
from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
from custom_components.audiconnect.v3.profile_store import restore_profile
from custom_components.audiconnect.v3.registry import CapabilityRegistry, VehicleContext

ROOT = Path(__file__).resolve().parents[1] / "custom_components/audiconnect/v3"


def model():
    return CapabilityRegistry.from_json_file(ROOT / "full_catalog.json")


def test_shared_journal_survives_restart_without_replaying():
    p = DevelopmentProfile(model(), VehicleContext(auth="auth0", region="DE"))
    attempt = p.begin_test("charging", "start", "cariad.charging.start", now=10)
    p.observe_http(attempt.sequence, 200)
    p.confirm(attempt.sequence, worked=True, inspected_vehicle=True, now=20)
    p.track_command(
        CommandRecord.begin("charging", "stop", "cariad.charging.stop", 200)
    )
    recovered = restore_profile(model(), p.discovery.context, p.snapshot())
    assert [record.origin for record in recovered.command_journal] == [
        "workbench",
        "home_assistant",
    ]
    assert recovered.command_journal[0].state == "verified"
    assert recovered.last_command is recovered.command_journal[1]
    assert recovered.last_command.unresolved


def test_history_is_bounded():
    p = DevelopmentProfile(model(), VehicleContext(auth="auth0", region="DE"))
    for i in range(HISTORY_LIMIT + 5):
        record = CommandRecord.begin("charging", "start", "cariad.charging.start", i)
        record.state = "backend_completed"
        p.track_command(record)
    assert len(p.command_journal) == HISTORY_LIMIT
    recovered = restore_profile(model(), p.discovery.context, p.snapshot())
    assert len(recovered.command_journal) == HISTORY_LIMIT


def test_context_change_invalidates_evidence_but_preserves_pending_action():
    old = VehicleContext(auth="auth0", region="DE")
    new = VehicleContext(auth="auth0", region="BE")
    p = DevelopmentProfile(model(), old, cooldown_seconds=0)
    attempt = p.begin_test("charging", "start", "cariad.charging.start", now=10)
    p.observe_http(attempt.sequence, 200)
    restored = restore_profile(model(), new, p.snapshot())
    assert restored.discovery.context == new
    assert restored.discovery._active is not None
    assert restored.invalidated_attempt_sequence == attempt.sequence
    restored.confirm(attempt.sequence, worked=True, inspected_vehicle=True, now=20)
    assert restored.control_results == {}
    assert restored.active == {}
    assert restored.command_journal[-1].state == "verified"


def test_unresolved_capability_survives_unrelated_commands_and_restart():
    from custom_components.audiconnect.v3.command_journal import (
        check_command_sequence,
        unresolved_normal_commands,
    )
    import pytest

    p = DevelopmentProfile(model(), VehicleContext(auth="auth0", region="DE"))
    uncertain = CommandRecord.begin("access", "unlock", "cariad.access.unlock", 1)
    uncertain.state = "uncertain"
    p.track_command(uncertain)
    check_command_sequence(p, 100, capability="climate", action="stop")
    with pytest.raises(RuntimeError, match="uncertain"):
        check_command_sequence(p, 100, capability="access", action="lock")
    for i in range(HISTORY_LIMIT + 2):
        other = CommandRecord.begin(
            "climate", "start", "cariad.climate.start.stored", 100 + i * 20
        )
        other.state = "verified"
        p.track_command(other)
    assert len(p.command_journal) == HISTORY_LIMIT
    restored = restore_profile(model(), p.discovery.context, p.snapshot())
    assert [row.command_id for row in unresolved_normal_commands(restored)] == [
        uncertain.command_id
    ]
    with pytest.raises(RuntimeError, match="uncertain"):
        check_command_sequence(restored, 3000, capability="access", action="lock")
    check_command_sequence(restored, 3000, capability="charging", action="start")


def test_control_resolution_only_blocks_affected_capability():
    from types import SimpleNamespace as NS
    from custom_components.audiconnect.v3.control_resolution import control_decision
    from custom_components.audiconnect.v3.vehicle import V3Vehicle

    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")
    car.auth_family = "auth0"
    car.advertised_capabilities.update({"access", "remoteLockUnlock", "charging"})
    p = DevelopmentProfile(model(), car.context)
    auth = NS(uses_auth0=True, service=NS(_spin="1234"))
    baseline = control_decision(car, p, auth, "access", "lock")
    climate = control_decision(car, p, auth, "climate", "stop")
    row = CommandRecord.begin(
        "climate", "window_heating_start", "cariad.climate.window_heating_start", 1
    )
    row.state = "uncertain"
    p.track_command(row)
    assert control_decision(car, p, auth, "access", "lock") == baseline
    assert control_decision(car, p, auth, "climate", "stop") == climate
    row = CommandRecord.begin("access", "unlock", "cariad.access.unlock", 100)
    row.state = "uncertain"
    p.track_command(row)
    assert (
        control_decision(car, p, auth, "access", "lock")["status"] == "pending_review"
    )


def test_http_outcome_is_per_command_and_survives_restart():
    p = DevelopmentProfile(model(), VehicleContext(auth="auth0", region="DE"))
    attempt = p.begin_test("charging", "start", "cariad.charging.start", now=10)
    p.observe_http(attempt.sequence, 502)
    assert p.engineering_record(attempt.sequence).http_status == 502
    assert p.engineering_record(attempt.sequence).state == "uncertain"
    normal = CommandRecord.begin("charging", "start", "cariad.charging.start", 200)
    normal.observe_http(204)
    p.track_command(normal)
    recovered = restore_profile(model(), p.discovery.context, p.snapshot())
    assert [r.http_status for r in recovered.command_journal] == [502, 204]
    assert (
        CommandRecord.restore(
            {k: v for k, v in normal.snapshot().items() if k != "http_status"}
        ).http_status
        is None
    )


def test_full_protected_journal_rejects_insertion_atomically():
    import pytest
    from custom_components.audiconnect.v3.development_profiles import (
        DevelopmentProfileError,
    )

    p = DevelopmentProfile(model(), VehicleContext(auth="auth0", region="DE"))
    for i in range(HISTORY_LIMIT):
        record = CommandRecord.begin("access", "unlock", "cariad.access.unlock", i)
        record.state = "uncertain"
        p.track_command(record)
    before = p.snapshot()
    last = p.last_command
    with pytest.raises(DevelopmentProfileError, match="journal full"):
        p.track_command(
            CommandRecord.begin("charging", "start", "cariad.charging.start", 100)
        )
    assert p.snapshot() == before
    assert p.last_command is last
    restored = restore_profile(model(), p.discovery.context, p.snapshot())
    assert len(restored.command_journal) == HISTORY_LIMIT
    assert restored.last_command.command_id == last.command_id


def test_failed_engineering_journal_insert_restores_discovery_transaction():
    import pytest
    from custom_components.audiconnect.v3.development_profiles import (
        DevelopmentProfileError,
    )

    p = DevelopmentProfile(model(), VehicleContext(auth="auth0", region="DE"))
    for i in range(HISTORY_LIMIT):
        record = CommandRecord.begin("access", "unlock", "cariad.access.unlock", i)
        record.state = "uncertain"
        p.track_command(record)
    before = p.snapshot()
    sequence = p.discovery._sequence
    with pytest.raises(DevelopmentProfileError, match="journal full"):
        p.begin_test("charging", "start", "cariad.charging.start", now=100)
    assert p.snapshot() == before
    assert p.discovery._active is None
    assert p.discovery._sequence == sequence
    p.command_journal[0].state = "reviewed"
    attempt = p.begin_test("charging", "start", "cariad.charging.start", now=101)
    assert attempt.sequence == sequence + 1
    assert p.engineering_record(attempt.sequence) is not None


def test_wake_budget_survives_restart_and_journal_eviction():
    import pytest
    from custom_components.audiconnect.v3.command_journal import check_wake_budget

    p = DevelopmentProfile(model(), VehicleContext(auth="auth0", region="DE"))
    for i in range(4):
        record = CommandRecord.begin(
            "remote", "wake", "cariad.remote.wake", 10000 + i * 1800
        )
        record.state = "backend_completed"
        p.track_command(record)
    for i in range(HISTORY_LIMIT + 5):
        record = CommandRecord.begin(
            "climate", "stop", "cariad.climate.stop", 16000 + i
        )
        record.state = "backend_completed"
        p.track_command(record)
    recovered = restore_profile(model(), p.discovery.context, p.snapshot())
    assert len([row for row in recovered.command_journal if row.is_wake]) == 4
    with pytest.raises(RuntimeError, match="wake budget"):
        check_wake_budget(recovered, 20000)
    check_wake_budget(recovered, 100000)


def test_security_acceptance_without_confirmation_blocks_only_access():
    import pytest
    from custom_components.audiconnect.v3.command_journal import check_command_sequence

    p = DevelopmentProfile(model(), VehicleContext(auth="auth0", region="DE"))
    row = CommandRecord.begin("access", "unlock", "cariad.access.unlock", 1000)
    row.observe_http(200)
    p.track_command(row)
    assert row.unresolved and row.requires_review
    with pytest.raises(RuntimeError, match="uncertain"):
        check_command_sequence(p, 1100, capability="access", action="lock")
    check_command_sequence(p, 1100, capability="climate", action="stop")
    row.state = "verified"
    check_command_sequence(p, 1100, capability="access", action="lock")
