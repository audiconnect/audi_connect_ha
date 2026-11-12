"""Product UI rationalisation regressions."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from custom_components.audiconnect.v3.product_contract import (
    CORE_STATUS_KINDS, retired_pilot_entity, account_cloud_refresh_vin,
)
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3.entities import V3StatusSensor, V3ReadOnlySensor
from custom_components.audiconnect.v3.command_policy import eligible_operation
from test_v3_clean_runtime import engine_for, status

VIN = "wauzzz4m0md123456"


def test_retired_ids_are_exact_and_v2_ids_are_preserved():
    assert CORE_STATUS_KINDS == ("cloud", "age", "freshness", "discovery")
    assert retired_pilot_entity(VIN + "_sensor_v3_climate_capability")
    assert retired_pilot_entity(VIN + "_sensor_v3_poll_status")
    assert not retired_pilot_entity(VIN + "_sensor_climatisation_state")
    assert not retired_pilot_entity(VIN + "_button_refresh_vehicle_data")
    assert not retired_pilot_entity("some_other_sensor_v3_poll_status")
    assert account_cloud_refresh_vin({VIN: None, "zzzzzzzzzzzzzzzzz": None}) == VIN


@pytest.mark.asyncio
async def test_stale_capture_does_not_trigger_another_status_get():
    reply = status()
    reply.data["climatisation"]["climatisationStatus"]["value"]["carCapturedTimestamp"] = (
        datetime.now(UTC) - timedelta(hours=3)).isoformat()
    engine, transport, _ = engine_for(reply)
    await engine.poll()
    assert transport.request_count == 1
    assert engine.last_cloud_poll_succeeded is True


@pytest.mark.asyncio
async def test_cloud_health_is_false_without_successful_response():
    engine, transport, _ = engine_for(status(http=429, value="invalid"))
    await engine.poll()
    assert engine.last_cloud_poll_succeeded is False
    assert engine.last_cloud_poll_success is None
    listener = NS(async_update_listeners=lambda: None,
                  async_set_updated_data=lambda _: pytest.fail("local update changed cloud health"))
    engine.entry.runtime_data = NS(coordinator=listener)
    engine._notify_discovery_change()
    assert engine.last_cloud_poll_succeeded is False


def test_manufacturer_model_year_and_missing_drivetrain():
    car = V3Vehicle.from_graphql({"vin": VIN, "nickname": "Q8",
        "vehicle": {"media": {"longName": "Audi A4"}, "core": {"modelYear": 2021}}}, "DE")
    assert car.model_year == "2021"
    car.advertised_capabilities.add("remoteEngineStart")
    assert eligible_operation(car, NS(uses_auth0=True, service=NS(_spin="test")),
                              "remote", "engine_start") is None
