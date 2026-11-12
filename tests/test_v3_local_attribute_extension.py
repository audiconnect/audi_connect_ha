"""Exercise a new attribute from the facade through HA projection and restart."""
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.audiconnect.v3.custom_attributes import attributes_for, validate_definition
from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
from custom_components.audiconnect.v3.engine import V3Engine
from custom_components.audiconnect.v3.entities import V3ReadOnlySensor
from custom_components.audiconnect.v3.profile_store import restore_profile
from custom_components.audiconnect.v3.registry import CapabilityRegistry
from custom_components.audiconnect.v3.transport import V3Response
from custom_components.audiconnect.v3.vehicle import V3Vehicle

ROOT = Path(__file__).resolve().parents[1] / "custom_components/audiconnect/v3"
IDENT = "user.attribute.test_pressure"
ROUTE = "user.read.test_pressure"
DEFINITION = {"id": IDENT, "capability": "test_group", "name": "Test pressure",
              "type": "number", "unit": "bar", "device_class": "pressure",
              "state_class": "measurement", "precision": 1}
CANDIDATE = {"id": ROUTE, "attribute": IDENT, "family": "cariad", "method": "GET",
             "path": "/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=example",
             "response_path": "/example/value", "capture_path": "/example/stamp",
             "attribute_definition": DEFINITION}


@pytest.mark.asyncio
async def test_new_local_sensor_needs_evidence_and_survives_restart():
    catalog = CapabilityRegistry.from_json_file(ROOT / "full_catalog.json")
    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")
    profile = DevelopmentProfile(catalog, car.context)
    now = datetime.now(UTC)
    request = AsyncMock(return_value=V3Response(200, {"example": {"value": 0, "stamp": now.isoformat()}}, now))
    engine = V3Engine(SimpleNamespace(), SimpleNamespace(entry_id="test"), catalog,
                      auth=SimpleNamespace(), transport=SimpleNamespace(request=request),
                      storage=SimpleNamespace(async_save=AsyncMock()))
    engine.vehicles[car.vin.lower()] = car
    engine.profiles[car.vin.lower()] = profile
    assert await engine.add_attribute_route(car.vin, CANDIDATE) == ROUTE
    assert IDENT not in profile.attribute_routes
    request.assert_not_awaited()
    with pytest.raises(ValueError):
        await engine.activate_attribute_route(car.vin, IDENT, ROUTE)
    result = await engine.test_attribute_route(car.vin, IDENT, ROUTE)
    assert result["result"] == "verified" and result["value"] == 0
    assert IDENT not in car.readings and IDENT not in profile.attribute_evidence
    await engine.activate_attribute_route(car.vin, IDENT, ROUTE)
    request.assert_awaited_once_with("cariad", "GET", CANDIDATE["path"].format(VIN=car.vin))
    restored = restore_profile(catalog, car.context, profile.snapshot())
    assert restored.attribute_routes[IDENT] == ROUTE
    # The next scheduled read publishes the selected mapping, not the test.
    engine._record_attribute_response(car, profile, IDENT, ROUTE, [CANDIDATE["response_path"]], request.return_value)
    field = attributes_for(restored)[IDENT]
    coordinator = SimpleNamespace(engine=engine, last_update_success=True)
    sensor = V3ReadOnlySensor(coordinator, car, field)
    assert sensor.unique_id == car.vin.lower() + "_sensor_v3_custom_test_pressure"
    assert sensor.native_value == 0 and sensor.available
    assert sensor.native_unit_of_measurement == "bar"
    await engine.disable_attribute_route(car.vin, IDENT)
    assert not sensor.available
    assert IDENT in restore_profile(catalog, car.context, profile.snapshot()).attribute_disabled
    await engine.activate_attribute_route(car.vin, IDENT, ROUTE)
    assert sensor.available
    profile.attribute_route_evidence[IDENT][ROUTE]["outcome"] = "api_error"
    assert restore_profile(catalog, car.context, profile.snapshot()).attribute_routes[IDENT] == ROUTE


@pytest.mark.parametrize("override", [
    {"id": "stateOfCharge"}, {"unit": "km"}, {"state_class": "total_increasing"},
    {"type": "boolean", "display_last_known": True}, {"precision": -1},
])
def test_invalid_local_contract_is_rejected(override):
    with pytest.raises(ValueError):
        validate_definition({**DEFINITION, **override})
