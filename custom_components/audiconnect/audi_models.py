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
    def __init__(self, data):
        self.data_fields = []
        response = data.get("StoredVehicleDataResponse")
        if response is None:
            response = data.get("CurrentVehicleDataByRequestResponse")

        vehicle_data = response.get("vehicleData")
        if vehicle_data is None:
            return

        vehicle_data = vehicle_data.get("data")
        for raw_data in vehicle_data:
            raw_fields = raw_data.get("field")
            if raw_fields is None:
                continue
            for raw_field in raw_fields:
                self.data_fields.append(Field(raw_field))


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
