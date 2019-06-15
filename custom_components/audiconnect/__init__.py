"""Support for Audi Connect."""
import logging
from datetime import timedelta
import threading
import asyncio

import voluptuous as vol

from audiapi.Services import RequestStatus

import homeassistant.helpers.config_validation as cv
from homeassistant.const import (
    CONF_NAME, CONF_PASSWORD, CONF_RESOURCES, CONF_SCAN_INTERVAL, CONF_USERNAME
)
from homeassistant.helpers import discovery
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect, async_dispatcher_send
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util.dt import utcnow

from .dashboard import Dashboard

DOMAIN = 'audiconnect'

DATA_KEY = DOMAIN

_LOGGER = logging.getLogger(__name__)

MIN_UPDATE_INTERVAL = timedelta(minutes=1)
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=10)

CONF_REGION = 'region'
CONF_SERVICE_URL = 'service_url'
CONF_MUTABLE = 'mutable'

MAX_RESPONSE_ATTEMPTS = 10
REQUEST_STATUS_SLEEP = 5

ATTR_VIN = 'vin'
REFRESH_VEHICLE_DATA_FAILED_EVENT = 'refresh_vehicle_data_failed'
REFRESH_VEHICLE_DATA_COMPLETED_EVENT = 'refresh_vehicle_data_completed'
SERVICE_REFRESH_VEHICLE_DATA = 'refresh_vehicle_data'
SERVICE_REFRESH_VEHICLE_DATA_SCHEMA = vol.Schema({
    vol.Required(ATTR_VIN): cv.string,
})

SIGNAL_STATE_UPDATED = '{}.updated'.format(DOMAIN)

COMPONENTS = {
    'sensor': 'sensor',
    'binary_sensor': 'binary_sensor',
    'lock': 'lock',
    'device_tracker': 'device_tracker',
    'switch': 'switch',
}

RESOURCES = [
     'position',
     'last_update_time',
     'mileage'
     'range',
     'service_inspection_time',
     'service_inspection_distance',
     'oil_change_time',
     'oil_change_distance',
     'oil_level',
     'charging_state',
     'max_charge_current',
     'engine_type1',
     'engine_type2',
     'parking_light',
     'any_window_open',
     'any_door_unlocked',
     'any_door_open',
     'trunk_unlocked',
     'trunk_open',
     'hood_open',
     'tank_level',
     'state_of_charge',
     'remaining_charging_time',
     'plug_state', 
     'sun_roof'
]

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_UPDATE_INTERVAL):
            vol.All(cv.time_period, vol.Clamp(min=MIN_UPDATE_INTERVAL)),
        vol.Optional(CONF_NAME, default={}):
            cv.schema_with_slug_keys(cv.string),
        vol.Optional(CONF_RESOURCES): vol.All(
            cv.ensure_list, [vol.In(RESOURCES)]),
        vol.Optional(CONF_REGION): cv.string,
        vol.Optional(CONF_MUTABLE, default=True): cv.boolean,
    })
}, extra=vol.ALLOW_EXTRA)

async def async_setup(hass, config):
    """Set up the Audi Connect component."""

    from .audi_connect_account import AudiConnectAccount
    connection = AudiConnectAccount(
        username=config[DOMAIN].get(CONF_USERNAME),
        password=config[DOMAIN].get(CONF_PASSWORD))

    interval = config[DOMAIN][CONF_SCAN_INTERVAL]

    data = hass.data[DATA_KEY] = AudiData(config)

    def is_enabled(attr):
        """Return true if the user has enabled the resource."""
        return attr in config[DOMAIN].get(CONF_RESOURCES, [attr])

    def discover_vehicle(vehicle):
        """Load relevant platforms."""
        data.vehicles.add(vehicle.vin)

        dashboard = Dashboard(vehicle)

        for instrument in (
                instrument
                for instrument in dashboard.instruments
                if instrument.component in COMPONENTS and
                is_enabled(instrument.slug_attr)):

            data.instruments.add(instrument)

            hass.async_create_task(
                discovery.async_load_platform(
                    hass,
                    COMPONENTS[instrument.component],
                    DOMAIN,
                    (vehicle.vin,
                     instrument.component,
                     instrument.attr),
                    config))

    async def update(now):

        """Update status from the online service."""
        try:
            if not await connection.update():
                _LOGGER.warning("Could not query server")
                return False

            for vehicle in connection.vehicles:
                if vehicle.vin not in data.vehicles:
                    discover_vehicle(vehicle)

            async_dispatcher_send(hass, SIGNAL_STATE_UPDATED)

            return True
        finally:
            async_track_point_in_utc_time(hass, update, utcnow() + interval)

    def refresh_vehicle_data(service):
        """Start thread to trigger update from car."""
        def do_trigger_vehicle_refresh():
            vin = service.data.get(ATTR_VIN).lower()

            try:
                vehicle = [v for v in connection.vehicles if v.vin.lower() == vin]

                if vehicle and len(vehicle) > 0:
                    request_id = vehicle[0].refresh_vehicle_data()

                    for attempt in range(MAX_RESPONSE_ATTEMPTS):
                        asyncio.run_coroutine_threadsafe(asyncio.sleep(REQUEST_STATUS_SLEEP), hass.loop).result()

                        status = vehicle[0].get_status_from_update(request_id)

                        if status == RequestStatus.SUCCESS:
                            asyncio.run_coroutine_threadsafe(update(utcnow()), hass.loop).result()

                            hass.bus.fire(
                                "{}_{}".format(DOMAIN, REFRESH_VEHICLE_DATA_COMPLETED_EVENT), {
                                    'vin': vin
                                })

                            return

            except Exception:
                _LOGGER.exception("Error refreshing vehicle data %s", vin)
                hass.bus.fire(
                    "{}_{}".format(DOMAIN, REFRESH_VEHICLE_DATA_FAILED_EVENT), {
                        'vin': vin
                        })

        threading.Thread(target=do_trigger_vehicle_refresh).start()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH_VEHICLE_DATA, refresh_vehicle_data,
                           schema=SERVICE_REFRESH_VEHICLE_DATA_SCHEMA)
                           
    return await update(utcnow())


class AudiData:
    """Hold component state."""

    def __init__(self, config):
        """Initialize the component state."""
        self.vehicles = set()
        self.instruments = set()
        self.config = config[DOMAIN]
        self.names = self.config.get(CONF_NAME)

    def instrument(self, vin, component, attr):
        """Return corresponding instrument."""
        return next((instrument
                     for instrument in self.instruments
                     if instrument.vehicle.vin == vin and
                     instrument.component == component and
                     instrument.attr == attr), None)

    def vehicle_name(self, vehicle):
        """Provide a friendly name for a vehicle."""
        if vehicle.vin and vehicle.vin.lower() in self.names:
            return self.names[vehicle.vin.lower()]
        if vehicle.vin:
            return vehicle.vin
        return ''


class AudiEntity(Entity):
    """Base class for all entities."""

    def __init__(self, data, vin, component, attribute):
        """Initialize the entity."""
        self.data = data
        self.vin = vin
        self.component = component
        self.attribute = attribute

    async def async_added_to_hass(self):
        """Register update dispatcher."""
        async_dispatcher_connect(
            self.hass, SIGNAL_STATE_UPDATED,
            self.async_schedule_update_ha_state)

    @property
    def instrument(self):
        """Return corresponding instrument."""
        return self.data.instrument(self.vin, self.component, self.attribute)

    @property
    def icon(self):
        """Return the icon."""
        return self.instrument.icon

    @property
    def vehicle(self):
        """Return vehicle."""
        return self.instrument.vehicle

    @property
    def _entity_name(self):
        return self.instrument.name

    @property
    def _vehicle_name(self):
        return self.data.vehicle_name(self.vehicle)

    @property
    def name(self):
        """Return full name of the entity."""
        return '{} {}'.format(
            self._vehicle_name,
            self._entity_name)

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def assumed_state(self):
        """Return true if unable to access real state of entity."""
        return True

    @property
    def device_state_attributes(self):
        """Return device specific state attributes."""
        return dict(self.instrument.attributes,
                    model='{}/{}'.format(
                        self.vehicle.model,
                        self.vehicle.registered))
