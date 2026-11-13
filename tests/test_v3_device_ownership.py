"""HA device ownership is authoritative for service routing."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError

from custom_components import audiconnect

VIN = "wauzzz4m0md123456"


def entry(ident, *, v3=None, present=True, loaded=True):
    account = SimpleNamespace(
        config_vehicles=[
            SimpleNamespace(vehicle=SimpleNamespace(vin=VIN))
        ] if present else [],
    )
    return SimpleNamespace(
        entry_id=ident,
        state=ConfigEntryState.LOADED if loaded else ConfigEntryState.NOT_LOADED,
        runtime_data=SimpleNamespace(v3=v3, account=account),
    )


def resolve(monkeypatch, entries, owners, *, identifiers=None, missing=False):
    device = SimpleNamespace(
        identifiers={("audiconnect", VIN)} if identifiers is None else identifiers,
        config_entries=set(owners),
    )
    monkeypatch.setattr(
        audiconnect.dr,
        "async_get",
        lambda hass: SimpleNamespace(async_get=lambda ident: None if missing else device),
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_entries=lambda domain: entries)
    )
    service = SimpleNamespace(data={"device_id": "device"})
    return audiconnect._resolve_service_call(hass, service)


def test_registered_v2_owner_wins_over_unrelated_v3(monkeypatch):
    v3 = Mock(spec=audiconnect.V3Engine)
    unrelated = entry("unrelated", v3=v3)
    owner = entry("owner")
    assert resolve(monkeypatch, [unrelated, owner], ["owner"]) == (
        VIN, owner.runtime_data.account
    )
    v3.require_vehicle.assert_not_called()


def test_registered_v3_owner_is_used(monkeypatch):
    v3 = Mock(spec=audiconnect.V3Engine)
    owner = entry("owner", v3=v3)
    assert resolve(monkeypatch, [entry("other"), owner], ["owner"]) == (VIN, v3)
    v3.require_vehicle.assert_called_once_with(VIN)


@pytest.mark.parametrize("owners", [[], ["first", "second"]])
def test_missing_or_shared_owner_fails_closed(monkeypatch, owners):
    with pytest.raises(HomeAssistantError, match="owning account"):
        resolve(monkeypatch, [entry("first"), entry("second")], owners)


def test_unloaded_owner_does_not_fall_back(monkeypatch):
    with pytest.raises(HomeAssistantError, match="not loaded"):
        resolve(monkeypatch, [entry("owner", loaded=False), entry("other")], ["owner"])


def test_missing_inventory_does_not_fall_back(monkeypatch):
    with pytest.raises(HomeAssistantError, match="not present"):
        resolve(monkeypatch, [entry("owner", present=False), entry("other")], ["owner"])


def test_v3_missing_inventory_does_not_fall_back(monkeypatch):
    v3 = Mock(spec=audiconnect.V3Engine)
    v3.require_vehicle.side_effect = ValueError("missing")
    with pytest.raises(HomeAssistantError, match="not present"):
        resolve(monkeypatch, [entry("owner", v3=v3), entry("other")], ["owner"])


def test_unknown_device_fails_closed(monkeypatch):
    with pytest.raises(HomeAssistantError, match="not found"):
        resolve(monkeypatch, [], [], missing=True)


@pytest.mark.parametrize(
    "identifiers",
    [set(), {("audiconnect", VIN), ("audiconnect", "another")}, {("other", VIN)}],
)
def test_missing_or_ambiguous_vin_fails_closed(monkeypatch, identifiers):
    with pytest.raises(HomeAssistantError, match="vehicle identity"):
        resolve(monkeypatch, [entry("owner")], ["owner"], identifiers=identifiers)
