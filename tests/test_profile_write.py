"""#722: set the location charging profile's target SoC — the value that
actually governs where a charge stops at that location. The write is a
read-modify-write (the CARIAD BFF PUT replaces the whole profile), so the one
field that must change has to change and every other field, the home-location
coordinates included, must survive untouched. That is what these pin, against a
real profile payload captured from the car.

The pure core (build_profile_update) is tested, so no HTTP boundary is mocked
and there is no mock-verifies-mock.

Composes with the pytest harness from #815 (no network).
"""

from __future__ import annotations

import copy

import pytest

from custom_components.audiconnect.audi_services import build_profile_update

from tests.fixture_q8_etron import PAYLOAD


@pytest.fixture
def value():
    """chargingProfiles.chargingProfilesStatus.value, as the car reports it."""
    return copy.deepcopy(PAYLOAD["chargingProfiles"]["chargingProfilesStatus"]["value"])


# --- the change itself ------------------------------------------------------------


def test_changes_only_the_target(value):
    original = copy.deepcopy(value["profiles"][0])  # Home, id 1
    resolved_id, body = build_profile_update(value, 1, 65)

    sent = body["profile"]
    assert resolved_id == 1
    assert sent["targetSOC_pct"] == 65
    # every OTHER field is byte-for-byte what the car reported
    for key in original:
        if key != "targetSOC_pct":
            assert sent[key] == original[key], f"{key} was altered"


def test_position_is_preserved(value):
    """position binds the profile to a location; dropping it would unbind it."""
    original_pos = value["profiles"][0]["position"]
    _, body = build_profile_update(value, 1, 70)
    assert body["profile"]["position"] == original_pos
    assert "position" in body["profile"]


def test_body_is_a_single_wrapped_profile(value):
    """The Audi PUT wraps ONE profile under `profile`, not the list."""
    _, body = build_profile_update(value, 1, 55)
    assert set(body) == {"profile"}
    assert isinstance(body["profile"], dict)
    assert body["profile"]["id"] == 1


def test_no_extra_or_missing_keys(value):
    """RMW must not invent a field (e.g. maxChargingCurrent this car omits) nor
    drop one. The key set is exactly what came back."""
    original_keys = set(value["profiles"][0])
    _, body = build_profile_update(value, 1, 60)
    assert set(body["profile"]) == original_keys


# --- profile selection ------------------------------------------------------------


def test_selects_by_id(value):
    _, body = build_profile_update(value, 2, 80)
    assert body["profile"]["id"] == 2
    assert body["profile"]["name"] == "Work"
    assert body["profile"]["targetSOC_pct"] == 80


def test_none_targets_the_parked_profile(value):
    """profile_id None uses vehiclePositionedInProfileID (1 here)."""
    assert value["vehiclePositionedInProfileID"] == 1
    resolved_id, body = build_profile_update(value, None, 75)
    assert resolved_id == 1
    assert body["profile"]["id"] == 1
    assert body["profile"]["targetSOC_pct"] == 75


def test_unknown_profile_id_raises(value):
    with pytest.raises(ValueError, match="No charging profile with id 99"):
        build_profile_update(value, 99, 80)


# --- validation -------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, 10, 19, 101, 105])
def test_target_out_of_range_raises(value, bad):
    with pytest.raises(ValueError, match="between 20 and 100"):
        build_profile_update(value, 1, bad)


@pytest.mark.parametrize("ok", [20, 55, 65, 100])
def test_target_in_range_accepted(value, ok):
    _, body = build_profile_update(value, 1, ok)
    assert body["profile"]["targetSOC_pct"] == ok


def test_source_value_is_not_mutated(value):
    """The helper must not edit the fetched payload in place; only the copy that
    goes on the wire carries the new value."""
    before = copy.deepcopy(value)
    build_profile_update(value, 1, 65)
    assert value == before
