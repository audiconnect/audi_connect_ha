import time
from datetime import datetime, timezone, timedelta
import logging
import asyncio
from typing import List
import re

from asyncio import TimeoutError
from aiohttp import ClientResponseError

from abc import ABC, abstractmethod

from .audi_services import AudiService
from .audi_api import AudiAPI
from .util import log_exception, get_attr, parse_int, parse_float, parse_datetime

_LOGGER = logging.getLogger(__name__)

MAX_RESPONSE_ATTEMPTS = 10
REQUEST_STATUS_SLEEP = 5

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
        self._support_vehicle_refresh = True
        self._logintime = 0

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
                    "LOGIN: Login to Audi service failed, trying again in {} seconds".format(
                        self._connect_delay
                    )
                )
                await asyncio.sleep(self._connect_delay)

    async def try_login(self, logError):
        try:
            _LOGGER.debug("LOGIN: Requesting login to Audi service...")
            await self._audi_service.login(self._username, self._password, False)
            _LOGGER.debug("LOGIN: Login to Audi service successful")
            return True
        except Exception as exception:
            if logError is True:
                _LOGGER.error("LOGIN: Login to Audi service failed: " + str(exception))
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

        except OSError as exception:
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
        redacted_vin = "*" * (len(vin) - 4) + vin[-4:]
        if not self._loggedin:
            await self.login()

        if not self._loggedin:
            return False

        if not self._support_vehicle_refresh:
            _LOGGER.debug(
                "Vehicle refresh support is disabled for VIN: %s. Exiting update process.",
                redacted_vin,
            )
            return "disabled"

        try:
            _LOGGER.debug(
                "Sending command to refresh vehicle data for VIN: %s",
                redacted_vin,
            )

            await self._audi_service.refresh_vehicle_data(vin)

            _LOGGER.debug(
                "Successfully refreshed vehicle data for VIN: %s",
                redacted_vin,
            )

            return True

        except TimeoutError:
            _LOGGER.debug(
                "TimeoutError encountered while refreshing vehicle data for VIN: %s.",
                redacted_vin,
            )
            return False
        except ClientResponseError as cre:
            if cre.status in (403, 404):
                _LOGGER.debug(
                    "VEHICLE REFRESH: ClientResponseError with status %s while refreshing vehicle data for VIN: %s. Disabling refresh vehicle data support.",
                    cre.status,
                    redacted_vin,
                )
                self._support_vehicle_refresh = False
                return "disabled"
            elif cre.status == 502:
                _LOGGER.warning(
                    "VEHICLE REFRESH: ClientResponseError with status %s while refreshing vehicle data for VIN: %s. This issue may resolve in time. If it persists, please open an issue.",
                    cre.status,
                    redacted_vin,
                )
                return False
            elif cre.status != 204:
                _LOGGER.debug(
                    "VEHICLE REFRESH: ClientResponseError with status %s while refreshing vehicle data for VIN: %s. Error: %s",
                    cre.status,
                    redacted_vin,
                    cre,
                )
                return False
            else:
                _LOGGER.debug(
                    "VEHICLE REFRESH: Refresh vehicle data currently not available for VIN: %s. Received 204 status.",
                    redacted_vin,
                )
                return False

        except Exception as e:
            _LOGGER.error(
                "VEHICLE REFRESH: An unexpected error occurred while refreshing vehicle data for VIN: %s. Error: %s",
                redacted_vin,
                e,
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

    async def start_climate_control(
        self,
        vin: str,
        temp_f: int,
        temp_c: int,
        glass_heating: bool,
        seat_fl: bool,
        seat_fr: bool,
        seat_rl: bool,
        seat_rr: bool,
    ):
        if not self._loggedin:
            await self.login()

        if not self._loggedin:
            return False

        try:
            _LOGGER.debug(
                f"Sending command to start climate control for vehicle {vin} with settings - Temp(F): {temp_f}, Temp(C): {temp_c}, Glass Heating: {glass_heating}, Seat FL: {seat_fl}, Seat FR: {seat_fr}, Seat RL: {seat_rl}, Seat RR: {seat_rr}"
            )

            await self._audi_service.start_climate_control(
                vin,
                temp_f,
                temp_c,
                glass_heating,
                seat_fl,
                seat_fr,
                seat_rl,
                seat_rr,
            )

            _LOGGER.debug(f"Successfully started climate control of vehicle {vin}")

            await self.notify(vin, ACTION_CLIMATISATION)

            return True

        except Exception as exception:
            _LOGGER.error(
                f"Unable to start climate control of vehicle {vin}. Error: {exception}",
                exc_info=True,
            )
            return False

    async def set_battery_charger(self, vin: str, activate: bool, timer: bool):
        if not self._loggedin:
            await self.login()

        if not self._loggedin:
            return False

        try:
            _LOGGER.debug(
                "Sending command to {action}{timer} charger to vehicle {vin}".format(
                    action="start" if activate else "stop",
                    vin=vin,
                    timer=" timed" if timer else "",
                ),
            )

            await self._audi_service.set_battery_charger(vin, activate, timer)

            _LOGGER.debug(
                "Successfully {action}{timer} charger of vehicle {vin}".format(
                    action="started" if activate else "stopped",
                    vin=vin,
                    timer=" timed" if timer else "",
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
        self.support_trip_data = True

        self.charging_complete_time_frozen = None

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
            # info = "charger"
            # await self.call_update(self.update_vehicle_charger, 3)
            info = "preheater"
            await self.call_update(self.update_vehicle_preheater, 3)
            # Return True on success, False on error
            return self._no_error
        except Exception as exception:
            log_exception(
                exception,
                "Unable to update vehicle data {} of {}".format(
                    info, self._vehicle.vin
                ),
            )

    def log_exception_once(self, exception, message):
        self._no_error = False
        err = message + ": " + str(exception).rstrip("\n")
        if err not in self._logged_errors:
            self._logged_errors.add(err)
            _LOGGER.error(err, exc_info=True)

    async def update_vehicle_statusreport(self):
        if not self.support_status_report:
            return

        try:
            status = await self._audi_service.get_stored_vehicle_data(self._vehicle.vin)
            self._vehicle.fields = {
                status.data_fields[i].name: status.data_fields[i].value
                for i in range(len(status.data_fields))
            }

            # Initialize with a default very old datetime
            self._vehicle.state["last_update_time"] = datetime(
                1970, 1, 1, tzinfo=timezone.utc
            )

            # Update with the newest carCapturedTimestamp from data_fields
            for f in status.data_fields:
                new_time = parse_datetime(f.measure_time)
                if new_time:
                    self._vehicle.state["last_update_time"] = max(
                        self._vehicle.state["last_update_time"], new_time
                    )

            # Update with the newest carCapturedTimestamp from states
            for state in status.states:
                new_time = parse_datetime(state.get("measure_time"))
                if new_time:
                    self._vehicle.state["last_update_time"] = max(
                        self._vehicle.state["last_update_time"], new_time
                    )

            # Update other states
            for state in status.states:
                self._vehicle.state[state["name"]] = state["value"]

        except TimeoutError:
            raise
        except ClientResponseError as resp_exception:
            if resp_exception.status in (403, 404):
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
        # Redact all but the last 4 characters of the VIN
        redacted_vin = "*" * (len(self._vehicle.vin) - 4) + self._vehicle.vin[-4:]
        _LOGGER.debug(
            "POSITION: Starting update_vehicle_position for VIN: %s", redacted_vin
        )

        if not self.support_position:
            _LOGGER.debug(
                "POSITION: Vehicle position support is disabled for VIN: %s. Exiting update process.",
                redacted_vin,
            )
            return

        try:
            _LOGGER.debug(
                "POSITION: Attempting to retrieve stored vehicle position for VIN: %s",
                redacted_vin,
            )
            resp = await self._audi_service.get_stored_position(self._vehicle.vin)
            # To enable detailed logging of raw vehicle position data for debugging purposes:
            # 1. Remove the '#' from the start of the _LOGGER.debug line below.
            # 2. Save the file.
            # 3. Restart Home Assistant to apply the changes.
            # Note: This will log sensitive data. To stop logging this data:
            # 1. Add the '#' back at the start of the _LOGGER.debug line.
            # 2. Save the file and restart Home Assistant again.
            # _LOGGER.debug("POSITION - UNREDACTED SENSITIVE DATA: Raw vehicle position data: %s", resp)
            if resp is not None:
                redacted_lat = re.sub(r"\d", "#", str(resp["data"]["lat"]))
                redacted_lon = re.sub(r"\d", "#", str(resp["data"]["lon"]))

                # Check if 'carCapturedTimestamp' is available in the data
                if "carCapturedTimestamp" in resp["data"]:
                    timestamp = parse_datetime(resp["data"]["carCapturedTimestamp"])
                    parktime = parse_datetime(resp["data"]["carCapturedTimestamp"])
                else:
                    # Log and use None timestamp and parktime
                    timestamp = None
                    parktime = None
                    _LOGGER.debug(
                        "POSITION: Timestamp not available for vehicle position data of VIN: %s.",
                        redacted_vin,
                    )
                _LOGGER.debug(
                    "POSITION: Vehicle position data received for VIN: %s, lat: %s, lon: %s, timestamp: %s, parktime: %s",
                    redacted_vin,
                    redacted_lat,
                    redacted_lon,
                    timestamp,
                    parktime,
                )

                self._vehicle.state["position"] = {
                    "latitude": resp["data"]["lat"],
                    "longitude": resp["data"]["lon"],
                    "timestamp": timestamp,
                    "parktime": parktime,
                }

                _LOGGER.debug(
                    "POSITION: Vehicle position updated successfully for VIN: %s",
                    redacted_vin,
                )
            else:
                _LOGGER.warning(
                    "POSITION: No vehicle position data received for VIN: %s. Response was None.",
                    redacted_vin,
                )

        except TimeoutError:
            _LOGGER.error(
                "POSITION: TimeoutError encountered while updating vehicle position for VIN: %s.",
                redacted_vin,
            )
            raise
        except ClientResponseError as cre:
            if cre.status in (403, 404):
                _LOGGER.error(
                    "POSITION: ClientResponseError with status %s for VIN: %s. Disabling vehicle position support.",
                    cre.status,
                    redacted_vin,
                )
                self.support_position = False
            elif cre.status == 502:
                _LOGGER.warning(
                    "POSITION: ClientResponseError with status %s while updating vehicle position for VIN: %s. This issue may resolve in time. If it persists, please open an issue.",
                    cre.status,
                    redacted_vin,
                )
            elif cre.status != 204:
                _LOGGER.error(
                    "POSITION: ClientResponseError with status %s for VIN: %s. Error: %s",
                    cre.status,
                    redacted_vin,
                    cre,
                )
            else:
                _LOGGER.debug(
                    "POSITION: Vehicle position currently not available for VIN: %s. Received 204 status.",
                    redacted_vin,
                )

        except Exception as e:
            _LOGGER.error(
                "POSITION: An unexpected error occurred while updating vehicle position for VIN: %s. Error: %s",
                redacted_vin,
                e,
            )

    async def update_vehicle_climater(self):
        redacted_vin = "*" * (len(self._vehicle.vin) - 4) + self._vehicle.vin[-4:]
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
                    self._vehicle.state["outdoorTemperature"] = round(
                        float(tmp) / 10 - 273, 1
                    )
                else:
                    self._vehicle.state["outdoorTemperature"] = None

                remainingClimatisationTime = get_attr(
                    result,
                    "climater.status.climatisationStatusData.remainingClimatisationTime.content",
                )
                self._vehicle.state["remainingClimatisationTime"] = (
                    remainingClimatisationTime
                )
                _LOGGER.debug(
                    "CLIMATER: remainingClimatisationTime: %s",
                    remainingClimatisationTime,
                )

                vehicleParkingClock = get_attr(
                    result,
                    "climater.status.vehicleParkingClockStatusData.vehicleParkingClock.content",
                )
                self._vehicle.state["vehicleParkingClock"] = parse_datetime(
                    vehicleParkingClock
                )
                _LOGGER.debug("CLIMATER: vehicleParkingClock: %s", vehicleParkingClock)

                isMirrorHeatingActive = get_attr(
                    result,
                    "climater.status.climatisationStatusData.climatisationElementStates.isMirrorHeatingActive.content",
                )
                self._vehicle.state["isMirrorHeatingActive"] = isMirrorHeatingActive
                _LOGGER.debug(
                    "CLIMATER: isMirrorHeatingActive: %s", isMirrorHeatingActive
                )

            else:
                _LOGGER.debug(
                    "No climater data received for VIN: %s. Response was None.",
                    redacted_vin,
                )

        except TimeoutError:
            _LOGGER.debug(
                "TimeoutError encountered while updating climater for VIN: %s.",
                redacted_vin,
            )
            raise
        except ClientResponseError as cre:
            if cre.status in (403, 404):
                _LOGGER.debug(
                    "CLIMATER: ClientResponseError with status %s while updating climater for VIN: %s. Disabling climater support.",
                    cre.status,
                    redacted_vin,
                )
                self.support_climater = False
            elif cre.status == 502:
                _LOGGER.warning(
                    "CLIMATER: ClientResponseError with status %s while updating climater for VIN: %s. This issue may resolve in time. If it persists, please open an issue.",
                    cre.status,
                    redacted_vin,
                )
            elif cre.status != 204:
                _LOGGER.debug(
                    "ClientResponseError with status %s while updating climater for VIN: %s. Error: %s",
                    cre.status,
                    redacted_vin,
                    cre,
                )
            else:
                _LOGGER.debug(
                    "Climater currently not available for VIN: %s. Received 204 status.",
                    redacted_vin,
                )

        except Exception as e:
            _LOGGER.error(
                "An unexpected error occurred while updating climater for VIN: %s. Error: %s",
                redacted_vin,
                e,
            )

    async def update_vehicle_preheater(self):
        redacted_vin = "*" * (len(self._vehicle.vin) - 4) + self._vehicle.vin[-4:]
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
        except ClientResponseError as cre:
            if cre.status in (403, 404, 502):
                _LOGGER.debug(
                    "PREHEATER: ClientResponseError with status %s while updating preheater for VIN: %s. Disabling preheater support.",
                    cre.status,
                    redacted_vin,
                )
                self.support_preheater = False
            # elif cre.status == 502:
            #    _LOGGER.warning(
            #        "PREHEATER: ClientResponseError with status %s while updating preheater for VIN: %s. This issue may resolve in time. If it persists, please open an issue.",
            #        cre.status,
            #        redacted_vin,
            #    )
            else:
                self.log_exception_once(
                    cre,
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
        redacted_vin = "*" * (len(self._vehicle.vin) - 4) + self._vehicle.vin[-4:]
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
                    self._vehicle.state["actualChargeRate"] = float(
                        self._vehicle.state["actualChargeRate"]
                    )
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
                self._vehicle.state["plugLockState"] = get_attr(
                    result, "charger.status.plugStatusData.plugLockState.content"
                )
                self._vehicle.state["externalPower"] = get_attr(
                    result, "charger.status.plugStatusData.externalPower.content"
                )
                self._vehicle.state["plugledColor"] = get_attr(
                    result, "charger.status.plugStatusData.plugledColor.content"
                )

        except TimeoutError:
            raise
        except ClientResponseError as cre:
            if cre.status in (403, 404):
                _LOGGER.debug(
                    "CHARGER: ClientResponseError with status %s while updating charger for VIN: %s. Disabling charger support.",
                    cre.status,
                    redacted_vin,
                )
                self.support_charger = False
            elif cre.status == 502:
                _LOGGER.warning(
                    "CHARGER: ClientResponseError with status %s while updating charger for VIN: %s. This issue may resolve in time. If it persists, please open an issue.",
                    cre.status,
                    redacted_vin,
                )
            else:
                self.log_exception_once(
                    cre,
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
        redacted_vin = "*" * (len(self._vehicle.vin) - 4) + self._vehicle.vin[-4:]
        if not self.support_trip_data:
            _LOGGER.debug(
                "TRIP DATA: Trip data support is disabled for VIN: %s. Exiting update process.",
                redacted_vin,
            )
            return
        try:
            td_cur, td_rst = await self._audi_service.get_tripdata(
                self._vehicle.vin, kind
            )
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
                "zeroEmissionDistance": td_cur.zeroEmissionDistance,
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
                "zeroEmissionDistance": td_rst.zeroEmissionDistance,
            }

        except TimeoutError:
            _LOGGER.debug(
                "TRIP DATA: TimeoutError encountered while updating trip data for VIN: %s.",
                redacted_vin,
            )
            raise
        except ClientResponseError as cre:
            if cre.status in (403, 404):
                _LOGGER.debug(
                    "TRIP DATA: ClientResponseError with status %s while updating trip data for VIN: %s. Disabling trip data support.",
                    cre.status,
                    redacted_vin,
                )
                self.support_trip_data = False
            elif cre.status == 502:
                _LOGGER.warning(
                    "TRIP DATA: ClientResponseError with status %s while updating trip data for VIN: %s. This issue may resolve in time. If it persists, please open an issue.",
                    cre.status,
                    redacted_vin,
                )
            elif cre.status != 204:
                _LOGGER.debug(
                    "TRIP DATA: ClientResponseError with status %s while updating trip data for VIN: %s. Error: %s",
                    cre.status,
                    redacted_vin,
                    cre,
                )
            else:
                _LOGGER.debug(
                    "TRIP DATA: Trip data currently not available for VIN: %s. Received 204 status.",
                    redacted_vin,
                )

        except Exception as e:
            _LOGGER.error(
                "TRIP DATA: An unexpected error occurred while updating trip data for VIN: %s. Error: %s",
                redacted_vin,
                e,
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
            return int(
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
            return int(
                self._vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION")
            )

    @property
    def service_inspection_distance_supported(self):
        check = self._vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION")
        if check and parse_int(check):
            return True

    @property
    def service_adblue_distance(self):
        """Return distance left for service inspection"""
        if self.service_adblue_distance_supported:
            return int(self._vehicle.fields.get("ADBLUE_RANGE"))

    @property
    def service_adblue_distance_supported(self):
        check = self._vehicle.fields.get("ADBLUE_RANGE")
        if check and parse_int(check):
            return True

    @property
    def oil_change_time(self):
        """Return time left for oil change"""
        if self.oil_change_time_supported:
            return int(
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
            return int(
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
            return parse_float(
                self._vehicle.fields.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE")
            )

    @property
    def oil_level_supported(self):
        """Check if oil level is supported."""
        check = self._vehicle.fields.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE")
        return not isinstance(check, bool) and check is not None

    @property
    def oil_level_binary(self):
        """Return oil level binary."""
        if self.oil_level_binary_supported:
            return not self._vehicle.fields.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE")

    @property
    def oil_level_binary_supported(self):
        """Check if oil level binary is supported."""
        return isinstance(
            self._vehicle.fields.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE"), bool
        )

    @property
    def preheater_active(self):
        if self.preheater_active_supported:
            res = (
                self._vehicle.state["preheaterState"]
                .get("climatisationStateReport")
                .get("climatisationState")
            )
            return res != "off"

    @property
    def preheater_active_supported(self):
        return self.preheater_state_supported

    @property
    def preheater_duration(self):
        if self.preheater_duration_supported:
            res = (
                self._vehicle.state["preheaterState"]
                .get("climatisationStateReport")
                .get("climatisationDuration")
            )
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
            res = (
                self._vehicle.state["preheaterState"]
                .get("climatisationStateReport")
                .get("remainingClimateTime")
            )
            return parse_int(res)

    @property
    def parking_light(self):
        """Return true if parking light is on"""
        if self.parking_light_supported:
            try:
                check = self._vehicle.fields.get("LIGHT_STATUS")
                return check[0]["status"] != "off" or check[1]["status"] != "off"
            except KeyError:
                return False

    @property
    def parking_light_supported(self):
        """Return true if parking light is supported"""
        check = self._vehicle.fields.get("LIGHT_STATUS")
        if check:
            return True

    @property
    def braking_status(self):
        """Return true if braking status is on"""
        if self.braking_status_supported:
            check = self._vehicle.fields.get("BRAKING_STATUS")
            return check != "2"

    @property
    def braking_status_supported(self):
        """Return true if braking status is supported"""
        check = self._vehicle.fields.get("BRAKING_STATUS")
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
        checkSunRoof = self._vehicle.fields.get("STATE_SUN_ROOF_MOTOR_COVER", None)
        checkRoofCover = self._vehicle.fields.get("STATE_ROOF_COVER_WINDOW", None)
        acceptable_window_states = ["3", "0", None]
        if (
            checkLeftFront
            and checkLeftRear
            and checkRightFront
            and checkRightRear
            and (checkSunRoof in acceptable_window_states)
            and (checkRoofCover in acceptable_window_states)
        ):
            return True

    @property
    def any_window_open(self):
        if self.any_window_open_supported:
            checkLeftFront = self._vehicle.fields.get("STATE_LEFT_FRONT_WINDOW")
            checkLeftRear = self._vehicle.fields.get("STATE_LEFT_REAR_WINDOW")
            checkRightFront = self._vehicle.fields.get("STATE_RIGHT_FRONT_WINDOW")
            checkRightRear = self._vehicle.fields.get("STATE_RIGHT_REAR_WINDOW")
            checkSunRoof = self._vehicle.fields.get("STATE_SUN_ROOF_MOTOR_COVER", None)
            checkRoofCover = self._vehicle.fields.get("STATE_ROOF_COVER_WINDOW", None)
            acceptable_window_states = ["3", None]
            return not (
                checkLeftFront == "3"
                and checkLeftRear == "3"
                and checkRightFront == "3"
                and checkRightRear == "3"
                and (checkSunRoof in acceptable_window_states)
                and (checkRoofCover in acceptable_window_states)
            )

    @property
    def left_front_window_open_supported(self):
        return self._vehicle.fields.get("STATE_LEFT_FRONT_WINDOW")

    @property
    def left_front_window_open(self):
        if self.left_front_window_open_supported:
            return self._vehicle.fields.get("STATE_LEFT_FRONT_WINDOW") != "3"

    @property
    def right_front_window_open_supported(self):
        return self._vehicle.fields.get("STATE_RIGHT_FRONT_WINDOW")

    @property
    def right_front_window_open(self):
        if self.right_front_window_open_supported:
            return self._vehicle.fields.get("STATE_RIGHT_FRONT_WINDOW") != "3"

    @property
    def left_rear_window_open_supported(self):
        return self._vehicle.fields.get("STATE_LEFT_REAR_WINDOW")

    @property
    def left_rear_window_open(self):
        if self.left_rear_window_open_supported:
            return self._vehicle.fields.get("STATE_LEFT_REAR_WINDOW") != "3"

    @property
    def right_rear_window_open_supported(self):
        return self._vehicle.fields.get("STATE_RIGHT_REAR_WINDOW")

    @property
    def right_rear_window_open(self):
        if self.right_rear_window_open_supported:
            return self._vehicle.fields.get("STATE_RIGHT_REAR_WINDOW") != "3"

    @property
    def sun_roof_supported(self):
        return self._vehicle.fields.get("STATE_SUN_ROOF_MOTOR_COVER")

    @property
    def sun_roof(self):
        if self.sun_roof_supported:
            return self._vehicle.fields.get("STATE_SUN_ROOF_MOTOR_COVER") != "3"

    @property
    def roof_cover_supported(self):
        return self._vehicle.fields.get("STATE_ROOF_COVER_WINDOW")

    @property
    def roof_cover(self):
        if self.roof_cover_supported:
            return self._vehicle.fields.get("STATE_ROOF_COVER_WINDOW") != "3"

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
    def left_front_door_open_supported(self):
        return self._vehicle.fields.get("OPEN_STATE_LEFT_FRONT_DOOR")

    @property
    def left_front_door_open(self):
        if self.left_front_door_open_supported:
            return self._vehicle.fields.get("OPEN_STATE_LEFT_FRONT_DOOR") != "3"

    @property
    def right_front_door_open_supported(self):
        return self._vehicle.fields.get("OPEN_STATE_RIGHT_FRONT_DOOR")

    @property
    def right_front_door_open(self):
        if self.right_front_door_open_supported:
            return self._vehicle.fields.get("OPEN_STATE_RIGHT_FRONT_DOOR") != "3"

    @property
    def left_rear_door_open_supported(self):
        return self._vehicle.fields.get("OPEN_STATE_LEFT_REAR_DOOR")

    @property
    def left_rear_door_open(self):
        if self.left_rear_door_open_supported:
            return self._vehicle.fields.get("OPEN_STATE_LEFT_REAR_DOOR") != "3"

    @property
    def right_rear_door_open_supported(self):
        return self._vehicle.fields.get("OPEN_STATE_RIGHT_REAR_DOOR")

    @property
    def right_rear_door_open(self):
        if self.right_rear_door_open_supported:
            return self._vehicle.fields.get("OPEN_STATE_RIGHT_REAR_DOOR") != "3"

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
        return check is not None and check != "unsupported"

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
            try:
                return parse_float(self._vehicle.state.get("maxChargeCurrent"))
            except ValueError:
                return -1

    @property
    def max_charge_current_supported(self):
        check = self._vehicle.state.get("maxChargeCurrent")
        if check is not None:
            return True

    @property
    def actual_charge_rate(self):
        """Return actual charge rate"""
        if self.actual_charge_rate_supported:
            try:
                return parse_float(self._vehicle.state.get("actualChargeRate"))
            except ValueError:
                return -1

    @property
    def actual_charge_rate_supported(self):
        check = self._vehicle.state.get("actualChargeRate")
        if check is not None:
            return True

    @property
    def actual_charge_rate_unit(self):
        return "km/h"

    @property
    def charging_power(self):
        """Return charging power"""
        if self.charging_power_supported:
            try:
                return parse_float(self._vehicle.state.get("chargingPower"))
            except ValueError:
                return -1

    @property
    def charging_power_supported(self):
        check = self._vehicle.state.get("chargingPower")
        if check is not None:
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
    def primary_engine_range_percent(self):
        """Return primary engine range"""
        if self.primary_engine_range_percent_supported:
            return self._vehicle.state.get("primaryEngineRangePercent")

    @property
    def primary_engine_range_percent_supported(self):
        check = self._vehicle.state.get("primaryEngineRangePercent")
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
        if check is not None and check != "unsupported":
            return True

    @property
    def car_type(self):
        """Return secondary engine range"""
        if self.car_type_supported:
            return self._vehicle.state.get("carType")

    @property
    def car_type_supported(self):
        check = self._vehicle.state.get("carType")
        if check and check != "unsupported":
            return True

    @property
    def secondary_engine_range_percent(self):
        """Return secondary engine range"""
        if self.secondary_engine_range_percent_supported:
            return self._vehicle.state.get("secondaryEngineRangePercent")

    @property
    def secondary_engine_range_percent_supported(self):
        check = self._vehicle.state.get("secondaryEngineRangePercent")
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
            return parse_int(self._vehicle.state.get("stateOfCharge"))

    @property
    def state_of_charge_supported(self):
        return parse_int(self._vehicle.state.get("stateOfCharge")) is not None

    @property
    def remaining_charging_time(self):
        """Return remaining charging time"""
        if self.remaining_charging_time_supported:
            return self._vehicle.state.get("remainingChargingTime", 0)

    @property
    def remaining_charging_time_unit(self):
        return "min"

    @property
    def remaining_charging_time_supported(self):
        return self.car_type in ["hybrid", "electric"]

    @property
    def charging_complete_time(self):
        """Return the datetime when charging is or was expected to be complete."""
        # Check if remaining charging time is not supported
        if not self.remaining_charging_time_supported:
            return None
        # If there's no last update or remaining time, we can't calculate
        if self.last_update_time is None or self.remaining_charging_time is None:
            return None
        # Calculate the complete time whenever there is a positive remaining time
        if self.remaining_charging_time > 0:
            calculated_time = self.last_update_time + timedelta(
                minutes=self.remaining_charging_time
            )
            self.charging_complete_time_frozen = (
                calculated_time  # Always update the frozen time
            )
            return calculated_time
        # If the remaining time is zero or negative, and no frozen time is set, return last_update_time
        if self.charging_complete_time_frozen is None:
            return self.last_update_time
        # Otherwise, return the frozen complete time
        return self.charging_complete_time_frozen

    @property
    def target_state_of_charge(self):
        """Return state of charge"""
        if self.target_state_of_charge_supported:
            return parse_int(self._vehicle.state.get("targetstateOfCharge"))

    @property
    def target_state_of_charge_supported(self):
        return parse_int(self._vehicle.state.get("targetstateOfCharge")) is not None

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
    def plug_lock_state(self):
        """Return plug lock state"""
        if self.plug_lock_state_supported:
            return self._vehicle.state.get("plugLockState")

    @property
    def plug_lock_state_supported(self):
        check = self._vehicle.state.get("plugLockState")
        if check:
            return True

    @property
    def external_power(self):
        """Return external Power"""
        if self.external_power_supported:
            external_power_status = self._vehicle.state.get("externalPower")
            if external_power_status == "unavailable":
                return "Not Ready"
            elif external_power_status == "ready":
                return "Ready"
            else:
                return external_power_status

    @property
    def external_power_supported(self):
        return self._vehicle.state.get("externalPower") is not None

    @property
    def plug_led_color(self):
        """Return plug LED Color"""
        if self.plug_led_color_supported:
            return self._vehicle.state.get("plugledColor")

    @property
    def plug_led_color_supported(self):
        check = self._vehicle.state.get("plugledColor")
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
    def glass_surface_heating(self):
        if self.glass_surface_heating_supported:
            return self._vehicle.state.get("isMirrorHeatingActive")

    @property
    def glass_surface_heating_supported(self):
        return self._vehicle.state.get("isMirrorHeatingActive") is not None

    @property
    def park_time(self):
        if self.park_time_supported:
            return self._vehicle.state.get("vehicleParkingClock")

    @property
    def park_time_supported(self):
        return self._vehicle.state.get("vehicleParkingClock") is not None

    @property
    def remaining_climatisation_time(self):
        if self.remaining_climatisation_time_supported:
            remaining_time = self._vehicle.state.get("remainingClimatisationTime")
            if remaining_time is not None and remaining_time < 0:
                return 0
            elif remaining_time is not None:
                return remaining_time
        return None

    @property
    def remaining_climatisation_time_supported(self):
        return self._vehicle.state.get("remainingClimatisationTime") is not None

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
