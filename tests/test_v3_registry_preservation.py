"""V3 switches runtime, not Home Assistant device registry identity."""

from __future__ import annotations

from types import SimpleNamespace as NS

from custom_components.audiconnect import _async_cleanup_orphaned_devices


def test_v3_runtime_never_prunes_existing_device_entries(monkeypatch):
    """A failed or partial inventory cannot delete a user's climate automation."""
    from custom_components.audiconnect import dr

    monkeypatch.setattr(
        dr,
        "async_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("V3 must not inspect/prune registry")
        ),
    )
    entry = NS(runtime_data=NS(v3=object()), entry_id="entry")
    _async_cleanup_orphaned_devices(None, entry)


def test_v2_empty_initial_inventory_is_not_a_delete_signal(monkeypatch):
    from custom_components.audiconnect import dr

    monkeypatch.setattr(
        dr,
        "async_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("No device deletion with an empty inventory")
        ),
    )
    entry = NS(
        runtime_data=NS(v3=None, account=NS(config_vehicles=[])),
        entry_id="entry",
    )
    _async_cleanup_orphaned_devices(None, entry)


def test_explicit_entry_removal_cleans_only_owned_storage(monkeypatch):
    import asyncio

    from homeassistant.helpers import storage
    from custom_components.audiconnect import async_remove_entry
    from custom_components.audiconnect.v3 import registry_lifecycle

    removed = []

    class MemoryStore:
        def __init__(self, hass, version, key, **kwargs):
            self.key = key

        async def async_remove(self):
            removed.append(self.key)

    monkeypatch.setattr(storage, "Store", MemoryStore)
    monkeypatch.setattr(registry_lifecycle, "Store", MemoryStore)
    asyncio.run(async_remove_entry(None, NS(entry_id="entry")))
    assert set(removed) == {
        "audiconnect_v3_entry_profiles",
        "audiconnect_v3_entry_trips",
        "audiconnect_v3_entry_hidden_entities",
    }
