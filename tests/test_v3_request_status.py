"""CARIAD request ID tracking: success is not physical vehicle readback."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


from custom_components.audiconnect.v3.request_status import (
    confirm,
    request_id_of,
    status_of,
)


def test_request_id_only_from_reviewed_shape():
    assert request_id_of({"data": {"requestID": "abc-123"}}) == "abc-123"
    assert request_id_of({"data": {"requestID": "../escape"}}) is None
    assert request_id_of({"requestID": "abc"}) is None
    assert request_id_of({"data": {"requestID": 1}}) is None


def test_pending_backend_state_is_not_vehicle_confirmation():
    reply = {"data": [{"id": "a", "status": "successful"}]}
    assert status_of(reply, "a") == "backend_completed"
    assert status_of(reply, "b") == "not_listed"
    assert (
        status_of({"data": [{"id": "a", "status": "in_progress"}]}, "a")
        == "in_progress"
    )
    assert status_of({"data": [{"id": "a", "status": "queued"}]}, "a") == "queued"
    assert status_of({"data": [{"id": "a", "status": "rejected"}]}, "a") == "rejected"
    assert status_of({"data": [{"id": "a", "status": "surprising"}]}, "a") == "unknown"


def transport(*, replies, remaining=100):
    return SimpleNamespace(
        remaining_calls=remaining,
        request=AsyncMock(side_effect=replies),
    )


def response(status, payload):
    return SimpleNamespace(status=status, data=payload)


def test_one_bounded_get_confirms_backend_not_physical_state():
    obj = transport(
        replies=[response(200, {"data": [{"id": "a", "status": "successful"}]})]
    )
    result = asyncio.run(confirm(obj, "WAUZZZ4M0MD123456", "a", delay_s=0))
    assert result == "backend_completed"
    obj.request.assert_awaited_once_with(
        "cariad",
        "GET",
        "/vehicle/v1/vehicles/WAUZZZ4M0MD123456/pendingrequests",
    )


def test_rejected_command_is_reported_without_mutation_retry():
    obj = transport(
        replies=[response(200, {"data": [{"id": "abc", "status": "failed"}]})]
    )
    assert asyncio.run(confirm(obj, "VIN", "abc", delay_s=0)) == "rejected"
    assert obj.request.await_count == 1
    assert all(call.args[1] == "GET" for call in obj.request.await_args_list)


def test_pending_or_missing_outcome_never_claims_success():
    obj = transport(
        replies=[
            response(200, {"data": [{"id": "abc", "status": "in_progress"}]}),
            response(200, {"data": []}),
            response(204, None),
        ]
    )
    assert asyncio.run(confirm(obj, "VIN", "abc", delay_s=0)) == "in_progress"
    assert obj.request.await_count == 3


def test_quota_and_auth_failures_stop_followup():
    low = transport(
        replies=[response(200, {"data": [{"id": "abc", "status": "completed"}]})],
        remaining=12,
    )
    assert asyncio.run(confirm(low, "VIN", "abc")) == "backend_completed"
    low.request.assert_awaited_once()
    limited = transport(replies=[response(429, None)])
    assert asyncio.run(confirm(limited, "VIN", "abc")) == "quota_limited"
    limited.request.assert_awaited_once()
    bad = transport(replies=[response(403, None)])
    assert asyncio.run(confirm(bad, "VIN", "abc")) == "unknown"
    assert bad.request.await_count == 1


def test_missing_is_not_completion_and_queue_is_not_physical_confirmation():
    obj = transport(replies=[response(200, {"data": []})] * 3)
    assert asyncio.run(confirm(obj, "VIN", "abc", delay_s=0)) == "not_listed"
    obj = transport(
        replies=[
            response(200, {"data": [{"id": "abc", "status": "queued"}]}),
            response(200, {"data": [{"id": "abc", "status": "in_progress"}]}),
            response(200, {"data": [{"id": "abc", "status": "error"}]}),
        ]
    )
    assert asyncio.run(confirm(obj, "VIN", "abc", delay_s=0)) == "rejected"
    assert obj.request.await_count == 3


def test_late_queue_result_is_exact_context_bound_and_not_physical_readback():
    from datetime import UTC, datetime, timedelta
    from pathlib import Path
    from custom_components.audiconnect.v3.command_journal import CommandRecord
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    from custom_components.audiconnect.v3.operation_revision import operation_revision
    from custom_components.audiconnect.v3.registry import (
        CapabilityRegistry,
        VehicleContext,
    )
    from custom_components.audiconnect.v3.request_status import reconcile_native_queue

    root = Path(__file__).parents[1] / "custom_components" / "audiconnect" / "v3"
    registry = CapabilityRegistry.from_json_file(root / "full_catalog.json")
    context = VehicleContext(auth="auth0", region="DE")
    profile = DevelopmentProfile(registry, context)
    now = datetime.now(UTC)
    route = "cariad.climate.settings"
    record = CommandRecord.begin(
        "climate",
        "set_settings",
        route,
        now.timestamp(),
        operation_revision=operation_revision(profile.registry.operations[route]),
    )
    record.observe_http(200)
    record.request_id = "own-request"
    record.request_context = profile.discovery.context
    profile.track_command(record)

    def payload(*rows):
        return {"climatisation": {"climatisationSettings": {"requests": list(rows)}}}

    queued = {"requestId": "own-request", "operation": "settings", "status": "queued"}
    later = now + timedelta(seconds=30)
    assert not reconcile_native_queue(
        profile,
        payload({**queued, "requestId": "other", "vcfRequestId": "own-request"}),
        later,
    )
    assert not reconcile_native_queue(
        profile, payload({**queued, "operation": "start"}), later
    )
    assert not reconcile_native_queue(profile, payload(queued, queued), later)
    assert reconcile_native_queue(profile, payload(queued), later) == [record]
    assert record.backend_result == "queued"
    assert record.state == "accepted_unconfirmed"
    assert not reconcile_native_queue(profile, payload(), later)
    assert record.backend_result == "queued"
    error = {**queued, "status": "error"}
    assert not reconcile_native_queue(profile, payload(error), now)
    assert reconcile_native_queue(profile, payload(error), later) == [record]
    assert record.state == "rejected"
    assert record.readback_observed_at is None

    # Rebind and restart do not authorize old journal IDs for new responses.
    record.backend_result = "queued"
    record.state = "accepted_unconfirmed"
    profile.rebind_context(VehicleContext(auth="auth0", region="BE"))
    assert not reconcile_native_queue(profile, payload(error), later)
    record.request_context = profile.discovery.context
    restored = CommandRecord.restore(record.snapshot())
    profile.command_journal[:] = [restored]
    assert not reconcile_native_queue(profile, payload(error), later)


def test_duplicate_request_ids_are_not_backend_evidence():
    reply = {
        "data": [
            {"id": "a", "status": "successful"},
            {"id": "a", "status": "rejected"},
        ]
    }
    assert status_of(reply, "a") == "unknown"
    assert status_of({"data": [{"id": "a", "status": "successful"}] * 201}, "a") == (
        "unknown"
    )
