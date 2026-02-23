"""myAudi integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .audi_account import (
    AudiAccount,
    SERVICE_EXECUTE_VEHICLE_ACTION,
    SERVICE_EXECUTE_VEHICLE_ACTION_SCHEMA,
    SERVICE_REFRESH_CLOUD_DATA,
    SERVICE_REFRESH_VEHICLE_DATA,
    SERVICE_REFRESH_VEHICLE_DATA_SCHEMA,
    SERVICE_SET_TARGET_SOC,
    SERVICE_SET_TARGET_SOC_SCHEMA,
    SERVICE_START_AUXILIARY_HEATING,
    SERVICE_START_AUXILIARY_HEATING_SCHEMA,
    SERVICE_START_CLIMATE_CONTROL,
    SERVICE_START_CLIMATE_CONTROL_SCHEMA,
)
from .const import CONF_SCAN_INITIAL, DOMAIN, PLATFORMS
from .coordinator import AudiDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class AudiRuntimeData:
    """Runtime data for each config entry."""

    account: AudiAccount
    coordinator: AudiDataUpdateCoordinator


async def async_setup(_hass: HomeAssistant, _config: dict[str, Any]) -> bool:
    """Set up via config entries only."""
    return True


async def _async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(config_entry.entry_id)


def _async_register_services(hass: HomeAssistant, account: AudiAccount, request_refresh: Any) -> None:
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_CLOUD_DATA):
        hass.services.async_register(DOMAIN, SERVICE_REFRESH_CLOUD_DATA, request_refresh)
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_VEHICLE_DATA):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_VEHICLE_DATA,
            account.refresh_vehicle_data,
            schema=SERVICE_REFRESH_VEHICLE_DATA_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_EXECUTE_VEHICLE_ACTION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_EXECUTE_VEHICLE_ACTION,
            account.execute_vehicle_action,
            schema=SERVICE_EXECUTE_VEHICLE_ACTION_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_START_CLIMATE_CONTROL):
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_CLIMATE_CONTROL,
            account.start_climate_control,
            schema=SERVICE_START_CLIMATE_CONTROL_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_START_AUXILIARY_HEATING):
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_AUXILIARY_HEATING,
            account.start_auxiliary_heating,
            schema=SERVICE_START_AUXILIARY_HEATING_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_TARGET_SOC):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_TARGET_SOC,
            account.set_target_soc,
            schema=SERVICE_SET_TARGET_SOC_SCHEMA,
        )


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up myAudi from a config entry."""
    account = AudiAccount(hass, config_entry)
    coordinator = AudiDataUpdateCoordinator.from_entry(hass, account, config_entry)

    async def _request_refresh(*_: Any) -> None:
        await coordinator.async_request_refresh()

    account.set_refresh_callback(_request_refresh)
    config_entry.runtime_data = AudiRuntimeData(account=account, coordinator=coordinator)

    config_entry.async_on_unload(config_entry.add_update_listener(_async_update_listener))

    if config_entry.options.get(CONF_SCAN_INITIAL, True):
        await coordinator.async_config_entry_first_refresh()

    _async_register_services(hass, account, _request_refresh)
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload myAudi entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
    if not unload_ok:
        return False

    if len(hass.config_entries.async_entries(DOMAIN)) <= 1:
        for service in (
            SERVICE_REFRESH_CLOUD_DATA,
            SERVICE_REFRESH_VEHICLE_DATA,
            SERVICE_EXECUTE_VEHICLE_ACTION,
            SERVICE_START_CLIMATE_CONTROL,
            SERVICE_START_AUXILIARY_HEATING,
            SERVICE_SET_TARGET_SOC,
        ):
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    return True


__all__ = ["AudiRuntimeData", "async_setup", "async_setup_entry", "async_unload_entry"]
