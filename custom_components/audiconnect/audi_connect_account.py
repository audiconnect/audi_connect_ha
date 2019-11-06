import json
import time
from datetime import timedelta, datetime
import logging
import asyncio

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

MAX_RESPONSE_ATTEMPTS = 10
REQUEST_STATUS_SLEEP = 5

from .audi_services import AudiLogonService, AudiCarService, AudiCarFinderService, AudiVehicleStatusReportService, AudiChargerService, RequestStatus 
from .audi_api import AudiAPI

class AudiConnectAccount:
    """Representation of an Audi Connect Account."""

    def __init__(self, session, username: str, password: str) -> None:

        self.api = AudiAPI(session)
        self.username = username
        self.password = password
        self.loggedin = False

        self.connect_retries = 3
        self.connect_delay = 10

        self.vehicles = []
        self._update_listeners = []

    async def login(self):
        for i in range(self.connect_retries):
            self.loggedin = await self.try_login(i == self.connect_retries-1)
            if self.loggedin is True:
                break

            await asyncio.sleep(self.connect_delay)

    async def try_login(self, logError):
        try:
            self.logon_service = AudiLogonService(self.api)
            await self.logon_service.login(self.username, self.password, False)
            return True
        except Exception as exception:
            if logError is True:
                _LOGGER.error(exception)

            return False

    async def update(self, *_):
        if not self.loggedin:
            await self.login()

        if not self.loggedin: 
            return False

        """Update the state of all vehicles.
        Notify all listeners about the update.
        """
        _LOGGER.debug(
            "Updating vehicle state for account %s, notifying %d listeners",
            self.username, len(self._update_listeners))
        try:
            if len(self.vehicles) > 0:
                for vehicle in self.vehicles:
                    await vehicle.update()

            else:
                car_service = AudiCarService(self.api)
                vehicles_response = await car_service.get_vehicles()
                vehicles = vehicles_response.vehicles
                self.vehicles = []
                for vehicle in vehicles:
                    try:
                        audiVehicle = AudiConnectVehicle(self.api, vehicle)
                        await audiVehicle.update()
                        self.vehicles.append(audiVehicle)
                    except Exception:
                        pass

            for listener in self._update_listeners:
                listener()
            
            self.loggedin = False

            return True

        except IOError as exception:
            _LOGGER.exception(exception)
            return False

    async def refresh_vehicle_data(self, vin, loop):
        if not self.loggedin:
            await self.login()

        if not self.loggedin: 
            return False

        vehicle = [v for v in self.vehicles if v.vin.lower() == vin]

        if vehicle and len(vehicle) > 0:
            request_id = await vehicle[0].refresh_vehicle_data()

            for attempt in range(MAX_RESPONSE_ATTEMPTS):
                await asyncio.sleep(REQUEST_STATUS_SLEEP)

                status = await vehicle[0].get_status_from_update(request_id)

                if status == RequestStatus.SUCCESS:
                    return True

        return False

class AudiConnectVehicle:
    def __init__(self, api: AudiAPI, vehicle) -> None:
        self.api = api
        self.vehicle = vehicle
        self.vin = vehicle.vin
        self.registered = vehicle.registered
        self.vehicle.state = {}
        self.logged_errors = set()

    async def update(self):
        await self.updateVehicleStatusReport()
        await self.updateVehicleDetails()
        await self.updateVehiclePosition()
        # self.updateVehicleClimater()
        await self.updateVehicleCharger()

    def logExceptionOnce(self, exception, message):
        err = message + ": " + str(exception).rstrip('\n')
        if not err in self.logged_errors:
            self.logged_errors.add(err)
            _LOGGER.error(err)

    async def updateVehicleStatusReport(self):
        try:
            status_service = AudiVehicleStatusReportService(self.api, self.vehicle)
            status = await status_service.get_stored_vehicle_data()
            self.vehicle.fields = {status.data_fields[i].name: status.data_fields[i].value for i in range(0, len(status.data_fields))}
            self.vehicle.state["last_update_time"] = datetime.strptime(status.data_fields[0].send_time, '%Y-%m-%dT%H:%M:%S')
        except Exception as exception:
            self.logExceptionOnce(exception, "Unable to obtain the vehicle status report of {}".format(self.vehicle.vin))

    async def updateVehicleDetails(self):
        try:
            car_service = AudiCarService(self.api)
            details = await car_service.get_vehicle_data(self.vehicle)
            self.vehicle.state["model"] = details["getVehicleDataResponse"]["VehicleSpecification"]["ModelCoding"]["@name"]
        except Exception as exception:
            self.logExceptionOnce(exception, "Unable to obtain the vehicle model of {}".format(self.vehicle.vin))

    async def updateVehiclePosition(self):
        try:
            finder_service = AudiCarFinderService(self.api, self.vehicle)
            resp = await finder_service.find()
            if resp.get("findCarResponse") is not None:
                position = resp["findCarResponse"]
            
            if position.get("Position") is not None and position["Position"].get("carCoordinate") is not None and position["Position"].get("timestampCarSentUTC") is not None and position.get("parkingTimeUTC") is not None:
                self.vehicle.state["position"] = { 
                    "latitude": '{:f}'.format(position["Position"]["carCoordinate"]["latitude"] / 1000000),  
                    "longitude": '{:f}'.format(position["Position"]["carCoordinate"]["longitude"] / 1000000),
                    "timestamp": position["Position"]["timestampCarSentUTC"],
                    "parktime": position["parkingTimeUTC"]
                }

        except Exception as exception:
            self.logExceptionOnce(exception, "Unable to update the vehicle position of {}".format(self.vehicle.vin))

    # def updateVehicleClimater(self):
    #     try:
    #         climaService = PreTripClimaService(self.api, self.vehicle)
    #         result = climaService.get_status()

    #     except Exception:
    #         pass

    async def updateVehicleCharger(self):
        try:
            chargerService = AudiChargerService(self.api, self.vehicle)
            result = await chargerService.get_charger()
            if result:
                try:
                    self.vehicle.state["maxChargeCurrent"] = result["charger"]["settings"]["maxChargeCurrent"]["content"]
                except Exception:
                    pass
                try:
                    self.vehicle.state["chargingState"] = result["charger"]["status"]["chargingStatusData"]["chargingState"]["content"]
                except Exception:
                    pass
                try:
                    self.vehicle.state["engineTypeFirstEngine"] = result["charger"]["status"]["cruisingRangeStatusData"]["engineTypeFirstEngine"]["content"]
                except Exception:
                    pass
                try:
                    self.vehicle.state["engineTypeSecondEngine"] = result["charger"]["status"]["cruisingRangeStatusData"]["engineTypeSecondEngine"]["content"]
                except Exception:
                    pass
                try:
                    self.vehicle.state["stateOfCharge"] = result["charger"]["status"]["batteryStatusData"]["stateOfCharge"]["content"]
                except Exception:
                    pass
                try:
                    self.vehicle.state["remainingChargingTime"] = result["charger"]["status"]["batteryStatusData"]["remainingChargingTime"]["content"]
                except Exception:
                    pass
                try:
                    self.vehicle.state["plugState"] = result["charger"]["status"]["plugStatusData"]["plugState"]["content"]
                except Exception:
                    pass

        except Exception as exception:
            self.logExceptionOnce(exception, "Unable to obtain the vehicle charger state for {}".format(self.vehicle.vin))

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
            return self.vehicle.state.get("last_update_time")

    @property
    def last_update_time_supported(self):
        check = self.vehicle.state.get("last_update_time")
        if check:
            return True

    @property
    def service_inspection_time(self):
        """Return time left for service inspection"""
        if self.service_inspection_time_supported:
            return -int(self.vehicle.fields.get("MAINTENANCE_INTERVAL_TIME_TO_INSPECTION"))

    @property
    def service_inspection_time_supported(self):
        check = self.vehicle.fields.get("MAINTENANCE_INTERVAL_TIME_TO_INSPECTION")
        if check and self.parseToInt(check):
            return True

    @property
    def service_inspection_distance(self):
        """Return distance left for service inspection"""
        if self.service_inspection_distance_supported:
            return -int(self.vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION"))

    @property
    def service_inspection_distance_supported(self):
        check = self.vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION")
        if check and self.parseToInt(check):
            return True

    @property
    def oil_change_time(self):
        """Return time left for oil change"""
        if self.oil_change_time_supported:
            return -int(self.vehicle.fields.get("MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE"))

    @property
    def oil_change_time_supported(self):
        check = self.vehicle.fields.get("MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE")
        if check and self.parseToInt(check):
            return True

    @property
    def oil_change_distance(self):
        """Return distance left for oil change"""
        if self.oil_change_distance_supported:
            return -int(self.vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE"))

    @property
    def oil_change_distance_supported(self):
        check = self.vehicle.fields.get("MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE")
        if check and self.parseToInt(check):
            return True

    @property
    def oil_level(self):
        """Return oil level percentage"""
        if self.oil_level_supported:
            return float(self.vehicle.fields.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE"))

    @property
    def oil_level_supported(self):
        check = self.vehicle.fields.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE")
        if check and self.parseToFloat(check):
            return True
            
    @property
    def sun_roof(self):
        if self.sun_roof_supported:
            res = self.vehicle.fields.get("STATE_SUN_ROOF_MOTOR_COVER")
            return res == "2"

    @property
    def sun_roof_supported(self):
        check = self.vehicle.fields.get("STATE_SUN_ROOF_MOTOR_COVER")
        if check and check != "0":
            return True

    @property
    def parking_light(self):
        """Return true if parking light is on"""
        if self.parking_light_supported:
            check = self.vehicle.fields.get("LIGHT_STATUS")
            return check != "2"

    @property
    def parking_light_supported(self):
        """Return true if parking light is supported"""
        check = self.vehicle.fields.get("LIGHT_STATUS")
        if check:
            return True

    @property
    def mileage(self):
        if self.mileage_supported:
            check = self.vehicle.fields.get("UTC_TIME_AND_KILOMETER_STATUS")
            return self.parseToInt(check)

    @property
    def mileage_supported(self):
        """Return true if mileage is supported"""
        check = self.vehicle.fields.get("UTC_TIME_AND_KILOMETER_STATUS")
        if check and self.parseToInt(check): return True

    @property
    def range(self):
        if self.range_supported:
            check = self.vehicle.fields.get("TOTAL_RANGE")
            return self.parseToInt(check)

    @property
    def range_supported(self):
        """Return true if range is supported"""
        check = self.vehicle.fields.get("TOTAL_RANGE")
        if check and self.parseToInt(check): return True

    @property
    def tank_level(self):
        if self.tank_level_supported:
            check = self.vehicle.fields.get("TANK_LEVEL_IN_PERCENTAGE")
            return self.parseToInt(check)

    @property
    def tank_level_supported(self):
        """Return true if tank_level is supported"""
        check = self.vehicle.fields.get("TANK_LEVEL_IN_PERCENTAGE")
        if check and self.parseToInt(check): return True

    @property
    def position(self):
        """Return position."""
        if self.position_supported:
            return self.vehicle.state.get('position')

    @property
    def position_supported(self):
        """Return true if vehicle has position."""
        check = self.vehicle.state.get('position')
        if check: 
            return True

    @property
    def model(self):
        """Return model"""
        if self.model_supported:
            return self.vehicle.state.get('model')

    @property
    def model_supported(self):
        check = self.vehicle.state.get('model')
        if check: 
            return True

    @property
    def any_window_open_supported(self):
        """Return true if window state is supported"""
        checkLeftFront = self.vehicle.fields.get('STATE_LEFT_FRONT_WINDOW')
        checkLeftRear = self.vehicle.fields.get('STATE_LEFT_REAR_WINDOW')
        checkRightFront = self.vehicle.fields.get('STATE_RIGHT_FRONT_WINDOW')
        checkRightRear = self.vehicle.fields.get('STATE_RIGHT_REAR_WINDOW')
        if checkLeftFront and checkLeftRear and checkRightFront and checkRightRear:
            return True

    @property
    def any_window_open(self):
        if self.any_window_open_supported:
            checkLeftFront = self.vehicle.fields.get('STATE_LEFT_FRONT_WINDOW')
            checkLeftRear = self.vehicle.fields.get('STATE_LEFT_REAR_WINDOW')
            checkRightFront = self.vehicle.fields.get('STATE_RIGHT_FRONT_WINDOW')
            checkRightRear = self.vehicle.fields.get('STATE_RIGHT_REAR_WINDOW')
            return not (checkLeftFront == "3" and checkLeftRear == "3" and checkRightFront == "3" and checkRightRear == "3")

    @property
    def any_door_unlocked_supported(self):
        checkLeftFront = self.vehicle.fields.get('LOCK_STATE_LEFT_FRONT_DOOR')
        checkLeftRear = self.vehicle.fields.get('LOCK_STATE_LEFT_REAR_DOOR')
        checkRightFront = self.vehicle.fields.get('LOCK_STATE_RIGHT_FRONT_DOOR')
        checkRightRear = self.vehicle.fields.get('LOCK_STATE_RIGHT_REAR_DOOR')
        if checkLeftFront and checkLeftRear and checkRightFront and checkRightRear:
            return True

    @property
    def any_door_unlocked(self):
        if self.any_door_unlocked_supported:
            checkLeftFront = self.vehicle.fields.get('LOCK_STATE_LEFT_FRONT_DOOR')
            checkLeftRear = self.vehicle.fields.get('LOCK_STATE_LEFT_REAR_DOOR')
            checkRightFront = self.vehicle.fields.get('LOCK_STATE_RIGHT_FRONT_DOOR')
            checkRightRear = self.vehicle.fields.get('LOCK_STATE_RIGHT_REAR_DOOR')
            return not (checkLeftFront == "2" and checkLeftRear == "2" and checkRightFront == "2" and checkRightRear == "2")
  
    @property
    def any_door_open_supported(self):
        checkLeftFront = self.vehicle.fields.get('OPEN_STATE_LEFT_FRONT_DOOR')
        checkLeftRear = self.vehicle.fields.get('OPEN_STATE_LEFT_REAR_DOOR')
        checkRightFront = self.vehicle.fields.get('OPEN_STATE_RIGHT_FRONT_DOOR')
        checkRightRear = self.vehicle.fields.get('OPEN_STATE_RIGHT_REAR_DOOR')
        if checkLeftFront and checkLeftRear and checkRightFront and checkRightRear:
            return True

    @property
    def any_door_open(self):
        if self.any_door_open_supported:
            checkLeftFront = self.vehicle.fields.get('OPEN_STATE_LEFT_FRONT_DOOR')
            checkLeftRear = self.vehicle.fields.get('OPEN_STATE_LEFT_REAR_DOOR')
            checkRightFront = self.vehicle.fields.get('OPEN_STATE_RIGHT_FRONT_DOOR')
            checkRightRear = self.vehicle.fields.get('OPEN_STATE_RIGHT_REAR_DOOR')
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
            check = self.vehicle.fields.get("LOCK_STATE_TRUNK_LID")
            return check != "2"

    @property
    def trunk_unlocked_supported(self):
        check = self.vehicle.fields.get("LOCK_STATE_TRUNK_LID")
        if check: 
            return True

    @property
    def trunk_open(self):
        if self.trunk_open_supported:
            check = self.vehicle.fields.get("OPEN_STATE_TRUNK_LID")
            return check != "3"

    @property
    def trunk_open_supported(self):
        check = self.vehicle.fields.get("OPEN_STATE_TRUNK_LID")
        if check: 
            return True

    @property
    def hood_open(self):
        if self.hood_open_supported:
            check = self.vehicle.fields.get("OPEN_STATE_HOOD")
            return check != "3"

    @property
    def hood_open_supported(self):
        check = self.vehicle.fields.get("OPEN_STATE_HOOD")
        if check: 
            return True

    @property
    def charging_state(self):
        """Return charging state"""
        if self.charging_state_supported:
            return self.vehicle.state.get('chargingState')

    @property
    def charging_state_supported(self):
        check = self.vehicle.state.get('chargingState')
        if check: 
            return True

    @property
    def max_charge_current(self):
        """Return max charge current"""
        if self.max_charge_current_supported:
            return self.parseToFloat(self.vehicle.state.get('maxChargeCurrent'))

    @property
    def max_charge_current_supported(self):
        check = self.vehicle.state.get('maxChargeCurrent')
        if check and self.parseToFloat(check): 
            return True

    @property
    def engine_type1(self):
        """Return engine type 1"""
        if self.engine_type1_supported:
            return self.vehicle.state.get('engineTypeFirstEngine')

    @property
    def engine_type1_supported(self):
        check = self.vehicle.state.get('engineTypeFirstEngine')
        if check and check != 'unsupported': 
            return True

    @property
    def engine_type2(self):
        """Return engine type 2"""
        if self.engine_type2_supported:
            return self.vehicle.state.get('engineTypeSecondEngine')

    @property
    def engine_type2_supported(self):
        check = self.vehicle.state.get('engineTypeSecondEngine')
        if check and check != 'unsupported': 
            return True

    @property
    def state_of_charge(self):
        """Return state of charge"""
        if self.state_of_charge_supported:
            return self.parseToFloat(self.vehicle.state.get('stateOfCharge'))

    @property
    def state_of_charge_supported(self):
        check = self.vehicle.state.get('stateOfCharge')
        if check and self.parseToFloat(check): 
            return True

    @property
    def remaining_charging_time(self):
        """Return remaining charging time"""
        if self.remaining_charging_time_supported:
            res = self.parseToInt(self.vehicle.state.get('remainingChargingTime'))
            if res == 65535:
                return "n/a"
            else:
                return "%02d:%02d" % divmod(res, 60)

    @property
    def remaining_charging_time_supported(self):
        check = self.vehicle.state.get('remainingChargingTime')
        if check and self.parseToFloat(check): 
            return True

    @property
    def plug_state(self):
        """Return plug state"""
        if self.plug_state_supported:
            return self.vehicle.state.get('plugState')

    @property
    def plug_state_supported(self):
        check = self.vehicle.state.get('plugState')
        if check: 
            return True

    async def refresh_vehicle_data(self):
        try:
            status_service = AudiVehicleStatusReportService(self.api, self.vehicle)
            res = await status_service.request_current_vehicle_data()
            return res.request_id
        
        except Exception:
            pass

    async def get_status_from_update(self, request_id):
        try:
            status_service = AudiVehicleStatusReportService(self.api, self.vehicle)
            return await status_service.get_request_status(request_id).status
        
        except Exception:
            pass
