"""Preserve Home Assistant entity identity when switching Audi runtimes.

V2 and V3 own the SAME config entry and HA devices. Never disable historical
V2 entity-registry entries merely because a V3 API value is missing or old.
The entity may be temporarily unavailable until V3 provides a compatible
implementation, but its entity_id, unique_id, automations and history survive.

Undo only recorded V2 disablement. Explicit retired V3-only pilot identities
and duplicate account cloud actions are the sole retirement exceptions.
Preserve registry history, user choices and account ownership.
"""

from __future__ import annotations

import asyncio
from typing import Any
from weakref import WeakValueDictionary
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from .product_contract import (
    retired_pilot_entity,
    account_cloud_refresh_vin,
    entity_key,
    compatibility_hidden,
    canonical_entity_category,
    product_inventory,
    canonical_entity_name,
    superseded_control_button,
)
from homeassistant.const import EntityCategory


# Weak values keep locks alive only while a transaction or waiter owns them.
# Entry identity is shared across reload and rollback, not runtime-instance scoped.
_VISIBILITY_LOCKS = WeakValueDictionary()


def _visibility_lock(hass, entry_id):
    key = (id(hass), entry_id)
    lock = _VISIBILITY_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _VISIBILITY_LOCKS[key] = lock
    return lock


def _visibility_store(hass, entry_id):
    return Store(hass, 1, f"audiconnect_v3_{entry_id}_hidden_entities")


async def async_remove_visibility(hass, entry_id):
    """Remove entry-owned migration state only on explicit entry removal."""
    async with _visibility_lock(hass, entry_id):
        await _visibility_store(hass, entry_id).async_remove()


async def async_apply_v3_entity_visibility(
    hass: Any, entry: Any, enabled: bool, *, expected_engine=None
) -> None:
    """Serialize changes and reject notifications from unloaded runtimes."""
    async with _visibility_lock(hass, entry.entry_id):
        if expected_engine is not None and (
            entry.state is not ConfigEntryState.LOADED
            or getattr(getattr(entry, "runtime_data", None), "v3", None)
            is not expected_engine
        ):
            return
        await _apply_visibility(hass, entry, enabled)


async def _apply_visibility(hass, entry, enabled):
    """Restore owned historical changes and apply reversible V3 presentation.

    Keep stable registry IDs and never override user names or visibility.
    This migration is intentionally idempotent in either direction.
    """
    store = _visibility_store(hass, entry.entry_id)
    data = await store.async_load() or {}
    if not isinstance(data, dict):
        data = {}

    recorded = set(data.get("entity_ids", []))
    registry = er.async_get(hass)
    owned = {
        entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    for entity_id in recorded & owned:
        current = registry.async_get(entity_id)
        if (
            current is not None
            and current.disabled_by == er.RegistryEntryDisabler.INTEGRATION
        ):
            registry.async_update_entity(entity_id, disabled_by=None)

    # Retire exact source-proven pilot IDs; keep registry records and user choices.
    runtime = getattr(entry, "runtime_data", None)
    engine = getattr(runtime, "v3", None)
    primary = None
    duplicate_ids = set(data.get("retired_duplicate_cloud_refresh", []))
    if engine is not None:
        # Retain the account anchor over reload and inventory reordering. If
        # the anchor disappears, choose a present vehicle only during setup.
        primary = getattr(engine, "cloud_refresh_vin", None)
        if primary is None:
            saved = data.get("cloud_refresh_anchor")
            primary = (
                saved
                if saved in engine.vehicles and engine.vehicles[saved].inventory_present
                else account_cloud_refresh_vin(engine.vehicles)
            )
            engine.cloud_refresh_vin = primary

    for entity_id in owned:
        current = registry.async_get(entity_id)
        unique_id = getattr(current, "unique_id", "")
        suffix = "_button_v3_refresh_cloud"
        old_vin = unique_id[: -len(suffix)] if unique_id.endswith(suffix) else ""
        duplicate_refresh = bool(
            primary and len(old_vin) == 17 and old_vin.isalnum() and old_vin != primary
        )
        if current is not None and (
            retired_pilot_entity(unique_id) or duplicate_refresh
        ):
            if current.disabled_by is None:
                registry.async_update_entity(
                    entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
                )
                if duplicate_refresh:
                    duplicate_ids.add(unique_id)
        elif (
            primary
            and unique_id == f"{primary}{suffix}"
            and unique_id in duplicate_ids
            and current.disabled_by == er.RegistryEntryDisabler.INTEGRATION
        ):
            registry.async_update_entity(entity_id, disabled_by=None)
            duplicate_ids.discard(unique_id)

    # Reversible default visibility migration, never disable/delete compatibility IDs.
    hidden = set(data.get("b10_hidden", []))
    reviewed = set(data.get("b10_reviewed", []))
    categories = dict(data.get("b10_categories", {}))
    names = dict(data.get("original_names", {}))
    disabled_compat = set(data.get("disabled_compatibility", []))
    stateful_hidden = set(data.get("stateful_hidden_buttons", []))
    stateful_reviewed = set(data.get("stateful_reviewed_buttons", []))
    for entity_id in owned:
        current = registry.async_get(entity_id)
        uid = getattr(current, "unique_id", "")
        key = entity_key(uid, entry.entry_id)
        if not key or not hasattr(current, "hidden_by"):
            continue
        localized = (getattr(current, "translation_key", None) or "").startswith("v3_")
        updates = {}
        if not enabled:
            if (
                uid in disabled_compat
                and current.disabled_by == er.RegistryEntryDisabler.INTEGRATION
            ):
                updates["disabled_by"] = None
            if (
                uid in hidden | stateful_hidden
                and current.hidden_by == er.RegistryEntryHider.INTEGRATION
            ):
                updates["hidden_by"] = None
            if uid in categories:
                previous, applied = categories[uid]
                if getattr(current.entity_category, "value", None) == applied:
                    updates["entity_category"] = (
                        EntityCategory(previous) if previous else None
                    )
            if localized:
                updates["translation_key"] = None
            if uid in names and hasattr(current, "original_name"):
                previous, applied = names[uid]
                if current.original_name == applied or localized:
                    updates["original_name"] = previous
            if updates:
                registry.async_update_entity(entity_id, **updates)
            continue
        if engine is None:
            continue
        car = engine.vehicles.get(uid.split("_", 1)[0].lower())
        definition = product_inventory()["entities"].get(key)
        if car is None and (not definition or definition.get("scope") != "account"):
            continue
        # HA owns localized runtime labels. Clean historical labels only until
        # native registration supplies its translation key. User names and IDs
        # are never rewritten.
        label = None if localized else canonical_entity_name(key, car)
        if (
            label
            and "{profile_id}" not in label
            and hasattr(current, "original_name")
            and current.original_name != label
        ):
            previous = names.get(uid, [current.original_name])[0]
            names[uid] = [previous, label]
            updates["original_name"] = label
        desired = canonical_entity_category(key)
        if definition is not None:
            category = EntityCategory(desired) if desired else None
            if current.entity_category != category:
                updates["entity_category"] = category
        if (
            key == "switch.climate_quick_control"
            and current.disabled_by is None
            and (
                current.hidden_by == er.RegistryEntryHider.INTEGRATION
                or uid not in reviewed
            )
            and current.hidden_by != er.RegistryEntryHider.USER
            and uid not in disabled_compat
        ):
            updates["disabled_by"] = er.RegistryEntryDisabler.INTEGRATION
            disabled_compat.add(uid)
        # Stateful aliases are hidden only when a switch can actually be
        # projected. Restore integration-owned visibility if evidence is absent
        # on a later setup; never override a user-hidden or disabled entry.
        superseded = car is not None and superseded_control_button(engine, car, key)
        if car is not None and uid in stateful_hidden and not superseded:
            if current.hidden_by == er.RegistryEntryHider.INTEGRATION:
                updates["hidden_by"] = None
            stateful_hidden.discard(uid)
            stateful_reviewed.discard(uid)
        elif superseded and uid not in stateful_reviewed:
            stateful_reviewed.add(uid)
            if current.hidden_by is None and current.disabled_by is None:
                updates["hidden_by"] = er.RegistryEntryHider.INTEGRATION
                stateful_hidden.add(uid)
        if car is not None and uid not in reviewed and compatibility_hidden(car, key):
            reviewed.add(uid)
            if current.hidden_by is None and current.disabled_by is None:
                updates["hidden_by"] = er.RegistryEntryHider.INTEGRATION
                hidden.add(uid)
        if "entity_category" in updates:
            previous = categories.get(
                uid, [getattr(current.entity_category, "value", None)]
            )[0]
            categories[uid] = [
                previous,
                getattr(updates["entity_category"], "value", None),
            ]
        if updates:
            registry.async_update_entity(entity_id, **updates)
    if not enabled:
        hidden.clear()
        reviewed.clear()
        categories.clear()
        names.clear()
        disabled_compat.clear()
        stateful_hidden.clear()
        stateful_reviewed.clear()

    # Historical V2 disable records are cleared; the cloud anchor is local
    # account metadata. Never save pilot retirement as a V2 restore candidate.
    result = {"entity_ids": []}
    if primary or data.get("cloud_refresh_anchor"):
        result["cloud_refresh_anchor"] = primary or data["cloud_refresh_anchor"]
    if duplicate_ids:
        result["retired_duplicate_cloud_refresh"] = sorted(duplicate_ids)
    if hidden:
        result["b10_hidden"] = sorted(hidden)
    if reviewed:
        result["b10_reviewed"] = sorted(reviewed)
    if categories:
        result["b10_categories"] = categories
    if names:
        result["original_names"] = names
    if disabled_compat:
        result["disabled_compatibility"] = sorted(disabled_compat)
    if stateful_hidden:
        result["stateful_hidden_buttons"] = sorted(stateful_hidden)
    if stateful_reviewed:
        result["stateful_reviewed_buttons"] = sorted(stateful_reviewed)
    await store.async_save(result)
