"""Provide system health information for Audi Connect."""

from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import CONF_API_LEVEL, CONF_REGION, DOMAIN


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register system health callbacks."""
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Get info for the info page."""
    from . import AudiRuntimeData

    info: dict[str, Any] = {}

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return info

    total_vehicles = 0
    all_logged_in = True
    regions: list[str] = []
    api_levels: list[str] = []
    min_rate_limit: int | None = None
    last_refresh = None
    last_error: str | None = None

    for entry in entries:
        runtime_data: AudiRuntimeData | None = getattr(entry, "runtime_data", None)
        if runtime_data is None:
            # Entry exists but setup failed (auth error, ConfigEntryNotReady, etc.)
            all_logged_in = False
            continue

        account = runtime_data.account
        coordinator = runtime_data.coordinator

        # Authentication status
        if not account.connection._loggedin:
            all_logged_in = False

        # Vehicle count
        total_vehicles += len(account.connection.vehicles)

        # Region
        region = entry.data.get(CONF_REGION)
        if region:
            regions.append(region)

        # API level
        api_level = entry.data.get(CONF_API_LEVEL)
        if api_level is not None:
            api_levels.append(str(api_level))

        # Rate limit from Vcf-Remaining-Calls header
        rate_limit = account.connection._audi_service._api.vcf_remaining_calls
        if rate_limit is not None:
            min_rate_limit = (
                min(min_rate_limit, rate_limit)
                if min_rate_limit is not None
                else rate_limit
            )

        # Last successful refresh (coordinator built-in)
        update_time = getattr(coordinator, "last_update_success_time", None)
        if update_time is not None:
            if last_refresh is None or update_time > last_refresh:
                last_refresh = update_time

        # Last update error (coordinator built-in)
        if coordinator.last_exception is not None:
            last_error = str(coordinator.last_exception)

    info["logged_in"] = all_logged_in
    info["vehicles"] = total_vehicles

    if regions:
        info["region"] = ", ".join(regions)

    if api_levels:
        info["api_level"] = ", ".join(api_levels)

    if min_rate_limit is not None:
        info["api_rate_limit_remaining"] = min_rate_limit

    if last_refresh is not None:
        info["last_successful_refresh"] = last_refresh.isoformat()

    if last_error is not None:
        info["last_update_error"] = last_error

    return info


__all__ = ["async_register"]
