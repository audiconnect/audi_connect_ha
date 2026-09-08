"""The climatisation settings block.

Everything here was already arriving from the car and being dropped. The target
temperature matters most: the climate entity held it locally and restored it
across restarts, on the belief that the API did not report it. It does.
"""

from __future__ import annotations

import copy

import pytest

from custom_components.audiconnect.audi_models import VehicleDataResponse

from tests.fixture_q8_etron import PAYLOAD


def states_of(payload):
    return {s["name"]: s["value"] for s in VehicleDataResponse(payload).states}


@pytest.fixture
def states():
    return states_of(copy.deepcopy(PAYLOAD))


def test_the_target_temperature_is_reported_by_the_car(states):
    """The claim this corrects: the climate entity was built around the API not
    reporting a target temperature."""
    assert states["climatisationTargetTemperatureC"] == 15.5
    assert states["climatisationTargetTemperatureF"] == 59


def test_the_car_stores_a_half_degree_the_write_cannot_send(states):
    """The readback is finer than the api_level 1 write, which truncates with
    int(temp_c). Worth pinning so the two are not confused again."""
    import inspect

    from custom_components.audiconnect import audi_services

    assert states["climatisationTargetTemperatureC"] % 1 != 0
    assert "int(temp_c)" in inspect.getsource(
        audi_services.AudiService.start_climate_control
    )


def test_the_settings_flags_are_parsed(states):
    assert states["climatisationWindowHeatingEnabled"] is False
    assert states["climatisationAtUnlock"] is False
    assert states["climatisationWithoutExternalPower"] is True


def test_only_the_zones_the_car_reports_appear(states):
    """This car reports two front zones and no rear ones, so the rear keys must
    be absent rather than defaulted to False."""
    assert states["climatisationZoneFrontLeft"] is False
    assert states["climatisationZoneFrontRight"] is False
    assert "climatisationZoneRearLeft" not in states
    assert "climatisationZoneRearRight" not in states


def test_a_reported_rear_zone_is_picked_up():
    """Control for the test above: the absence is the car's, not the parser's."""
    payload = copy.deepcopy(PAYLOAD)
    payload["climatisation"]["climatisationSettings"]["value"][
        "zoneRearLeftEnabled"
    ] = True
    assert states_of(payload)["climatisationZoneRearLeft"] is True


def test_a_missing_settings_block_yields_nothing(states):
    payload = copy.deepcopy(PAYLOAD)
    del payload["climatisation"]["climatisationSettings"]
    bare = states_of(payload)
    assert "climatisationTargetTemperatureC" not in bare
    # control: the rest of the climatisation block still parses
    assert bare["climatisationState"] == "off"


# --- the climate entity now prefers the car's value --------------------------------


class StubCoordinator:
    last_update_success = True

    def __init__(self):
        self.account = type("A", (), {"connection": None})()

    async def async_request_refresh(self):
        pass


def climate_with(reported):
    from custom_components.audiconnect.climate import AudiClimate

    vehicle = type(
        "V",
        (),
        {
            "vin": "WAUZZZ00000000001",
            "climatisation_state": "off",
            "climatisation_target_temperature": reported,
        },
    )()
    entity = AudiClimate(StubCoordinator(), vehicle)
    entity.async_write_ha_state = lambda: None
    return entity


def test_the_entity_shows_what_the_car_reports():
    assert climate_with(15.5).target_temperature == 15.5


def test_the_local_value_is_only_a_fallback():
    """A car that reports nothing still gets a usable default rather than an
    empty thermostat."""
    assert climate_with(None).target_temperature == 21.0
