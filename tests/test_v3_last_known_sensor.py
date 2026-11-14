"""Passive V2-compatible values remain readable without pretending to be live.

Cloud receipt age cannot turn an old vehicle sample into fresh data, and
command readback and instantaneous measurements remain freshness-gated.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.audiconnect.v3.entities import (
    V3ReadOnlySensor,
    _reading_available,
)


def test_passive_last_known_held_without_marking_live():
    captured = (datetime.now(UTC) - timedelta(hours=4)).isoformat()
    row = {
        "value": 52,
        "captured": captured,
        "observed": datetime.now(UTC).isoformat(),
        "family": "cariad",
        "status": "readable_but_stale",
    }
    assert _reading_available(row, allow_last_known=True)
    assert not _reading_available(row)  # safety-critical binary/lock consumers
    fake = SimpleNamespace(
        vehicle=SimpleNamespace(readings={"stateOfCharge": row}),
        attribute={"capability": "charging", "id": "stateOfCharge"},
        _allow_last_known=True,
    )
    attrs = V3ReadOnlySensor.extra_state_attributes.fget(fake)
    assert attrs["vehicle_freshness"] == "stale_last_known"
    assert attrs["age_minutes"] >= 240


def test_unknown_or_missing_value_is_never_exposed():
    assert not _reading_available(None, allow_last_known=True)
    assert not _reading_available(
        {"value": None, "status": "verified"}, allow_last_known=True
    )
    assert not _reading_available(
        {"value": 1, "status": "api_error"}, allow_last_known=True
    )
    assert _reading_available(
        {"value": 0, "status": "readable_but_stale"}, allow_last_known=True
    )


def test_contract_separates_last_reported_state_from_live_measurements():
    from custom_components.audiconnect.v3.attribute_contracts import contract_for

    assert contract_for("state_of_charge")["display_last_known"] is True
    assert contract_for("range")["display_last_known"] is True
    for key in ("charging_state", "door_lock_status", "doors_trunk_status"):
        assert contract_for(key)["display_last_known"] is True
    for key in (
        "charging_power",
        "climatisation_state",
        "vehicle_reported_online",
        "remaining_climatisation_time",
    ):
        assert contract_for(key)["display_last_known"] is False


def test_v3_sensor_availability_uses_attribute_contract_not_all_sensors():
    from custom_components.audiconnect.v3.vehicle import V3Vehicle
    from datetime import timedelta

    vehicle = V3Vehicle(
        vin="WAUZZZ4M0MD123456",
        name="Audi",
        model="Q8",
        model_family="",
        country="DE",
    )
    stamp = (datetime.now(UTC) - timedelta(hours=4)).isoformat()
    vehicle.readings.update(
        {
            "stateOfCharge": {
                "value": 67,
                "captured": stamp,
                "status": "readable_but_stale",
                "family": "cariad",
            },
            "chargingState": {
                "value": "charging",
                "captured": stamp,
                "status": "readable_but_stale",
                "family": "cariad",
            },
        }
    )
    coordinator = SimpleNamespace(async_add_listener=lambda cb: None)
    passive = V3ReadOnlySensor(
        coordinator,
        vehicle,
        {
            "id": "stateOfCharge",
            "entity_key": "state_of_charge",
            "capability": "charging",
        },
    )
    active = V3ReadOnlySensor(
        coordinator,
        vehicle,
        {
            "id": "chargingState",
            "entity_key": "charging_state",
            "capability": "charging",
        },
    )
    assert passive.available and passive.native_value == 67
    assert passive.extra_state_attributes["vehicle_freshness"] == "stale_last_known"
    assert active.available and active.native_value == "charging"
    assert active.extra_state_attributes["vehicle_freshness"] == "stale_last_known"
    assert not _reading_available(vehicle.readings["chargingState"])
