"""Every switch and button description is exercised against the real connection
class, not a stub that accepts anything.

The climatisation switch shipped calling set_vehicle_climatisation(vin, True),
which raises NotImplementedError upstream: the legacy start action is dead. The
description looked correct and no test touched the callable, so the switch could
never turn on. That control is now a climate entity (see
test_climate_entity.py), but the class of bug is what these tests guard: they
call every description's callables against a recording double that refuses any
method AudiConnectAccount does not define.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from custom_components.audiconnect.audi_connect_account import AudiConnectAccount
from custom_components.audiconnect.button import BUTTON_DESCRIPTIONS
from custom_components.audiconnect.switch import SWITCH_DESCRIPTIONS

VIN = "WAUZZZ00000000001"

# Methods the descriptions are allowed to call, each verified below to exist on
# AudiConnectAccount and to be usable for that direction.
LIVE_METHODS = {
    "set_vehicle_pre_heater",
    "set_battery_charger",
    "set_vehicle_window_heating",
}


class RecordingConnection:
    """Records calls; raises on anything AudiConnectAccount does not define."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if not hasattr(AudiConnectAccount, name):
            raise AttributeError(f"AudiConnectAccount has no method {name!r}")

        async def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return True

        return _call


def calls_of(fn):
    conn = RecordingConnection()
    asyncio.run(fn(conn, VIN))
    return conn.calls


@pytest.mark.parametrize("description", SWITCH_DESCRIPTIONS, ids=lambda d: d.key)
def test_switch_callables_hit_methods_that_exist(description):
    for fn in (description.turn_on_fn, description.turn_off_fn):
        [(name, args, _)] = calls_of(fn)
        assert name in LIVE_METHODS
        assert args[0] == VIN


@pytest.mark.parametrize("description", BUTTON_DESCRIPTIONS, ids=lambda d: d.key)
def test_button_callables_are_awaitable(description):
    """Buttons take the account, not the connection, so just check the callable
    produces a coroutine rather than blowing up at definition time."""

    class Account:
        connection = RecordingConnection()

        def __getattr__(self, name):
            async def _call(*a, **k):
                return True

            return _call

    result = description.press_fn(Account(), VIN)
    assert inspect.isawaitable(result)
    asyncio.run(result)
