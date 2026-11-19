"""Verify Home Assistant long-term statistics are available for numeric data.

Regression for upstream #878 / closed PR #882. Non-numeric and timestamp
sensors must not be marked as numeric measurements.
"""

from __future__ import annotations

import pytest
from homeassistant.components.sensor import SensorStateClass

from custom_components.audiconnect.sensor import SENSOR_DESCRIPTIONS


_DESCRIPTIONS = {description.key: description for description in SENSOR_DESCRIPTIONS}

NUMERIC_MEASUREMENTS = (
    "service_adblue_distance",
    "range",
    "hybrid_range",
    "service_inspection_time",
    "service_inspection_distance",
    "oil_change_time",
    "oil_change_distance",
    "oil_level",
    "max_charge_current",
    "charging_current_limit_a",
    "primary_engine_range",
    "secondary_engine_range",
    "primary_engine_range_percent",
    "secondary_engine_range_percent",
    "charging_power",
    "tank_level",
    "state_of_charge",
    "target_state_of_charge",
    "outdoor_temperature",
    "remaining_climatisation_time",
    "active_charging_profile_min_soc",
    "preheater_duration",
    "preheater_remaining",
)


@pytest.mark.parametrize("key", NUMERIC_MEASUREMENTS)
def test_numeric_measurement_has_statistics_state_class(key):
    assert _DESCRIPTIONS[key].state_class is SensorStateClass.MEASUREMENT, key


def test_mileage_keeps_total_increasing_semantics():
    assert _DESCRIPTIONS["mileage"].state_class is SensorStateClass.TOTAL_INCREASING


@pytest.mark.parametrize(
    "key",
    [
        "charging_state",
        "charging_mode",
        "car_type",
        "last_update_time",
        "charging_complete_time",
        "position_last_updated",
        "active_charging_profile_name",
    ],
)
def test_non_numeric_and_timestamp_sensors_are_not_marked_measurement(key):
    assert _DESCRIPTIONS[key].state_class is None
