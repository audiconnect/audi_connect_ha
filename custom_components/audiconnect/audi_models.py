class VehicleData:
    def __init__(self, config_entry):
        self.sensors = set()
        self.binary_sensors = set()
        self.switches = set()
        self.device_trackers = set()
        self.locks = set()
        self.config_entry = config_entry
        self.vehicle = None

class CurrentVehicleDataResponse:
    def __init__(self, data):
        data = data["CurrentVehicleDataResponse"]
        self.request_id = data["requestId"]
        self.vin = data["vin"]

class VehicleDataResponse:
    Q4_MAPPING = {
        "frontRightLock": "LOCK_STATE_RIGHT_FRONT_DOOR",
        "frontRightOpen": "OPEN_STATE_RIGHT_FRONT_DOOR",
        "frontLeftLock": "LOCK_STATE_LEFT_FRONT_DOOR",
        "frontLeftOpen": "OPEN_STATE_LEFT_FRONT_DOOR",
        "rearRightLock": "LOCK_STATE_RIGHT_REAR_DOOR",
        "rearRightOpen": "OPEN_STATE_RIGHT_REAR_DOOR",
        "rearLeftLock": "LOCK_STATE_LEFT_REAR_DOOR",
        "rearLeftOpen": "OPEN_STATE_LEFT_REAR_DOOR",
        "trunkLock": "LOCK_STATE_TRUNK_LID",
        "trunkOpen": "OPEN_STATE_TRUNK_LID",
        "bonnetLock": "LOCK_STATE_HOOD",
        "bonnetOpen": "OPEN_STATE_HOOD",
        "sunRoofWindow": "STATE_SUN_ROOF_MOTOR_COVER",
        "frontLeftWindow" : "STATE_LEFT_FRONT_WINDOW",
        "frontRightWindow" : "STATE_RIGHT_FRONT_WINDOW",
        "rearLeftWindow" : "STATE_LEFT_REAR_WINDOW",
        "rearRightWindow" : "STATE_RIGHT_REAR_WINDOW"
    }

    def __init__(self, data):
        self.data_fields = []
        self.states = []
        
        if 'fuelStatus' in data:
            FuelStatus = data["fuelStatus"]["rangeStatus"]["value"]["primaryEngine"]["currentFuelLevel_pct"]
            cruisingRange = data["fuelStatus"]["rangeStatus"]["value"]["totalRange_km"]
            tsCarCaptured = data["fuelStatus"]["rangeStatus"]["value"]["carCapturedTimestamp"]
        
            socField = {
                "textId": "TANK_LEVEL_IN_PERCENTAGE",
                "value": FuelStatus,
                "tsCarCaptured": tsCarCaptured,
                       }
            rangeField = {
            "textId": "TOTAL_RANGE",
            "value": cruisingRange,
            "tsCarCaptured": tsCarCaptured,
            }
            self.data_fields.append(Field(socField))
            self.data_fields.append(Field(rangeField))
        
        
        
        else:
            print("No fuelStatus KEY")
            
        if 'measurements' in data:
            adblueRange = data["measurements"]["rangeStatus"]["value"]["adBlueRange"]
            milage = data["measurements"]["odometerStatus"]["value"]["odometer"]
            milageTsCarCaptured = data["measurements"]["odometerStatus"]["value"]["carCapturedTimestamp"]
            adblueTsCarCaptured = data["measurements"]["rangeStatus"]["value"]["carCapturedTimestamp"]
            adblueField = {
                "textId": "ADBLUE_RANGE",
                "value": adblueRange,
                "tsCarCaptured": adblueTsCarCaptured,
                }
        
            self.data_fields.append(Field(adblueField))        
            milageField = {
            "textId": "UTC_TIME_AND_KILOMETER_STATUS",
            "value": milage,
            "tsCarCaptured": milageTsCarCaptured,
            }
            self.data_fields.append(Field(milageField))
        
            self.states.append({"name" : "last_update_time", "value" : data["measurements"]["odometerStatus"]["value"]["carCapturedTimestamp"]})
        
        
        else:
            print("No measurements KEY")
            
        if 'vehicleLights' in data:
            lightTsCarCaptured = data["vehicleLights"]["lightsStatus"]["value"]["carCapturedTimestamp"]
            lightServiceStatus = data["vehicleLights"]["lightsStatus"]["value"]["lights"][0]["status"]
            lightstatus = {
            "textId": "LIGHT_STATUS",
            "value": lightServiceStatus,
            "tsCarCaptured": lightTsCarCaptured,
            }
            self.data_fields.append(Field(lightstatus))
        else:
            print("No vehicleLights KEY")
            
        if 'vehicleHealthInspection' in data:
            oilTsCarCaptured = data["vehicleHealthInspection"]["maintenanceStatus"]["value"]["carCapturedTimestamp"]
            oilServiceDuekm = data["vehicleHealthInspection"]["maintenanceStatus"]["value"]["oilServiceDue_km"]
            oilServiceDuedays = data["vehicleHealthInspection"]["maintenanceStatus"]["value"]["oilServiceDue_days"]
            inspectionServiceDuekm = data["vehicleHealthInspection"]["maintenanceStatus"]["value"]["inspectionDue_km"]
            inspectionServiceDuedays = data["vehicleHealthInspection"]["maintenanceStatus"]["value"]["inspectionDue_days"]
            oilFieldkm = {
            "textId": "MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE",
            "value": oilServiceDuekm,
            "tsCarCaptured": oilTsCarCaptured,
            }
            oilFieldday = {
            "textId": "MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE",
            "value": oilServiceDuedays,
            "tsCarCaptured": oilTsCarCaptured,
            }
            inspectionFieldkm = {
            "textId": "MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION",
            "value": inspectionServiceDuekm,
            "tsCarCaptured": oilTsCarCaptured,
            }
            inspectionFieldday = {
            "textId": "MAINTENANCE_INTERVAL_TIME_TO_INSPECTION",
            "value": inspectionServiceDuedays,
            "tsCarCaptured": oilTsCarCaptured,
            }
        
            self.data_fields.append(Field(oilFieldkm))
            self.data_fields.append(Field(oilFieldday))

            self.data_fields.append(Field(inspectionFieldkm))
            self.data_fields.append(Field(inspectionFieldday))
        
        else:
            print("No vehicleHealthInspection KEY")
            
        if 'oilLevel' in data:   
            if data["oilLevel"]["oilLevelStatus"]["value"]["value"] == True :
                 oilFieldlevelper = 100
            else:
                 oilFieldlevelper = 1
            oillTsCarCaptured = data["oilLevel"]["oilLevelStatus"]["value"]["carCapturedTimestamp"]
        
            oilFieldlevel = {
            "textId": "OIL_LEVEL_DIPSTICKS_PERCENTAGE",
            "value": oilFieldlevelper,
            "tsCarCaptured": oillTsCarCaptured,
            }
            self.data_fields.append(Field(oilFieldlevel))
        else:
            print("No oilLevel KEY")
            
            
        self.appendWindowState(data)
        self.appendDoorState(data)

      
        
            

        if 'charging' in data:
            self.states.append({"name" : "actualChargeRate", "value" : data["charging"]["chargingStatus"]["value"]["chargeRate_kmph"]})
            self.states.append({"name" : "chargingPower", "value" : data["charging"]["chargingStatus"]["value"]["chargePower_kW"]})
            self.states.append({"name" : "chargeMode", "value" : data["charging"]["chargingStatus"]["value"]["chargeMode"]})
            self.states.append({"name" : "chargingState", "value" : data["charging"]["chargingStatus"]["value"]["chargingState"]})
            self.states.append({"name" : "remainingChargingTime", "value" : data["charging"]["chargingStatus"]["value"]["remainingChargingTimeToComplete_min"]})
            self.states.append({"name" : "plugState", "value" : data["charging"]["plugStatus"]["value"]["plugConnectionState"]})
        else:
            print("No Charching KEY")
        
        

    def appendDoorState(self, data):
        doors = data["access"]["accessStatus"]["value"]["doors"];
        tsCarCapturedAccess = data["access"]["accessStatus"]["value"]["carCapturedTimestamp"];
        for door in doors:
            status = door["status"]
            name = door["name"]
            if not name+"Lock" in self.Q4_MAPPING:
                continue
            status = door["status"]
            lock = "0"
            open = "0"
            unsupported = False
            for state in status:
                if state == "unsupported":
                  unsupported = True
                if state == "locked":
                    lock = "2"
                if state == "closed":
                    open = "3"
            if (not unsupported):
                doorFieldLock = {
                    "textId": self.Q4_MAPPING[name+"Lock"],
                    "value": lock,
                    "tsCarCaptured": tsCarCapturedAccess,
                }
                self.data_fields.append(Field(doorFieldLock))

                doorFieldOpen = {
                    "textId": self.Q4_MAPPING[name+"Open"],
                    "value": open,
                    "tsCarCaptured": tsCarCapturedAccess,
                }
                self.data_fields.append(Field(doorFieldOpen))

    def appendWindowState(self, data):
        windows = data["access"]["accessStatus"]["value"]["windows"];
        tsCarCapturedAccess = data["access"]["accessStatus"]["value"]["carCapturedTimestamp"];
        for window in windows:
            name = window["name"]
            status = window["status"]
            if (status[0] == "unsupported") or not name+"Window" in self.Q4_MAPPING:
                continue
            windowField = {
                "textId": self.Q4_MAPPING[name + "Window"],
                "value": "3" if status[0] == "closed" else "0",
                "tsCarCaptured": tsCarCapturedAccess,
            }
            self.data_fields.append(Field(windowField))

class TripDataResponse:
    def __init__(self, data):
        self.data_fields = []

        self.tripID = data["tripID"]

        self.averageElectricEngineConsumption = None
        if "averageElectricEngineConsumption" in data:
             self.averageElectricEngineConsumption = float(data["averageElectricEngineConsumption"]) / 10

        self.averageFuelConsumption = None
        if "averageFuelConsumption" in data:
            self.averageFuelConsumption = float(data["averageFuelConsumption"]) / 10

        self.averageSpeed = None
        if "averageSpeed" in data:
            self.averageSpeed = int(data["averageSpeed"])

        self.mileage = None
        if "mileage" in data:
            self.mileage = int(data["mileage"])

        self.startMileage = None
        if "startMileage" in data:
            self.startMileage = int(data["startMileage"])

        self.traveltime = None
        if "traveltime" in data:
            self.traveltime = int(data["traveltime"])

        self.timestamp = None
        if "timestamp" in data:
            self.timestamp = data["timestamp"]

        self.overallMileage = None
        if "overallMileage" in data:
            self.overallMileage = int(data["overallMileage"])


class Field:
    IDS = {
        "0x0": "UNKNOWN",
        "0x0101010002": "UTC_TIME_AND_KILOMETER_STATUS",
        "0x0203010001": "MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE",
        "0x0203010002": "MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE",
        "0x0203010003": "MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION",
        "0x0203010004": "MAINTENANCE_INTERVAL_TIME_TO_INSPECTION",
        "0x0203010006": "MAINTENANCE_INTERVAL_ALARM_INSPECTION",
        "0x0203010007": "MAINTENANCE_INTERVAL_MONTHLY_MILEAGE",
        "0x0203010005": "WARNING_OIL_CHANGE",
        "0x0204040001": "OIL_LEVEL_AMOUNT_IN_LITERS",
        "0x0204040002": "OIL_LEVEL_MINIMUM_WARNING",
        "0x0204040003": "OIL_LEVEL_DIPSTICKS_PERCENTAGE",
        "0x02040C0001": "ADBLUE_RANGE",
        "0x0301010001": "LIGHT_STATUS",
        "0x0301030001": "BRAKING_STATUS",
        "0x0301030005": "TOTAL_RANGE",
        "0x030103000A": "TANK_LEVEL_IN_PERCENTAGE",
        "0x0301040001": "LOCK_STATE_LEFT_FRONT_DOOR",
        "0x0301040002": "OPEN_STATE_LEFT_FRONT_DOOR",
        "0x0301040003": "SAFETY_STATE_LEFT_FRONT_DOOR",
        "0x0301040004": "LOCK_STATE_LEFT_REAR_DOOR",
        "0x0301040005": "OPEN_STATE_LEFT_REAR_DOOR",
        "0x0301040006": "SAFETY_STATE_LEFT_REAR_DOOR",
        "0x0301040007": "LOCK_STATE_RIGHT_FRONT_DOOR",
        "0x0301040008": "OPEN_STATE_RIGHT_FRONT_DOOR",
        "0x0301040009": "SAFETY_STATE_RIGHT_FRONT_DOOR",
        "0x030104000A": "LOCK_STATE_RIGHT_REAR_DOOR",
        "0x030104000B": "OPEN_STATE_RIGHT_REAR_DOOR",
        "0x030104000C": "SAFETY_STATE_RIGHT_REAR_DOOR",
        "0x030104000D": "LOCK_STATE_TRUNK_LID",
        "0x030104000E": "OPEN_STATE_TRUNK_LID",
        "0x030104000F": "SAFETY_STATE_TRUNK_LID",
        "0x0301040010": "LOCK_STATE_HOOD",
        "0x0301040011": "OPEN_STATE_HOOD",
        "0x0301040012": "SAFETY_STATE_HOOD",
        "0x0301050001": "STATE_LEFT_FRONT_WINDOW",
        "0x0301050003": "STATE_LEFT_REAR_WINDOW",
        "0x0301050005": "STATE_RIGHT_FRONT_WINDOW",
        "0x0301050007": "STATE_RIGHT_REAR_WINDOW",
        "0x0301050009": "STATE_DECK",
        "0x030105000B": "STATE_SUN_ROOF_MOTOR_COVER",
        "0x0301030006": "PRIMARY_RANGE",
        "0x0301030007": "PRIMARY_DRIVE",
        "0x0301030008": "SECONDARY_RANGE",
        "0x0301030009": "SECONDARY_DRIVE",
        "0x0301030002": "STATE_OF_CHARGE",
        "0x0301020001": "TEMPERATURE_OUTSIDE",
        "0x0202": "ACTIVE_INSTRUMENT_CLUSTER_WARNING",
    }

    def __init__(self, data):
        self.name = None
        self.id = data.get("id")
        self.unit = data.get("unit")
        self.value = data.get("value")
        self.measure_time = data.get("tsCarCaptured")
        self.send_time = data.get("tsCarSent")
        self.measure_mileage = data.get("milCarCaptured")
        self.send_mileage = data.get("milCarSent")
#        _LOGGER.error("DATAX: " + str(data))

        
        
        for field_id, name in self.IDS.items():
            if field_id == self.id:
                self.name = name
                break
        if self.name is None:
            # No direct mapping found - maybe we've at least got a text id
            self.name = data.get("textId")

    def __str__(self):
        str_rep = str(self.name) + " " + str(self.value)
        if self.unit is not None:
            str_rep += self.unit
        return str_rep


class Vehicle:
    def __init__(self):
        self.vin = ""
        self.csid = ""
        self.model = ""
        self.model_year = ""
        self.model_family = ""
        self.title = ""

    def parse(self, data):
        self.vin = data.get("vin")
        self.csid = data.get("csid")
        if data.get("vehicle") is not None and data.get("vehicle").get("media") is not None:
            self.model = data.get("vehicle").get("media").get("longName")
        if data.get("vehicle") is not None and data.get("vehicle").get("core") is not None:
            self.model_year = data.get("vehicle").get("core").get("modelYear")
        if data.get("nickname") is not None and len(data.get("nickname")) > 0:
            self.title = data.get("nickname")
        elif data.get("vehicle") is not None and data.get("vehicle").get("media") is not None:
            self.title = data.get("vehicle").get("media").get("shortName")

    def __str__(self):
        return str(self.__dict__)


class VehiclesResponse:
    def __init__(self):
        self.vehicles = []
        self.blacklisted_vins = 0

    def parse(self, data):
        for item in data.get("userVehicles"):
            vehicle = Vehicle()
            vehicle.parse(item)
            self.vehicles.append(vehicle)
