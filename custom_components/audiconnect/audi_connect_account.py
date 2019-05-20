import json
import time
from datetime import timedelta, datetime
import logging

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

from audiapi.API import API
from audiapi.Services import VehicleService, LogonService, CarService, CarFinderService, VehicleStatusReportService, RequestStatus, PreTripClimaService

class ChargerService(VehicleService):
    def get_charger(self):
        return self._api.get(self.url('/vehicles/{vin}/charger'))

    def _get_path(self):
        return 'bs/batterycharge/v1'

class AudiConnectAccount:
    """Representation of an Audi Connect Account."""

    def __init__(self, username: str, password: str) -> None:

        self.api = API()
        self.username = username

        self.logon_service = LogonService(self.api)
        if not self.logon_service.restore_token():
            self.logon_service.login(username, password)

        self.vehicles = []
        self._update_listeners = []

    async def update(self, *_):
        """Update the state of all vehicles.
        Notify all listeners about the update.
        """
        _LOGGER.debug(
            "Updating vehicle state for account %s, notifying %d listeners",
            self.username, len(self._update_listeners))
        try:
            if len(self.vehicles) > 0:
                for vehicle in self.vehicles:
                    vehicle.update()

            else:
                car_service = CarService(self.api)
                vehicles_response = car_service.get_vehicles()
                vehicles = vehicles_response.vehicles
                self.vehicles = []
                for vehicle in vehicles:
                    try:
                        audiVehicle = AudiConnectVehicle(self.api, vehicle)
                        audiVehicle.update()
                        self.vehicles.append(audiVehicle)
                    except Exception:
                        pass

            for listener in self._update_listeners:
                listener()
            
            return True

        except IOError as exception:
            _LOGGER.error("Error updating the vehicle state")
            _LOGGER.exception(exception)


class AudiConnectVehicle:
    def __init__(self, api: API, vehicle) -> None:
        self.api = api
        self.vehicle = vehicle
        self.vin = vehicle.vin
        self.registered = vehicle.registered

    def update(self):
        self.updateVehicleStatusReport()
        self.updateVehicleDetails()
        self.updateVehiclePosition()
        # self.updateVehicleClimater()
        self.updateVehicleCharger()

    def updateVehicleStatusReport(self):
        try:
            status_service = VehicleStatusReportService(self.api, self.vehicle)
            status = status_service.get_stored_vehicle_data()
            self.vehicle.state = {status.data_fields[i].name: status.data_fields[i].value for i in range(0, len(status.data_fields))}
            self.vehicle.state["last_update_time"] = datetime.strptime(status.data_fields[0].send_time, '%Y-%m-%dT%H:%M:%S')
        except Exception:
            pass

    def updateVehicleDetails(self):
        try:
            car_service = CarService(self.api)
            details = car_service.get_vehicle_data(self.vehicle)
            self.vehicle.state["model"] = details["getVehicleDataResponse"]["VehicleSpecification"]["ModelCoding"]["@name"]
        except Exception:
            pass

    def updateVehiclePosition(self):
        try:
            finder_service = CarFinderService(self.api, self.vehicle)
            position = finder_service.find()["findCarResponse"]         
            self.vehicle.state["position"] = { 
                "latitude": position["Position"]["carCoordinate"]["latitude"],  
                "longitude": position["Position"]["carCoordinate"]["longitude"],
                "timestamp": datetime.strptime(position["Position"]["timestampCarSentUTC"], '%Y-%m-%dT%H:%M:%S%z'),
                "parktime": datetime.strptime(position["parkingTimeUTC"], '%Y-%m-%dT%H:%M:%S%z')
            }

        except Exception:
            pass

    # def updateVehicleClimater(self):
    #     try:
    #         climaService = PreTripClimaService(self.api, self.vehicle)
    #         result = climaService.get_status()

    #     except Exception:
    #         pass

    def updateVehicleCharger(self):
        try:
            chargerService = ChargerService(self.api, self.vehicle)
            result = chargerService.get_charger()
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

        except Exception:
            pass

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

    # def add_update_listener(self, listener):
    #     """Add a listener for update notifications."""
    #     self._update_listeners.append(listener)

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
            return -float(self.vehicle.state.get("MAINTENANCE_INTERVAL_TIME_TO_INSPECTION"))

    @property
    def service_inspection_time_supported(self):
        check = self.vehicle.state.get("MAINTENANCE_INTERVAL_TIME_TO_INSPECTION")
        if check and self.parseToFloat(check):
            return True

    @property
    def service_inspection_distance(self):
        """Return distance left for service inspection"""
        if self.service_inspection_distance_supported:
            return -float(self.vehicle.state.get("MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION"))

    @property
    def service_inspection_distance_supported(self):
        check = self.vehicle.state.get("MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION")
        if check and self.parseToFloat(check):
            return True

    @property
    def oil_change_time(self):
        """Return time left for oil change"""
        if self.oil_change_time_supported:
            return -float(self.vehicle.state.get("MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE"))

    @property
    def oil_change_time_supported(self):
        check = self.vehicle.state.get("MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE")
        if check and self.parseToFloat(check):
            return True

    @property
    def oil_change_distance(self):
        """Return distance left for oil change"""
        if self.oil_change_distance_supported:
            return -float(self.vehicle.state.get("MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE"))

    @property
    def oil_change_distance_supported(self):
        check = self.vehicle.state.get("MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE")
        if check and self.parseToFloat(check):
            return True

    @property
    def oil_level(self):
        """Return oil level percentage"""
        if self.oil_level_supported:
            return float(self.vehicle.state.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE"))

    @property
    def oil_level_supported(self):
        check = self.vehicle.state.get("OIL_LEVEL_DIPSTICKS_PERCENTAGE")
        if check and self.parseToFloat(check):
            return True

    @property
    def parking_light(self):
        """Return true if parking light is on"""
        if self.parking_light_supported:
            check = self.vehicle.state.get("LIGHT_STATUS")
            return check == 2

    @property
    def parking_light_supported(self):
        """Return true if parking light is supported"""
        check = self.vehicle.state.get("LIGHT_STATUS")
        if check:
            return True

    @property
    def mileage(self):
        if self.mileage_supported:
            check = self.vehicle.state.get("UTC_TIME_AND_KILOMETER_STATUS")
            return self.parseToFloat(check)

    @property
    def mileage_supported(self):
        """Return true if mileage is supported"""
        check = self.vehicle.state.get("UTC_TIME_AND_KILOMETER_STATUS")
        if check and self.parseToFloat(check): return True

    @property
    def range(self):
        if self.range_supported:
            check = self.vehicle.state.get("TOTAL_RANGE")
            return self.parseToFloat(check)

    @property
    def range_supported(self):
        """Return true if range is supported"""
        check = self.vehicle.state.get("TOTAL_RANGE")
        if check and self.parseToFloat(check): return True

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
        checkLeftFront = self.vehicle.state.get('STATE_LEFT_FRONT_WINDOW')
        checkLeftRear = self.vehicle.state.get('STATE_LEFT_REAR_WINDOW')
        checkRightFront = self.vehicle.state.get('STATE_RIGHT_FRONT_WINDOW')
        checkRightRear = self.vehicle.state.get('STATE_RIGHT_REAR_WINDOW')
        if checkLeftFront and checkLeftRear and checkRightFront and checkRightRear:
            return True

    @property
    def any_window_open(self):
        if self.any_window_open_supported:
            checkLeftFront = self.vehicle.state.get('STATE_LEFT_FRONT_WINDOW')
            checkLeftRear = self.vehicle.state.get('STATE_LEFT_REAR_WINDOW')
            checkRightFront = self.vehicle.state.get('STATE_RIGHT_FRONT_WINDOW')
            checkRightRear = self.vehicle.state.get('STATE_RIGHT_REAR_WINDOW')
            return not (checkLeftFront == "3" and checkLeftRear == "3" and checkRightFront == "3" and checkRightRear == "3")

    @property
    def any_door_unlocked_supported(self):
        checkLeftFront = self.vehicle.state.get('LOCK_STATE_LEFT_FRONT_DOOR')
        checkLeftRear = self.vehicle.state.get('LOCK_STATE_LEFT_REAR_DOOR')
        checkRightFront = self.vehicle.state.get('LOCK_STATE_RIGHT_FRONT_DOOR')
        checkRightRear = self.vehicle.state.get('LOCK_STATE_RIGHT_REAR_DOOR')
        if checkLeftFront and checkLeftRear and checkRightFront and checkRightRear:
            return True

    @property
    def any_door_unlocked(self):
        if self.any_door_unlocked_supported:
            checkLeftFront = self.vehicle.state.get('LOCK_STATE_LEFT_FRONT_DOOR')
            checkLeftRear = self.vehicle.state.get('LOCK_STATE_LEFT_REAR_DOOR')
            checkRightFront = self.vehicle.state.get('LOCK_STATE_RIGHT_FRONT_DOOR')
            checkRightRear = self.vehicle.state.get('LOCK_STATE_RIGHT_REAR_DOOR')
            return not (checkLeftFront == "2" and checkLeftRear == "2" and checkRightFront == "2" and checkRightRear == "2")
  
    @property
    def trunk_unlocked(self):
        if self.trunk_unlocked_supported:
            check = self.vehicle.state.get("LOCK_STATE_TRUNK_LID")
            return check != "2"

    @property
    def trunk_unlocked_supported(self):
        check = self.vehicle.state.get("LOCK_STATE_TRUNK_LID")
        if check: 
            return True

                #     self.vehicle.state["maxChargeCurrent"] = result["charger"]["settings"]["maxChargeCurrent"]["content"]
                # except Exception:
                #     pass
                # try:
                #     self.vehicle.state["chargingState"] = result["charger"]["status"]["chargingStatusData"]["chargingState"]["content"]

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
            return self.vehicle.state.get('maxChargeCurrent')

    @property
    def max_charge_current_supported(self):
        check = self.vehicle.state.get('maxChargeCurrent')
        if check: 
            return True

    @property
    def engine_type1(self):
        """Return engine type 1"""
        if self.engine_type1_supported:
            return self.vehicle.state.get('engineTypeFirstEngine')

    @property
    def engine_type1_supported(self):
        check = self.vehicle.state.get('engineTypeFirstEngine')
        if check: 
            return True

    @property
    def engine_type2(self):
        """Return engine type 2"""
        if self.engine_type2_supported:
            return self.vehicle.state.get('engineTypeSecondEngine')

    @property
    def engine_type2_supported(self):
        check = self.vehicle.state.get('engineTypeSecondEngine')
        if check: 
            return True

    def refresh_vehicle_data(self):
        try:
            status_service = VehicleStatusReportService(self.api, self.vehicle)
            res = status_service.request_current_vehicle_data()
            return res.request_id
        
        except Exception:
            pass

    def get_status_from_update(self, request_id):
        try:
            status_service = VehicleStatusReportService(self.api, self.vehicle)
            return status_service.get_request_status(request_id).status
        
        except Exception:
            pass


    # def get_status(self, timeout = 10):
    #     """Check status from call"""
    #     retry_counter = 0
    #     while retry_counter < timeout:
    #         resp = self.call('-/emanager/get-notifications', data='dummy')
    #         data = resp.get('actionNotificationList', {})
    #         if data:
    #             return data
    #         time.sleep(1)
    #         retry_counter += 1
    #     return False