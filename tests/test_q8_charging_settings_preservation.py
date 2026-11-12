"""Auth0 charging settings are read-modify-write, never blind replacement."""

from __future__ import annotations

import asyncio
import json

import pytest

from custom_components.audiconnect.audi_services import AudiService

VIN = "TESTVIN00000000001"


class API:
    def __init__(self, charging=None):
        self.charging = charging
        self.urls = []
        self.writes = []

    def use_token(self, token):
        pass

    async def get(self, url):
        self.urls.append(url)
        return {"charging": {"chargingSettings": {"value": self.charging}}}

    async def request(self, method, url, headers=None, data=None, **kwargs):
        self.writes.append((method, url, json.loads(data)))
        return {"data": {}}


def service(settings, auth0=True):
    api = API(charging=settings)
    svc = AudiService(api, "BE", None, 0)
    svc._bearer_token_json = {"access_token": "FAKE"}
    svc._uses_auth0 = auth0
    return svc, api


def test_soc_change_preserves_other_charging_settings():
    svc, api = service(
        {
            "carCapturedTimestamp": "2026-11-10T12:00:00Z",
            "maxChargeCurrentAC_A": 12,
            "autoUnlockPlugWhenChargedAC": "on",
            "targetSOC_pct": 70,
        }
    )
    asyncio.run(svc.set_target_state_of_charge(VIN, 80))
    assert len(api.urls) == 1
    assert "jobs=charging" in api.urls[0]
    assert len(api.writes) == 1
    method, url, payload = api.writes[0]
    assert method == "PUT" and url.endswith("/charging/settings")
    assert payload == {
        "maxChargeCurrentAC_A": 12,
        "autoUnlockPlugWhenChargedAC": "on",
        "targetSOC_pct": 80,
    }


def test_absent_settings_fails_closed_before_put():
    svc, api = service(None)
    with pytest.raises(ValueError, match="refusing blind update"):
        asyncio.run(svc.set_target_state_of_charge(VIN, 80))
    assert len(api.urls) == 1
    assert not api.writes


def test_invalid_soc_rejected_before_read_or_write():
    svc, api = service({})
    with pytest.raises(ValueError, match="20 and 100"):
        asyncio.run(svc.set_target_state_of_charge(VIN, 10))
    assert not api.urls and not api.writes


def test_legacy_path_unchanged_without_an_extra_get():
    svc, api = service(None, auth0=False)
    asyncio.run(svc.set_target_state_of_charge(VIN, 80))
    assert not api.urls
    assert api.writes[0][2] == {"targetSOC_pct": 80}


def test_unknown_vehicle_specific_charge_setting_fails_closed_before_put():
    svc, api = service(
        {
            "carCapturedTimestamp": "2026-11-10T12:00:00Z",
            "targetSOC_pct": 70,
            "vehicleSpecificChargePreference": {"enabled": True},
        }
    )
    with pytest.raises(ValueError, match="potentially destructive"):
        asyncio.run(svc.set_target_state_of_charge(VIN, 80))
    assert len(api.urls) == 1
    assert api.writes == []


def test_verified_charge_setting_fields_are_all_preserved():
    svc, api = service(
        {
            "targetSOC_pct": 70,
            "maxChargeCurrentAC_A": 12,
            "maxChargeCurrentAC": "reduced",
            "autoUnlockPlugWhenChargedAC": "off",
            "carCapturedTimestamp": "2026-11-10T12:00:00Z",
        }
    )
    asyncio.run(svc.set_target_state_of_charge(VIN, 85))
    assert api.writes[0][2] == {
        "targetSOC_pct": 85,
        "maxChargeCurrentAC_A": 12,
        "maxChargeCurrentAC": "reduced",
        "autoUnlockPlugWhenChargedAC": "off",
    }
