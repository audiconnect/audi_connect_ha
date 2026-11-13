"""Audi Connect integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from dataclasses import dataclass, field
from typing import Any

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from .audi_account import (
    SERVICE_EXECUTE_VEHICLE_ACTION,
    SERVICE_EXECUTE_VEHICLE_ACTION_SCHEMA,
    SERVICE_REFRESH_CLOUD_DATA,
    SERVICE_REFRESH_VEHICLE_DATA,
    SERVICE_REFRESH_VEHICLE_DATA_SCHEMA,
    SERVICE_SET_CHARGE_MODE,
    SERVICE_SET_CHARGE_MODE_SCHEMA,
    SERVICE_SET_LOCATION_CHARGE_TARGET,
    SERVICE_SET_LOCATION_CHARGE_TARGET_SCHEMA,
    SERVICE_SET_TARGET_SOC,
    SERVICE_SET_TARGET_SOC_SCHEMA,
    SERVICE_START_AUXILIARY_HEATING,
    SERVICE_START_AUXILIARY_HEATING_SCHEMA,
    SERVICE_START_CLIMATE_CONTROL,
    SERVICE_START_CLIMATE_CONTROL_SCHEMA,
    SERVICE_START_ENGINE,
    SERVICE_START_ENGINE_SCHEMA,
    SERVICE_STOP_ENGINE,
    SERVICE_STOP_ENGINE_SCHEMA,
    AudiAccount,
)
from .const import (
    CONF_API_LEVEL,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_REGION,
    CONF_SCAN_INITIAL,
    CONF_USERNAME,
    DEFAULT_API_LEVEL,
    DOMAIN,
    PLATFORMS,
    uses_auth0,
)
from .coordinator import AudiDataUpdateCoordinator
from .local_extensions import DEALER_FIELDS, update_local_dealer_options
from .v3.coordinator_clean import V3CleanCoordinator
from .v3.engine import V3Engine
from .v3.service_commands import execute as v3_execute_action
from .v3.registry import CapabilityRegistry
from .v3.runtime import (
    V3_DEFAULT,
    V3_ENABLED,
    V3_RUNTIME_OPTION,
    catalog_path,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_PROBE_API_PATHS = "probe_api_paths"
SERVICE_SET_LOCAL_DEALER = "set_local_dealer"
PROBE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Optional("extended", default=False): bool,
    }
)
LOCAL_DEALER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Optional("clear", default=False): bool,
        **{vol.Optional(field): cv.string for field in DEALER_FIELDS},
    }
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entry to a newer version."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        # v1 -> v2:
        # - Service calls changed from manual VIN text input to device selector
        #   dropdown. Remove any devices that have lost all their entities
        #   (orphaned from a previous bad state).
        # - Options flow cleanup: "scan_active" removed (HA built-in "Enable
        #   polling" toggle replaces it); "api_level" moved from options to
        #   reconfigure flow (stored in data).
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        devices = dr.async_entries_for_config_entry(
            device_registry, config_entry.entry_id
        )
        for device_entry in devices:
            if not er.async_entries_for_device(
                entity_registry, device_entry.id, include_disabled_entities=True
            ):
                _LOGGER.info(
                    "Migration v1->v2: removing orphaned device %s (no entities)",
                    device_entry.id,
                )
                device_registry.async_remove_device(device_entry.id)

        # Promote api_level from options → data if it was overridden there,
        # then strip removed keys from options.
        new_data = {**config_entry.data}
        new_options = {**config_entry.options}

        if CONF_API_LEVEL in new_options:
            new_data[CONF_API_LEVEL] = int(new_options.pop(CONF_API_LEVEL))
        elif CONF_API_LEVEL not in new_data:
            new_data[CONF_API_LEVEL] = DEFAULT_API_LEVEL

        new_options.pop("scan_active", None)

        hass.config_entries.async_update_entry(
            config_entry, version=2, data=new_data, options=new_options
        )

    if config_entry.version == 2:
        # v2 -> v3:
        # Drop credentials in regions that require interactive authentication.
        new_data = {**config_entry.data}
        if uses_auth0(new_data.get(CONF_REGION)) and not new_data.get(
            CONF_REFRESH_TOKEN
        ):
            new_data.pop(CONF_PASSWORD, None)
            new_data.pop(CONF_USERNAME, None)
        hass.config_entries.async_update_entry(config_entry, version=3, data=new_data)

    _LOGGER.info("Migration to version %s successful", config_entry.version)
    return True


@dataclass
class AudiRuntimeData:
    """Runtime data for each config entry."""

    account: AudiAccount | None
    coordinator: AudiDataUpdateCoordinator | V3CleanCoordinator
    v3: V3Engine | None = None
    loaded_platforms: list[Platform] = field(default_factory=lambda: list(PLATFORMS))
    options_snapshot: dict[str, Any] = field(default_factory=dict)
    data_snapshot: dict[str, Any] = field(default_factory=dict)


def _resolve_service_call(
    hass: HomeAssistant, service: ServiceCall
) -> tuple[str, AudiAccount | V3Engine]:
    """Resolve a device to its one owning config entry and active runtime.

    Never select an account by scanning other accounts for a matching VIN.
    A shared or unavailable device must fail before any vehicle action.
    """
    device = dr.async_get(hass).async_get(service.data[CONF_DEVICE_ID])
    if device is None:
        raise HomeAssistantError("Audi Connect device was not found")

    vins = {
        identifier.lower()
        for domain, identifier in device.identifiers
        if domain == DOMAIN
    }
    if len(vins) != 1:
        raise HomeAssistantError(
            "Audi Connect device has no unambiguous vehicle identity"
        )
    vin = next(iter(vins))

    owners = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id in device.config_entries
    ]
    if len(owners) != 1:
        raise HomeAssistantError(
            "Audi Connect device has no unambiguous owning account"
        )
    entry = owners[0]
    runtime = getattr(entry, "runtime_data", None)
    if entry.state is not ConfigEntryState.LOADED or runtime is None:
        raise HomeAssistantError("Audi Connect owning account is not loaded")

    if isinstance(runtime.v3, V3Engine):
        try:
            runtime.v3.require_vehicle(vin)
        except ValueError as err:
            raise HomeAssistantError(
                "Audi Connect vehicle is not present in its owning account"
            ) from err
        return vin, runtime.v3

    account = runtime.account
    if account is not None and any(
        data.vehicle and data.vehicle.vin.lower() == vin
        for data in account.config_vehicles
    ):
        return vin, account
    raise HomeAssistantError(
        "Audi Connect vehicle is not present in its owning account"
    )


def _get_all_coordinators(hass: HomeAssistant) -> list[AudiDataUpdateCoordinator]:
    """Get coordinators from all loaded config entries."""
    coordinators: list[AudiDataUpdateCoordinator] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime_data: AudiRuntimeData | None = getattr(entry, "runtime_data", None)
        if runtime_data is not None:
            coordinators.append(runtime_data.coordinator)
    return coordinators


def _reloadable_data(config_entry: ConfigEntry) -> dict[str, Any]:
    """Entry data that the running integration is configured from.

    The refresh token is excluded: it rotates on its own during normal operation
    and reloading on every rotation would tear the integration down for nothing.
    """
    return {k: v for k, v in config_entry.data.items() if k != CONF_REFRESH_TOKEN}


async def _async_update_listener(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Reload when the configuration changed, in options *or* in data.

    The S-PIN, region and API level live in entry data, not in options, so
    comparing options alone would silently skip the reload a reconfigure needs.
    Home Assistant reloads on its own today, but from 2026.12 it defers to this
    listener whenever one is registered, and the missed reload would surface as
    "my new S-PIN is ignored until I restart".
    """
    runtime_data: AudiRuntimeData | None = getattr(config_entry, "runtime_data", None)
    if (
        runtime_data is not None
        and runtime_data.options_snapshot == dict(config_entry.options)
        and runtime_data.data_snapshot == _reloadable_data(config_entry)
    ):
        # Only the refresh token rotated; nothing the running setup depends on.
        return
    await hass.config_entries.async_reload(config_entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register global services once (multi-account safe via device lookup)."""

    async def _handle_refresh_cloud_data(service: ServiceCall) -> None:
        for coordinator in _get_all_coordinators(hass):
            await coordinator.async_request_refresh()

    async def _handle_refresh_vehicle_data(service: ServiceCall) -> None:
        vin, account = _resolve_service_call(hass, service)
        if isinstance(account, V3Engine):
            await v3_execute_action(account, vin, "refresh_vehicle_data")
        else:
            await account.refresh_vehicle_data(vin)

    async def _handle_probe_api_paths(service: ServiceCall) -> None:
        """Retain the upstream V2 probe service without invoking V2 from V3."""
        vin, account = _resolve_service_call(hass, service)
        if isinstance(account, V3Engine):
            raise HomeAssistantError(
                "V3 uses its own read discovery. Use the Engineering Workbench "
                "for targeted scans; this legacy probe service is available in V2."
            )
        await account.connection.probe_read_only_api(
            vin, extended=service.data.get("extended", False)
        )

    async def _handle_set_local_dealer(service: ServiceCall) -> None:
        """Opt-in local metadata only; no Audi network calls."""
        vin, account = _resolve_service_call(hass, service)
        fields = {
            key: service.data[key] for key in DEALER_FIELDS if key in service.data
        }
        entry = account.entry if isinstance(account, V3Engine) else account.config_entry
        current = dict(entry.options)
        options = update_local_dealer_options(
            current, vin, fields, clear=service.data.get("clear", False)
        )
        if options != current:
            hass.config_entries.async_update_entry(entry, options=options)

    async def _handle_execute_vehicle_action(service: ServiceCall) -> None:
        vin, account = _resolve_service_call(hass, service)
        if isinstance(account, V3Engine):
            await v3_execute_action(
                account, vin, str(service.data.get("action", "")), dict(service.data)
            )
        else:
            await account.execute_vehicle_action(vin, service)

    async def _handle_start_climate_control(service: ServiceCall) -> None:
        vin, account = _resolve_service_call(hass, service)
        if isinstance(account, V3Engine):
            await v3_execute_action(
                account, vin, "start_climatisation", dict(service.data)
            )
        else:
            await account.start_climate_control(vin, service)

    async def _handle_start_auxiliary_heating(service: ServiceCall) -> None:
        vin, account = _resolve_service_call(hass, service)
        if isinstance(account, V3Engine):
            await v3_execute_action(
                account, vin, "start_auxiliary_heating", dict(service.data)
            )
        else:
            await account.start_auxiliary_heating(vin, service)

    async def _handle_set_location_charge_target(service: ServiceCall) -> None:
        vin, account = _resolve_service_call(hass, service)
        if isinstance(account, V3Engine):
            await v3_execute_action(
                account, vin, "set_location_charge_target", dict(service.data)
            )
        else:
            await account.set_location_charge_target(vin, service)

    async def _handle_set_charge_mode(service: ServiceCall) -> None:
        vin, account = _resolve_service_call(hass, service)
        if isinstance(account, V3Engine):
            await v3_execute_action(account, vin, "set_charge_mode", dict(service.data))
        else:
            await account.set_charge_mode(vin, service)

    async def _handle_set_target_soc(service: ServiceCall) -> None:
        vin, account = _resolve_service_call(hass, service)
        if isinstance(account, V3Engine):
            await v3_execute_action(account, vin, "set_target_soc", dict(service.data))
        else:
            await account.set_target_soc(vin, service)

    async def _handle_start_engine(service: ServiceCall) -> None:
        vin, account = _resolve_service_call(hass, service)
        if isinstance(account, V3Engine):
            await v3_execute_action(account, vin, "start_engine")
        else:
            await account.start_engine(vin)

    async def _handle_stop_engine(service: ServiceCall) -> None:
        vin, account = _resolve_service_call(hass, service)
        if isinstance(account, V3Engine):
            await v3_execute_action(account, vin, "stop_engine")
        else:
            await account.stop_engine(vin)

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
    # Remove obsolete engineering actions left by older development builds.
    for obsolete in ("probe_vehicle_health", "probe_trip_data", "refresh_trip_data"):
        if hass.services.has_service(DOMAIN, obsolete):
            hass.services.async_remove(DOMAIN, obsolete)
    if not hass.services.has_service(DOMAIN, SERVICE_PROBE_API_PATHS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_PROBE_API_PATHS,
            _handle_probe_api_paths,
            schema=PROBE_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_LOCAL_DEALER):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_LOCAL_DEALER,
            _handle_set_local_dealer,
            schema=LOCAL_DEALER_SCHEMA,
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
    if not hass.services.has_service(DOMAIN, SERVICE_SET_LOCATION_CHARGE_TARGET):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_LOCATION_CHARGE_TARGET,
            _handle_set_location_charge_target,
            schema=SERVICE_SET_LOCATION_CHARGE_TARGET_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_CHARGE_MODE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_CHARGE_MODE,
            _handle_set_charge_mode,
            schema=SERVICE_SET_CHARGE_MODE_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_TARGET_SOC):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_TARGET_SOC,
            _handle_set_target_soc,
            schema=SERVICE_SET_TARGET_SOC_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_START_ENGINE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_ENGINE,
            _handle_start_engine,
            schema=SERVICE_START_ENGINE_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_STOP_ENGINE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_STOP_ENGINE,
            _handle_stop_engine,
            schema=SERVICE_STOP_ENGINE_SCHEMA,
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
    if runtime_data.v3 is not None:
        # V3 must not destructively prune HA device registry entries as a side
        # effect of a mode switch or an incomplete account inventory. Device
        # removal needs a separate authoritative-inventory workflow.
        return

    active_vins: set[str] = set()
    for vehicle_data in runtime_data.account.config_vehicles:
        if vehicle_data.vehicle and vehicle_data.vehicle.vin:
            active_vins.add(vehicle_data.vehicle.vin.lower())

    if not active_vins:
        # A skipped/failed startup scan is not evidence that every Audi was
        # removed. Never delete registered devices from an empty snapshot.
        return

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
    # Accept whichever credential the entry actually holds, regardless of region:
    # device-code was offered everywhere in 2.2.1b1/b2, so a non-European entry can
    # hold a perfectly good refresh token. Only prompt when neither is present.
    has_refresh_token = bool(config_entry.data.get(CONF_REFRESH_TOKEN))
    has_credentials = bool(
        config_entry.data.get(CONF_USERNAME) and config_entry.data.get(CONF_PASSWORD)
    )
    if not has_refresh_token and not has_credentials:
        raise ConfigEntryAuthFailed(
            "Audi Connect needs to sign in again"
            if uses_auth0(config_entry.data.get(CONF_REGION))
            else "Audi Connect needs your myAudi username and password to sign in"
        )

    selected_v3 = config_entry.options.get(V3_RUNTIME_OPTION, V3_DEFAULT) == V3_ENABLED
    if selected_v3:
        # One Audi account, one refresh-token owner. V3 supplies its own
        # independent vehicle polling and command engine; creating AudiAccount
        # here does NOT activate its V2 coordinator or cloud business polls.
        from .v3.auth import V3Auth

        account = AudiAccount(hass, config_entry)
        registry = await hass.async_add_executor_job(
            CapabilityRegistry.from_json_file, catalog_path()
        )
        engine = V3Engine(
            hass,
            config_entry,
            registry,
            auth=V3Auth(hass, config_entry, shared_account=account),
        )
        coordinator = V3CleanCoordinator(hass, engine, config_entry)
        config_entry.runtime_data = AudiRuntimeData(
            account=account,
            coordinator=coordinator,
            v3=engine,
            loaded_platforms=list(
                PLATFORMS
            ),  # Same 9 HA platforms; V3 owns implementation.
            options_snapshot=dict(config_entry.options),
            data_snapshot=_reloadable_data(config_entry),
        )
    else:
        account = AudiAccount(hass, config_entry)
        coordinator = AudiDataUpdateCoordinator.from_entry(hass, account, config_entry)

        async def _request_refresh(*_: Any) -> None:
            await coordinator.async_request_refresh()

        account.set_refresh_callback(_request_refresh)
        config_entry.runtime_data = AudiRuntimeData(
            account=account,
            coordinator=coordinator,
            options_snapshot=dict(config_entry.options),
            data_snapshot=_reloadable_data(config_entry),
        )

    config_entry.async_on_unload(
        config_entry.add_update_listener(_async_update_listener)
    )
    # V3 must enumerate its vehicles before creating the limited HA entities.
    # V2 retains the user's historical "scan on setup" preference.
    if selected_v3 or config_entry.options.get(CONF_SCAN_INITIAL, True):
        await coordinator.async_config_entry_first_refresh()

    _async_cleanup_orphaned_devices(hass, config_entry)
    # Register the same HA service IDs in both runtimes. Service handlers
    # resolve VIN ownership to the active adapter, never a parallel V2 poller.
    _async_register_services(hass)
    if selected_v3:
        from .v3.registry_lifecycle import async_apply_v3_entity_visibility
        from .v3.dashboard import async_setup_dashboard

        await async_apply_v3_entity_visibility(hass, config_entry, True)
        await hass.config_entries.async_forward_entry_setups(
            config_entry, config_entry.runtime_data.loaded_platforms
        )
        if config_entry.options.get("v3_development_workbench", False):
            await async_setup_dashboard(hass)
    else:
        from .v3.registry_lifecycle import async_apply_v3_entity_visibility

        await async_apply_v3_entity_visibility(hass, config_entry, False)
        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload Audi Connect entry."""
    runtime = getattr(config_entry, "runtime_data", None)
    platforms = runtime.loaded_platforms if runtime is not None else PLATFORMS
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, platforms
    )
    if not unload_ok:
        return False

    if isinstance(getattr(runtime, "v3", None), V3Engine):
        from .v3.dashboard import async_remove_dashboard

        # On V3→V2 switch, or opting out, hide the sidebar panel. Do not
        # remove it if another live V3 entry explicitly opted in.
        others = any(
            entry.entry_id != config_entry.entry_id
            and entry.options.get("runtime_version", "v2") == "v3_climate"
            and entry.options.get("v3_development_workbench", False)
            and isinstance(
                getattr(getattr(entry, "runtime_data", None), "v3", None),
                V3Engine,
            )
            for entry in hass.config_entries.async_entries(DOMAIN)
        )
        if not others:
            async_remove_dashboard(hass)

    if len(hass.config_entries.async_entries(DOMAIN)) <= 1:
        for service in (
            SERVICE_PROBE_API_PATHS,
            SERVICE_SET_LOCAL_DEALER,
            SERVICE_REFRESH_CLOUD_DATA,
            SERVICE_REFRESH_VEHICLE_DATA,
            SERVICE_EXECUTE_VEHICLE_ACTION,
            SERVICE_START_CLIMATE_CONTROL,
            SERVICE_START_AUXILIARY_HEATING,
            SERVICE_SET_CHARGE_MODE,
            SERVICE_SET_LOCATION_CHARGE_TARGET,
            SERVICE_SET_TARGET_SOC,
            SERVICE_START_ENGINE,
            SERVICE_STOP_ENGINE,
        ):
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)

    return True


async def async_remove_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Remove all entry-owned V3 storage, not on unload or runtime switch."""
    from .v3.profile_store import V3ProfileStorage
    from .v3.registry_lifecycle import async_remove_visibility
    from .v3.trip_archive import V3TripArchive

    entry_id = config_entry.entry_id
    await V3ProfileStorage(hass, entry_id).async_remove()
    await V3TripArchive(hass, entry_id).async_remove()
    await async_remove_visibility(hass, entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    return True


__all__ = [
    "AudiRuntimeData",
    "async_migrate_entry",
    "async_setup_entry",
    "async_unload_entry",
]
