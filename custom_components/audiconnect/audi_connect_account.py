import json
import time
from datetime import timedelta, datetime
import logging
import asyncio
from typing import List

from asyncio import TimeoutError
from aiohttp import ClientResponseError

import voluptuous as vol
from abc import ABC, abstractmethod

_LOGGER = logging.getLogger(__name__)

MAX_RESPONSE_ATTEMPTS = 10
REQUEST_STATUS_SLEEP = 5

from .audi_services import AudiService
from .audi_api import AudiAPI
from .util import log_exception, get_attr, parse_int, parse_float

ACTION_LOCK = "lock"
ACTION_CLIMATISATION = "climatisation"
ACTION_CHARGER = "charger"
ACTION_WINDOW_HEATING = "window_heating"
ACTION_PRE_HEATER = "pre_heater"


class AudiConnectObserver(ABC):
    @abstractmethod
    async def handle_notification(self, vin: str, action: str) -> None:
        pass


class AudiConnectAccount:
    """Representation of an Audi Connect Account."""

    def __init__(
        self, session, username: str, password: str, country: str, spin: str
    ) -> None:

        self._api = AudiAPI(session)
        self._audi_service = AudiService(self._api, country, spin)

        self._username = username
        self._password = password
        self._loggedin = False
        self._logintime = time.time()

        self._connect_retries = 3
        self._connect_delay = 10

        self._update_listeners = []

        self._vehicles = []
        self._audi_vehicles = []

        self._observers: List[AudiConnectObserver] = []

    def add_observer(self, observer: AudiConnectObserver) -> None:
        self._observers.append(observer)

    async def notify(self, vin: str, action: str) -> None:
        for observer in self._observers:
            await observer.handle_notification(vin, action)

    async def login(self):
        for i in range(self._connect_retries):
            self._loggedin = await self.try_login(i == self._connect_retries - 1)
            if self._loggedin is True:
                self._logintime = time.time()
                break

            if i < self._connect_retries - 1:
                _LOGGER.error(
                    "Login to Audi service failed, trying again in {} seconds".format(
                        self._connect_delay
                    )
                )
                await asyncio.sleep(self._connect_delay)

    async def try_login(self, logError):
        try:
            await self._audi_service.login(self._username, self._password, False)
            return True
        except Exception as exception:
            if logError is True:
                _LOGGER.error("Login to Audi service failed: " + str(exception))

            return False

    async def update(self, vinlist):
        if not self._loggedin:
            await self.login()

        if not self._loggedin:
            return False

        #
        elapsed_sec = time.time() - self._logintime
        if await self._audi_service.refresh_token_if_necessary(elapsed_sec):
            # Store current timestamp when refresh was performed and successful
            self._logintime = time.time()

        """Update the state of all vehicles."""
        try:
            if len(self._audi_vehicles) > 0:
                for vehicle in self._audi_vehicles:
                    await self.add_or_update_vehicle(vehicle, vinlist)

            else:
                vehicles_response = await self._audi_service.get_vehicle_information()
                self._audi_vehicles = vehicles_response.vehicles
                self._vehicles = []
                for vehicle in self._audi_vehicles:
                    await self.add_or_update_vehicle(vehicle, vinlist)

            for listener in self._update_listeners:
                listener()

            # TR/2021-12-01: do not set to False as refresh_token is used
            # self._loggedin = False

            return True

        except IOError as exception:
            # Force a re-login in case of failure/exception
            self._loggedin = False
            _LOGGER.exception(exception)
            return False

    async def add_or_update_vehicle(self, vehicle, vinlist):
        if vehicle.vin is not None:
            if vinlist is None or vehicle.vin.lower() in vinlist:
                vupd = [x for x in self._vehicles if x.vin == vehicle.vin.lower()]
                if len(vupd) > 0:
                    if await vupd[0].update() is False:
                        self._loggedin = False
                else:
                    try:
                        audiVehicle = AudiConnectVehicle(self._audi_service, vehicle)
                        if await audiVehicle.update() is False:
                            self._loggedin = False
                        self._vehicles.append(audiVehicle)
                    except Exception:
                        pass

    async def refresh_vehicle_data(self, vin: str):
        if not self._loggedin:
            await self.login()

        if not self._loggedin:
            return False

        try:
            _LOGGER.debug(
                "Sending command to refresh data to vehicle {vin}".format(vin=vin)
            )

            await self._audi_service.refresh_vehicle_data(vin)

            _LOGGER.debug(
                "Successfully refreshed data of vehicle {vin}".format(vin=vin)
            )

            return True
        except Exception as exception:
            log_exception(
                exception,
                "Unable to refresh vehicle data of {}".format(vin),
            )

            return False

    async def set_vehicle_lock(self, vin: str, lock: bool):
        if not self._loggedin:
            await self.login()

        if not self._loggedin:
            return False

        try:
            _LOGGER.debug(
                "Sending command to {action} to vehicle {vin}".format(
                    action="lock" if lock else "unlock", vin=vin
                ),
            )

            await self._audi_service.set_vehicle_lock(vin, lock)

            _LOGGER.debug(
                "Successfully {action} vehicle {vin}".format(
                    action="locked" if lock else "unlocked", vin=vin
                ),
            )

            await self.notify(vin, ACTION_LOCK)

            return True

        except Exception as exception:
            log_exception(
                exception,
                "Unable to {action} {vin}".format(
                    action="lock" if lock else "unlock", vin=vin
                ),
            )

    async def set_vehicle_climatisation(self, vin: str, activate: bool):
        if not self._loggedin:
            await self.login()

        if not self._loggedin:
            return False

        try:
            _LOGGER.debug(
                "Sending command to {action} climatisation to vehicle {vin}".format(
                    action="start" if activate else "stop", vin=vin
                ),
            )

            await self._audi_service.set_climatisation(vin, activate)

            _LOGGER.debug(
                "Successfully {action} climatisation of vehicle {vin}".format(
                    action="started" if activate else "stopped", vin=vin
                ),
            )

            await self.notify(vin, ACTION_CLIMATISATION)

            return True

        except Exception as exception:
            log_exception(
                exception,
                "Unable to {action} climatisation of vehicle {vin}".format(
                    action="start" if activate else "stop", vin=vin
                ),
            )

    async def set_battery_charger(self, vin: str, activate: bool):
        if not self._loggedin:
            await self.login()

        if not self._loggedin:
            return False

        try:
            _LOGGER.debug(
                "Sending command to {action} charger to vehicle {vin}".format(
                    action="start" if activate else "stop", vin=vin
                ),
            )

            await self._audi_service.set_battery_charger(vin, activate)

            _LOGGER.debug(
                "Successfully {action} charger of vehicle {vin}".format(
                    action="started" if activate else "stopped", vin=vin
                ),
            )

            await self.notify(vin, ACTION_CHARGER)

            return True

        except Exception as exception:
            log_exception(
                exception,
                "Unable to {action} charger of vehicle {vin}".format(
                    action="start" if activate else "stop", vin=vin
                ),
            )

    async def set_vehicle_window_heating(self, vin: str, activate: bool):
        if not self._loggedin:
            await self.login()

        if not self._loggedin:
            return False

        try:
            _LOGGER.debug(
                "Sending command to {action} window heating to vehicle {vin}".format(
                    action="start" if activate else "stop", vin=vin
                ),
            )

            await self._audi_service.set_window_heating(vin, activate)

            _LOGGER.debug(
                "Successfully {action} window heating of vehicle {vin}".format(
                    action="started" if activate else "stopped", vin=vin
                ),
            )

            await self.notify(vin, ACTION_WINDOW_HEATING)

            return True

        except Exception as exception:
            log_exception(
                exception,
                "Unable to {action} window heating of vehicle {vin}".format(
                    action="start" if activate else "stop", vin=vin
                ),
            )

    async def set_vehicle_pre_heater(self, vin: str, activate: bool):
        if not self._loggedin:
            await self.login()

        if not self._loggedin:
            return False

        try:
            _LOGGER.debug(
                "Sending command to {action} pre-heater to vehicle {vin}".format(
                    action="start" if activate else "stop", vin=vin
                ),
            )

            await self._audi_service.set_pre_heater(vin, activate)

            _LOGGER.debug(
                "Successfully {action} pre-heater of vehicle {vin}".format(
                    action="started" if activate else "stopped", vin=vin
                ),
            )

            await self.notify(vin, ACTION_PRE_HEATER)

            return True

        except Exception as exception:
            log_exception(
                exception,
                "Unable to {action} pre-heater of vehicle {vin}".format(
                    action="start" if activate else "stop", vin=vin
                ),
            )


class AudiConnectVehicle:
    def __init__(self, audi_service: AudiService, vehicle) -> None:
        self._audi_service = audi_service
        self._vehicle = vehicle
        self._vin = vehicle.vin.lower()
        self._vehicle.state = {}
        self._vehicle.fields = {}
        self._logged_errors = set()
        self._no_error = False

        self.support_status_report = True
        self.support_position = True
        self.support_climater = True
        self.support_preheater = True
        self.support_charger = True

    @property
    def vin(self):
        return self._vin

    @property
    def csid(self):
        return self._vehicle.csid

    @property
    def title(self):
        return self._vehicle.title

    @property
    def model(self):
        return self._vehicle.model

    @property
    def model_year(self):
        return self._vehicle.model_year

    @property
    def model_family(self):
        return self._vehicle.model_family

    async def call_update(self, func, ntries: int):
        try:
            await func()
        except TimeoutError:
            if ntries > 1:
                await asyncio.sleep(2)
                await self.call_update(func, ntries - 1)
            else:
                raise

    async def update(self):
        info = ""
        try:
            self._no_error = True
            info = "statusreport"
            await self.call_update(self.update_vehicle_statusreport, 3)
            info = "shortterm"
            await self.call_update(self.update_vehicle_shortterm, 3)
            info = "longterm"
            await self.call_update(self.update_vehicle_longterm, 3)
            info = "position"
            await self.call_update(self.update_vehicle_position, 3)
            info = "climater"
            await self.call_update(self.update_vehicle_climater, 3)
            info = "charger"
            await self.call_update(self.update_vehicle_charger, 3)
            info = "preheater"
            await self.call_update(self.update_vehicle_preheater, 3)
            # Return True on success, False on error
            return self._no_error
        except Exception as exception:
            log_exception(
                exception,
                "Unable to update vehicle data {} of {}".format(info, self._vehicle.vin),
            )

    def log_exception_once(self, exception, message):
        self._no_error = False
        err = message + ": " + str(exception).rstrip("\n")
        if not err in self._logged_errors:
            self._logged_errors.add(err)
            _LOGGER.error(err)

    async def update_vehicle_statusreport(self):
        if not self.support_status_report:
            return

        try:
            status = await self._audi_service.get_stored_vehicle_data(self._vehicle.vin)
            self._vehicle.fields = {
                status.data_fields[i].name: status.data_fields[i].value
                for i in range(0, len(status.data_fields))
            }
            self._vehicle.state["last_update_time"] = status.data_fields[0].send_time

        except TimeoutError:
            raise
        except ClientResponseError as resp_exception:
            if resp_exception.status == 403 or resp_exception.status == 502:
                _LOGGER.error(
                    "support_status_report set to False: {status}".format(
                        status=resp_exception.status
                    )
                )
                self.support_status_report = False
            else:
                self.log_exception_once(
                    resp_exception,
                    "Unable to obtain the vehicle status report of {}".format(
                        self._vehicle.vin
                    ),
                )
        except Exception as exception:
            self.log_exception_once(
                exception,
                "Unable to obtain the vehicle status report of {}".format(
                    self._vehicle.vin
                ),
            )

    async def update_vehicle_position(self):
        if not self.support_position:
            return

        try:
            resp = await self._audi_service.get_stored_position(self._vehicle.vin)
            if resp.get("findCarResponse") is not None:
                position = resp["findCarResponse"]

            if (
                position.get("Position") is not None
                and position["Position"].get("carCoordinate") is not None
            ):
                self._vehicle.state["position"] = {
                    "latitude": get_attr(position, "Position.carCoordinate.latitude")
                    / 1000000,
                    "longitude": get_attr(position, "Position.carCoordinate.longitude")
                    / 1000000,
                    "timestamp": get_attr(position, "Position.timestampCarSentUTC"),
                    "parktime": position.get("parkingTimeUTC")
                    if position.get("parkingTimeUTC") is not None
                    else get_attr(position, "Position.timestampCarSentUTC"),
                }

        except TimeoutError:
            raise
        except ClientResponseError as resp_exception:
            if resp_exception.status == 403 or resp_exception.status == 502:
                _LOGGER.error(
                    "support_position set to False: {status}".format(
                        status=resp_exception.status
                    )
                )
                self.support_position = False
            # If error is 204 is returned, the position is currently not available
            elif resp_exception.status != 204:
                self.log_exception_once(
                    resp_exception,
                    "Unable to update the vehicle position of {}".format(
                        self._vehicle.vin
                    ),
                )
        except Exception as exception:
            self.log_exception_once(
                exception,
                "Unable to update the vehicle position of {}".format(self._vehicle.vin),
            )

    async def update_vehicle_climater(self):
        if not self.support_climater:
            return

        try:
            result = await self._audi_service.get_climater(self._vehicle.vin)
            if result:
                self._vehicle.state["climatisationState"] = get_attr(
                    result,
                    "climater.status.climatisationStatusData.climatisationState.content",
                )
                tmp = get_attr(
                    result,
                    "climater.status.temperatureStatusData.outdoorTemperature.content",
                )
                if tmp is not None:
                    self._vehicle.state["outdoorTemperature"] = round(float(tmp) / 10 - 273, 1)
                else:
                    self._vehicle.state["outdoorTemperature"] = None

        except TimeoutError:
            raise
        except ClientResponseError as resp_exception:
            if resp_exception.status == 403 or resp_exception.status == 502:
                _LOGGER.error(
                    "support_climater set to False: {status}".format(
                        status=resp_exception.status
                    )
                )
                self.support_climater = False
            else:
                self.log_exception_once(
                    resp_exception,
                    "Unable to obtain the vehicle climatisation state for {}".format(
                        self._vehicle.vin
                    ),
                )
        except Exception as exception:
            self.log_exception_once(
                exception,
                "Unable to obtain the vehicle climatisation state for {}".format(
                    self._vehicle.vin
                ),
            )

    async def update_vehicle_preheater(self):
        if not self.support_preheater:
            return

        try:
            result = await self._audi_service.get_preheater(self._vehicle.vin)
            if result:
                self._vehicle.state["preheaterState"] = get_attr(
                    result,
                    "statusResponse",
                )

        except TimeoutError:
            raise
        except ClientResponseError as resp_exception:
            if resp_exception.status == 403 or resp_exception.status == 502:
                _LOGGER.error(
                    "support_preheater set to False: {status}".format(
                        status=resp_exception.status
                    )
                )
                self.support_preheater = False
            else:
                self.log_exception_once(
                    resp_exception,
                    "Unable to obtain the vehicle preheater state for {}".format(
                        self._vehicle.vin
                    ),
                )
        except Exception as exception:
            self.log_exception_once(
                exception,
                "Unable to obtain the vehicle preheater state for {}".format(
                    self._vehicle.vin
                ),
            )

    async def update_vehicle_charger(self):
        if not self.support_charger:
            return

        try:
            result = await self._audi_service.get_charger(self._vehicle.vin)
            if result:
                self._vehicle.state["maxChargeCurrent"] = get_attr(
                    result, "charger.settings.maxChargeCurrent.content"
                )

                self._vehicle.state["chargingState"] = get_attr(
                    result, "charger.status.chargingStatusData.chargingState.content"
                )
                self._vehicle.state["actualChargeRate"] = get_attr(
                    result, "charger.status.chargingStatusData.actualChargeRate.content"
                )
                if self._vehicle.state["actualChargeRate"] is not None:
                   self._vehicle.state["actualChargeRate"] = float(self._vehicle.state["actualChargeRate"]) / 10
                self._vehicle.state["actualChargeRateUnit"] = get_attr(
                    result, "charger.status.chargingStatusData.chargeRateUnit.content"
                )
                self._vehicle.state["chargingPower"] = get_attr(
                    result, "charger.status.chargingStatusData.chargingPower.content"
                )
                self._vehicle.state["chargingMode"] = get_attr(
                    result, "charger.status.chargingStatusData.chargingMode.content"
                )

                self._vehicle.state["energyFlow"] = get_attr(
                    result, "charger.status.chargingStatusData.energyFlow.content"
                )

                self._vehicle.state["engineTypeFirstEngine"] = get_attr(
                    result,
                    "charger.status.cruisingRangeStatusData.engineTypeFirstEngine.content",
                )
                self._vehicle.state["engineTypeSecondEngine"] = get_attr(
                    result,
                    "charger.status.cruisingRangeStatusData.engineTypeSecondEngine.content",
                )
                self._vehicle.state["hybridRange"] = get_attr(
                    result, "charger.status.cruisingRangeStatusData.hybridRange.content"
                )
                self._vehicle.state["primaryEngineRange"] = get_attr(
                    result,
                    "charger.status.cruisingRangeStatusData.primaryEngineRange.content",
                )
                self._vehicle.state["secondaryEngineRange"] = get_attr(
                    result,
                    "charger.status.cruisingRangeStatusData.secondaryEngineRange.content",
                )

                self._vehicle.state["stateOfCharge"] = get_attr(
                    result, "charger.status.batteryStatusData.stateOfCharge.content"
                )
                self._vehicle.state["remainingChargingTime"] = get_attr(
                    result,
                    "charger.status.batteryStatusData.remainingChargingTime.content",
                )
                self._vehicle.state["plugState"] = get_attr(
                    result, "charger.status.plugStatusData.plugState.content"
                )

        except TimeoutError:
            raise
        except ClientResponseError as resp_exception:
            if resp_exception.status == 403 or resp_exception.status == 502:
                _LOGGER.error(
                    "support_charger set to False: {status}".format(
                        status=resp_exception.status
                    )
                )
                self.support_charger = False
            else:
                self.log_exception_once(
                    resp_exception,
                    "Unable to obtain the vehicle charger state for {}".format(
                        self._vehicle.vin
                    ),
                )
        except Exception as exception:
            self.log_exception_once(
                exception,
                "Unable to obtain the vehicle charger state for {}".format(
                    self._vehicle.vin
                ),
            )

    async def update_vehicle_longterm(self):
        await self.update_vehicle_tripdata("longTerm")

    async def update_vehicle_shortterm(self):
        await self.update_vehicle_tripdata("shortTerm")

    async def update_vehicle_tripdata(self, kind: str):
        try:
            td_cur, td_rst = await self._audi_service.get_tripdata(self._vehicle.vin, kind)
            self._vehicle.state[kind.lower() + "_current"] = {
                "tripID": td_cur.tripID,
                "averageElectricEngineConsumption": td_cur.averageElectricEngineConsumption,
                "averageFuelConsumption": td_cur.averageFuelConsumption,
                "averageSpeed": td_cur.averageSpeed,
                "mileage": td_cur.mileage,
                "startMileage": td_cur.startMileage,
                "traveltime": td_cur.traveltime,
                "timestamp": td_cur.timestamp,
                "overallMileage": td_cur.overallMileage,
            }
            self._vehicle.state[kind.lower() + "_reset"] = {
                "tripID": td_rst.tripID,
                "averageElectricEngineConsumption": td_rst.averageElectricEngineConsumption,
                "averageFuelConsumption": td_rst.averageFuelConsumption,
                "averageSpeed": td_rst.averageSpeed,
                "mileage": td_rst.mileage,
                "startMileage": td_rst.startMileage,
                "traveltime": td_rst.traveltime,
                "timestamp": td_rst.timestamp,
                "overallMileage": td_rst.overallMileage,
            }

        except TimeoutError:
            raise
        except ClientResponseError as resp_exception:
            self.log_exception_once(
                resp_exception,
                "Unable to obtain the vehicle {kind} tripdata of {vin}".format(
                    kind=kind, vin=self._vehicle.vin
                ),
            )
        except Exception as exception:
            self.log_exception_once(
                exception,
                "Unable to obtain the vehicle {kind} tripdata of {vin}".format(
                    kind=kind, vin=self._vehicle.vin
                ),
            )

    @property
    def last_update_time(self):
        if self.last_update_time_supported:
            return self._vehicle.state.get("last_update_time")

    @property
    def last_update_time_supported(self):
        check = self._vehicle.state.get("last_update_time")
        if check:
            return True

    @property
    def service_inspection_time(self):
        """Return time left for service inspection"""
        if self.service_inspection_time_supported:
            return -int(
                self._vehicle.fields.get("MAINTENANCE_INTERVAL_TIME_TO_INSPECTION")
            )

    @property
    def service_inspection_time_supported(self):
        check = self._vehicle.fields.get("MAINTENANCE_INTERVAL_TIME_TO_INSPECTION")
        if check and parse_int(check):
            return True

    @property
    def service_inspection_distance(self):
        """Return distance left for service inspection"""
        if self.service_inspection_distance_supported:
            return -int(
                self._vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION")
            )

    @property
    def service_inspection_distance_supported(self):
        check = self._vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION")
        if check and parse_int(check):
            return True

    @property
    def oil_change_time(self):
        """Return time left for oil change"""
        if self.oil_change_time_supported:
            return -int(
                self._vehicle.fields.get("MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE")
            )

    @property
    def oil_change_time_supported(self):
        check = self._vehicle.fields.get("MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE")
        if check and parse_int(check):
            return True

    @property
    def oil_change_distance(self):
        """Return distance left for oil change"""
        if self.oil_change_distance_supported:
            return -int(
                self._vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE")
            )

    @property
    def oil_change_distance_supported(self):
        check = self._vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE")
        if check and parse_int(check):
            return True

    @property
    def oil_level(self):
        """Return oil level percentage"""
        if self.oil_level_supported:
            return float(self._vehicle.fields.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE"))

    @property
    def oil_level_supported(self):
        check = self._vehicle.fields.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE")
        if check and parse_float(check):
            return True

    @property
    def sun_roof(self):
        if self.sun_roof_supported:
            res = self._vehicle.fields.get("STATE_SUN_ROOF_MOTOR_COVER")
            return res == "2"

    @property
    def sun_roof_supported(self):
        check = self._vehicle.fields.get("STATE_SUN_ROOF_MOTOR_COVER")
        if check and check != "0":
            return True

    @property
    def preheater_active(self):
        if self.preheater_active_supported:
            res = self._vehicle.state["preheaterState"].get('climatisationStateReport').get('climatisationState')
            return res != "off"

    @property
    def preheater_active_supported(self):
        return self.preheater_state_supported

    @property
    def preheater_duration(self):
        if self.preheater_duration_supported:
            res = self._vehicle.state["preheaterState"].get('climatisationStateReport').get('climatisationDuration')
            return parse_int(res)

    @property
    def preheater_duration_supported(self):
        return self.preheater_state_supported

    @property
    def preheater_remaining_supported(self):
        return self.preheater_state_supported

    @property
    def preheater_remaining(self):
        if self.preheater_remaining_supported:
            res = self._vehicle.state["preheaterState"].get('climatisationStateReport').get('remainingClimateTime')
            return parse_int(res)

    @property
    def parking_light(self):
        """Return true if parking light is on"""
        if self.parking_light_supported:
            check = self._vehicle.fields.get("LIGHT_STATUS")
            return check != "2"

    @property
    def parking_light_supported(self):
        """Return true if parking light is supported"""
        check = self._vehicle.fields.get("LIGHT_STATUS")
        if check:
            return True

    @property
    def mileage(self):
        if self.mileage_supported:
            check = self._vehicle.fields.get("UTC_TIME_AND_KILOMETER_STATUS")
            return parse_int(check)

    @property
    def mileage_supported(self):
        """Return true if mileage is supported"""
        check = self._vehicle.fields.get("UTC_TIME_AND_KILOMETER_STATUS")
        if check and parse_int(check):
            return True

    @property
    def range(self):
        if self.range_supported:
            check = self._vehicle.fields.get("TOTAL_RANGE")
            return parse_int(check)

    @property
    def range_supported(self):
        """Return true if range is supported"""
        check = self._vehicle.fields.get("TOTAL_RANGE")
        if check and parse_int(check):
            return True

    @property
    def tank_level(self):
        if self.tank_level_supported:
            check = self._vehicle.fields.get("TANK_LEVEL_IN_PERCENTAGE")
            return parse_int(check)

    @property
    def tank_level_supported(self):
        """Return true if tank_level is supported"""
        check = self._vehicle.fields.get("TANK_LEVEL_IN_PERCENTAGE")
        if check and parse_int(check):
            return True

    @property
    def position(self):
        """Return position."""
        if self.position_supported:
            return self._vehicle.state.get("position")

    @property
    def position_supported(self):
        """Return true if vehicle has position."""
        check = self._vehicle.state.get("position")
        if check:
            return True

    @property
    def any_window_open_supported(self):
        """Return true if window state is supported"""
        checkLeftFront = self._vehicle.fields.get("STATE_LEFT_FRONT_WINDOW")
        checkLeftRear = self._vehicle.fields.get("STATE_LEFT_REAR_WINDOW")
        checkRightFront = self._vehicle.fields.get("STATE_RIGHT_FRONT_WINDOW")
        checkRightRear = self._vehicle.fields.get("STATE_RIGHT_REAR_WINDOW")
        if checkLeftFront and checkLeftRear and checkRightFront and checkRightRear:
            return True

    @property
    def any_window_open(self):
        if self.any_window_open_supported:
            checkLeftFront = self._vehicle.fields.get("STATE_LEFT_FRONT_WINDOW")
            checkLeftRear = self._vehicle.fields.get("STATE_LEFT_REAR_WINDOW")
            checkRightFront = self._vehicle.fields.get("STATE_RIGHT_FRONT_WINDOW")
            checkRightRear = self._vehicle.fields.get("STATE_RIGHT_REAR_WINDOW")
            return not (
                checkLeftFront == "3"
                and checkLeftRear == "3"
                and checkRightFront == "3"
                and checkRightRear == "3"
            )

    @property
    def any_door_unlocked_supported(self):
        checkLeftFront = self._vehicle.fields.get("LOCK_STATE_LEFT_FRONT_DOOR")
        checkLeftRear = self._vehicle.fields.get("LOCK_STATE_LEFT_REAR_DOOR")
        checkRightFront = self._vehicle.fields.get("LOCK_STATE_RIGHT_FRONT_DOOR")
        checkRightRear = self._vehicle.fields.get("LOCK_STATE_RIGHT_REAR_DOOR")
        if checkLeftFront and checkLeftRear and checkRightFront and checkRightRear:
            return True

    @property
    def any_door_unlocked(self):
        if self.any_door_unlocked_supported:
            checkLeftFront = self._vehicle.fields.get("LOCK_STATE_LEFT_FRONT_DOOR")
            checkLeftRear = self._vehicle.fields.get("LOCK_STATE_LEFT_REAR_DOOR")
            checkRightFront = self._vehicle.fields.get("LOCK_STATE_RIGHT_FRONT_DOOR")
            checkRightRear = self._vehicle.fields.get("LOCK_STATE_RIGHT_REAR_DOOR")
            return not (
                checkLeftFront == "2"
                and checkLeftRear == "2"
                and checkRightFront == "2"
                and checkRightRear == "2"
            )

    @property
    def any_door_open_supported(self):
        checkLeftFront = self._vehicle.fields.get("OPEN_STATE_LEFT_FRONT_DOOR")
        checkLeftRear = self._vehicle.fields.get("OPEN_STATE_LEFT_REAR_DOOR")
        checkRightFront = self._vehicle.fields.get("OPEN_STATE_RIGHT_FRONT_DOOR")
        checkRightRear = self._vehicle.fields.get("OPEN_STATE_RIGHT_REAR_DOOR")
        if checkLeftFront and checkLeftRear and checkRightFront and checkRightRear:
            return True

    @property
    def any_door_open(self):
        if self.any_door_open_supported:
            checkLeftFront = self._vehicle.fields.get("OPEN_STATE_LEFT_FRONT_DOOR")
            checkLeftRear = self._vehicle.fields.get("OPEN_STATE_LEFT_REAR_DOOR")
            checkRightFront = self._vehicle.fields.get("OPEN_STATE_RIGHT_FRONT_DOOR")
            checkRightRear = self._vehicle.fields.get("OPEN_STATE_RIGHT_REAR_DOOR")
            return not (
                checkLeftFront == "3"
                and checkLeftRear == "3"
                and checkRightFront == "3"
                and checkRightRear == "3"
            )

    @property
    def doors_trunk_status_supported(self):
        return (
            self.any_door_open_supported
            and self.any_door_unlocked_supported
            and self.trunk_open_supported
            and self.trunk_unlocked_supported
        )

    @property
    def doors_trunk_status(self):
        if (
            self.any_door_open_supported
            and self.any_door_unlocked_supported
            and self.trunk_open_supported
            and self.trunk_unlocked_supported
        ):
            if self.any_door_open or self.trunk_open:
                return "Open"
            elif self.any_door_unlocked or self.trunk_unlocked:
                return "Closed"
            else:
                return "Locked"

    @property
    def trunk_unlocked(self):
        if self.trunk_unlocked_supported:
            check = self._vehicle.fields.get("LOCK_STATE_TRUNK_LID")
            return check != "2"

    @property
    def trunk_unlocked_supported(self):
        check = self._vehicle.fields.get("LOCK_STATE_TRUNK_LID")
        if check:
            return True

    @property
    def trunk_open(self):
        if self.trunk_open_supported:
            check = self._vehicle.fields.get("OPEN_STATE_TRUNK_LID")
            return check != "3"

    @property
    def trunk_open_supported(self):
        check = self._vehicle.fields.get("OPEN_STATE_TRUNK_LID")
        if check:
            return True

    @property
    def hood_open(self):
        if self.hood_open_supported:
            check = self._vehicle.fields.get("OPEN_STATE_HOOD")
            return check != "3"

    @property
    def hood_open_supported(self):
        check = self._vehicle.fields.get("OPEN_STATE_HOOD")
        if check:
            return True

    @property
    def charging_state(self):
        """Return charging state"""
        if self.charging_state_supported:
            return self._vehicle.state.get("chargingState")

    @property
    def charging_state_supported(self):
        check = self._vehicle.state.get("chargingState")
        if check:
            return True

    @property
    def charging_mode(self):
        """Return charging mode"""
        if self.charging_mode_supported:
            return self._vehicle.state.get("chargingMode")

    @property
    def charging_mode_supported(self):
        check = self._vehicle.state.get("chargingMode")
        if check is not None:
            return True

    @property
    def energy_flow(self):
        """Return charging mode"""
        if self.energy_flow_supported:
            return self._vehicle.state.get("energyFlow")

    @property
    def energy_flow_supported(self):
        check = self._vehicle.state.get("energyFlow")
        if check is not None:
            return True

    @property
    def max_charge_current(self):
        """Return max charge current"""
        if self.max_charge_current_supported:
            return parse_float(self._vehicle.state.get("maxChargeCurrent"))

    @property
    def max_charge_current_supported(self):
        check = self._vehicle.state.get("maxChargeCurrent")
        if check and parse_float(check):
            return True

    @property
    def actual_charge_rate(self):
        """Return actual charge rate"""
        if self.actual_charge_rate_supported:
            return parse_float(self._vehicle.state.get("actualChargeRate"))

    @property
    def actual_charge_rate_supported(self):
        check = self._vehicle.state.get("actualChargeRate")
        if check and parse_float(check):
            return True

    @property
    def actual_charge_rate_unit(self):
        if self.actual_charge_rate_supported:
            res = self._vehicle.state.get("actualChargeRateUnit")
            if res:
                return res.replace("_per_", "/")

            return res

    @property
    def charging_power(self):
        """Return charging power"""
        if self.charging_power_supported:
            return parse_int(self._vehicle.state.get("chargingPower")) / 1000

    @property
    def charging_power_supported(self):
        check = self._vehicle.state.get("chargingPower")
        if check and parse_int(check):
            return True

    @property
    def primary_engine_type(self):
        """Return primary engine type"""
        if self.primary_engine_type_supported:
            return self._vehicle.state.get("engineTypeFirstEngine")

    @property
    def primary_engine_type_supported(self):
        check = self._vehicle.state.get("engineTypeFirstEngine")
        if check and check != "unsupported":
            return True

    @property
    def secondary_engine_type(self):
        """Return secondary engine type"""
        if self.secondary_engine_type_supported:
            return self._vehicle.state.get("engineTypeSecondEngine")

    @property
    def secondary_engine_type_supported(self):
        check = self._vehicle.state.get("engineTypeSecondEngine")
        if check and check != "unsupported":
            return True

    @property
    def primary_engine_range(self):
        """Return primary engine range"""
        if self.primary_engine_range_supported:
            return self._vehicle.state.get("primaryEngineRange")

    @property
    def primary_engine_range_supported(self):
        check = self._vehicle.state.get("primaryEngineRange")
        if check and check != "unsupported":
            return True

    @property
    def secondary_engine_range(self):
        """Return secondary engine range"""
        if self.secondary_engine_range_supported:
            return self._vehicle.state.get("secondaryEngineRange")

    @property
    def secondary_engine_range_supported(self):
        check = self._vehicle.state.get("secondaryEngineRange")
        if check and check != "unsupported":
            return True

    @property
    def hybrid_range(self):
        """Return hybrid range"""
        if self.hybrid_range_supported:
            return self._vehicle.state.get("hybridRange")

    @property
    def hybrid_range_supported(self):
        check = self._vehicle.state.get("hybridRange")
        if check and check != "unsupported":
            return True

    @property
    def state_of_charge(self):
        """Return state of charge"""
        if self.state_of_charge_supported:
            return parse_float(self._vehicle.state.get("stateOfCharge"))

    @property
    def state_of_charge_supported(self):
        check = self._vehicle.state.get("stateOfCharge")
        if check and parse_float(check):
            return True

    @property
    def remaining_charging_time(self):
        """Return remaining charging time"""
        if self.remaining_charging_time_supported:
            res = parse_int(self._vehicle.state.get("remainingChargingTime"))
            if res == 65535:
                return "n/a"
            else:
                return "%02d:%02d" % divmod(res, 60)

    @property
    def remaining_charging_time_supported(self):
        check = self._vehicle.state.get("remainingChargingTime")
        if check and parse_float(check):
            return True

    @property
    def plug_state(self):
        """Return plug state"""
        if self.plug_state_supported:
            return self._vehicle.state.get("plugState")

    @property
    def plug_state_supported(self):
        check = self._vehicle.state.get("plugState")
        if check:
            return True

    @property
    def climatisation_state(self):
        if self.climatisation_state_supported:
            return self._vehicle.state.get("climatisationState")

    @property
    def climatisation_state_supported(self):
        check = self._vehicle.state.get("climatisationState")
        if check:
            return True

    @property
    def outdoor_temperature(self):
        if self.outdoor_temperature_supported:
            return self._vehicle.state.get("outdoorTemperature")

    @property
    def outdoor_temperature_supported(self):
        check = self._vehicle.state.get("outdoorTemperature")
        if check:
            return True

    @property
    def preheater_state(self):
        check = self._vehicle.state.get("preheaterState")
        if check:
            return True

    @property
    def preheater_state_supported(self):
        check = self._vehicle.state.get("preheaterState")
        if check:
            return True

    def lock_supported(self):
        return (
            self.doors_trunk_status_supported and self._audi_service._spin is not None
        )
    @property
    def shortterm_current(self):
        """Return shortterm."""
        if self.shortterm_current_supported:
            return self._vehicle.state.get("shortterm_current")

    @property
    def shortterm_current_supported(self):
        """Return true if vehicle has shortterm_current."""
        check = self._vehicle.state.get("shortterm_current")
        if check:
            return True

    @property
    def shortterm_reset(self):
        """Return shortterm."""
        if self.shortterm_reset_supported:
            return self._vehicle.state.get("shortterm_reset")

    @property
    def shortterm_reset_supported(self):
        """Return true if vehicle has shortterm_reset."""
        check = self._vehicle.state.get("shortterm_reset")
        if check:
            return True

    @property
    def longterm_current(self):
        """Return longterm."""
        if self.longterm_current_supported:
            return self._vehicle.state.get("longterm_current")

    @property
    def longterm_current_supported(self):
        """Return true if vehicle has longterm_current."""
        check = self._vehicle.state.get("longterm_current")
        if check:
            return True

    @property
    def longterm_reset(self):
        """Return longterm."""
        if self.longterm_reset_supported:
            return self._vehicle.state.get("longterm_reset")

    @property
    def longterm_reset_supported(self):
        """Return true if vehicle has longterm_reset."""
        check = self._vehicle.state.get("longterm_reset")
        if check:
            return True
