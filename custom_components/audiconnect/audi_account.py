from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .audi_connect_account import AudiConnectAccount, AudiConnectObserver
from .audi_models import VehicleData
from .const import (
    CONF_ACTION,
    CONF_API_LEVEL,
    CONF_CLIMATE_AT_UNLOCK,
    CONF_CLIMATE_GLASS,
    CONF_CLIMATE_MODE,
    CONF_CLIMATE_SEAT_FL,
    CONF_CLIMATE_SEAT_FR,
    CONF_CLIMATE_SEAT_RL,
    CONF_CLIMATE_SEAT_RR,
    CONF_CLIMATE_TEMP_C,
    CONF_CLIMATE_TEMP_F,
    CONF_DEVICE_ID,
    CONF_DURATION,
    CONF_FILTER_VINS,
    CONF_REFRESH_AFTER_ACTION,
    CONF_REGION,
    CONF_UPDATE_SLEEP,
    CONF_SPIN,
    CONF_TARGET_SOC,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_API_LEVEL,
    DOMAIN,
    REFRESH_VEHICLE_DATA_COMPLETED_EVENT,
    REFRESH_VEHICLE_DATA_FAILED_EVENT,
    UPDATE_SLEEP,
)
from .dashboard import Dashboard

_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH_VEHICLE_DATA = "refresh_vehicle_data"
SERVICE_REFRESH_VEHICLE_DATA_SCHEMA = vol.Schema(
    {vol.Required(CONF_DEVICE_ID): cv.string}
)

SERVICE_EXECUTE_VEHICLE_ACTION = "execute_vehicle_action"
SERVICE_EXECUTE_VEHICLE_ACTION_SCHEMA = vol.Schema(
    {vol.Required(CONF_DEVICE_ID): cv.string, vol.Required(CONF_ACTION): cv.string}
)

SERVICE_START_CLIMATE_CONTROL = "start_climate_control"
SERVICE_START_CLIMATE_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Optional(CONF_CLIMATE_TEMP_F): cv.positive_int,
        vol.Optional(CONF_CLIMATE_TEMP_C): cv.positive_int,
        vol.Optional(CONF_CLIMATE_GLASS): cv.boolean,
        vol.Optional(CONF_CLIMATE_SEAT_FL): cv.boolean,
        vol.Optional(CONF_CLIMATE_SEAT_FR): cv.boolean,
        vol.Optional(CONF_CLIMATE_SEAT_RL): cv.boolean,
        vol.Optional(CONF_CLIMATE_SEAT_RR): cv.boolean,
        vol.Optional(CONF_CLIMATE_AT_UNLOCK): cv.boolean,
        vol.Optional(CONF_CLIMATE_MODE): cv.string,
    }
)

SERVICE_START_AUXILIARY_HEATING = "start_auxiliary_heating"
SERVICE_START_AUXILIARY_HEATING_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Optional(CONF_DURATION): cv.positive_int,
    }
)

SERVICE_SET_TARGET_SOC = "set_target_soc"
SERVICE_SET_TARGET_SOC_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Required(CONF_TARGET_SOC): vol.All(
            cv.positive_int, vol.Range(min=20, max=100)
        ),
    }
)

SERVICE_REFRESH_CLOUD_DATA = "refresh_cloud_data"


class AudiAccount(AudiConnectObserver):
    """Account wrapper that owns Audi API client and mapped vehicle instruments."""

    def __init__(self, hass: HomeAssistant, config_entry: Any) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.config_vehicles: list[VehicleData] = []
        self._known_vehicle_vins: set[str] = set()
        self._refresh_callback: Callable[[], Any] | None = None

        session = async_get_clientsession(self.hass)
        excluded_vins = [
            vin.strip().lower()
            for vin in self.config_entry.options.get(
                CONF_FILTER_VINS, self.config_entry.data.get(CONF_FILTER_VINS, "")
            ).split(",")
            if vin.strip()
        ]

        self.connection = AudiConnectAccount(
            session=session,
            username=self.config_entry.data.get(CONF_USERNAME),
            password=self.config_entry.data.get(CONF_PASSWORD),
            country=self.config_entry.data.get(CONF_REGION),
            spin=self.config_entry.data.get(CONF_SPIN),
            api_level=self.config_entry.data.get(CONF_API_LEVEL, DEFAULT_API_LEVEL),
            excluded_vins=excluded_vins,
        )
        self.connection.add_observer(self)

    def set_refresh_callback(self, callback: Callable[[], Any]) -> None:
        self._refresh_callback = callback

    def _build_vehicle_data(self, vehicle: Any) -> VehicleData:
        cfg_vehicle = VehicleData(self.config_entry)
        cfg_vehicle.vehicle = vehicle
        dashboard = Dashboard(self.connection, vehicle)

        for instrument in dashboard.instruments:
            component = instrument.component
            if component == "sensor":
                cfg_vehicle.sensors.add(instrument)
            elif component == "binary_sensor":
                cfg_vehicle.binary_sensors.add(instrument)
            elif component == "switch":
                cfg_vehicle.switches.add(instrument)
            elif component == "device_tracker":
                cfg_vehicle.device_trackers.add(instrument)
            elif component == "lock":
                cfg_vehicle.locks.add(instrument)

        return cfg_vehicle

    async def async_refresh_data(self) -> list[VehicleData]:
        """Refresh cloud data and update discovered vehicles."""
        _LOGGER.debug("Starting refresh cloud data...")
        if not await self.connection.update(None):
            _LOGGER.warning("Failed refresh cloud data")
            raise RuntimeError("Failed refresh cloud data")

        known = {
            vehicle.vehicle.vin.lower(): vehicle
            for vehicle in self.config_vehicles
            if vehicle.vehicle and vehicle.vehicle.vin
        }
        for vehicle in self.connection.vehicles:
            vin = vehicle.vin.lower()
            if vin in known:
                continue
            self._known_vehicle_vins.add(vin)
            self.config_vehicles.append(self._build_vehicle_data(vehicle))

        _LOGGER.debug("Successfully refreshed cloud data")
        return self.config_vehicles

    async def execute_vehicle_action(self, vin: str, service: ServiceCall) -> None:
        """Execute a vehicle action by VIN."""
        vin = vin.lower()
        action = service.data.get(CONF_ACTION).lower()

        if action == "lock":
            await self.connection.set_vehicle_lock(vin, True)
        elif action == "unlock":
            await self.connection.set_vehicle_lock(vin, False)
        elif action == "start_climatisation":
            await self.connection.set_vehicle_climatisation(vin, True)
        elif action == "stop_climatisation":
            await self.connection.set_vehicle_climatisation(vin, False)
        elif action == "start_charger":
            await self.connection.set_battery_charger(vin, True, False)
        elif action == "start_timed_charger":
            await self.connection.set_battery_charger(vin, True, True)
        elif action == "stop_charger":
            await self.connection.set_battery_charger(vin, False, False)
        elif action == "start_preheater":
            _LOGGER.warning(
                'The "Start Preheater (Legacy)" action is deprecated and will be removed in a future release. '
                'Please use the "Start Auxiliary Heating" service instead.'
            )
            await self.connection.set_vehicle_pre_heater(vin, True)
        elif action == "stop_preheater":
            await self.connection.set_vehicle_pre_heater(vin, False)
        elif action == "start_window_heating":
            await self.connection.set_vehicle_window_heating(vin, True)
        elif action == "stop_window_heating":
            await self.connection.set_vehicle_window_heating(vin, False)

    async def start_climate_control(self, vin: str, service: ServiceCall) -> None:
        """Start climate control for a vehicle by VIN."""
        await self.connection.start_climate_control(
            vin.lower(),
            service.data.get(CONF_CLIMATE_TEMP_F),
            service.data.get(CONF_CLIMATE_TEMP_C),
            service.data.get(CONF_CLIMATE_GLASS, False),
            service.data.get(CONF_CLIMATE_SEAT_FL, False),
            service.data.get(CONF_CLIMATE_SEAT_FR, False),
            service.data.get(CONF_CLIMATE_SEAT_RL, False),
            service.data.get(CONF_CLIMATE_SEAT_RR, False),
            service.data.get(CONF_CLIMATE_AT_UNLOCK, False),
            service.data.get(CONF_CLIMATE_MODE),
        )

    async def start_auxiliary_heating(self, vin: str, service: ServiceCall) -> None:
        """Start auxiliary heating for a vehicle by VIN."""
        await self.connection.set_vehicle_pre_heater(
            vin=vin.lower(),
            activate=True,
            duration=service.data.get(CONF_DURATION),
        )

    async def set_target_soc(self, vin: str, service: ServiceCall) -> None:
        """Set target state of charge for a vehicle by VIN."""
        await self.connection.set_target_state_of_charge(
            vin.lower(),
            service.data.get(CONF_TARGET_SOC),
        )

    async def handle_notification(self, vin: str, action: str) -> None:
        if self.config_entry.options.get(CONF_REFRESH_AFTER_ACTION, False):
            await self._refresh_vehicle_data(vin)
        else:
            update_sleep = self.config_entry.options.get(
                CONF_UPDATE_SLEEP, UPDATE_SLEEP
            )
            _LOGGER.debug("Sleeping %s seconds before cloud data refresh", update_sleep)
            await asyncio.sleep(update_sleep)
            if self._refresh_callback:
                await self._refresh_callback()

    async def refresh_vehicle_data(self, vin: str) -> None:
        """Refresh data for a specific vehicle by VIN."""
        await self._refresh_vehicle_data(vin.lower())

    async def _refresh_vehicle_data(self, vin: str) -> None:
        redacted_vin = "*" * (len(vin) - 4) + vin[-4:]
        result = await self.connection.refresh_vehicle_data(vin)

        if result is True:
            self.hass.bus.async_fire(
                f"{DOMAIN}_{REFRESH_VEHICLE_DATA_COMPLETED_EVENT}",
                {"vin": redacted_vin},
            )
        elif result != "disabled":
            self.hass.bus.async_fire(
                f"{DOMAIN}_{REFRESH_VEHICLE_DATA_FAILED_EVENT}", {"vin": redacted_vin}
            )

        update_sleep = self.config_entry.options.get(CONF_UPDATE_SLEEP, UPDATE_SLEEP)
        _LOGGER.debug("Sleeping %s seconds before cloud data refresh", update_sleep)
        await asyncio.sleep(update_sleep)
        if self._refresh_callback:
            await self._refresh_callback()


__all__ = [
    "AudiAccount",
    "SERVICE_EXECUTE_VEHICLE_ACTION",
    "SERVICE_EXECUTE_VEHICLE_ACTION_SCHEMA",
    "SERVICE_REFRESH_CLOUD_DATA",
    "SERVICE_REFRESH_VEHICLE_DATA",
    "SERVICE_REFRESH_VEHICLE_DATA_SCHEMA",
    "SERVICE_SET_TARGET_SOC",
    "SERVICE_SET_TARGET_SOC_SCHEMA",
    "SERVICE_START_AUXILIARY_HEATING",
    "SERVICE_START_AUXILIARY_HEATING_SCHEMA",
    "SERVICE_START_CLIMATE_CONTROL",
    "SERVICE_START_CLIMATE_CONTROL_SCHEMA",
]
