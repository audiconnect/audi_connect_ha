"""Critical HA services must not silently swallow rejected Q8 commands."""

from __future__ import annotations
import asyncio
from types import SimpleNamespace as NS
import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.audiconnect.audi_account import AudiAccount
from custom_components.audiconnect.const import (
    CONF_ACTION,
    CONF_CHARGE_MODE,
    CONF_TARGET_SOC,
)


class Connection:
    def __init__(self, *, accepted=False):
        self.accepted = accepted
        self.calls = []

    async def set_vehicle_lock(self, vin, lock):
        self.calls.append(("lock", vin, lock))
        return self.accepted

    async def start_climate_control(self, *args):
        self.calls.append(("climate", args))
        return self.accepted

    async def set_charge_mode(self, vin, mode):
        self.calls.append(("mode", vin, mode))
        return self.accepted

    async def set_target_state_of_charge(self, vin, target):
        self.calls.append(("soc", vin, target))
        return self.accepted


def account(result=False):
    obj = object.__new__(AudiAccount)
    conn = Connection(accepted=result)
    obj.connection = conn
    return obj, conn


@pytest.mark.parametrize("action", ["lock", "unlock"])
def test_vehicle_actions_fail_loudly_when_connection_rejects(action):
    obj, conn = account(result=False)
    with pytest.raises(HomeAssistantError, match=action):
        asyncio.run(
            obj.execute_vehicle_action(
                "EXAMPLEVIN00000001", NS(data={CONF_ACTION: action})
            )
        )
    assert len(conn.calls) == 1


def test_lock_success_returns_normally():
    obj, conn = account(result=True)
    asyncio.run(
        obj.execute_vehicle_action("EXAMPLEVIN00000001", NS(data={CONF_ACTION: "lock"}))
    )
    assert conn.calls[0][0] == "lock"


def test_legacy_named_start_climatisation_uses_modern_bodyless_start():
    obj, conn = account(result=True)
    asyncio.run(
        obj.execute_vehicle_action(
            "EXAMPLEVIN00000001", NS(data={CONF_ACTION: "start_climatisation"})
        )
    )
    assert conn.calls == [("climate", ("examplevin00000001",))]


def test_legacy_named_start_climatisation_reports_rejection():
    obj, _ = account(result=False)
    with pytest.raises(HomeAssistantError, match="start climatisation"):
        asyncio.run(
            obj.execute_vehicle_action(
                "EXAMPLEVIN00000001", NS(data={CONF_ACTION: "start_climatisation"})
            )
        )


def test_climate_direct_service_rejection_raises():
    obj, conn = account(result=False)
    with pytest.raises(HomeAssistantError, match="start climate control"):
        asyncio.run(obj.start_climate_control("EXAMPLEVIN00000001", NS(data={})))
    assert conn.calls[0][0] == "climate"


@pytest.mark.parametrize(
    ("method", "data"),
    [
        ("set_charge_mode", {CONF_CHARGE_MODE: "timer"}),
        ("set_target_soc", {CONF_TARGET_SOC: 80}),
    ],
)
def test_charge_services_rejection_raises(method, data):
    obj, conn = account(result=False)
    with pytest.raises(HomeAssistantError):
        asyncio.run(getattr(obj, method)("EXAMPLEVIN00000001", NS(data=data)))
    assert len(conn.calls) == 1


def test_unknown_action_cannot_be_reported_as_success():
    obj, _ = account()
    with pytest.raises(HomeAssistantError, match="Unknown"):
        asyncio.run(
            obj.execute_vehicle_action(
                "EXAMPLEVIN00000001", NS(data={CONF_ACTION: "not_existing"})
            )
        )
