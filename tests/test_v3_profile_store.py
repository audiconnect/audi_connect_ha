"""V3 development profile HA-storage roundtrips (no API calls)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.audiconnect.v3.development_profiles import (
    DevelopmentProfile, DevelopmentProfileError,
)
from custom_components.audiconnect.v3.profile_store import restore_profile
from custom_components.audiconnect.v3.registry import (
    CapabilityRegistry, VehicleContext,
)

PATH = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/v3_climate_catalog.json"
)


def fresh():
    catalog = CapabilityRegistry(json.loads(PATH.read_text()))
    context = VehicleContext(auth="auth0", region="DE", model_family="q8")
    return catalog, context, DevelopmentProfile(catalog, context, cooldown_seconds=0)


def test_confirmed_route_is_recovered_without_dispatching_car_action():
    catalog, context, profile = fresh()
    route = "cariad.climate.start.stored"
    run = profile.begin_test("climate", "start", route, now=10)
    profile.observe_http(run.sequence, 200)
    profile.confirm(run.sequence, worked=True, inspected_vehicle=True, now=15)
    profile.choose_working("climate", "start", route)
    result = restore_profile(catalog, context, profile.snapshot(), cooldown_seconds=0)
    assert result.active["climate.start"] == route
    assert result.discovery._active is None
    assert result.discovery._sequence == 1


def test_unfinished_request_after_restart_blocks_new_action():
    catalog, context, profile = fresh()
    first = profile.begin_test(
        "climate", "start", "cariad.climate.start.stored", now=10
    )
    profile.observe_http(first.sequence, None)
    result = restore_profile(catalog, context, profile.snapshot(), cooldown_seconds=0)
    with pytest.raises(Exception, match="previous action"):
        result.begin_test("climate", "stop", "cariad.climate.stop", now=50)
    result.confirm(first.sequence, worked=False, inspected_vehicle=True, now=60)
    assert result.discovery._active is None


def test_unverified_selection_cannot_be_injected_via_storage():
    catalog, context, profile = fresh()
    data = profile.snapshot()
    data["active"] = {"climate.start": "cariad.climate.start.stored"}
    with pytest.raises(DevelopmentProfileError, match="confirm"):
        restore_profile(catalog, context, data)


def test_status_result_must_be_fresh_to_remain_selected():
    catalog, context, profile = fresh()
    operation = "cariad.climate.status.batch"
    profile.record_status(
        "climate", operation, http_status=200, schema_valid=True, fresh=True
    )
    profile.choose_working("climate", "status", operation)
    result = restore_profile(catalog, context, profile.snapshot())
    assert result.active["climate.status"] == operation
    data = profile.snapshot()
    data["read_evidence"][operation]["fresh"] = False
    with pytest.raises(DevelopmentProfileError, match="inconsistent"):
        restore_profile(catalog, context, data)


def test_custom_route_survives_snapshot_without_becoming_active():
    catalog, context, profile = fresh()
    ident = profile.add({
        "id": "user.climate.start.my_probe",
        "capability": "climate", "aspect": "start", "family": "cariad",
        "method": "POST",
        "path": "/vehicle/v1/vehicles/{VIN}/climatisation/start",
        "body": {"targetTemperature": 22},
    })
    result = restore_profile(catalog, context, profile.snapshot())
    assert ident in result.registry.operations
    assert not result.active


def test_disabled_start_is_restored_without_disabling_climate_status():
    catalog, context, profile = fresh()
    profile.disable("climate", "start")
    restored = restore_profile(catalog, context, profile.snapshot())
    assert "climate.start" in restored.discovery.disabled
    assert restored.registry.resolve(
        "climate", "status", context
    )["operation"] == "cariad.climate.status.batch"


@pytest.mark.asyncio
async def test_partial_vehicle_save_never_erases_another_car_profile():
    from custom_components.audiconnect.v3.profile_store import V3ProfileStorage

    class FakeStore:
        def __init__(self):
            self.data = {"profiles": {"other_vehicle": {"schema_version": 1}}}

        async def async_load(self):
            return self.data

        async def async_save(self, data):
            self.data = data

    catalog, ctx, profile = fresh()
    storage = V3ProfileStorage.__new__(V3ProfileStorage)
    storage._store = FakeStore()
    await storage.async_save({"current_vehicle": profile})
    assert set(storage._store.data["profiles"]) == {
        "current_vehicle", "other_vehicle"
    }
    loaded = await storage.async_load(
        catalog, {"current_vehicle": ctx}
    )
    assert isinstance(loaded["current_vehicle"], DevelopmentProfile)



def test_saved_unverified_candidate_survives_restart_but_not_active():
    catalog, context, profile = fresh()
    candidate = "cariad.climate.start.stored"
    profile.save_candidate("climate", "start", candidate)
    assert "climate.start" not in profile.active
    restored = restore_profile(catalog, context, profile.snapshot())
    assert restored.draft_selected["climate.start"] == candidate
    assert "climate.start" not in restored.active
    assert restored.control_results == {}


def test_invalid_candidate_cannot_be_injected_through_saved_profile():
    catalog, context, profile = fresh()
    saved = profile.snapshot()
    saved["draft_selected"] = {"climate.start": "mbb.climate.start"}
    with pytest.raises(DevelopmentProfileError):
        restore_profile(catalog, context, saved)


def test_historical_physical_review_survives_context_change_without_authorizing_control():
    catalog, context, profile = fresh()
    route = "cariad.climate.start.stored"
    run = profile.begin_test("climate", "start", route, now=10)
    profile.observe_http(run.sequence, 200)
    profile.confirm(run.sequence, worked=True, inspected_vehicle=True, now=15)
    profile.choose_working("climate", "start", route)
    revision = profile.active_revisions["climate.start"]
    refined = VehicleContext(auth="auth0", region="DE", model_family="q8", vehicle_type="phev")
    restored = restore_profile(catalog, refined, profile.snapshot(), cooldown_seconds=0)
    assert not restored.control_results
    assert not restored.active and not restored.active_revisions
    history = restored.historical_control_evidence
    assert len(history) == 1 and history[0]["outcome"] == "worked"
    assert history[0]["operation"] == route and history[0]["operation_revision"] == revision
    again = restore_profile(catalog, refined, restored.snapshot(), cooldown_seconds=0)
    assert again.historical_control_evidence == history
    assert not again.control_results and not again.active


def test_identity_draft_roundtrip_does_not_activate_or_dispatch():
    from custom_components.audiconnect.v3.transport import INVENTORY_OPERATION
    catalog, context, profile = fresh()
    query = "query Probe { userVehicles { vin vehicle { core { modelYear } } } }"
    profile.save_identity_draft(INVENTORY_OPERATION, query, {})
    result = restore_profile(catalog, context, profile.snapshot())
    assert result.identity_drafts[INVENTORY_OPERATION] == {"query": query, "variables": {}}
    assert not result.active and not result.command_journal
    with pytest.raises(ValueError):
        result.save_identity_draft(INVENTORY_OPERATION, "mutation { userVehicles { vin } }", {})
    assert result.identity_drafts[INVENTORY_OPERATION]["query"] == query
