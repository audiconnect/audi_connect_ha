"""Q8: Auth0 door commands use CARIAD and do not silently fall back to legacy RLU."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import ClientResponseError
from custom_components.audiconnect.audi_services import AudiService

VIN = "WAUZZZ00000000000"


class RecordingApi:
    def __init__(self, result=None, failure=None):
        self.calls = []
        self.result = {"data": {}} if result is None else result
        self.failure = failure

    def use_token(self, token):
        pass

    async def request(self, method, url, headers=None, data=None, **kwargs):
        self.calls.append((method, url, headers, data))
        if self.failure is not None:
            raise self.failure
        return self.result


def make_service(*, auth0=True, spin="1234", api=None):
    api = api or RecordingApi()
    svc = AudiService(api, "BE", spin, 0)
    svc._uses_auth0 = auth0
    svc._bearer_token_json = {"access_token": "TEST_TOKEN"}
    return svc, api


@pytest.mark.parametrize("action", ["lock", "unlock"])
def test_auth0_uses_cariad_access_with_spin(action):
    svc, api = make_service()
    asyncio.run(svc.set_vehicle_lock(VIN, action == "lock"))
    assert len(api.calls) == 1
    method, url, headers, body = api.calls[0]
    assert method == "POST"
    assert url.endswith(f"/vehicle/v1/vehicles/{VIN}/access/{action}")
    assert "rlu/v1" not in url
    assert json.loads(body) == {"spin": "1234"}
    assert headers["Authorization"] == "Bearer TEST_TOKEN"
    assert "1234" not in url


def test_auth0_missing_spin_fails_closed():
    svc, api = make_service(spin=None)
    with pytest.raises(ValueError, match="S-PIN"):
        asyncio.run(svc.set_vehicle_lock(VIN, True))
    assert api.calls == []


def test_auth0_does_not_fallback_to_legacy_on_rejection():
    api = RecordingApi(failure=ClientResponseError(None, (), status=403, message="Forbidden"))
    svc, _ = make_service(api=api)
    with pytest.raises(ClientResponseError):
        asyncio.run(svc.set_vehicle_lock(VIN, False))
    assert len(api.calls) == 1
    assert "/access/unlock" in api.calls[0][1]


def test_auth0_accepts_no_content_ack_without_false_success_confirmation():
    api = RecordingApi(failure=ClientResponseError(None, (), status=204, message="No Content"))
    svc, _ = make_service(api=api)
    asyncio.run(svc.set_vehicle_lock(VIN, True))
    assert len(api.calls) == 1


def test_auth0_confirms_when_request_id_is_provided():
    api = RecordingApi(result={"data": {"requestID": "test-id"}})
    svc, _ = make_service(api=api)
    observed = []

    async def confirm(vin, action, request_id, noun="Charging", **kwargs):
        observed.append((vin, action, request_id, noun))

    svc._confirm_vehicle_request = confirm
    asyncio.run(svc.set_vehicle_lock(VIN, False))
    assert observed == [(VIN, "unlock", "test-id", "Door lock")]


def test_non_auth0_keeps_legacy_api_unmodified():
    svc, api = make_service(auth0=False)
    called = []

    async def legacy(vin, lock):
        called.append((vin, lock))

    svc._set_vehicle_lock_legacy = legacy
    asyncio.run(svc.set_vehicle_lock(VIN, True))
    assert called == [(VIN, True)]
    assert api.calls == []
