"""Auth0 Q8 climate routing regression: do not call legacy fs-car endpoints."""

import asyncio

from custom_components.audiconnect.audi_services import AudiService

VIN = "WAUZZZ00000000000"


class RecordingAPI:
    def __init__(self):
        self.calls = []

    async def request(self, method, url, headers=None, data=None, **kwargs):
        self.calls.append((method, url))
        return {"data": {}}


def make_service(auth0=True):
    api = RecordingAPI()
    service = AudiService(api, "DE", None, 0)
    service._uses_auth0 = auth0
    service._bearer_token_json = {"access_token": "dummy"}
    return service, api


def test_auth0_overrides_legacy_preference_for_climate():
    service, _api = make_service()
    assert service._api_level == 0
    assert service._climate_api_level() == 1


def test_non_auth0_preserves_configured_api_level():
    service, _api = make_service(False)
    assert service._climate_api_level() == 0


def test_auth0_start_uses_modern_cariad_route():
    service, api = make_service()
    asyncio.run(service.start_climate_control(VIN))
    assert len(api.calls) == 1
    assert api.calls[0][1].endswith("/climatisation/start")
    assert "/fs-car/" not in api.calls[0][1]


def test_auth0_stop_uses_modern_cariad_route():
    service, api = make_service()
    asyncio.run(service.set_climatisation(VIN, False))
    assert len(api.calls) == 1
    assert api.calls[0][1].endswith("/climatisation/stop")
    assert "/fs-car/" not in api.calls[0][1]
