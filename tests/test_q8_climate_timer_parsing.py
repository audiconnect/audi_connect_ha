"""Climate timers are real car-sourced entities with local-clock semantics."""

from __future__ import annotations

from types import SimpleNamespace as NS
from custom_components.audiconnect.audi_models import VehicleDataResponse
from custom_components.audiconnect.sensor import (
    SENSOR_DESCRIPTIONS,
    _climatisation_timer_attrs,
)

TS = "2026-11-10T14:00:00Z"


def parsed(timers, timestamp=TS):
    raw = {
        "climatisationTimers": {
            "climatisationTimersStatus": {
                "value": {"carCapturedTimestamp": timestamp, "timers": timers}
            }
        }
    }
    return {s["name"]: s["value"] for s in VehicleDataResponse(raw).states}


def test_parses_single_and_recurring_climate_timers_without_timezone_guesses():
    s = parsed(
        [
            {
                "id": 1,
                "enabled": True,
                "singleTimer": {"startDateTimeLocal": "2026-11-11T06:30:00"},
            },
            {
                "id": 2,
                "enabled": True,
                "recurringTimer": {
                    "departureTimeLocal": "07:30",
                    "repetitionDays": ["monday", "friday"],
                },
            },
            {"id": 3, "enabled": False},
        ]
    )
    assert s["climatisationTimerCount"] == 3
    assert s["climatisationTimerEnabledCount"] == 2
    assert s["nextClimatisationTimerLocal"] == "2026-11-11T06:30:00"
    assert s["climatisationTimers"][1]["repetitionDays"] == ["monday", "friday"]
    attrs = _climatisation_timer_attrs(
        NS(climatisation_timers=s["climatisationTimers"])
    )
    assert attrs["start_timezone"] == "vehicle_local_not_inferred"


def test_no_fake_timestamp_when_api_block_is_incomplete():
    assert parsed([], timestamp=None) == {}
    assert "climatisationTimers" not in parsed("not-a-list")
    assert parsed([])["climatisationTimerEnabledCount"] == 0


def test_huge_or_unknown_timer_fields_are_bounded_and_redacted():
    values = [
        {
            "id": i,
            "enabled": True,
            "vin": "DO_NOT_COPY",
            "homePosition": {"lat": 1.0},
            "singleTimer": {"startDateTimeLocal": "2026-11-11T06:30:00"},
        }
        for i in range(100)
    ]
    result = parsed(values)
    assert len(result["climatisationTimers"]) == 12
    assert "DO_NOT_COPY" not in repr(result)
    assert "homePosition" not in repr(result)


def test_new_sensor_keys_are_distinct_and_public():
    by_key = {d.key: d for d in SENSOR_DESCRIPTIONS}
    assert (
        by_key["climatisation_timer_enabled_count"].capability == "climatisationTimers"
    )
    assert by_key["next_climatisation_timer_local"].capability == "climatisationTimers"
    assert (
        "vehicle local"
        not in (by_key["next_climatisation_timer_local"].name or "").lower()
    )
