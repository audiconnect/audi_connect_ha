"""Audi Connect integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
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
from .const import CONF_DEVICE_ID, CONF_SCAN_INITIAL, DOMAIN, PLATFORMS
from .coordinator import AudiDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class AudiRuntimeData:
    """Runtime data for each config entry."""

    account: AudiAccount
    coordinator: AudiDataUpdateCoordinator


def _resolve_device_to_vin(hass: HomeAssistant, device_id: str) -> str | None:
    """Resolve a Home Assistant device registry ID to the vehicle VIN."""
    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get(device_id)
    if device_entry is None:
        return None
    for domain, identifier in device_entry.identifiers:
        if domain == DOMAIN:
            return identifier
    return None


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


def _resolve_service_call(
    hass: HomeAssistant, service: ServiceCall
) -> tuple[str, AudiAccount] | None:
    """Resolve device_id from a service call to (vin, account).

    Returns None and logs an error if resolution fails.
    """
    device_id = service.data[CONF_DEVICE_ID]
    vin = _resolve_device_to_vin(hass, device_id)
    if vin is None:
        _LOGGER.error("No VIN found for device %s", device_id)
        return None
    account = _get_account_for_vin(hass, vin)
    if account is None:
        _LOGGER.error("No account found for VIN associated with device %s", device_id)
        return None
    return vin, account


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
    """Register global services once (multi-account safe via device lookup)."""

    async def _handle_refresh_cloud_data(service: ServiceCall) -> None:
        for coordinator in _get_all_coordinators(hass):
            await coordinator.async_request_refresh()

    async def _handle_refresh_vehicle_data(service: ServiceCall) -> None:
        result = _resolve_service_call(hass, service)
        if result is None:
            return
        vin, account = result
        await account.refresh_vehicle_data(vin)

    async def _handle_execute_vehicle_action(service: ServiceCall) -> None:
        result = _resolve_service_call(hass, service)
        if result is None:
            return
        vin, account = result
        await account.execute_vehicle_action(vin, service)

    async def _handle_start_climate_control(service: ServiceCall) -> None:
        result = _resolve_service_call(hass, service)
        if result is None:
            return
        vin, account = result
        await account.start_climate_control(vin, service)

    async def _handle_start_auxiliary_heating(service: ServiceCall) -> None:
        result = _resolve_service_call(hass, service)
        if result is None:
            return
        vin, account = result
        await account.start_auxiliary_heating(vin, service)

    async def _handle_set_target_soc(service: ServiceCall) -> None:
        result = _resolve_service_call(hass, service)
        if result is None:
            return
        vin, account = result
        await account.set_target_soc(vin, service)

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


def _async_cleanup_orphaned_devices(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Remove devices that no longer have a matching vehicle in the account.

    This ensures that after migration or vehicle removal, no orphaned device
    entries remain in the device registry.
    """
    runtime_data: AudiRuntimeData | None = getattr(config_entry, "runtime_data", None)
    if runtime_data is None:
        return

    active_vins: set[str] = set()
    for vehicle_data in runtime_data.account.config_vehicles:
        if vehicle_data.vehicle and vehicle_data.vehicle.vin:
            active_vins.add(vehicle_data.vehicle.vin.lower())

    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, config_entry.entry_id)

    for device_entry in devices:
        device_vin: str | None = None
        for domain, identifier in device_entry.identifiers:
            if domain == DOMAIN:
                device_vin = identifier
                break

        if device_vin is not None and device_vin.lower() not in active_vins:
            _LOGGER.info(
                "Removing orphaned device %s (VIN no longer active)",
                device_entry.id,
            )
            device_registry.async_remove_device(device_entry.id)


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

    _async_cleanup_orphaned_devices(hass, config_entry)
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
