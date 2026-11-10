"""Q8: modern Auth0 climate controls send the intended BFF requests."""
from __future__ import annotations
import asyncio
import pytest
from aiohttp import ClientResponseError
from custom_components.audiconnect.audi_services import AudiService

VIN = "WAUZZZ00000000000"


class FakeApi:
    def __init__(self, *, status=200):
        self.status = status
        self.calls = []

    def use_token(self, token):
        pass

    async def request(self, method, url, headers=None, data=None, **kwargs):
        self.calls.append((method, url, data))
        if self.status != 200:
            raise ClientResponseError(None, (), status=self.status, message="Test status")
        return {"data": {}}


def make_svc(status=200):
    api = FakeApi(status=status)
    service = AudiService(api, "BE", None, 0)
    service._uses_auth0 = True
    service._bearer_token_json = {"access_token": "FAKE_TOKEN"}
    return service, api


def test_bodyless_start_uses_modern_cariad_api_even_at_saved_level_zero():
    service, api = make_svc()
    asyncio.run(service.start_climate_control(VIN))
    assert api.calls == [
        ("POST", f"https://emea.bff.cariad.digital/vehicle/v1/vehicles/{VIN}/climatisation/start", None)
    ]


def test_stop_uses_modern_cariad_api():
    service, api = make_svc()
    asyncio.run(service.set_climatisation(VIN, False))
    assert api.calls == [
        ("POST", f"https://emea.bff.cariad.digital/vehicle/v1/vehicles/{VIN}/climatisation/stop", None)
    ]


@pytest.mark.parametrize("command", ["start", "stop"])
def test_no_content_is_not_mistaken_for_a_failed_command(command):
    service, api = make_svc(status=204)
    if command == "start":
        asyncio.run(service.start_climate_control(VIN))
    else:
        asyncio.run(service.set_climatisation(VIN, False))
    assert len(api.calls) == 1
    assert api.calls[0][1].endswith(f"/climatisation/{command}")


@pytest.mark.parametrize("command", ["start", "stop"])
def test_auth_errors_not_silently_accepted(command):
    service, api = make_svc(status=403)
    with pytest.raises(ClientResponseError):
        if command == "start":
            asyncio.run(service.start_climate_control(VIN))
        else:
            asyncio.run(service.set_climatisation(VIN, False))
    assert len(api.calls) == 1
