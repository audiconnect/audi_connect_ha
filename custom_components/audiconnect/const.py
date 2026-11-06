from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform

DOMAIN = "audiconnect"

CONF_VIN = "vin"
CONF_DEVICE_ID = "device_id"
CONF_CARNAME = "carname"
CONF_ACTION = "action"
CONF_CLIMATE_TEMP_F = "temp_f"
CONF_CLIMATE_TEMP_C = "temp_c"
CONF_CLIMATE_GLASS = "glass_heating"
CONF_CLIMATE_SEAT_FL = "seat_fl"
CONF_CLIMATE_SEAT_FR = "seat_fr"
CONF_CLIMATE_SEAT_RL = "seat_rl"
CONF_CLIMATE_SEAT_RR = "seat_rr"
CONF_CLIMATE_AT_UNLOCK = "climatisation_at_unlock"
CONF_CLIMATE_MODE = "climatisation_mode"
CONF_SCAN_INITIAL = "scan_initial"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_API_LEVEL = "api_level"
CONF_DURATION = "duration"
CONF_CHARGE_MODE = "charge_mode"
CONF_PROFILE_ID = "profile_id"
CONF_TARGET_SOC = "target_soc"

MIN_UPDATE_INTERVAL = 15
DEFAULT_UPDATE_INTERVAL = 15
UPDATE_SLEEP = 5
DEFAULT_API_LEVEL = 0

CONF_SPIN = "spin"
CONF_REGION = "region"
CONF_FILTER_VINS = "filter_vins"
CONF_REFRESH_AFTER_ACTION = "refresh_vehicle_data_after_action"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_UPDATE_SLEEP = "update_sleep"
AUTH0_REFRESH_TOKEN_PREFIX = "auth0:"
AUTH0_REDIRECT_URI = "http://localhost:8080/myaudi-callback"

REFRESH_VEHICLE_DATA_FAILED_EVENT = "refresh_failed"
REFRESH_VEHICLE_DATA_COMPLETED_EVENT = "refresh_completed"

REGION_EUROPE = "DE"
REGION_CANADA = "CA"
REGION_USA = "US"
REGION_CHINA = "CN"

REGIONS: dict[int, str] = {
    1: REGION_EUROPE,
    2: REGION_CANADA,
    3: REGION_USA,
    4: REGION_CHINA,
}

AUTH0_REGIONS: set[str] = {REGION_EUROPE, REGION_CANADA}


def uses_auth0(region: str | None) -> bool:
    """Return whether the region uses the interactive Auth0 login."""
    return (region or REGION_EUROPE) in AUTH0_REGIONS


def entry_uses_auth0(entry_data: Mapping[str, Any]) -> bool:
    """Return whether an entry should reauthenticate with Auth0."""
    refresh_token = entry_data.get(CONF_REFRESH_TOKEN)
    if isinstance(refresh_token, str) and refresh_token.startswith(
        AUTH0_REFRESH_TOKEN_PREFIX
    ):
        return True
    return uses_auth0(entry_data.get(CONF_REGION))


API_LEVELS: list[int] = [0, 1]

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
]

__all__ = [
    "API_LEVELS",
    "AUTH0_REFRESH_TOKEN_PREFIX",
    "AUTH0_REDIRECT_URI",
    "AUTH0_REGIONS",
    "CONF_ACTION",
    "CONF_API_LEVEL",
    "CONF_CARNAME",
    "CONF_CLIMATE_AT_UNLOCK",
    "CONF_CLIMATE_GLASS",
    "CONF_CLIMATE_MODE",
    "CONF_CLIMATE_SEAT_FL",
    "CONF_CLIMATE_SEAT_FR",
    "CONF_CLIMATE_SEAT_RL",
    "CONF_CLIMATE_SEAT_RR",
    "CONF_CLIMATE_TEMP_C",
    "CONF_CLIMATE_TEMP_F",
    "CONF_DEVICE_ID",
    "CONF_DURATION",
    "CONF_FILTER_VINS",
    "CONF_PASSWORD",
    "CONF_REFRESH_AFTER_ACTION",
    "CONF_REFRESH_TOKEN",
    "CONF_REGION",
    "CONF_SCAN_INITIAL",
    "CONF_SCAN_INTERVAL",
    "CONF_SPIN",
    "CONF_CHARGE_MODE",
    "CONF_PROFILE_ID",
    "CONF_TARGET_SOC",
    "CONF_UPDATE_SLEEP",
    "CONF_USERNAME",
    "CONF_VIN",
    "DEFAULT_API_LEVEL",
    "DEFAULT_UPDATE_INTERVAL",
    "DOMAIN",
    "MIN_UPDATE_INTERVAL",
    "PLATFORMS",
    "REFRESH_VEHICLE_DATA_COMPLETED_EVENT",
    "REFRESH_VEHICLE_DATA_FAILED_EVENT",
    "REGIONS",
    "UPDATE_SLEEP",
    "entry_uses_auth0",
    "uses_auth0",
]
