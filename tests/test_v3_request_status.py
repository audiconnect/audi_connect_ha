"""CARIAD request ID tracking: success is not physical vehicle readback."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.audiconnect.v3.request_status import (
    confirm, request_id_of, status_of,
)


def test_request_id_only_from_reviewed_shape():
    assert request_id_of({"data": {"requestID": "abc-123"}}) == "abc-123"
    assert request_id_of({"data": {"requestID": "../escape"}}) is None
    assert request_id_of({"requestID": "abc"}) is None
    assert request_id_of({"data": {"requestID": 1}}) is None


def test_pending_backend_state_is_not_vehicle_confirmation():
    reply = {"data": [{"id": "a", "status": "successful"}]}
    assert status_of(reply, "a") == "backend_completed"
    assert status_of(reply, "b") == "unknown"
    assert status_of({"data": [{"id": "a", "status": "in_progress"}]}, "a") == "pending"
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
    obj = transport(replies=[
        response(200, {"data": [{"id": "a", "status": "successful"}]})
    ])
    result = asyncio.run(confirm(obj, "WAUZZZ4M0MD123456", "a", delay_s=0))
    assert result == "backend_completed"
    obj.request.assert_awaited_once_with(
        "cariad", "GET",
        "/vehicle/v1/vehicles/WAUZZZ4M0MD123456/pendingrequests",
    )


def test_rejected_command_is_reported_without_mutation_retry():
    obj = transport(replies=[
        response(200, {"data": [{"id": "abc", "status": "failed"}]})
    ])
    assert asyncio.run(confirm(obj, "VIN", "abc", delay_s=0)) == "rejected"
    assert obj.request.await_count == 1
    assert all(call.args[1] == "GET" for call in obj.request.await_args_list)


def test_pending_or_missing_outcome_never_claims_success():
    obj = transport(replies=[
        response(200, {"data": [{"id": "abc", "status": "in_progress"}]}),
        response(200, {"data": []}),
        response(204, None),
    ])
    assert asyncio.run(confirm(obj, "VIN", "abc", delay_s=0)) == "accepted_unconfirmed"
    assert obj.request.await_count == 3


def test_quota_and_auth_failures_stop_followup():
    low = transport(replies=[], remaining=12)
    assert asyncio.run(confirm(low, "VIN", "abc")) == "quota_limited"
    low.request.assert_not_awaited()
    bad = transport(replies=[response(403, None)])
    assert asyncio.run(confirm(bad, "VIN", "abc")) == "unknown"
    assert bad.request.await_count == 1
