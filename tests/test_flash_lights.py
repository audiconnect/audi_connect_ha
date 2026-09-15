"""Flashing the lights, and never sounding the horn.

The endpoint takes a mode, and "honkandflash" on the same path wakes the
street. The mode is therefore hard-coded rather than parameterised, and these
tests exist mostly to keep it that way: several of them fail if anyone adds a
way for a caller to choose.

Contract (path, method, body) is from WeConnect-python, which drives the same
Cariad BFF. The probe that preceded it returned 404 on GET for every candidate
path, which is consistent: there is no GET route.
"""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from custom_components.audiconnect import audi_services
from custom_components.audiconnect.button import BUTTON_DESCRIPTIONS

VIN = "WAUZZZ00000000001"
LAT, LON = 51.5, -0.12


class RecordingApi:
    def __init__(self):
        self.calls = []

    async def request(self, method, url, data=None, headers=None, **kw):
        self.calls.append({"method": method, "url": url, "data": data})
        return None


def service():
    svc = object.__new__(audi_services.AudiService)
    svc._api = RecordingApi()
    svc._bearer_token_json = {"access_token": "x"}
    svc._country = "DE"
    svc._api_level = 1
    return svc


def sent(svc):
    call = svc._api.calls[0]
    return call, json.loads(call["data"])


# --- the request ------------------------------------------------------------------


def test_it_posts_to_honkandflash():
    svc = service()
    asyncio.run(svc.flash_lights(VIN, LAT, LON))
    call, _ = sent(svc)
    assert call["method"] == "POST"
    assert call["url"].endswith(f"/vehicles/{VIN}/honkandflash")


def test_the_body_carries_the_position_the_api_requires():
    svc = service()
    asyncio.run(svc.flash_lights(VIN, LAT, LON))
    _, body = sent(svc)
    assert body["userPosition"] == {"latitude": LAT, "longitude": LON}


def test_the_duration_is_sent_and_defaults_to_ten():
    svc = service()
    asyncio.run(svc.flash_lights(VIN, LAT, LON))
    assert sent(svc)[1]["duration_s"] == 10
    svc2 = service()
    asyncio.run(svc2.flash_lights(VIN, LAT, LON, 3))
    assert sent(svc2)[1]["duration_s"] == 3


# --- the horn ---------------------------------------------------------------------


def test_the_mode_is_always_flash():
    svc = service()
    asyncio.run(svc.flash_lights(VIN, LAT, LON))
    assert sent(svc)[1]["mode"] == "flash"


def test_no_caller_can_choose_the_mode():
    """The signature must not offer a mode. If one is ever added, this fails
    before anyone discovers it by hearing it."""
    params = inspect.signature(audi_services.AudiService.flash_lights).parameters
    assert "mode" not in params
    assert set(params) == {"self", "vin", "latitude", "longitude", "duration_s"}


def _code_without_docstring(fn) -> str:
    """The docstring explains why the horn is excluded and so mentions it. Only
    the executable part is meaningful here."""
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    body = node.body[1:] if ast.get_docstring(node) else node.body
    return "\n".join(ast.unparse(stmt) for stmt in body)


def test_the_mode_is_a_literal_in_the_code():
    """Not a variable, not a default, not derived from an argument. The horn is
    one string away on this endpoint, so the value is pinned in place."""
    code = _code_without_docstring(audi_services.AudiService.flash_lights)
    assert "'mode': 'flash'" in code or '"mode": "flash"' in code
    # The only honkandflash left is the URL path.
    assert code.count("honkandflash") == 1


def test_the_account_layer_names_no_mode_at_all():
    from custom_components.audiconnect.audi_connect_account import AudiConnectAccount

    code = _code_without_docstring(AudiConnectAccount.flash_lights)
    assert "honk" not in code.lower()
    assert "mode" not in code.lower()


# --- the entity -------------------------------------------------------------------


class Vehicle:
    def __init__(self, caps=None, position=None):
        self.vin = VIN
        if position is not None:
            self.position = position

    def has_capability(self, capability):
        return None if not self._caps else capability in self._caps

    _caps = None


def flash_description():
    return next(d for d in BUTTON_DESCRIPTIONS if d.key == "flash_lights")


def test_the_button_exists_on_a_capable_car():
    v = Vehicle()
    v._caps = {"honkAndFlash"}
    assert flash_description().supported_fn(v) is True


def test_no_button_on_a_car_without_the_capability():
    v = Vehicle(position={"latitude": LAT})
    v._caps = {"charging"}
    assert flash_description().supported_fn(v) is False


def test_a_car_that_reports_no_capabilities_falls_back_to_position():
    with_pos = Vehicle(position={"latitude": LAT})
    without = Vehicle()
    assert flash_description().supported_fn(with_pos) is True
    assert flash_description().supported_fn(without) is False


# --- refusing to fire without a position ------------------------------------------


class Connection:
    """Exercises AudiConnectAccount.flash_lights without the HTTP boundary."""

    def __init__(self, position):
        from custom_components.audiconnect.audi_connect_account import (
            AudiConnectAccount,
        )

        self.obj = object.__new__(AudiConnectAccount)
        self.obj._loggedin = True
        # `vehicles` is a read-only property over `_vehicles`.
        self.obj._vehicles = [type("V", (), {"vin": VIN, "position": position})()]
        self.sent = []

        class Svc:
            async def flash_lights(_s, *a):
                self.sent.append(a)

        self.obj._audi_service = Svc()


@pytest.mark.parametrize("position", [None, {}, {"latitude": LAT}, {"longitude": LON}])
def test_it_refuses_rather_than_sending_a_request_the_api_will_reject(position):
    c = Connection(position)
    assert asyncio.run(c.obj.flash_lights(VIN)) is False
    assert c.sent == []


def test_it_sends_when_the_position_is_known():
    c = Connection({"latitude": LAT, "longitude": LON})
    assert asyncio.run(c.obj.flash_lights(VIN)) is True
    assert c.sent == [(VIN, LAT, LON, 10)]
