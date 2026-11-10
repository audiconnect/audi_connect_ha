"""Home Assistant diagnostics for Audi Connect.

Read-only; does not poll, refresh, send commands or export raw vehicle data.
No credentials, token, VIN, device IDs, location or raw API responses are included.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .capability_catalog import snapshot_capabilities
from .freshness import vehicle_age_minutes, vehicle_freshness
from .const import (
    CONF_API_LEVEL,
    CONF_REFRESH_AFTER_ACTION,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    DEFAULT_API_LEVEL,
    DEFAULT_UPDATE_INTERVAL,
)

# Fixed list of source state keys: report their presence, never their values.
_OBSERVED_KEYS = (
    "stateOfCharge",
    "chargingState",
    "chargingPower",
    "plugState",
    "climatisationState",
    "remainingClimatisationTime",
    "position",
    "last_update_time",
    "userCapabilities",
    "shortterm_current",
    "longterm_current",
)
_FEATURE_FLAGS = (
    "support_status_report",
    "support_position",
    "support_climater",
    "support_preheater",
    "support_charger",
    "support_trip_data",
)


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _vehicle_snapshot(vehicle: Any, index: int, uses_auth0: bool) -> dict[str, Any]:
    """Safe capability and data-presence view; excludes vehicle identifiers."""
    raw_vehicle = getattr(vehicle, "_vehicle", None)
    state = getattr(raw_vehicle, "state", None)
    fields = getattr(raw_vehicle, "fields", None)
    state = state if isinstance(state, dict) else {}
    fields = fields if isinstance(fields, dict) else {}
    features: dict[str, str] = {}
    for flag in _FEATURE_FLAGS:
        value = getattr(vehicle, flag, None)
        if value is True:
            features[flag] = "poll_enabled_not_command_proven"
        elif value is False:
            features[flag] = (
                "legacy_poll_disabled_for_auth0_session"
                if uses_auth0
                and flag
                in {
                    "support_climater",
                    "support_preheater",
                    "support_charger",
                    "support_trip_data",
                }
                else "disabled_or_unsupported"
            )
        else:
            features[flag] = "unknown"
    return {
        "vehicle_slot": index,  # Not a VIN or persistent vehicle identity.
        "feature_flags": features,
        "state_key_presence": {
            key: key in state and state[key] is not None for key in _OBSERVED_KEYS
        },
        "state_field_count": len(state),
        "vehicle_field_count": len(fields),
        "model_metadata_source": (
            getattr(vehicle, "model_source", "unavailable")
            if getattr(vehicle, "model_source", "unavailable") in {
                "audi_long_name", "audi_short_name", "nickname_fallback", "unavailable"
            } else "unavailable"
        ),
        "park_time_source": (
            getattr(vehicle, "park_time_source", "unavailable")
            if getattr(vehicle, "park_time_source", "unavailable") in {
                "vehicle_parking_clock",
                "last_parked_position_capture_estimate",
                "unavailable",
            } else "unavailable"
        ),
        "capability_inventory": snapshot_capabilities(vehicle),
        "vehicle_data_age_minutes": vehicle_age_minutes(
            getattr(vehicle, "last_update_time", None)
        ),
        "vehicle_data_freshness": vehicle_freshness(
            getattr(vehicle, "last_update_time", None)
        ),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return a bounded safe local diagnostics snapshot for one Audi entry."""
    runtime = getattr(entry, "runtime_data", None)
    entry_info: dict[str, Any] = {
        "region": entry.data.get(CONF_REGION),
        "api_level": entry.data.get(CONF_API_LEVEL, DEFAULT_API_LEVEL),
        "scan_interval_minutes": entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        ),
        "refresh_vehicle_data_after_action": bool(
            entry.options.get(CONF_REFRESH_AFTER_ACTION, False)
        ),
        "entry_state": str(getattr(entry, "state", "unknown")).split(".")[-1].lower(),
    }

    # Names and entity IDs may include vehicle identifiers: count only.
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    per_domain: Counter[str] = Counter()
    disabled_per_domain: Counter[str] = Counter()
    for entity in entities:
        domain = entity.entity_id.split(".", 1)[0]
        per_domain[domain] += 1
        if entity.disabled_by is not None:
            disabled_per_domain[domain] += 1

    result: dict[str, Any] = {
        "schema_version": 1,
        "entry": entry_info,
        "entities": {
            "total": len(entities),
            "per_platform": dict(sorted(per_domain.items())),
            "disabled_per_platform": dict(sorted(disabled_per_domain.items())),
        },
        "runtime_loaded": runtime is not None,
    }
    if runtime is None:
        return result

    account = runtime.account
    connection = account.connection
    coordinator = runtime.coordinator
    service = connection._audi_service
    api = service._api
    uses_auth0 = bool(getattr(service, "uses_auth0", False))
    vehicles = list(getattr(connection, "vehicles", []))
    # Never include coordinator.last_exception: it may contain a URL with a VIN.
    result["runtime"] = {
        "session_established_not_command_authorized": bool(
            getattr(connection, "_loggedin", False)
        ),
        "uses_auth0": uses_auth0,
        "last_update_success": bool(
            getattr(coordinator, "last_update_success", False)
        ),
        "last_successful_refresh": _iso(
            getattr(coordinator, "last_cloud_poll_success", None)
        ),
        "last_cloud_poll_attempt": _iso(
            getattr(coordinator, "last_cloud_poll_attempt", None)
        ),
        "last_poll_exception_type": (
            type(coordinator.last_exception).__name__
            if getattr(coordinator, "last_exception", None)
            else None
        ),
        "rate_limit_remaining_last_observed": getattr(
            api, "vcf_remaining_calls", None
        ),
        "rate_limit_observed_at": _iso(
            getattr(api, "vcf_remaining_calls_last_observed", None)
        ),
        "vehicle_count": len(vehicles),
        "vehicles": [
            {
                **_vehicle_snapshot(vehicle, idx, uses_auth0),
                "local_dealer_configured": bool(
                    isinstance(entry.options.get("local_dealers", {}), dict)
                    and entry.options.get("local_dealers", {}).get(vehicle.vin.lower())
                ),
            }
            for idx, vehicle in enumerate(vehicles[:10], 1)
        ],
        "recent_http_observations": list(
            getattr(api, "diagnostic_events", [])
        )[-40:],
        "read_only_api_probes": [
            {"vehicle_slot": index, "report": report}
            for index, vehicle in enumerate(vehicles[:10], 1)
            if (
                report := connection.get_read_only_probe_report(vehicle.vin)
            ) is not None
        ] if hasattr(connection, "get_read_only_probe_report") else [],
    }
    return result
