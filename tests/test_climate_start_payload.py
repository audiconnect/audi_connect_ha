"""#771: on API level 1 some vehicles reject a settings payload outright, because
they have no comfort climatisation profile to apply it to. When the caller asks
for climatisation without supplying any settings, send no body and let the car
use the settings it already holds, which is what the myAudi app does.

No network: the API layer is replaced with a recorder.
"""

from __future__ import annotations

import asyncio
import json

from custom_components.audiconnect.audi_services import AudiService


class _RecordingAPI:
    """Stands in for AudiAPI and records what the service tried to send."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def use_token(self, token) -> None:  # noqa: D102
        pass

    async def request(self, method, url, headers=None, data=None, **kwargs):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "data": data}
        )
        return {"action": {"actionId": "test-action"}}


def _service(api_level: int, country: str = "DE") -> tuple[AudiService, _RecordingAPI]:
    api = _RecordingAPI()
    service = AudiService(api, country, None, api_level)
    service._bearer_token_json = {"access_token": "test-token"}
    service.vwToken = {"access_token": "test-token"}

    async def _succeeded(*args, **kwargs):
        return None

    # The follow-up poll is a separate concern; this test is about the payload.
    service.check_request_succeeded = _succeeded
    return service, api


def _start(service: AudiService, **kwargs) -> None:
    asyncio.run(service.start_climate_control("WAUZZZ00000000000", **kwargs))


def test_no_settings_sends_no_body() -> None:
    # The Q6 e-tron case from #771: nothing supplied, so nothing is imposed.
    service, api = _service(api_level=1)
    _start(service)

    assert len(api.calls) == 1
    assert api.calls[0]["data"] is None


def test_supplied_temperature_still_sends_a_body() -> None:
    service, api = _service(api_level=1)
    _start(service, temp_c=22)

    body = json.loads(api.calls[0]["data"])
    assert body["targetTemperature"] == 22
    assert body["targetTemperatureUnit"] == "celsius"


def test_a_single_supplied_setting_is_enough_to_send_a_body() -> None:
    # Asking for one seat is still asking for something, so the vehicle's own
    # settings must not silently win.
    service, api = _service(api_level=1)
    _start(service, seat_fl=True)

    body = json.loads(api.calls[0]["data"])
    assert body["zoneFrontLeftEnabled"] is True
    assert body["zoneFrontRightEnabled"] is False


def test_climatisation_mode_defaults_instead_of_serialising_null() -> None:
    # The service call leaves climatisation_mode unset unless the user picks one,
    # which used to put a literal null on the wire.
    service, api = _service(api_level=1)
    _start(service, temp_c=21)

    body = json.loads(api.calls[0]["data"])
    assert body["climatisationMode"] == "comfort"


def test_explicitly_disabling_everything_still_sends_a_body() -> None:
    # All-false is a real instruction, not an absence of one.
    service, api = _service(api_level=1)
    _start(
        service,
        glass_heating=False,
        seat_fl=False,
        seat_fr=False,
        seat_rl=False,
        seat_rr=False,
        climatisation_at_unlock=False,
    )

    body = json.loads(api.calls[0]["data"])
    assert body["windowHeatingEnabled"] is False
    assert body["zoneFrontLeftEnabled"] is False


def test_api_level_0_zone_settings_are_unchanged_by_missing_values() -> None:
    # API level 0 has always sent a full payload and must keep doing so; an
    # unsupplied seat is off, exactly as before. US so the request goes to the
    # fixed endpoint rather than a looked-up home region.
    service, api = _service(api_level=0, country="US")
    _start(service)

    body = json.loads(api.calls[0]["data"])
    zones = body["action"]["settings"]["climaterElementSettings"]["zoneSettings"][
        "zoneSetting"
    ]
    assert [zone["value"]["isEnabled"] for zone in zones] == [
        False,
        False,
        False,
        False,
    ]
    assert body["action"]["settings"]["targetTemperature"] == 2941
