"""Differential parity: both parsers receive the same CARIAD response.

This is fixture-backed evidence, not a physical car or HA recorder acceptance.
"""
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from custom_components.audiconnect.audi_models import VehicleDataResponse
from custom_components.audiconnect.v3.attribute_runtime import observe_read_only
from custom_components.audiconnect.v3.vehicle import V3Vehicle

from fixture_q8_etron import PAYLOAD


def wire(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: wire(v) for k, v in value.items()}
    if isinstance(value, list):
        return [wire(v) for v in value]
    return value


@pytest.mark.parametrize("key", [
    "stateOfCharge", "chargingState", "chargingPower", "actualChargeRate",
    "chargeType", "targetstateOfCharge", "plugState", "plugLockState",
    "externalPower", "plugledColor", "remainingChargingTime", "doorLockStatus",
])
def test_q8_cariad_raw_values_match_v2_and_v3(key):
    payload = wire(PAYLOAD)
    v2 = {row["name"]: row["value"] for row in VehicleDataResponse(payload).states}
    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")
    profile = SimpleNamespace(attribute_routes={}, attribute_evidence={})
    observe_read_only(car, profile, payload, datetime(2026, 8, 18, 21, 10, tzinfo=UTC))
    assert key in v2 and key in car.readings
    assert car.readings[key]["value"] == v2[key]
    if key != "doorLockStatus":
        assert car.readings[key]["captured"] is not None
