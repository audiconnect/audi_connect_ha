"""Optional parking address is isolated from Audi status and private diagnostics."""

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.audiconnect.v3.parking import (
    GEOCODING_ENDPOINT,
    REVERSE_GEOCODING,
    geocoding_endpoint,
    geocoding_point,
    valid_geocoding_endpoint,
)
from custom_components.audiconnect.v3.status_engine import StatusEngine

ENDPOINT = "https://geocoder.example.invalid/reverse"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://geocoder.example.invalid/reverse",
        "https://nominatim.openstreetmap.org/reverse",
        "https://NOMINATIM.OPENSTREETMAP.ORG./reverse",
        "https://nominatim.openstreetmap。org/reverse",
        "https://ＮＯＭＩＮＡＴＩＭ.openstreetmap.org/reverse",
        "https://%6eominatim.openstreetmap.org/reverse",
        "https://name:secret@geocoder.example.invalid/reverse",
        ENDPOINT + "?key=secret",
        ENDPOINT + "#fragment",
        "https://geocoder.example.invalid/",
    ],
)
def test_requires_authorized_https_reverse_endpoint(url):
    assert not valid_geocoding_endpoint(url)


def test_opt_in_and_coordinate_precision():
    assert valid_geocoding_endpoint(ENDPOINT)
    entry = NS(options={GEOCODING_ENDPOINT: ENDPOINT})
    assert geocoding_endpoint(entry) is None
    entry.options[REVERSE_GEOCODING] = True
    assert geocoding_endpoint(entry) == ENDPOINT
    assert geocoding_point({"latitude": 0, "longitude": 0}) == (0, 0)
    assert geocoding_point({"latitude": 51.123456, "longitude": 4.56789}) == (
        51.123,
        4.568,
    )
    assert geocoding_point({"latitude": 91, "longitude": 0}) is None


def status():
    engine = StatusEngine(
        hass=NS(data={}),
        entry=NS(options={REVERSE_GEOCODING: True, GEOCODING_ENDPOINT: ENDPOINT}),
        auth=None,
        transport=None,
        storage=None,
        vehicles={},
        profiles={},
        discover=None,
        known_inventory=None,
        operation_request=None,
        api_record=None,
        notify=Mock(),
    )
    engine.parking_read_allowed = lambda car, **kwargs: True
    engine._parking_address_endpoint = ENDPOINT
    return engine


@pytest.mark.asyncio
async def test_address_is_only_for_current_point_and_current_consent(monkeypatch):
    engine = status()
    car = NS(
        vin="example",
        inventory_present=True,
        position={"latitude": 51.123456, "longitude": 4.56789},
    )
    engine.vehicles[car.vin] = car
    point = geocoding_point(car.position)
    reverse = AsyncMock(return_value="Approximate place")
    monkeypatch.setattr(
        "custom_components.audiconnect.v3.parking.reverse_address", reverse
    )
    await engine._collect_parking_address(car, ENDPOINT, point)
    reverse.assert_awaited_once_with(engine.hass, ENDPOINT, point)
    assert engine.parking_address(car) == "Approximate place"
    engine._notify.assert_called_once()
    car.position["latitude"] = 52
    assert engine.parking_address(car) is None
    car.position["latitude"] = 51.123456
    engine.entry.options[REVERSE_GEOCODING] = False
    assert engine.parking_address(car) is None
    engine._start_parking_address()
    assert not engine._parking_address_cache
    assert engine._parking_address_endpoint is None
    reverse.reset_mock()
    await engine._collect_parking_address(car, ENDPOINT, point)
    reverse.assert_not_awaited()
    assert not engine._parking_address_cache


@pytest.mark.asyncio
async def test_failed_lookup_does_not_publish_or_change_native_state(monkeypatch):
    engine = status()
    reverse = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "custom_components.audiconnect.v3.parking.reverse_address", reverse
    )
    car = NS(
        vin="example", inventory_present=True, position={"latitude": 51, "longitude": 4}
    )
    engine.vehicles[car.vin] = car
    await engine._collect_parking_address(car, ENDPOINT, (51, 4))
    assert not engine._parking_address_cache
    assert engine._parking_address_retry_at > 0
    assert engine.last_cloud_poll_success is None
    engine._notify.assert_not_called()


def test_separate_address_sensor_uses_existing_status_owner():
    from custom_components.audiconnect.v3.entities import V3ParkingAddressSensor

    engine = status()
    car = NS(vin="example", readings={}, inventory_present=True, position=None)
    engine.vehicles[car.vin] = car
    sensor = V3ParkingAddressSensor(NS(engine=NS(status=engine)), car)
    assert sensor.unique_id == "example_sensor_parking_address"
    assert not sensor.available
    car.position = {"latitude": 51, "longitude": 4}
    engine._parking_address_cache[(51, 4)] = "Approximate place"
    assert sensor.available
    assert sensor.native_value == "Approximate place"
    assert sensor.extra_state_attributes["address_precision"] == "approximate"


@pytest.mark.asyncio
async def test_reverse_lookup_sends_only_rounded_point_and_never_redirects(monkeypatch):
    from custom_components.audiconnect.v3.parking import reverse_address

    async def chunks(_size):
        yield b'{"display_name": "Approximate address", "private": "not retained"}'

    response = NS(status=200, content=NS(iter_chunked=chunks))
    from unittest.mock import MagicMock

    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    session = NS(get=Mock(return_value=context))
    monkeypatch.setattr(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        lambda hass: session,
    )
    assert await reverse_address(None, ENDPOINT, (51.123456, 4.56789)) == (
        "Approximate address"
    )
    session.get.assert_called_once()
    args, kwargs = session.get.call_args
    assert args == (ENDPOINT,)
    assert kwargs["params"] == {"lat": "51.123", "lon": "4.568", "format": "jsonv2"}
    assert kwargs["allow_redirects"] is False
    assert set(kwargs["headers"]) == {"User-Agent"}
    session.get.reset_mock()
    assert await reverse_address(None, ENDPOINT, (999, 0)) is None
    assert (
        await reverse_address(
            None, "https://nominatim.openstreetmap.org/reverse", (51, 4)
        )
        is None
    )
    session.get.assert_not_called()


@pytest.mark.asyncio
async def test_queued_lookup_does_not_send_or_publish_after_vehicle_changes(
    monkeypatch,
):
    engine = status()
    car = NS(
        vin="example", inventory_present=True, position={"latitude": 51, "longitude": 4}
    )
    engine.vehicles[car.vin] = car
    reverse = AsyncMock(return_value="Approximate place")
    monkeypatch.setattr(
        "custom_components.audiconnect.v3.parking.reverse_address", reverse
    )
    engine.parking_read_allowed = lambda car, **kwargs: False
    await engine._collect_parking_address(car, ENDPOINT, (51, 4))
    reverse.assert_not_awaited()
    engine.parking_read_allowed = lambda car, **kwargs: True

    async def move_before_response(*args):
        car.position["latitude"] = 52
        return "Old address"

    reverse.side_effect = move_before_response
    await engine._collect_parking_address(car, ENDPOINT, (51, 4))
    reverse.assert_awaited_once()
    assert not engine._parking_address_cache
    assert engine.parking_address(car) is None
    engine._notify.assert_not_called()
