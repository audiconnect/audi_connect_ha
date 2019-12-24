import json
import time
from datetime import timedelta, datetime
import logging
import asyncio

from asyncio import TimeoutError

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

MAX_RESPONSE_ATTEMPTS = 10
REQUEST_STATUS_SLEEP = 5

from .audi_services import AudiService, RequestStatus 
from .audi_api import AudiAPI

class AudiConnectAccount:
    """Representation of an Audi Connect Account."""

    def __init__(self, session, username: str, password: str, country: str, spin: str) -> None:

        self._api = AudiAPI(session)
        self._audi_service = AudiService(self._api, country, spin)

        self._username = username
        self._password = password
        self._loggedin = False

        self._connect_retries = 3
        self._connect_delay = 10

        self._update_listeners = []

        self._vehicles = []
        self._audi_vehicles = []
        
    async def login(self):
        for i in range(self._connect_retries):
            self._loggedin = await self.try_login(i == self._connect_retries-1)
            if self._loggedin is True:
                break
            
            if i < self._connect_retries - 1:
                _LOGGER.error("Login to Audi service failed, trying again in {} seconds".format(self._connect_delay))
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

        """Update the state of all vehicles.
        Notify all listeners about the update.
        """
        _LOGGER.debug(
            "Updating vehicle state for account %s, notifying %d listeners",
            self._username, len(self._update_listeners))
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
            
            self._loggedin = False

            return True

        except IOError as exception:
            _LOGGER.exception(exception)
            return False

    async def add_or_update_vehicle(self, vehicle, vinlist):
        if vinlist is None or vehicle.vin.lower() in vinlist:
            vupd = [x for x in self._vehicles if x.vin == vehicle.vin.lower()]
            if len(vupd) > 0:
                await vupd[0].update()
            else:
                try:
                    audiVehicle = AudiConnectVehicle(self._audi_service, vehicle)
                    await audiVehicle.update()
                    self._vehicles.append(audiVehicle)
                except Exception:
                    pass

    async def login_and_get_vehicle(self, vin: str):
        if not self._loggedin:
            await self.login()

        if not self._loggedin: 
            return None

        vehicle = [v for v in self._vehicles if v.vin.lower() == vin.lower()]
        if vehicle and len(vehicle) > 0:
            return vehicle[0]
        
        return None

    async def refresh_vehicle_data(self, vin: str):
        vehicle = await self.login_and_get_vehicle(vin)
        if vehicle is None: 
            return False

        request_id = await vehicle.refresh_vehicle_data()

        for attempt in range(MAX_RESPONSE_ATTEMPTS):
            await asyncio.sleep(REQUEST_STATUS_SLEEP)

            status = await vehicle.get_status_from_update(request_id)

            if status == RequestStatus.SUCCESS:
                return True

        return False

    async def set_vehicle_lock(self, vin: str, lock: bool):
        vehicle = await self.login_and_get_vehicle(vin)
        if vehicle is None: 
            return False
        
        return await vehicle.set_vehicle_lock(lock)

    async def set_vehicle_climatisation(self, vin: str, activate: bool):
        vehicle = await self.login_and_get_vehicle(vin)
        if vehicle is None: 
            return False
        
        return await vehicle.set_climatisation(activate)

    async def set_vehicle_pre_heater(self, vin: str, activate: bool):
        vehicle = await self.login_and_get_vehicle(vin)
        if vehicle is None: 
            return False
        
        return await vehicle.set_pre_heater(activate)
    
    async def set_vehicle_window_heating(self, vin: str, activate: bool):
        vehicle = await self.login_and_get_vehicle(vin)
        if vehicle is None: 
            return False
        
        return await vehicle.set_window_heating(activate)

class AudiConnectVehicle:
    def __init__(self, audi_service: AudiService, vehicle) -> None:
        self._audi_service = audi_service
        self._vehicle = vehicle
        self._vin = vehicle.vin.lower()
        self._vehicle.state = {}
        self._vehicle.fields = {}
        self._logged_errors = set()

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
        
    async def update(self):
        try:
            await self.updateVehicleStatusReport()
            await self.updateVehiclePosition()
            await self.updateVehicleClimater()
            await self.updateVehicleCharger()
        except Exception as exception:
            self.logException(exception, "Unable to update vehicle date of {}".format(self._vehicle.vin))

    def logExceptionOnce(self, exception, message):
        err = message + ": " + str(exception).rstrip('\n')
        if not err in self._logged_errors:
            self._logged_errors.add(err)
            _LOGGER.error(err)

    def logException(self, exception, message):
        err = message + ": " + str(exception).rstrip('\n')
        _LOGGER.error(err)

    async def updateVehicleStatusReport(self):
        try:
            status = await  self._audi_service.get_stored_vehicle_data(self._vehicle.vin)
            self._vehicle.fields = {status.data_fields[i].name: status.data_fields[i].value for i in range(0, len(status.data_fields))}
            self._vehicle.state["last_update_time"] = datetime.strptime(status.data_fields[0].send_time, '%Y-%m-%dT%H:%M:%S')
        except TimeoutError:
            raise
        except Exception as exception:
            self.logExceptionOnce(exception, "Unable to obtain the vehicle status report of {}".format(self._vehicle.vin))

    async def updateVehiclePosition(self):
        try:
            resp = await self._audi_service.get_stored_position(self._vehicle.vin)
            if resp.get("findCarResponse") is not None:
                position = resp["findCarResponse"]
            
            if position.get("Position") is not None and position["Position"].get("carCoordinate") is not None:
                self._vehicle.state["position"] = { 
                    "latitude": position["Position"]["carCoordinate"]["latitude"] / 1000000,  
                    "longitude": position["Position"]["carCoordinate"]["longitude"] / 1000000,
                    "timestamp": position["Position"].get("timestampCarSentUTC"),
                    "parktime": position.get("parkingTimeUTC")
                }

        except TimeoutError:
            raise
        except Exception as exception:
            self.logExceptionOnce(exception, "Unable to update the vehicle position of {}".format(self._vehicle.vin))

    async def updateVehicleClimater(self):
        try:
            result = await self._audi_service.get_climater(self._vehicle.vin)
            if result:
                try:
                    self._vehicle.state["climatisationState"] = result["climater"]["status"]["climatisationStatusData"]["climatisationState"]["content"]
                except Exception:
                    pass

        except TimeoutError:
            raise
        except Exception as exception:
            self.logExceptionOnce(exception, "Unable to obtain the vehicle climatisation state for {}".format(self._vehicle.vin))

    async def updateVehicleCharger(self):
        try:
            result = await self._audi_service.get_charger(self._vehicle.vin)
            if result:
                try:
                    self._vehicle.state["maxChargeCurrent"] = result["charger"]["settings"]["maxChargeCurrent"]["content"]
                except Exception:
                    pass
                try:
                    self._vehicle.state["chargingState"] = result["charger"]["status"]["chargingStatusData"]["chargingState"]["content"]
                except Exception:
                    pass
                try:
                    self._vehicle.state["engineTypeFirstEngine"] = result["charger"]["status"]["cruisingRangeStatusData"]["engineTypeFirstEngine"]["content"]
                except Exception:
                    pass
                try:
                    self._vehicle.state["engineTypeSecondEngine"] = result["charger"]["status"]["cruisingRangeStatusData"]["engineTypeSecondEngine"]["content"]
                except Exception:
                    pass
                try:
                    self._vehicle.state["stateOfCharge"] = result["charger"]["status"]["batteryStatusData"]["stateOfCharge"]["content"]
                except Exception:
                    pass
                try:
                    self._vehicle.state["remainingChargingTime"] = result["charger"]["status"]["batteryStatusData"]["remainingChargingTime"]["content"]
                except Exception:
                    pass
                try:
                    self._vehicle.state["plugState"] = result["charger"]["status"]["plugStatusData"]["plugState"]["content"]
                except Exception:
                    pass

        except TimeoutError:
            raise
        except Exception as exception:
            self.logExceptionOnce(exception, "Unable to obtain the vehicle charger state for {}".format(self._vehicle.vin))

    def parseToInt(self, val: str):
        try:
            return int(val)
        except ValueError:
            return None

    def parseToFloat(self, val: str):
        try:
            return float(val)
        except ValueError:
            return None

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
            return -int(self._vehicle.fields.get("MAINTENANCE_INTERVAL_TIME_TO_INSPECTION"))

    @property
    def service_inspection_time_supported(self):
        check = self._vehicle.fields.get("MAINTENANCE_INTERVAL_TIME_TO_INSPECTION")
        if check and self.parseToInt(check):
            return True

    @property
    def service_inspection_distance(self):
        """Return distance left for service inspection"""
        if self.service_inspection_distance_supported:
            return -int(self._vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION"))

    @property
    def service_inspection_distance_supported(self):
        check = self._vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION")
        if check and self.parseToInt(check):
            return True

    @property
    def oil_change_time(self):
        """Return time left for oil change"""
        if self.oil_change_time_supported:
            return -int(self._vehicle.fields.get("MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE"))

    @property
    def oil_change_time_supported(self):
        check = self._vehicle.fields.get("MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE")
        if check and self.parseToInt(check):
            return True

    @property
    def oil_change_distance(self):
        """Return distance left for oil change"""
        if self.oil_change_distance_supported:
            return -int(self._vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE"))

    @property
    def oil_change_distance_supported(self):
        check = self._vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE")
        if check and self.parseToInt(check):
            return True

    @property
    def oil_level(self):
        """Return oil level percentage"""
        if self.oil_level_supported:
            return float(self._vehicle.fields.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE"))

    @property
    def oil_level_supported(self):
        check = self._vehicle.fields.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE")
        if check and self.parseToFloat(check):
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
            return self.parseToInt(check)

    @property
    def mileage_supported(self):
        """Return true if mileage is supported"""
        check = self._vehicle.fields.get("UTC_TIME_AND_KILOMETER_STATUS")
        if check and self.parseToInt(check): return True

    @property
    def range(self):
        if self.range_supported:
            check = self._vehicle.fields.get("TOTAL_RANGE")
            return self.parseToInt(check)

    @property
    def range_supported(self):
        """Return true if range is supported"""
        check = self._vehicle.fields.get("TOTAL_RANGE")
        if check and self.parseToInt(check): return True

    @property
    def tank_level(self):
        if self.tank_level_supported:
            check = self._vehicle.fields.get("TANK_LEVEL_IN_PERCENTAGE")
            return self.parseToInt(check)

    @property
    def tank_level_supported(self):
        """Return true if tank_level is supported"""
        check = self._vehicle.fields.get("TANK_LEVEL_IN_PERCENTAGE")
        if check and self.parseToInt(check): return True

    @property
    def position(self):
        """Return position."""
        if self.position_supported:
            return self._vehicle.state.get('position')

    @property
    def position_supported(self):
        """Return true if vehicle has position."""
        check = self._vehicle.state.get('position')
        if check: 
            return True

    @property
    def any_window_open_supported(self):
        """Return true if window state is supported"""
        checkLeftFront = self._vehicle.fields.get('STATE_LEFT_FRONT_WINDOW')
        checkLeftRear = self._vehicle.fields.get('STATE_LEFT_REAR_WINDOW')
        checkRightFront = self._vehicle.fields.get('STATE_RIGHT_FRONT_WINDOW')
        checkRightRear = self._vehicle.fields.get('STATE_RIGHT_REAR_WINDOW')
        if checkLeftFront and checkLeftRear and checkRightFront and checkRightRear:
            return True

    @property
    def any_window_open(self):
        if self.any_window_open_supported:
            checkLeftFront = self._vehicle.fields.get('STATE_LEFT_FRONT_WINDOW')
            checkLeftRear = self._vehicle.fields.get('STATE_LEFT_REAR_WINDOW')
            checkRightFront = self._vehicle.fields.get('STATE_RIGHT_FRONT_WINDOW')
            checkRightRear = self._vehicle.fields.get('STATE_RIGHT_REAR_WINDOW')
            return not (checkLeftFront == "3" and checkLeftRear == "3" and checkRightFront == "3" and checkRightRear == "3")

    @property
    def any_door_unlocked_supported(self):
        checkLeftFront = self._vehicle.fields.get('LOCK_STATE_LEFT_FRONT_DOOR')
        checkLeftRear = self._vehicle.fields.get('LOCK_STATE_LEFT_REAR_DOOR')
        checkRightFront = self._vehicle.fields.get('LOCK_STATE_RIGHT_FRONT_DOOR')
        checkRightRear = self._vehicle.fields.get('LOCK_STATE_RIGHT_REAR_DOOR')
        if checkLeftFront and checkLeftRear and checkRightFront and checkRightRear:
            return True

    @property
    def any_door_unlocked(self):
        if self.any_door_unlocked_supported:
            checkLeftFront = self._vehicle.fields.get('LOCK_STATE_LEFT_FRONT_DOOR')
            checkLeftRear = self._vehicle.fields.get('LOCK_STATE_LEFT_REAR_DOOR')
            checkRightFront = self._vehicle.fields.get('LOCK_STATE_RIGHT_FRONT_DOOR')
            checkRightRear = self._vehicle.fields.get('LOCK_STATE_RIGHT_REAR_DOOR')
            return not (checkLeftFront == "2" and checkLeftRear == "2" and checkRightFront == "2" and checkRightRear == "2")
  
    @property
    def any_door_open_supported(self):
        checkLeftFront = self._vehicle.fields.get('OPEN_STATE_LEFT_FRONT_DOOR')
        checkLeftRear = self._vehicle.fields.get('OPEN_STATE_LEFT_REAR_DOOR')
        checkRightFront = self._vehicle.fields.get('OPEN_STATE_RIGHT_FRONT_DOOR')
        checkRightRear = self._vehicle.fields.get('OPEN_STATE_RIGHT_REAR_DOOR')
        if checkLeftFront and checkLeftRear and checkRightFront and checkRightRear:
            return True

    @property
    def any_door_open(self):
        if self.any_door_open_supported:
            checkLeftFront = self._vehicle.fields.get('OPEN_STATE_LEFT_FRONT_DOOR')
            checkLeftRear = self._vehicle.fields.get('OPEN_STATE_LEFT_REAR_DOOR')
            checkRightFront = self._vehicle.fields.get('OPEN_STATE_RIGHT_FRONT_DOOR')
            checkRightRear = self._vehicle.fields.get('OPEN_STATE_RIGHT_REAR_DOOR')
            return not (checkLeftFront == "3" and checkLeftRear == "3" and checkRightFront == "3" and checkRightRear == "3")
    
    @property
    def doors_trunk_status_supported(self):
        return self.any_door_open_supported and self.any_door_unlocked_supported and self.trunk_open_supported and self.trunk_unlocked_supported
 
    @property
    def doors_trunk_status(self):
        if self.any_door_open_supported and self.any_door_unlocked_supported and self.trunk_open_supported and self.trunk_unlocked_supported:
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
            return self._vehicle.state.get('chargingState')

    @property
    def charging_state_supported(self):
        check = self._vehicle.state.get('chargingState')
        if check: 
            return True

    @property
    def max_charge_current(self):
        """Return max charge current"""
        if self.max_charge_current_supported:
            return self.parseToFloat(self._vehicle.state.get('maxChargeCurrent'))

    @property
    def max_charge_current_supported(self):
        check = self._vehicle.state.get('maxChargeCurrent')
        if check and self.parseToFloat(check): 
            return True

    @property
    def engine_type1(self):
        """Return engine type 1"""
        if self.engine_type1_supported:
            return self._vehicle.state.get('engineTypeFirstEngine')

    @property
    def engine_type1_supported(self):
        check = self._vehicle.state.get('engineTypeFirstEngine')
        if check and check != 'unsupported': 
            return True

    @property
    def engine_type2(self):
        """Return engine type 2"""
        if self.engine_type2_supported:
            return self._vehicle.state.get('engineTypeSecondEngine')

    @property
    def engine_type2_supported(self):
        check = self._vehicle.state.get('engineTypeSecondEngine')
        if check and check != 'unsupported': 
            return True

    @property
    def state_of_charge(self):
        """Return state of charge"""
        if self.state_of_charge_supported:
            return self.parseToFloat(self._vehicle.state.get('stateOfCharge'))

    @property
    def state_of_charge_supported(self):
        check = self._vehicle.state.get('stateOfCharge')
        if check and self.parseToFloat(check): 
            return True

    @property
    def remaining_charging_time(self):
        """Return remaining charging time"""
        if self.remaining_charging_time_supported:
            res = self.parseToInt(self._vehicle.state.get('remainingChargingTime'))
            if res == 65535:
                return "n/a"
            else:
                return "%02d:%02d" % divmod(res, 60)

    @property
    def remaining_charging_time_supported(self):
        check = self._vehicle.state.get('remainingChargingTime')
        if check and self.parseToFloat(check): 
            return True

    @property
    def plug_state(self):
        """Return plug state"""
        if self.plug_state_supported:
            return self._vehicle.state.get('plugState')

    @property
    def plug_state_supported(self):
        check = self._vehicle.state.get('plugState')
        if check: 
            return True

    @property
    def climatisation_state(self):
        if self.max_charge_current_supported:
            return self._vehicle.state.get('climatisationState')

    @property
    def max_climatisation_state_supported(self):
        check = self._vehicle.state.get('climatisationState')
        if check: 
            return True

    @property
    def lock_supported(self):
        return self.doors_trunk_status_supported and self._audi_service._spin is not None

    async def set_vehicle_lock(self, lock: bool):
        try:
            await self._audi_service.set_vehicle_lock(self._vehicle.vin, lock)      
        except Exception:
            pass

    async def set_pre_heater(self, activate: bool):
        try:
            await self._audi_service.set_pre_heater(self._vehicle.vin, activate)      
        except Exception:
            pass

    async def set_climatisation(self, start: bool):
        try:
            await self._audi_service.set_climatisation(self._vehicle.vin, start)      
        except Exception:
            pass

    async def set_window_heating(self, start: bool):
        try:
            await self._audi_service.set_window_heating(self._vehicle.vin, start)      
        except Exception:
            pass

    async def refresh_vehicle_data(self):
        try:
            res = await self._audi_service.request_current_vehicle_data(self._vehicle.vin)
            return res.request_id
        
        except Exception:
            pass

    async def get_status_from_update(self, request_id):
        try:
            res = await self._audi_service.get_request_status(self._vehicle.vin, request_id)
            return res.status
        
        except Exception:
            pass
