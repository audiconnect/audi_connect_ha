"""#722/#725: the location charging profile is what governs a charge, not the
global charging/settings target, and the two disagree whenever a profile is in
force. Also covers the charging timers, which were fetched and dropped.

Runs against a real selectivestatus payload from a 2022 Q8 Sportback e-tron
rather than an invented one, because the bug was that the shipped parsing
believed a schema the car does not use. Home coordinates are scrubbed in the
fixture; every other value is verbatim from the car.

Composes with the pytest harness from #815 (no network).
"""

from __future__ import annotations

import copy

import pytest

from custom_components.audiconnect.audi_models import VehicleDataResponse

from tests.fixture_q8_etron import PAYLOAD


def states_of(payload):
    """Parse a payload and return its states as a plain name -> value dict, which is
    exactly what update_vehicle_statusreport copies onto vehicle.state."""
    resp = VehicleDataResponse(payload)
    return {s["name"]: s["value"] for s in resp.states}


@pytest.fixture
def payload():
    return copy.deepcopy(PAYLOAD)


# --- the governing target ---------------------------------------------------------


def test_active_profile_target_soc_is_the_governing_number(payload):
    """The car sits in profile 1 (60%) while the global setting says 70%. The whole
    point of the change: expose the 60, which is what the car obeys."""
    states = states_of(payload)
    assert states["activeChargingProfileTargetSoc"] == 60
    assert states["activeChargingProfileName"] == "Home"
    assert states["activeChargingProfileId"] == 1


def test_global_target_still_parsed_and_differs(payload):
    """Negative control for the test above: the pre-existing global sensor keeps
    reporting 70, so a test that read 60 from the wrong field would fail here."""
    states = states_of(payload)
    assert states["targetstateOfCharge"] == 70
    assert states["targetstateOfCharge"] != states["activeChargingProfileTargetSoc"]


def test_active_profile_follows_vehicle_position(payload):
    """Move the car to the other profile and the governing target must follow it."""
    value = payload["chargingProfiles"]["chargingProfilesStatus"]["value"]
    value["vehiclePositionedInProfileID"] = 2

    states = states_of(payload)
    assert states["activeChargingProfileId"] == 2
    assert states["activeChargingProfileName"] == "Work"
    assert states["activeChargingProfileTargetSoc"] == 100


def test_min_soc_exposed(payload):
    states = states_of(payload)
    assert states["activeChargingProfileMinSoc"] == 2


# --- profile list -----------------------------------------------------------------


def test_profile_summary_lists_all_profiles(payload):
    states = states_of(payload)
    assert states["chargingProfileCount"] == 2
    names = [p["name"] for p in states["chargingProfiles"]]
    assert names == ["Home", "Work"]


def test_profile_summary_omits_position(payload):
    """position is the owner's home coordinates. Attributes land in the recorder
    database and in diagnostics downloads, so the summary must not carry them."""
    states = states_of(payload)
    for profile in states["chargingProfiles"]:
        assert "position" not in profile


# --- preferred charging window ----------------------------------------------------


def test_preferred_charging_window(payload):
    """The per-location time band a smart tariff writes when it moves a charge."""
    states = states_of(payload)
    assert states["preferredChargingTimeStart"] == "23:13"
    assert states["preferredChargingTimeEnd"] == "02:09"
    assert states["preferredChargingTimeEnabled"] is False


def test_preferred_window_prefers_the_enabled_one(payload):
    """With several windows the enabled one wins, not merely the first."""
    profiles = payload["chargingProfiles"]["chargingProfilesStatus"]["value"]["profiles"]
    profiles[0]["preferredChargingTimes"] = [
        {"id": 1, "enabled": False, "startTimeLocal": "23:13", "endTimeLocal": "02:09"},
        {"id": 2, "enabled": True, "startTimeLocal": "01:30", "endTimeLocal": "05:30"},
    ]

    states = states_of(payload)
    assert states["preferredChargingTimeStart"] == "01:30"
    assert states["preferredChargingTimeEnabled"] is True


# --- timers -----------------------------------------------------------------------


def test_timers_parsed(payload):
    states = states_of(payload)
    assert len(states["chargingTimers"]) == 5
    assert states["chargingTimers"][0]["departureTimeLocal"] == "11:05"
    assert states["chargingTimers"][0]["repetitionDays"] == ["thursday"]


def test_no_enabled_timers_on_this_car(payload):
    """Every timer is currently off, so the count is 0 and no next departure is set."""
    states = states_of(payload)
    assert states["chargingTimerEnabledCount"] == 0
    assert "nextChargingTimerDeparture" not in states


def test_enabled_timer_surfaces_next_departure(payload):
    """Positive control for the test above: enabling one must make both appear."""
    timers = payload["chargingTimers"]["chargingTimersStatus"]["value"]["timers"]
    timers[0]["enabled"] = True

    states = states_of(payload)
    assert states["chargingTimerEnabledCount"] == 1
    assert states["nextChargingTimerDeparture"] == "11:05"


# --- absence and malformed input --------------------------------------------------


def test_missing_profile_block_is_not_an_error(payload):
    """departureProfiles/departureTimers are requested but not returned for this
    model, so absent blocks must parse to nothing rather than raise."""
    del payload["chargingProfiles"]
    del payload["chargingTimers"]

    states = states_of(payload)
    assert "activeChargingProfileTargetSoc" not in states
    assert "chargingTimers" not in states
    # the rest of the payload still parses
    assert states["stateOfCharge"] == 69


def test_error_object_instead_of_value_is_not_an_error(payload):
    """CARIAD answers 200 with an error object per job during an outage."""
    payload["chargingProfiles"] = {"error": {"message": "unavailable"}}

    states = states_of(payload)
    assert "activeChargingProfileTargetSoc" not in states
    assert states["stateOfCharge"] == 69


def test_position_pointing_at_an_unknown_profile(payload):
    """If the car reports a profile id that isn't in the list, the id is still
    exposed but no target is invented for it."""
    payload["chargingProfiles"]["chargingProfilesStatus"]["value"][
        "vehiclePositionedInProfileID"
    ] = 99

    states = states_of(payload)
    assert states["activeChargingProfileId"] == 99
    assert "activeChargingProfileTargetSoc" not in states
    assert states["chargingProfileCount"] == 2
