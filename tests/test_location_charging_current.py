"""Tests for the location charging profile AC current update."""

import pytest

from custom_components.audiconnect.audi_services import (
    MAX_CHARGING_CURRENT_OPTIONS,
    build_profile_current_update,
)

# Shape as reported by a 2026 SQ6 e-tron (position redacted).
PROFILES = {
    "vehiclePositionedInProfileID": 1,
    "profiles": [
        {
            "uuid": "05efb496-340c-43a3-add5-15b8146053d8",
            "id": 1,
            "name": "Home",
            "maxChargingCurrent": "reduced",
            "minSOC_pct": 2,
            "options": {
                "autoUnlockPlugWhenCharged": "invalid",
                "usePreferredChargingTimes": False,
                "smartChargingEnabled": True,
                "usePrivateCurrentEnabled": False,
            },
            "preferredChargingTimes": [
                {"id": 1, "enabled": False, "startTime": "14:40", "endTime": "14:40"}
            ],
            "timers": None,
            "position": {"lat": 0.0, "lon": 0.0, "alt": 0, "gpsRadius_m": 100},
        }
    ],
}


def test_options_are_the_values_the_app_writes():
    assert MAX_CHARGING_CURRENT_OPTIONS == ("max", "reduced")


def test_changes_only_max_charging_current_in_the_active_profile():
    profile_id, body = build_profile_current_update(PROFILES, None, "max")
    assert profile_id == 1
    sent = body["profile"]
    assert sent["maxChargingCurrent"] == "max"
    original = PROFILES["profiles"][0]
    for key, value in original.items():
        if key != "maxChargingCurrent":
            assert sent[key] == value
    # The input is not mutated.
    assert original["maxChargingCurrent"] == "reduced"


def test_explicit_profile_id():
    profile_id, body = build_profile_current_update(PROFILES, 1, "reduced")
    assert profile_id == 1
    assert body["profile"]["maxChargingCurrent"] == "reduced"


def test_rejects_unknown_value():
    with pytest.raises(ValueError):
        build_profile_current_update(PROFILES, None, "maximum")


def test_rejects_missing_profile():
    with pytest.raises(ValueError):
        build_profile_current_update(PROFILES, 7, "max")
