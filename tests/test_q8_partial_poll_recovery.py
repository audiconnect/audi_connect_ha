"""One bad CARIAD job cannot erase usable Q8 data or reset last update."""
import asyncio
import copy
from datetime import UTC, datetime

from custom_components.audiconnect.audi_connect_account import AudiConnectVehicle
from custom_components.audiconnect.audi_models import VehicleDataResponse
from tests.fixture_q8_etron import PAYLOAD


class Vehicle:
    vin = "TESTVIN00000000001"
    csid = "test"
    title = "Q8"
    model = "Q8"
    model_year = "2025"
    model_family = "PHEV"


class Service:
    def __init__(self):
        self.payload = copy.deepcopy(PAYLOAD)

    async def get_stored_vehicle_data(self, vin):
        return VehicleDataResponse(self.payload)


def test_partial_job_error_preserves_good_readings_and_last_real_timestamp():
    service = Service()
    car = AudiConnectVehicle(service, Vehicle())
    asyncio.run(car.update_vehicle_statusreport())
    old_fields = car._vehicle.fields.copy()
    old_time = car._vehicle.state["last_update_time"]
    assert old_fields and old_time.year > 2020

    service.payload = {
        "charging": {"chargingStatus": {"error": {"message": "gateway"}}},
        "userCapabilities": {"capabilitiesStatus": {
            "value": [{"id": "charging", "status": []}]
        }},
    }
    asyncio.run(car.update_vehicle_statusreport())
    assert car._vehicle.fields == old_fields
    assert car._vehicle.state["last_update_time"] == old_time
    assert car._vehicle.state["userCapabilities"] == ["charging"]


def test_entirely_errored_response_keeps_all_old_values():
    service = Service()
    car = AudiConnectVehicle(service, Vehicle())
    asyncio.run(car.update_vehicle_statusreport())
    old_state = car._vehicle.state.copy()
    old_fields = car._vehicle.fields.copy()
    service.payload = {
        "access": {"accessStatus": {"error": {"message": "temporary outage"}}}
    }
    asyncio.run(car.update_vehicle_statusreport())
    assert car._vehicle.fields == old_fields
    assert car._vehicle.state == old_state
