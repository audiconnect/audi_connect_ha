import logging
from datetime import timedelta
import voluptuous as vol

from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.dispatcher import (
    async_dispatcher_send,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util.dt import utcnow
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
)

from .dashboard import Dashboard
from .audi_connect_account import AudiConnectAccount, AudiConnectObserver
from .audi_models import VehicleData

from .const import (
    DOMAIN,
    CONF_VIN,
    CONF_ACTION,
    CONF_CLIMATE_TEMP_F,
    CONF_CLIMATE_TEMP_C,
    CONF_CLIMATE_GLASS,
    CONF_CLIMATE_SEAT_FL,
    CONF_CLIMATE_SEAT_FR,
    CONF_CLIMATE_SEAT_RL,
    CONF_CLIMATE_SEAT_RR,
    CONF_REGION,
    CONF_SPIN,
    SIGNAL_STATE_UPDATED,
    TRACKER_UPDATE,
    COMPONENTS,
)

REFRESH_VEHICLE_DATA_FAILED_EVENT = "refresh_failed"
REFRESH_VEHICLE_DATA_COMPLETED_EVENT = "refresh_completed"

SERVICE_REFRESH_VEHICLE_DATA = "refresh_vehicle_data"
SERVICE_REFRESH_VEHICLE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_VIN): cv.string,
    }
)

SERVICE_EXECUTE_VEHICLE_ACTION = "execute_vehicle_action"
SERVICE_EXECUTE_VEHICLE_ACTION_SCHEMA = vol.Schema(
    {vol.Required(CONF_VIN): cv.string, vol.Required(CONF_ACTION): cv.string}
)

SERVICE_START_CLIMATE_CONTROL = "start_climate_control"
SERVICE_START_CLIMATE_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_VIN): cv.string,
        vol.Optional(CONF_CLIMATE_TEMP_F): cv.positive_int,
        vol.Optional(CONF_CLIMATE_TEMP_C): cv.positive_int,
        vol.Optional(CONF_CLIMATE_GLASS): cv.boolean,
        vol.Optional(CONF_CLIMATE_SEAT_FL): cv.boolean,
        vol.Optional(CONF_CLIMATE_SEAT_FR): cv.boolean,
        vol.Optional(CONF_CLIMATE_SEAT_RL): cv.boolean,
        vol.Optional(CONF_CLIMATE_SEAT_RR): cv.boolean,
    }
)

SERVICE_REFRESH_CLOUD_DATA = "refresh_cloud_data"

_LOGGER = logging.getLogger(__name__)


class AudiAccount(AudiConnectObserver):
    def __init__(self, hass, config_entry, unit_system: str, scan_interval: int):
        """Initialize the component state."""
        self.hass = hass
        self.config_entry = config_entry
        self.config_vehicles = set()
        self.vehicles = set()
        self.interval = scan_interval
        self.unit_system = unit_system

    def init_connection(self):
        session = async_get_clientsession(self.hass)
        self.connection = AudiConnectAccount(
            session=session,
            username=self.config_entry.data.get(CONF_USERNAME),
            password=self.config_entry.data.get(CONF_PASSWORD),
            country=self.config_entry.data.get(CONF_REGION),
            spin=self.config_entry.data.get(CONF_SPIN),
        )

        self.hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_VEHICLE_DATA,
            self.refresh_vehicle_data,
            schema=SERVICE_REFRESH_VEHICLE_DATA_SCHEMA,
        )
        self.hass.services.async_register(
            DOMAIN,
            SERVICE_EXECUTE_VEHICLE_ACTION,
            self.execute_vehicle_action,
            schema=SERVICE_EXECUTE_VEHICLE_ACTION_SCHEMA,
        )
        self.hass.services.async_register(
            DOMAIN,
            SERVICE_START_CLIMATE_CONTROL,
            self.start_climate_control,
            schema=SERVICE_START_CLIMATE_CONTROL_SCHEMA,
        )
        self.hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_CLOUD_DATA,
            self.refresh_cloud_data,
        )

        self.connection.add_observer(self)

    def is_enabled(self, attr):
        return True
        # """Return true if the user has enabled the resource."""
        # return attr in config[DOMAIN].get(CONF_RESOURCES, [attr])

    def discover_vehicles(self, vehicles):
        if len(vehicles) > 0:
            for vehicle in vehicles:
                vin = vehicle.vin.lower()

                self.vehicles.add(vin)

                cfg_vehicle = VehicleData(self.config_entry)
                cfg_vehicle.vehicle = vehicle
                self.config_vehicles.add(cfg_vehicle)

                dashboard = Dashboard(
                    self.connection, vehicle, unit_system=self.unit_system
                )

                for instrument in (
                    instrument
                    for instrument in dashboard.instruments
                    if instrument._component in COMPONENTS
                    and self.is_enabled(instrument.slug_attr)
                ):
                    if instrument._component == "sensor":
                        cfg_vehicle.sensors.add(instrument)
                    if instrument._component == "binary_sensor":
                        cfg_vehicle.binary_sensors.add(instrument)
                    if instrument._component == "switch":
                        cfg_vehicle.switches.add(instrument)
                    if instrument._component == "device_tracker":
                        cfg_vehicle.device_trackers.add(instrument)
                    if instrument._component == "lock":
                        cfg_vehicle.locks.add(instrument)

            self.hass.async_add_job(
                self.hass.config_entries.async_forward_entry_setup(
                    self.config_entry, "sensor"
                )
            )
            self.hass.async_add_job(
                self.hass.config_entries.async_forward_entry_setup(
                    self.config_entry, "binary_sensor"
                )
            )
            self.hass.async_add_job(
                self.hass.config_entries.async_forward_entry_setup(
                    self.config_entry, "switch"
                )
            )
            self.hass.async_add_job(
                self.hass.config_entries.async_forward_entry_setup(
                    self.config_entry, "device_tracker"
                )
            )
            self.hass.async_add_job(
                self.hass.config_entries.async_forward_entry_setup(
                    self.config_entry, "lock"
                )
            )

    async def update(self, now):
        """Update status from the cloud."""
        _LOGGER.info("Running update for Audi Connect service at %s", now)
        try:
            if not await self.connection.update(None):
                _LOGGER.warning("Failed to update from Audi Connect service")
                return False

            # Discover new vehicles that have not been added yet
            new_vehicles = [
                x for x in self.connection._vehicles if x.vin not in self.vehicles
            ]
            if new_vehicles:
                _LOGGER.info("Discovered %d new vehicles", len(new_vehicles))
            self.discover_vehicles(new_vehicles)

            async_dispatcher_send(self.hass, SIGNAL_STATE_UPDATED)

            for config_vehicle in self.config_vehicles:
                for instrument in config_vehicle.device_trackers:
                    async_dispatcher_send(self.hass, TRACKER_UPDATE, instrument)

            _LOGGER.info("Successfully updated Audi Connect service")
            return True
        finally:
            # Schedule next update
            next_update = utcnow() + timedelta(minutes=self.interval)
            _LOGGER.info(
                "Scheduling next update for Audi Connect service at %s", next_update
            )
            async_track_point_in_utc_time(self.hass, self.update, next_update)

    async def refresh_cloud_data(self, now):
        """Refresh data from the cloud."""
        _LOGGER.info("Running refresh_cloud_data for Audi Connect service")
        try:
            if not await self.connection.update(None):
                _LOGGER.warning("Failed to update from Audi Connect service")
                return False

            # Discover new vehicles that have not been added yet
            new_vehicles = [
                x for x in self.connection._vehicles if x.vin not in self.vehicles
            ]
            if new_vehicles:
                _LOGGER.info("Discovered %d new vehicles", len(new_vehicles))
            self.discover_vehicles(new_vehicles)

            async_dispatcher_send(self.hass, SIGNAL_STATE_UPDATED)

            for config_vehicle in self.config_vehicles:
                for instrument in config_vehicle.device_trackers:
                    async_dispatcher_send(self.hass, TRACKER_UPDATE, instrument)

            _LOGGER.info("Successfully completed cloud update for Audi Connect service")
            return True
        except Exception as e:
            _LOGGER.error("An error occurred during the cloud update process: %s", e)
            return False

    async def execute_vehicle_action(self, service):
        device_id = service.data.get(CONF_VIN).lower()
        device = dr.async_get(self.hass).async_get(device_id)
        vin = dict(device.identifiers).get(DOMAIN)
        action = service.data.get(CONF_ACTION).lower()

        if action == "lock":
            await self.connection.set_vehicle_lock(vin, True)
        if action == "unlock":
            await self.connection.set_vehicle_lock(vin, False)
        if action == "start_climatisation":
            await self.connection.set_vehicle_climatisation(vin, True)
        if action == "stop_climatisation":
            await self.connection.set_vehicle_climatisation(vin, False)
        if action == "start_charger":
            await self.connection.set_battery_charger(vin, True, False)
        if action == "start_timed_charger":
            await self.connection.set_battery_charger(vin, True, True)
        if action == "stop_charger":
            await self.connection.set_battery_charger(vin, False, False)
        if action == "start_preheater":
            await self.connection.set_vehicle_pre_heater(vin, True)
        if action == "stop_preheater":
            await self.connection.set_vehicle_pre_heater(vin, False)
        if action == "start_window_heating":
            await self.connection.set_vehicle_window_heating(vin, True)
        if action == "stop_window_heating":
            await self.connection.set_vehicle_window_heating(vin, False)

    async def start_climate_control(self, service):
        _LOGGER.info("Initiating Start Climate Control Service...")
        device_id = service.data.get(CONF_VIN).lower()
        device = dr.async_get(self.hass).async_get(device_id)
        vin = dict(device.identifiers).get(DOMAIN)
        # Optional Parameters
        temp_f = service.data.get(CONF_CLIMATE_TEMP_F, None)
        temp_c = service.data.get(CONF_CLIMATE_TEMP_C, None)
        glass_heating = service.data.get(CONF_CLIMATE_GLASS, False)
        seat_fl = service.data.get(CONF_CLIMATE_SEAT_FL, False)
        seat_fr = service.data.get(CONF_CLIMATE_SEAT_FR, False)
        seat_rl = service.data.get(CONF_CLIMATE_SEAT_RL, False)
        seat_rr = service.data.get(CONF_CLIMATE_SEAT_RR, False)

        await self.connection.start_climate_control(
            vin,
            temp_f,
            temp_c,
            glass_heating,
            seat_fl,
            seat_fr,
            seat_rl,
            seat_rr,
        )

    async def handle_notification(self, vin: str, action: str) -> None:
        await self._refresh_vehicle_data(vin)

    async def refresh_vehicle_data(self, service):
        device_id = service.data.get(CONF_VIN).lower()
        device = dr.async_get(self.hass).async_get(device_id)
        vin = dict(device.identifiers).get(DOMAIN)
        await self._refresh_vehicle_data(vin)

    async def _refresh_vehicle_data(self, vin):
        res = await self.connection.refresh_vehicle_data(vin)

        if res is True:
            await self.update(utcnow())

            self.hass.bus.fire(
                "{}_{}".format(DOMAIN, REFRESH_VEHICLE_DATA_COMPLETED_EVENT),
                {"vin": vin},
            )

        else:
            _LOGGER.exception("Error refreshing vehicle data %s", vin)
            self.hass.bus.fire(
                "{}_{}".format(DOMAIN, REFRESH_VEHICLE_DATA_FAILED_EVENT), {"vin": vin}
            )
