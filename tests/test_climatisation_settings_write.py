"""Writing climatisation settings.

PUT climatisation/settings takes the whole object, so a single toggle has to
round-trip every other field or it clears them. Same hazard as the charging
profile write, and the same read-modify-write answer.

The endpoint was previously recorded as not existing, on the strength of a GET
returning 404. It means there is no GET route: the honk-and-flash work found
the identical 404-on-GET for a path that is real for POST.
"""

from __future__ import annotations

import asyncio
import copy
import json

import pytest

from custom_components.audiconnect.audi_services import (
    build_climatisation_settings_update,
)

from tests.fixture_q8_etron import PAYLOAD


def settings():
    return copy.deepcopy(PAYLOAD["climatisation"]["climatisationSettings"]["value"])


# --- the read-modify-write core ---------------------------------------------------


def test_every_other_field_survives_one_change():
    """The whole point. Toggling a seat must not clear the temperature."""
    current = settings()
    body = build_climatisation_settings_update(current, zoneFrontLeftEnabled=True)
    assert body["zoneFrontLeftEnabled"] is True
    for field in (
        "targetTemperature_C",
        "climatizationAtUnlock",
        "windowHeatingEnabled",
        "climatisationWithoutExternalPower",
    ):
        assert body[field] == current[field], field


def test_the_server_timestamp_is_not_echoed_back():
    body = build_climatisation_settings_update(settings(), windowHeatingEnabled=True)
    assert "carCapturedTimestamp" not in body
    # control: it is in the source object
    assert "carCapturedTimestamp" in settings()


def test_several_fields_can_change_at_once():
    body = build_climatisation_settings_update(
        settings(), zoneFrontLeftEnabled=True, zoneFrontRightEnabled=True
    )
    assert body["zoneFrontLeftEnabled"] is True
    assert body["zoneFrontRightEnabled"] is True


def test_a_field_the_car_did_not_report_can_still_be_set():
    """This car reports no rear zones. Setting one adds it rather than failing,
    since the car decides what it accepts."""
    body = build_climatisation_settings_update(settings(), zoneRearLeftEnabled=True)
    assert body["zoneRearLeftEnabled"] is True


@pytest.mark.parametrize("bad", ["targetSOC_pct", "mode", "honk", "zoneFrontLeft"])
def test_a_field_that_is_not_a_setting_is_refused(bad):
    """A typo becomes an error here rather than a field the car silently
    ignores."""
    with pytest.raises(ValueError, match="Not climatisation settings"):
        build_climatisation_settings_update(settings(), **{bad: True})


@pytest.mark.parametrize("empty", [None, {}, "notadict", []])
def test_it_refuses_to_build_from_nothing(empty):
    """Without the current settings there is nothing to preserve, and sending a
    lone field would clear the rest."""
    with pytest.raises(ValueError, match="No climatisation settings"):
        build_climatisation_settings_update(empty, windowHeatingEnabled=True)


# --- the request ------------------------------------------------------------------


class Api:
    def __init__(self, current):
        self.current = current
        self.calls = []

    def use_token(self, *_):
        pass

    async def get(self, url):
        self.calls.append(("GET", url, None))
        return {"climatisation": {"climatisationSettings": {"value": self.current}}}

    async def request(self, method, url, data=None, headers=None, **kw):
        self.calls.append((method, url, data))
        return None


def service(current=None):
    from custom_components.audiconnect import audi_services

    svc = object.__new__(audi_services.AudiService)
    svc._api = Api(settings() if current is None else current)
    svc._bearer_token_json = {"access_token": "x"}
    svc._country = "DE"
    svc._api_level = 1
    return svc


def test_it_reads_then_puts_the_whole_object():
    svc = service()
    asyncio.run(svc.set_climatisation_settings("VIN1", windowHeatingEnabled=True))
    methods = [c[0] for c in svc._api.calls]
    assert methods == ["GET", "PUT"], "must read before writing"

    put = svc._api.calls[1]
    assert put[1].endswith("/climatisation/settings")
    body = json.loads(put[2])
    assert body["windowHeatingEnabled"] is True
    assert body["targetTemperature_C"] == settings()["targetTemperature_C"]


def test_it_sends_nothing_when_the_car_reports_no_settings():
    svc = service(current={})
    with pytest.raises(ValueError):
        asyncio.run(svc.set_climatisation_settings("VIN1", windowHeatingEnabled=True))
    assert [c[0] for c in svc._api.calls] == ["GET"], "must not PUT a lone field"


# --- the switches -----------------------------------------------------------------


def test_each_setting_switch_writes_its_own_field():
    from custom_components.audiconnect.switch import SWITCH_DESCRIPTIONS

    class Conn:
        def __init__(self):
            self.calls = []

        async def set_climatisation_setting(self, vin, field, value):
            self.calls.append((field, value))
            return True

    expected = {
        "climatisation_window_heating": "windowHeatingEnabled",
        "climatisation_at_unlock": "climatizationAtUnlock",
        "climatisation_zone_front_left": "zoneFrontLeftEnabled",
        "climatisation_zone_front_right": "zoneFrontRightEnabled",
        "climatisation_zone_rear_left": "zoneRearLeftEnabled",
        "climatisation_zone_rear_right": "zoneRearRightEnabled",
    }
    seen = {}
    for d in SWITCH_DESCRIPTIONS:
        if d.key not in expected:
            continue
        conn = Conn()
        asyncio.run(d.turn_on_fn(conn, "VIN1"))
        asyncio.run(d.turn_off_fn(conn, "VIN1"))
        seen[d.key] = conn.calls

    assert set(seen) == set(expected), "a setting switch went missing"
    for key, field in expected.items():
        assert seen[key] == [(field, True), (field, False)], key


def test_the_lambdas_bound_their_own_field():
    """Closures over a loop variable would give every switch the last field.
    This is the case that would make six switches all write the rear right seat."""
    from custom_components.audiconnect.switch import SWITCH_DESCRIPTIONS

    fields = set()

    class Conn:
        async def set_climatisation_setting(self, vin, field, value):
            fields.add(field)
            return True

    for d in SWITCH_DESCRIPTIONS:
        if d.key.startswith("climatisation_"):
            asyncio.run(d.turn_on_fn(Conn(), "VIN1"))
    assert len(fields) == 6, f"expected six distinct fields, got {fields}"
