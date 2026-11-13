"""Administrator-only development panel and V3 WebSocket operations.

The dashboard never receives auth tokens, raw cloud dumps, or VIN-containing
diagnostic exports. Admin actions may address their own authenticated VIN.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState

from ..const import DOMAIN
from .engine import V3Engine
from .runtime import V3_DEFAULT, V3_ENABLED, V3_RUNTIME_OPTION

_PANEL = "audiconnect-v3"
_READY_KEY = "audiconnect_v3_dashboard_registered"
_HANDLERS_KEY = "audiconnect_v3_dashboard_commands_registered"


def _workbench_engine(entry: Any) -> V3Engine:
    """Only a loaded, opted-in integration can expose engineering operations."""
    if entry is None or entry.domain != DOMAIN:
        raise ValueError("Unknown Audi integration")
    if entry.options.get(
        V3_RUNTIME_OPTION, V3_DEFAULT
    ) != V3_ENABLED or not entry.options.get("v3_development_workbench", False):
        raise ValueError("V3 Development Workbench is not enabled")
    runtime = getattr(entry, "runtime_data", None)
    engine = getattr(runtime, "v3", None)
    if entry.state is not ConfigEntryState.LOADED or not isinstance(engine, V3Engine):
        raise ValueError("V3 integration is not loaded")
    return engine


def _engine(hass: Any, entry_id: str) -> V3Engine:
    return _workbench_engine(hass.config_entries.async_get_entry(entry_id))


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "audiconnect/v3/list"})
@websocket_api.async_response
async def ws_list(hass, connection, msg):
    records = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        try:
            engine = _workbench_engine(entry)
        except ValueError:
            continue
        records.append(
            {
                "entry_id": entry.entry_id,
                "vehicles": [
                    {
                        "vin": car.vin,
                        "name": car.name,
                        "model": car.model,
                        "api_family": "mbb"
                        if car.context.auth == "legacy"
                        else "cariad",
                        "climate_state": car.climate_state,
                        "status_route": car.climate_source,
                        "age_minutes": car.capture_age_minutes,
                        "start_enabled": engine.control_enabled(car.vin, "start"),
                        "stop_enabled": engine.control_enabled(car.vin, "stop"),
                    }
                    for car in engine.vehicles.values()
                    if car.inventory_present
                ],
                "poll_success": engine.last_cloud_poll_success.isoformat()
                if engine.last_cloud_poll_success
                else None,
                "quota": engine.transport.remaining_calls,
            }
        )
    connection.send_result(msg["id"], {"integrations": records})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/status",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
    }
)
@websocket_api.async_response
async def ws_status(hass, connection, msg):
    try:
        from .capability_status import build_status_report

        engine = _engine(hass, msg["entry_id"])
        vehicle = engine.require_vehicle(msg["vin"])
        profile = engine.profiles[vehicle.vin.lower()]
        engine.commands.refresh_bindings()
        report = build_status_report(vehicle, profile)
        report["normal_command"] = (
            profile.last_command.snapshot() if profile.last_command else None
        )
        from .command_journal import unresolved_normal_commands

        # Only the latest unresolved routine command per capability is a current
        # warning; security review items remain visible until acknowledged.
        latest_by_capability = {
            row.capability: row
            for row in getattr(profile, "command_journal", ())
            if row.origin == "home_assistant"
        }
        report["unresolved_commands"] = [
            {**row.snapshot(), "review_required": row.requires_review}
            for row in unresolved_normal_commands(profile)
            if row.requires_review
            or latest_by_capability.get(row.capability, row) is row
        ]
        report["command_journal"] = [row.snapshot() for row in profile.command_journal]
        report["fast_bindings"] = profile.fast_bindings
        from .product_contract import entity_projection_report, entity_key

        report["account_entity_projection"] = entity_projection_report(engine)
        from .transport import IDENTITY_QUERIES

        report["identity_templates"] = {
            key: value
            for key, value in IDENTITY_QUERIES.items()
            if key in ("graphql.inventory.vehicleList", "graphql.inventory.images")
        }
        report["identity_drafts"] = {
            key: value
            for key, value in getattr(profile, "identity_drafts", {}).items()
            if key in report["identity_templates"]
        }
        report["identity_fixed_parameters"] = {}
        # Admin-only actual HA entity IDs for the selected VIN, never in exported diagnostics.
        if hasattr(hass, "states") and hasattr(hass, "data"):
            from homeassistant.helpers import entity_registry as er

            registry = er.async_get(hass)
            actual = {}
            for entity in er.async_entries_for_config_entry(
                registry, engine.entry.entry_id
            ):
                key = entity_key(entity.unique_id, engine.entry.entry_id)
                from .product_contract import product_inventory

                if (
                    not entity.unique_id.lower().startswith(vehicle.vin.lower() + "_")
                    and product_inventory()["entities"].get(key, {}).get("scope")
                    != "account"
                ):
                    continue
                if key:
                    if key in (
                        "sensor.custom_attribute",
                        "binary_sensor.custom_attribute",
                    ):
                        # Admin index needs the exact local contract; public diagnostics
                        # intentionally keep all local attributes anonymous.
                        key = (
                            entity.domain
                            + "."
                            + entity.unique_id.split("_", 1)[1].removeprefix(
                                entity.domain + "_"
                            )
                        )
                    actual.setdefault(key, []).append(entity.entity_id)
            from .entity_traceability import link_entities

            link_entities(report, actual)
            # Admin-only scalar observation trace; never add private values
            # to the shared capability report or exported diagnostics.
            for row in report["rows"]:
                reading = vehicle.readings.get(row.get("attribute"), {})
                value = reading.get("value")
                if row.get("entity_key") and type(value) in (str, int, float, bool):
                    row["normalized_value"] = engine.redact_evidence(
                        value, vehicle.vin
                    )["payload"]
        if hasattr(engine, "health"):
            report["integration_health"] = engine.health.snapshot(engine, vehicle)
        from .read_discovery import user_test_candidates

        report["end_user_progress"] = engine.discovery_progress(vehicle, profile)
        report["end_user_candidates"] = [
            {
                "label": label,
                "capability": capability,
                "action": action,
                "operation": operation,
                "approval_group": group,
            }
            for label, capability, action, operation, group in user_test_candidates(
                engine, vehicle, profile
            ).values()
        ]
        report["expert_candidates"] = [
            {
                "label": label,
                "capability": capability,
                "action": action,
                "operation": operation,
                "approval_group": group,
            }
            for label, capability, action, operation, group in user_test_candidates(
                engine, vehicle, profile, include_verified=True
            ).values()
        ]
        coordinator = getattr(
            getattr(engine.entry, "runtime_data", None), "coordinator", None
        )
        interval = getattr(coordinator, "update_interval", None)
        report["end_user_timing"] = {
            "poll_interval_seconds": interval.total_seconds() if interval else None,
            "last_poll_success": engine.last_cloud_poll_success.isoformat()
            if engine.last_cloud_poll_success
            else None,
            "last_poll_attempt": engine.last_cloud_poll_attempt.isoformat()
            if engine.last_cloud_poll_attempt
            else None,
        }
        connection.send_result(msg["id"], report)
    except (ValueError, KeyError, RuntimeError) as exc:
        connection.send_error(msg["id"], "v3_status_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/resume_discovery",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
    }
)
@websocket_api.async_response
async def ws_resume_discovery(hass, connection, msg):
    try:
        progress = await _engine(hass, msg["entry_id"]).resume_read_discovery(
            msg["vin"]
        )
        connection.send_result(msg["id"], progress)
    except (ValueError, KeyError, RuntimeError, OSError, TimeoutError) as exc:
        connection.send_error(msg["id"], "v3_discovery_resume_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/add_route",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("route"): dict,
    }
)
@websocket_api.async_response
async def ws_add_route(hass, connection, msg):
    try:
        result = await _engine(hass, msg["entry_id"]).add_route(
            msg["vin"], msg["route"]
        )
        connection.send_result(msg["id"], {"operation": result})
    except (ValueError, KeyError, TypeError) as exc:
        connection.send_error(msg["id"], "v3_invalid_route", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/share_definition",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("operation"): vol.All(str, vol.Length(min=1, max=120)),
    }
)
@websocket_api.async_response
async def ws_share_definition(hass, connection, msg):
    """Return only the saved definition after the backend privacy check."""
    try:
        definition = _engine(hass, msg["entry_id"]).share_definition(
            msg["vin"], msg["operation"]
        )
        connection.send_result(msg["id"], definition)
    except (ValueError, KeyError, TypeError):
        connection.send_error(
            msg["id"],
            "v3_share_definition_failed",
            "Definition unavailable or contains potentially private values",
        )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/discard_route",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("operation"): vol.All(str, vol.Length(min=1, max=120)),
    }
)
@websocket_api.async_response
async def ws_discard_route(hass, connection, msg):
    try:
        await _engine(hass, msg["entry_id"]).discard_unused_route(
            msg["vin"], msg["operation"]
        )
        connection.send_result(msg["id"], {"deleted": True})
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        connection.send_error(msg["id"], "v3_discard_route_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/review",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("sequence"): int,
        vol.Required("result"): vol.In(("worked", "failed", "uncertain")),
    }
)
@websocket_api.async_response
async def ws_review(hass, connection, msg):
    try:
        engine = _engine(hass, msg["entry_id"])
        result = await engine.review_action(msg["vin"], msg["sequence"], msg["result"])
        connection.send_result(msg["id"], result)
    except (ValueError, RuntimeError, TypeError) as exc:
        connection.send_error(msg["id"], "v3_review_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/review_normal_command",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("command_id"): str,
    }
)
@websocket_api.async_response
async def ws_review_normal_command(hass, connection, msg):
    try:
        await _engine(hass, msg["entry_id"]).review_normal_command(
            msg["vin"], msg["command_id"]
        )
        connection.send_result(msg["id"], {"reviewed": True})
    except (ValueError, RuntimeError, KeyError) as exc:
        connection.send_error(msg["id"], "v3_review_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/select",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("aspect"): str,
        vol.Optional("capability", default="climate"): str,
        vol.Required("operation"): str,
    }
)
@websocket_api.async_response
async def ws_select(hass, connection, msg):
    try:
        await _engine(hass, msg["entry_id"]).select_working(
            msg["vin"], msg["aspect"], msg["operation"], capability=msg["capability"]
        )
        connection.send_result(msg["id"], {"selected": msg["operation"]})
    except (ValueError, RuntimeError, KeyError) as exc:
        connection.send_error(msg["id"], "v3_select_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/attribute_routes",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("attribute"): str,
    }
)
@websocket_api.async_response
async def ws_attribute_routes(hass, connection, msg):
    try:
        result = _engine(hass, msg["entry_id"]).attribute_routes_for(
            msg["vin"], msg["attribute"]
        )
        connection.send_result(msg["id"], result)
    except (ValueError, KeyError) as exc:
        connection.send_error(msg["id"], "v3_attribute_routes_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/attribute_add",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("definition"): dict,
    }
)
@websocket_api.async_response
async def ws_attribute_add(hass, connection, msg):
    try:
        ident = await _engine(hass, msg["entry_id"]).add_attribute_route(
            msg["vin"], msg["definition"]
        )
        connection.send_result(msg["id"], {"saved": ident, "activated": False})
    except (ValueError, KeyError, TypeError) as exc:
        connection.send_error(msg["id"], "v3_attribute_add_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/attribute_test",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("attribute"): str,
        vol.Required("operation"): str,
    }
)
@websocket_api.async_response
async def ws_attribute_test(hass, connection, msg):
    try:
        result = await _engine(hass, msg["entry_id"]).test_attribute_route(
            msg["vin"], msg["attribute"], msg["operation"]
        )
        connection.send_result(msg["id"], result)
    except (ValueError, RuntimeError, KeyError, TimeoutError, OSError) as exc:
        connection.send_error(msg["id"], "v3_attribute_test_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/attribute_save",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("attribute"): str,
        vol.Required("operation"): str,
    }
)
@websocket_api.async_response
async def ws_attribute_save(hass, connection, msg):
    try:
        await _engine(hass, msg["entry_id"]).save_attribute_candidate(
            msg["vin"], msg["attribute"], msg["operation"]
        )
        connection.send_result(
            msg["id"], {"saved": msg["operation"], "activated": False}
        )
    except (ValueError, RuntimeError, KeyError) as exc:
        connection.send_error(msg["id"], "v3_attribute_save_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/attribute_activate",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("attribute"): str,
        vol.Required("operation"): str,
    }
)
@websocket_api.async_response
async def ws_attribute_activate(hass, connection, msg):
    try:
        await _engine(hass, msg["entry_id"]).activate_attribute_route(
            msg["vin"], msg["attribute"], msg["operation"]
        )
        connection.send_result(msg["id"], {"active": msg["operation"]})
    except (ValueError, RuntimeError, KeyError) as exc:
        connection.send_error(msg["id"], "v3_attribute_activation_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/attribute_disable",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("attribute"): str,
        vol.Optional("disabled", default=True): bool,
    }
)
@websocket_api.async_response
async def ws_attribute_disable(hass, connection, msg):
    try:
        await _engine(hass, msg["entry_id"]).disable_attribute_route(
            msg["vin"], msg["attribute"], disabled=msg.get("disabled", True)
        )
        connection.send_result(msg["id"], {"disabled": msg.get("disabled", True)})
    except (ValueError, RuntimeError, KeyError) as exc:
        connection.send_error(msg["id"], "v3_attribute_disable_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/control_routes",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("capability"): str,
        vol.Required("action"): str,
    }
)
@websocket_api.async_response
async def ws_control_routes(hass, connection, msg):
    try:
        value = _engine(hass, msg["entry_id"]).control_routes_for(
            msg["vin"], msg["capability"], msg["action"]
        )
        connection.send_result(msg["id"], value)
    except (ValueError, KeyError, RuntimeError) as exc:
        connection.send_error(msg["id"], "v3_control_routes_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/control_test",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("capability"): str,
        vol.Required("action"): str,
        vol.Required("operation"): str,
        vol.Required("approval"): vol.In(("non_spin", "spin")),
        vol.Optional("parameters"): dict,
        vol.Optional("end_user", default=False): bool,
        vol.Optional("expert", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_control_test(hass, connection, msg):
    try:
        engine = _engine(hass, msg["entry_id"])
        value = await engine.approved_control_discovery(
            msg["vin"],
            msg["action"],
            msg["operation"],
            capability=msg["capability"],
            approval=msg["approval"],
            params=msg.get("parameters"),
            guided=msg.get("end_user", False),
            expert=msg.get("expert", False),
        )
        connection.send_result(msg["id"], value)
    except (ValueError, KeyError, RuntimeError, TypeError) as exc:
        connection.send_error(msg["id"], "v3_control_test_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/control_disable",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("capability"): str,
        vol.Required("action"): str,
        vol.Optional("disabled", default=True): bool,
    }
)
@websocket_api.async_response
async def ws_control_disable(hass, connection, msg):
    try:
        await _engine(hass, msg["entry_id"]).disable_control(
            msg["vin"],
            msg["capability"],
            msg["action"],
            disabled=msg.get("disabled", True),
        )
        connection.send_result(msg["id"], {"disabled": msg.get("disabled", True)})
    except (ValueError, KeyError, RuntimeError) as exc:
        connection.send_error(msg["id"], "v3_control_disable_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/api_results",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Optional("family", default="all"): vol.In(
            ("all", "cariad", "mbb", "graphql")
        ),
        vol.Optional("include_engineering", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_api_results(hass, connection, msg):
    try:
        engine = _engine(hass, msg["entry_id"])
        result = {
            "records": engine.api_results_for(msg["vin"], msg.get("family", "all"))
        }
        if msg.get("include_engineering"):
            result["engineering_history"] = engine.engineering_history_for(
                msg["vin"], msg.get("family", "all")
            )
            result["execution_reviews"] = engine.profiles[
                engine.require_vehicle(msg["vin"]).vin.lower()
            ].execution_reviews
        connection.send_result(msg["id"], result)
    except (ValueError, KeyError, RuntimeError) as exc:
        connection.send_error(msg["id"], "v3_api_results_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/review_execution",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("operation"): vol.All(str, vol.Length(min=1, max=120)),
        vol.Required("at"): vol.All(str, vol.Length(min=1, max=64)),
        vol.Required("outcome"): vol.In(
            ("unreviewed", "worked", "failed", "inconclusive")
        ),
        vol.Required("comment"): vol.All(str, vol.Length(max=500)),
    }
)
@websocket_api.async_response
async def ws_review_execution(hass, connection, msg):
    try:
        engine = _engine(hass, msg["entry_id"])
        await engine.review_execution(
            msg["vin"], msg["operation"], msg["at"], msg["outcome"], msg["comment"]
        )
        connection.send_result(msg["id"], {"saved": True})
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        connection.send_error(msg["id"], "v3_execution_review_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/engineering_response",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("operation"): vol.All(str, vol.Length(min=1, max=120)),
    }
)
@websocket_api.async_response
async def ws_engineering_response(hass, connection, msg):
    try:
        engine = _engine(hass, msg["entry_id"])
        connection.send_result(
            msg["id"], engine.engineering_response_for(msg["vin"], msg["operation"])
        )
    except (ValueError, KeyError, RuntimeError):
        connection.send_error(
            msg["id"], "v3_engineering_response_failed", "Response unavailable"
        )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/test_family_reads",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("family"): vol.In(("cariad", "mbb", "graphql")),
        vol.Optional("full", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_test_family_reads(hass, connection, msg):
    try:
        result = await _engine(hass, msg["entry_id"]).test_family_reads(
            msg["vin"], msg["family"], full=msg.get("full", False)
        )
        connection.send_result(msg["id"], result)
    except (ValueError, KeyError, RuntimeError, OSError, TimeoutError) as exc:
        connection.send_error(msg["id"], "v3_family_read_test_failed", str(exc))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/test_identity_operation",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("operation"): str,
        vol.Optional("query"): vol.All(str, vol.Length(min=1, max=4096)),
        vol.Optional("variables"): dict,
        vol.Optional("activate", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_test_identity_operation(hass, connection, msg):
    try:
        from .transport import IDENTITY_QUERIES, identity_request_body

        engine = _engine(hass, msg["entry_id"])
        operation = msg["operation"]
        query = msg.get("query")
        variables = msg.get("variables")
        if variables is not None and (
            query is None or operation not in IDENTITY_QUERIES
        ):
            raise ValueError("Variables require a GraphQL query")
        defaults = (
            identity_request_body(operation).get("variables", {})
            if operation in IDENTITY_QUERIES
            else {}
        )
        if query is not None and (
            query != IDENTITY_QUERIES.get(operation)
            or (variables is not None and variables != defaults)
        ):
            if msg.get("activate"):
                raise ValueError("Only reviewed identity sources can be activated")
            result = await engine.experiment_identity_query(
                msg["vin"], operation, query, variables
            )
        else:
            result = await engine.test_identity_operation(
                msg["vin"], operation, activate=msg.get("activate", False)
            )
            result["execution"] = engine.engineering_response_for(msg["vin"], operation)
        connection.send_result(msg["id"], result)
    except (ValueError, KeyError, RuntimeError, OSError, TimeoutError):
        connection.send_error(
            msg["id"],
            "v3_identity_test_failed",
            "Identity read failed: check query syntax, VIN selection, quota and session",
        )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/save_identity_draft",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Required("operation"): str,
        vol.Required("query"): vol.All(str, vol.Length(min=1, max=4096)),
        vol.Required("variables"): dict,
    }
)
@websocket_api.async_response
async def ws_save_identity_draft(hass, connection, msg):
    try:
        await _engine(hass, msg["entry_id"]).save_identity_draft(
            msg["vin"], msg["operation"], msg["query"], msg["variables"]
        )
        connection.send_result(
            msg["id"], {"saved": msg["operation"], "activated": False}
        )
    except (ValueError, KeyError, RuntimeError, OSError):
        connection.send_error(
            msg["id"], "v3_identity_draft_failed", "Invalid or unsaved identity draft"
        )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "audiconnect/v3/trip_history",
        vol.Required("entry_id"): str,
        vol.Required("vin"): str,
        vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0, max=10000)),
        vol.Optional("limit", default=100): vol.All(int, vol.Range(min=1, max=250)),
    }
)
@websocket_api.async_response
async def ws_trip_history(hass, connection, msg):
    """Paginated local archive; no cloud request or raw trip identifiers."""
    try:
        car = _engine(hass, msg["entry_id"]).require_vehicle(msg["vin"])
        offset, limit = msg["offset"], msg["limit"]
        rows = car.trip_history
        connection.send_result(
            msg["id"],
            {
                "total": len(rows),
                "offset": offset,
                "limit": limit,
                "coverage": "observed_records",
                "trips": [
                    {k: v for k, v in row.items() if k != "tripID" and v is not None}
                    for row in rows[offset : offset + limit]
                ],
            },
        )
    except (ValueError, KeyError, RuntimeError):
        connection.send_error(
            msg["id"], "v3_trip_history_failed", "Trip archive unavailable"
        )


def _panel_module_url(frontend_dir: Path) -> str:
    """Invalidate the browser cache only when the packaged script changes."""
    digest = sha256((frontend_dir / "panel.js").read_bytes()).hexdigest()[:16]
    return f"/audiconnect_v3/panel.js?v={digest}"


async def async_setup_dashboard(hass) -> None:
    if hass.data.get(_READY_KEY):
        return
    frontend_dir = Path(__file__).parent / "frontend"
    module_url = await hass.async_add_executor_job(_panel_module_url, frontend_dir)
    # HA websocket commands and static paths live for the HA process.
    # Removing and re-adding the optional sidebar must not register duplicates.
    if not hass.data.get(_HANDLERS_KEY):
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/audiconnect_v3", str(frontend_dir), False)]
        )
        for handler in (
            ws_list,
            ws_status,
            ws_resume_discovery,
            ws_add_route,
            ws_discard_route,
            ws_share_definition,
            ws_review,
            ws_review_normal_command,
            ws_select,
            ws_attribute_routes,
            ws_attribute_add,
            ws_attribute_test,
            ws_attribute_save,
            ws_attribute_activate,
            ws_attribute_disable,
            ws_control_routes,
            ws_control_test,
            ws_control_disable,
            ws_api_results,
            ws_review_execution,
            ws_engineering_response,
            ws_test_family_reads,
            ws_test_identity_operation,
            ws_save_identity_draft,
            ws_trip_history,
        ):
            websocket_api.async_register_command(hass, handler)
        hass.data[_HANDLERS_KEY] = True
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="audiconnect-v3-panel",
        frontend_url_path=_PANEL,
        module_url=module_url,
        sidebar_title="Audi Engineering Dashboard",
        sidebar_icon="mdi:car-cog",
        require_admin=True,
        embed_iframe=False,
    )
    hass.data[_READY_KEY] = True


def async_remove_dashboard(hass) -> None:
    if hass.data.pop(_READY_KEY, False):
        frontend.async_remove_panel(hass, _PANEL, warn_if_unknown=False)
