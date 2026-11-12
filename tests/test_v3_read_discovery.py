import pytest
"""Automated CARIAD GET discovery keeps absent fields as inconclusive, not unsupported."""
from types import SimpleNamespace
from custom_components.audiconnect.v3.read_discovery import (
    record_jobs, pending_groups, reserve_group, summary,
)
from custom_components.audiconnect.v3.historical_catalog import V2_JOBS


def blank_profile():
    return SimpleNamespace(job_discovery={}, job_probe_attempts={}, attribute_evidence={})


def test_startup_shared_status_observes_jobs_but_missing_is_not_unsupported():
    profile = blank_profile()
    record_jobs(profile, V2_JOBS, status=200, payload={
        "charging":{"batteryStatus":{"value":{"currentSOC_pct":40}}}
    })
    assert profile.job_discovery["charging"] == "observed"
    assert profile.job_discovery["climatisation"] == "not_observed"
    assert summary(profile)["not_scanned_jobs"] == 0
    assert summary(profile)["catalog_jobs"] == 23
    first=pending_groups(profile, max_groups=2)
    assert first[0] == ("climatisation",)
    assert len(first) == 2


def test_group_probe_is_bounded_does_not_repeat_or_auto_mutate():
    profile=blank_profile()
    profile.job_discovery={"climatisation":"not_observed", "charging":"not_observed"}
    selected=pending_groups(profile,max_groups=1)
    assert selected == [("climatisation",)]
    reserve_group(profile,selected[0])
    assert pending_groups(profile,max_groups=1)[0] == ("charging",)
    assert profile.job_probe_attempts["climatisation"]==1
    assert all(job in V2_JOBS for job in profile.job_probe_attempts)


def test_transient_api_errors_cannot_mark_a_supported_job_missing():
    profile=blank_profile()
    record_jobs(profile, ("charging",), status=429, payload=None)
    assert profile.job_discovery["charging"] == "inconclusive"
    record_jobs(profile, ("charging",), status=200, payload={"charging":{"status":"ok"}})
    assert profile.job_discovery["charging"] == "inconclusive"
    record_jobs(profile, ("charging",), status=207, payload={
        "charging":{"batteryStatus":{"value":{"currentSOC_pct":42}}}
    })
    assert profile.job_discovery["charging"] == "observed"
    record_jobs(profile, ("charging",), status=503, payload=None)
    assert profile.job_discovery["charging"] == "observed"

def test_automatic_probe_plan_covers_every_known_missing_job():
    profile = blank_profile()
    attempted = set()
    while groups := pending_groups(profile, max_groups=2):
        for group in groups:
            assert not attempted.intersection(group)
            attempted.update(group)
            reserve_group(profile, group)
    assert attempted == set(V2_JOBS)


def test_active_ventilation_timer_namespace_is_read_evidence():
    profile = blank_profile()
    record_jobs(profile, ("activeVentilation",), status=207, payload={
        "climatisationTimers": {"activeVentilationTimersStatus": {"value": {
            "timers": [{"id": 1, "enabled": False}]}}}
    })
    assert profile.job_discovery["activeVentilation"] == "observed"
    assert "climatisation" not in profile.job_discovery


def test_assessment_percent_is_not_observed_percent():
    profile = blank_profile()
    record_jobs(profile, V2_JOBS, status=207, payload={
        "charging": {"batteryStatus": {"value": {"currentSOC_pct": 40}}}})
    assert summary(profile)["assessed_jobs"] == 1
    reserve_group(profile, ("climatisation",))
    assert summary(profile)["assessed_jobs"] == 2
    assert summary(profile)["observed_jobs"] == 1
    assert summary(profile)["assessment_percent"] > summary(profile)["observed_percent"]


def test_standalone_discovery_progress_survives_snapshot_and_transient_failure():
    from pathlib import Path
    from custom_components.audiconnect.v3.read_discovery import record_standalone_read, user_progress
    from custom_components.audiconnect.v3.registry import CapabilityRegistry
    from custom_components.audiconnect.v3.vehicle import V3Vehicle
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    from custom_components.audiconnect.v3.profile_store import restore_profile
    root = Path(__file__).resolve().parents[1] / "custom_components/audiconnect/v3"
    registry = CapabilityRegistry.from_json_file(root / "full_catalog.json")
    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")
    auth = SimpleNamespace(uses_auth0=True, service=SimpleNamespace(_spin=None))
    profile = DevelopmentProfile(registry, car.context)
    record_standalone_read(profile, "cariad.mobility.status.lastTrip", 200)
    record_standalone_read(profile, "cariad.mobility.status.lastTrip", 429)
    record_standalone_read(profile, "cariad.mobility.status.shortTerm", 404)
    profile = restore_profile(registry, car.context, profile.snapshot())
    assert profile.standalone_discovery["cariad.mobility.status.lastTrip"] == 200
    result = user_progress(car, profile, auth)
    assert result["read_total"] == 28
    assert result["read_assessed"] == 2
    assert result["controls_physically_verified"] == 0
    assert result["read_assessment_percent"] == round(200 / 28, 1)
    disabled = user_progress(car, profile, auth, parking_allowed=False)
    assert disabled["read_total"] == 27
    assert disabled["excluded_read_routes"] == {
        "cariad.mobility.status.parkingPosition": "tracker_disabled_by_user"}
    assert disabled["read_assessment_percent"] == round(200 / 27, 1)


def test_unknown_jobs_remain_in_normal_batch_only_explicit_job_negative_excludes():
    from custom_components.audiconnect.v3.attribute_runtime import planned_jobs
    profile = blank_profile()
    car = SimpleNamespace(v2_initial_discovery_completed=True)
    record_jobs(profile, V2_JOBS, status=207, payload={
        "charging": {"batteryStatus": {"value": {"currentSOC_pct": 40}}},
        "batterySupport": {"error": {"code": "jobNotSupported"}},
        "lvBattery": {"error": {"code": "temporarilyUnavailable"}},
        "activeVentilation": {"timerStatus": {"error": {"code": "unsupported"}}},
    })
    reserve_group(profile, ("lvBattery",))
    assert set(planned_jobs(car, profile)) == set(V2_JOBS) - {"batterySupport"}
    assert "batterySupport" not in {job for group in pending_groups(profile, max_groups=23) for job in group}
    record_jobs(profile, ("batterySupport",), status=429, payload=None)
    assert profile.job_discovery["batterySupport"] == "unsupported"
    record_jobs(profile, ("batterySupport",), status=207, payload={})
    assert profile.job_discovery["batterySupport"] == "unsupported"
    record_jobs(profile, ("batterySupport",), status=200,
                payload={"batterySupport": {"status": {"value": {"enabled": True}}}})
    assert "batterySupport" in planned_jobs(car, profile)


def test_read_route_exclusion_requires_explicit_negative_and_survives_transient_failure():
    from custom_components.audiconnect.v3.read_discovery import record_standalone_read, read_excluded
    profile = SimpleNamespace(standalone_discovery={}, unsupported_reads=set())
    route = "cariad.mobility.status.lastTrip"
    for status in (401, 403, 404, 429, 503):
        record_standalone_read(profile, route, status)
        assert not read_excluded(profile, route)
    record_standalone_read(profile, route, 404, {"error": {"code": "notSupported"}})
    assert read_excluded(profile, route)
    record_standalone_read(profile, route, 429)
    assert read_excluded(profile, route)
    record_standalone_read(profile, route, 200, {"data": []})
    assert not read_excluded(profile, route)


def test_explicit_read_exclusions_survive_restart_and_context_change_invalidates_them():
    from pathlib import Path
    from custom_components.audiconnect.v3.registry import CapabilityRegistry, VehicleContext
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    from custom_components.audiconnect.v3.profile_store import restore_profile
    from custom_components.audiconnect.v3.read_discovery import record_standalone_read
    root = Path(__file__).resolve().parents[1] / "custom_components/audiconnect/v3"
    registry = CapabilityRegistry.from_json_file(root / "full_catalog.json")
    context = VehicleContext(auth="auth0", region="DE")
    profile = DevelopmentProfile(registry, context)
    profile.job_discovery["batterySupport"] = "unsupported"
    route = "cariad.mobility.status.lastTrip"
    record_standalone_read(profile, route, 410)
    restored = restore_profile(registry, context, profile.snapshot())
    assert restored.job_discovery["batterySupport"] == "unsupported"
    assert route in restored.unsupported_reads
    restored.rebind_context(VehicleContext(auth="auth0", region="BE"))
    assert not restored.unsupported_reads
    assert not restored.job_discovery


def test_retryable_vendor_error_gets_bounded_recovery_after_initial_scan():
    from custom_components.audiconnect.v3.read_discovery import MAX_TARGETED_PROBE_ATTEMPTS
    profile = blank_profile()
    job = "chargingProfiles"
    profile.job_discovery = {key: "observed" for key in V2_JOBS}
    profile.job_discovery.update({job: "not_observed", "departureTimers": "not_observed"})
    reserve_group(profile, (job,))
    record_jobs(profile, (job,), status=207, payload={
        job: {"chargingProfilesStatus": {"error": {"code": 4112, "retry": True}}}})
    assert profile.job_discovery[job] == "inconclusive"
    record_jobs(profile, (job,), status=207, payload={})
    assert profile.job_discovery[job] == "inconclusive"
    assert pending_groups(profile, max_groups=1) == [("departureTimers",)]
    reserve_group(profile, ("departureTimers",))
    for _ in range(MAX_TARGETED_PROBE_ATTEMPTS - 1):
        assert pending_groups(profile, max_groups=1) == [(job,)]
        reserve_group(profile, (job,))
    assert pending_groups(profile, max_groups=2) == []
    record_jobs(profile, (job,), status=207, payload={
        job: {"chargingProfilesStatus": {"value": {"profiles": [{"id": 1}]}}}})
    assert profile.job_discovery[job] == "observed"


def test_retryable_negative_is_not_a_permanent_exclusion():
    profile = blank_profile()
    record_jobs(profile, ("chargingProfiles",), status=207, payload={
        "chargingProfiles": {"error": {"code": "jobNotSupported", "retry": True}}})
    assert profile.job_discovery["chargingProfiles"] == "inconclusive"


def test_retry_budget_survives_profile_restore():
    from pathlib import Path
    from custom_components.audiconnect.v3.registry import CapabilityRegistry, VehicleContext
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    from custom_components.audiconnect.v3.profile_store import restore_profile
    from custom_components.audiconnect.v3.read_discovery import MAX_TARGETED_PROBE_ATTEMPTS
    root = Path(__file__).resolve().parents[1] / "custom_components/audiconnect/v3"
    registry = CapabilityRegistry.from_json_file(root / "full_catalog.json")
    context = VehicleContext(auth="auth0", region="DE")
    profile = DevelopmentProfile(registry, context)
    profile.job_discovery["chargingProfiles"] = "inconclusive"
    for _ in range(MAX_TARGETED_PROBE_ATTEMPTS):
        reserve_group(profile, ("chargingProfiles",))
    restored = restore_profile(registry, context, profile.snapshot())
    assert restored.job_probe_attempts["chargingProfiles"] == MAX_TARGETED_PROBE_ATTEMPTS
    assert restored.job_discovery["chargingProfiles"] == "inconclusive"


def test_read_discovery_distinguishes_exhaustion_from_success():
    from pathlib import Path
    from custom_components.audiconnect.v3.read_discovery import user_progress, MAX_TARGETED_PROBE_ATTEMPTS
    from custom_components.audiconnect.v3.registry import CapabilityRegistry
    from custom_components.audiconnect.v3.vehicle import V3Vehicle
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    root = Path(__file__).resolve().parents[1] / "custom_components/audiconnect/v3"
    registry = CapabilityRegistry.from_json_file(root / "full_catalog.json")
    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")
    auth = SimpleNamespace(uses_auth0=True, service=SimpleNamespace(_spin=None))
    profile = DevelopmentProfile(registry, car.context)
    assert user_progress(car, profile, auth)["read_state"] == "discovering"
    profile.job_discovery = {job: "observed" for job in V2_JOBS}
    profile.job_discovery["chargingProfiles"] = "inconclusive"
    profile.job_probe_attempts["chargingProfiles"] = MAX_TARGETED_PROBE_ATTEMPTS
    progress = user_progress(car, profile, auth)
    assert progress["read_retry_exhausted_jobs"] == ["chargingProfiles"]
    assert progress["read_state"] == "awaiting_data"
    profile.standalone_discovery = {op: 200 for op in progress["standalone_http"]}
    progress = user_progress(car, profile, auth)
    assert progress["read_state"] == "complete_with_unresolved"
    assert progress["read_assessed"] < progress["read_total"]
    profile.job_discovery["chargingProfiles"] = "observed"
    assert user_progress(car, profile, auth)["read_state"] == "complete"


@pytest.mark.asyncio
async def test_recovery_resets_only_unresolved_read_attempts():
    from unittest.mock import AsyncMock
    from custom_components.audiconnect.v3.engine import V3Engine
    profile = SimpleNamespace(job_probe_attempts={"charging": 3, "batterySupport": 1, "chargingProfiles": 3},
                              job_discovery={"charging": "observed", "batterySupport": "unsupported",
                                             "chargingProfiles": "inconclusive"})
    car = SimpleNamespace(vin="WAUZZZ4M0MD123456")
    coordinator = SimpleNamespace(async_request_refresh=AsyncMock())
    engine = SimpleNamespace(require_vehicle=lambda vin: car, profiles={car.vin.lower():profile},
        storage=SimpleNamespace(async_save=AsyncMock()), entry=SimpleNamespace(runtime_data=SimpleNamespace(coordinator=coordinator)),
        health=SimpleNamespace(snapshot=lambda *args: {"status":"operational"}),
        discovery_progress=lambda *args: {"read_state":"discovering"})
    result = await V3Engine.resume_read_discovery(engine, car.vin)
    assert result["read_state"] == "discovering"
    assert profile.job_probe_attempts == {"charging":3, "batterySupport":1}
    coordinator.async_request_refresh.assert_awaited_once()
