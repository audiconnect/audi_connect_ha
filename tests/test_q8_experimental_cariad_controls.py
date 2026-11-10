"""Unproven CARIAD mutations are explicit actions only, never background calls."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest
from aiohttp import ClientResponseError

from custom_components.audiconnect.audi_services import AudiService
from custom_components.audiconnect.button import (
    BUTTON_DESCRIPTIONS,
    _modern_capable,
    _wakeup_capable,
)

VIN = "TESTVIN00000000001"


class API:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    def use_token(self, token):
        pass

    async def request(self, method, url, headers=None, data=None, **kwargs):
        self.calls.append((method, url, headers, data))
        if self.failure:
            raise self.failure
        return None


def service(auth0=True, failure=None):
    api = API(failure)
    svc = AudiService(api, "BE", "TEST_SPIN", 0)
    svc._uses_auth0 = auth0
    svc._bearer_token_json = {"access_token": "TEST_TOKEN"}
    return svc, api


def test_manual_wake_uses_modern_trigger_route_and_no_legacy_fallback():
    svc, api = service()
    asyncio.run(svc.trigger_vehicle_wakeup(VIN))
    assert len(api.calls) == 1
    assert api.calls[0][1].endswith("/vehiclewakeuptrigger")
    assert api.calls[0][3] == "{}"


@pytest.mark.parametrize(
    ("start", "suffix"),
    [(True, "/windowheating/start"), (False, "/windowheating/stop")],
)
def test_modern_window_heating_uses_json_not_legacy_xml(start, suffix):
    svc, api = service()
    asyncio.run(svc.set_window_heating(VIN, start))
    assert len(api.calls) == 1
    assert api.calls[0][1].endswith(suffix)
    assert api.calls[0][3] == "{}"


def test_204_is_accepted_only_as_transport_acknowledgement():
    error = ClientResponseError(None, (), status=204, message="No Content")
    svc, api = service(failure=error)
    asyncio.run(svc.trigger_vehicle_wakeup(VIN))
    asyncio.run(svc.set_window_heating(VIN, True))
    assert len(api.calls) == 2


def test_403_never_silently_succeeds_and_never_retries():
    err = ClientResponseError(None, (), status=403, message="Forbidden")
    svc, api = service(failure=err)
    with pytest.raises(ClientResponseError):
        asyncio.run(svc.trigger_vehicle_wakeup(VIN))
    assert len(api.calls) == 1


def test_unproven_controls_require_user_opt_in_and_explicit_capability():
    v = NS(
        _audi_service=NS(uses_auth0=True),
        has_capability=lambda x: x in {"charging", "climatisation", "vehicleWakeUp"},
        impaired_capabilities=frozenset(),
    )
    assert _modern_capable(v, "charging")
    assert _wakeup_capable(v)
    new = {d.key: d for d in BUTTON_DESCRIPTIONS}
    for key in (
        "start_charging_modern",
        "stop_charging_modern",
        "start_window_heating_modern",
        "stop_window_heating_modern",
        "wake_vehicle_modern",
    ):
        assert new[key].experimental is True
        assert new[key].supported_fn(v) is True
    assert "start_climate_car_settings" not in new
    assert "stop_climate" not in new
    assert new["flash_lights"].experimental is False


def test_no_capability_or_auth0_means_controls_hidden():
    v = NS(
        _audi_service=NS(uses_auth0=False),
        has_capability=lambda x: None,
        impaired_capabilities=frozenset(),
    )
    assert not _modern_capable(v, "charging")
    assert not _wakeup_capable(v)
