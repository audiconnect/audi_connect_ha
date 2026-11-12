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
