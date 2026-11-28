"""Consumer-only HA presentation. No engineering routes or cloud operations."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .. import _device_entry_ids
from ..const import DOMAIN
from ..local_extensions import get_local_dealer, update_local_dealer_options
from .engine import V3Engine
from .product_contract import (
    canonical_entity_translation_key,
    entity_key,
    product_inventory,
)
from .runtime import (
    V3_DEFAULT,
    V3_ENABLED,
    V3_RUNTIME_OPTION,
    dashboard_enabled,
    workbench_enabled,
)
from .trip_archive import trip_history_payload


def _loaded_engine(entry):
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
        or entry.options.get(V3_RUNTIME_OPTION, V3_DEFAULT) != V3_ENABLED
    ):
        return None
    engine = getattr(getattr(entry, "runtime_data", None), "v3", None)
    return engine if isinstance(engine, V3Engine) else None


def _scoped_vehicle(hass, registered):
    """Resolve exact native registry ownership, never a client-supplied VIN."""
    if (
        registered is None
        or registered.platform != DOMAIN
        or registered.disabled_by is not None
        or registered.hidden_by is not None
        or not registered.device_id
        or not registered.config_entry_id
    ):
        return None
    entry = hass.config_entries.async_get_entry(registered.config_entry_id)
    engine = _loaded_engine(entry)
    if engine is None or not dashboard_enabled(entry.options):
        return None
    key = entity_key(registered.unique_id, entry.entry_id)
    if key not in product_inventory()["entities"]:
        return None
    vin = registered.unique_id.split("_", 1)[0].lower()
    vehicle = engine.vehicles.get(vin)
    if vehicle is None or not vehicle.inventory_present:
        return None
    device = dr.async_get(hass).async_get(registered.device_id)
    if device is None or (DOMAIN, vin) not in device.identifiers:
        return None
    owners = _device_entry_ids(device)
    if entry.entry_id not in owners:
        return None
    # A legacy shared device must not resolve through two loaded Audi accounts.
    for other_id in owners - {entry.entry_id}:
        other = _loaded_engine(hass.config_entries.async_get_entry(other_id))
        if (
            other is not None
            and vin in other.vehicles
            and other.vehicles[vin].inventory_present
        ):
            return None
    return entry, vehicle, device, key


def _display_name(value, vin, fallback):
    if not isinstance(value, str) or not value.strip() or vin in value.lower():
        return fallback
    return value


def vehicle_list(hass, user):
    """Expose only permitted native product entities, never raw VINs or options."""
    registry = er.async_get(hass)
    vehicles = {}
    conflicts = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if _loaded_engine(entry) is None or not dashboard_enabled(entry.options):
            continue
        for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
            if not user.permissions.check_entity(registered.entity_id, POLICY_READ):
                continue
            scoped = _scoped_vehicle(hass, registered)
            if scoped is None:
                continue
            owner, car, device, key = scoped
            vin = car.vin.lower()
            row = vehicles.setdefault(
                device.id,
                {
                    "device_id": device.id,
                    "entry_id": owner.entry_id,
                    "name": _display_name(
                        device.name_by_user or device.name, vin, "Audi"
                    ),
                    "entities": [],
                    **(
                        {
                            "engineering_context": {
                                "entry_id": owner.entry_id,
                                "vin": car.vin,
                            }
                        }
                        if getattr(user, "is_admin", False)
                        and workbench_enabled(owner.options)
                        else {}
                    ),
                },
            )
            if row["entry_id"] != owner.entry_id:
                conflicts.add(device.id)
                continue
            definition = product_inventory()["entities"][key]
            row["entities"].append(
                {
                    "entity_id": registered.entity_id,
                    "key": key,
                    "name": _display_name(
                        registered.name or registered.original_name,
                        vin,
                        definition.get("name")
                        or key.split(".", 1)[1].replace("_", " "),
                    ),
                    "translation_key": None
                    if registered.name
                    or key == "number.charge_profile_{profile_id}_target_soc"
                    else canonical_entity_translation_key(key, car),
                    "control": user.permissions.check_entity(
                        registered.entity_id, POLICY_CONTROL
                    ),
                }
            )
    return [
        {
            **{key: value for key, value in row.items() if key != "entry_id"},
            "entities": sorted(row["entities"], key=lambda item: item["key"]),
            **(
                {"configuration_entry": row["entry_id"]}
                if getattr(user, "is_admin", False)
                else {}
            ),
        }
        for ident, row in sorted(vehicles.items())
        if ident not in conflicts
    ]


@cache
def _panel_labels():
    """Static translation data; load outside the HA event loop."""
    return json.loads(
        (Path(__file__).parent / "frontend" / "vehicle_labels.json").read_text(
            encoding="utf-8"
        )
    )


@websocket_api.websocket_command({vol.Required("type"): "audiconnect/vehicle/list"})
@websocket_api.async_response
async def ws_vehicle_list(hass, connection, msg):
    labels = await hass.async_add_executor_job(_panel_labels)
    connection.send_result(
        msg["id"], {"vehicles": vehicle_list(hass, connection.user), "labels": labels}
    )


def vehicle_trips(
    hass,
    user,
    entity_id,
    *,
    offset=0,
    limit=100,
    export=False,
    start_date=None,
    end_date=None,
):
    """Read the existing archive only through a permitted native history entity."""
    if not user.permissions.check_entity(entity_id, POLICY_READ):
        raise PermissionError("Trip history unavailable")
    scoped = _scoped_vehicle(hass, er.async_get(hass).async_get(entity_id))
    if scoped is None or scoped[3] != "sensor.trip_history":
        raise ValueError("Trip history unavailable")
    return trip_history_payload(
        scoped[1].trip_history,
        offset=offset,
        limit=limit,
        export=export,
        start_date=start_date,
        end_date=end_date,
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/vehicle/trips",
        vol.Required("entity_id"): str,
        vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0, max=10000)),
        vol.Optional("limit", default=100): vol.All(int, vol.Range(min=1, max=250)),
        vol.Optional("export", default=False): bool,
        vol.Optional("start_date"): vol.All(str, vol.Length(min=10, max=10)),
        vol.Optional("end_date"): vol.All(str, vol.Length(min=10, max=10)),
    }
)
@websocket_api.async_response
async def ws_vehicle_trips(hass, connection, msg):
    """The native trip-history entity's read permission scopes the archive."""
    try:
        connection.send_result(
            msg["id"],
            vehicle_trips(
                hass,
                connection.user,
                msg["entity_id"],
                offset=msg["offset"],
                limit=msg["limit"],
                export=msg["export"],
                start_date=msg.get("start_date"),
                end_date=msg.get("end_date"),
            ),
        )
    except PermissionError:
        connection.send_error(msg["id"], "unauthorized", "Trip history unavailable")
    except (KeyError, ValueError, RuntimeError):
        connection.send_error(msg["id"], "invalid_request", "Trip history unavailable")


def local_service_details(hass, user, entity_id, updates=None):
    """One local options owner, with the same validation as HA OptionsFlow."""
    if not user.is_admin or not user.permissions.check_entity(entity_id, POLICY_READ):
        raise PermissionError("Service settings unavailable")
    scoped = _scoped_vehicle(hass, er.async_get(hass).async_get(entity_id))
    if scoped is None or scoped[3] != "sensor.local_dealer":
        raise ValueError("Service settings unavailable")
    entry, vehicle, _, _ = scoped
    if updates is not None:
        options = update_local_dealer_options(dict(entry.options), vehicle.vin, updates)
        if options != dict(entry.options):
            hass.config_entries.async_update_entry(entry, options=options)
        return get_local_dealer(options, vehicle.vin)
    return get_local_dealer(entry.options, vehicle.vin)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/vehicle/service_details",
        vol.Required("entity_id"): str,
        vol.Optional("updates"): dict,
    }
)
@websocket_api.async_response
async def ws_service_details(hass, connection, msg):
    """Read or update only the selected vehicle's local service settings."""
    try:
        connection.send_result(
            msg["id"],
            {
                "settings": local_service_details(
                    hass, connection.user, msg["entity_id"], msg.get("updates")
                )
            },
        )
    except PermissionError:
        connection.send_error(msg["id"], "unauthorized", "Service settings unavailable")
    except (KeyError, ValueError, RuntimeError):
        connection.send_error(msg["id"], "invalid_request", "Check service details")
