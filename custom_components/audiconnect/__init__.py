"""Audi Connect integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
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
from .const import CONF_SCAN_INITIAL, CONF_VIN, DOMAIN, PLATFORMS
from .coordinator import AudiDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class AudiRuntimeData:
    """Runtime data for each config entry."""

    account: AudiAccount
    coordinator: AudiDataUpdateCoordinator


def _get_account_for_vin(hass: HomeAssistant, vin: str) -> AudiAccount | None:
    """Find the AudiAccount that owns a given VIN across all config entries."""
    vin_lower = vin.lower()
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime_data: AudiRuntimeData | None = getattr(entry, "runtime_data", None)
        if runtime_data is None:
            continue
        for vehicle_data in runtime_data.account.config_vehicles:
            if vehicle_data.vehicle and vehicle_data.vehicle.vin.lower() == vin_lower:
                return runtime_data.account
    return None


def _get_all_coordinators(hass: HomeAssistant) -> list[AudiDataUpdateCoordinator]:
    """Get coordinators from all loaded config entries."""
    coordinators: list[AudiDataUpdateCoordinator] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime_data: AudiRuntimeData | None = getattr(entry, "runtime_data", None)
        if runtime_data is not None:
            coordinators.append(runtime_data.coordinator)
    return coordinators


async def _async_update_listener(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    await hass.config_entries.async_reload(config_entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register global services once (multi-account safe via VIN lookup)."""

    async def _handle_refresh_cloud_data(service: ServiceCall) -> None:
        for coordinator in _get_all_coordinators(hass):
            await coordinator.async_request_refresh()

    async def _handle_refresh_vehicle_data(service: ServiceCall) -> None:
        vin = service.data[CONF_VIN]
        account = _get_account_for_vin(hass, vin)
        if account is None:
            _LOGGER.error("No account found for VIN %s", vin)
            return
        await account.refresh_vehicle_data(service)

    async def _handle_execute_vehicle_action(service: ServiceCall) -> None:
        vin = service.data[CONF_VIN]
        account = _get_account_for_vin(hass, vin)
        if account is None:
            _LOGGER.error("No account found for VIN %s", vin)
            return
        await account.execute_vehicle_action(service)

    async def _handle_start_climate_control(service: ServiceCall) -> None:
        vin = service.data[CONF_VIN]
        account = _get_account_for_vin(hass, vin)
        if account is None:
            _LOGGER.error("No account found for VIN %s", vin)
            return
        await account.start_climate_control(service)

    async def _handle_start_auxiliary_heating(service: ServiceCall) -> None:
        vin = service.data[CONF_VIN]
        account = _get_account_for_vin(hass, vin)
        if account is None:
            _LOGGER.error("No account found for VIN %s", vin)
            return
        await account.start_auxiliary_heating(service)

    async def _handle_set_target_soc(service: ServiceCall) -> None:
        vin = service.data[CONF_VIN]
        account = _get_account_for_vin(hass, vin)
        if account is None:
            _LOGGER.error("No account found for VIN %s", vin)
            return
        await account.set_target_soc(service)

    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_CLOUD_DATA):
        hass.services.async_register(
            DOMAIN, SERVICE_REFRESH_CLOUD_DATA, _handle_refresh_cloud_data
        )
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_VEHICLE_DATA):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_VEHICLE_DATA,
            _handle_refresh_vehicle_data,
            schema=SERVICE_REFRESH_VEHICLE_DATA_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_EXECUTE_VEHICLE_ACTION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_EXECUTE_VEHICLE_ACTION,
            _handle_execute_vehicle_action,
            schema=SERVICE_EXECUTE_VEHICLE_ACTION_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_START_CLIMATE_CONTROL):
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_CLIMATE_CONTROL,
            _handle_start_climate_control,
            schema=SERVICE_START_CLIMATE_CONTROL_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_START_AUXILIARY_HEATING):
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_AUXILIARY_HEATING,
            _handle_start_auxiliary_heating,
            schema=SERVICE_START_AUXILIARY_HEATING_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_TARGET_SOC):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_TARGET_SOC,
            _handle_set_target_soc,
            schema=SERVICE_SET_TARGET_SOC_SCHEMA,
        )


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Audi Connect from a config entry."""
    account = AudiAccount(hass, config_entry)
    coordinator = AudiDataUpdateCoordinator.from_entry(hass, account, config_entry)

    async def _request_refresh(*_: Any) -> None:
        await coordinator.async_request_refresh()

    account.set_refresh_callback(_request_refresh)
    config_entry.runtime_data = AudiRuntimeData(
        account=account, coordinator=coordinator
    )

    config_entry.async_on_unload(
        config_entry.add_update_listener(_async_update_listener)
    )

    if config_entry.options.get(CONF_SCAN_INITIAL, True):
        await coordinator.async_config_entry_first_refresh()

    _async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload Audi Connect entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
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


__all__ = ["AudiRuntimeData", "async_setup_entry", "async_unload_entry"]
