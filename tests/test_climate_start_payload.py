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

    async def get(self, url, **kwargs):
        """The start reads the car's stored settings first. These values are
        deliberately ON so a body that clears them is visible in the assertions."""
        return {
            "climatisation": {
                "climatisationSettings": {
                    "value": {
                        "carCapturedTimestamp": "2026-09-12 12:00:00+00:00",
                        "targetTemperature_C": 15.5,
                        "targetTemperature_F": 60,
                        "climatisationWithoutExternalPower": True,
                        "climatizationAtUnlock": True,
                        "windowHeatingEnabled": True,
                        "zoneFrontLeftEnabled": True,
                        "zoneFrontRightEnabled": True,
                    }
                }
            }
        }


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
    # Asking for one seat is still asking for something, so a body is sent.
    service, api = _service(api_level=1)
    _start(service, seat_fl=True)

    body = json.loads(api.calls[0]["data"])
    assert body["zoneFrontLeftEnabled"] is True


def test_an_unsupplied_setting_keeps_what_the_car_has() -> None:
    """Changed deliberately on 2026-09-12, replacing an assertion that an
    unsupplied zone was sent as False. That behaviour was the defect: the
    endpoint replaces rather than merges, so starting climatisation from the
    climate entity (which passes only a temperature) wiped the stored window
    heating and every seat zone. Confirmed live, where the myAudi app's own
    start preserved them and ours cleared them on the same car minutes apart.
    None now means leave it alone; only an explicit False turns something off."""
    service, api = _service(api_level=1)
    _start(service, seat_fl=True)

    body = json.loads(api.calls[0]["data"])
    assert body["zoneFrontRightEnabled"] is True  # the car's value, not forced off
    assert body["windowHeatingEnabled"] is True
    assert body["climatizationAtUnlock"] is True


def test_a_temperature_only_start_preserves_the_stored_settings() -> None:
    """The exact live regression: the climate entity passes only temp_c."""
    service, api = _service(api_level=1)
    _start(service, temp_c=20)

    body = json.loads(api.calls[0]["data"])
    assert body["targetTemperature"] == 20
    assert body["windowHeatingEnabled"] is True
    assert body["zoneFrontLeftEnabled"] is True
    assert body["zoneFrontRightEnabled"] is True


def test_an_unchanged_temperature_is_not_rounded() -> None:
    """The car stores half degrees. Passing its own value back through int()
    would quietly move 15.5 to 15 on a start that never asked to change it."""
    service, api = _service(api_level=1)
    _start(service, seat_fl=True)

    body = json.loads(api.calls[0]["data"])
    assert body["targetTemperature"] == 15.5


def test_a_car_without_rear_zones_is_not_sent_any() -> None:
    """Only the fields the car reports are sent. #771's vehicles reject a
    payload they have no profile for, and inventing rear zones is exactly that."""
    service, api = _service(api_level=1)
    _start(service, seat_fl=True)

    body = json.loads(api.calls[0]["data"])
    assert "zoneRearLeftEnabled" not in body
    assert "zoneRearRightEnabled" not in body


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


def test_api_level_0_bare_temperature_start_sends_no_null_booleans() -> None:
    """The live regression, API level 0 (the legacy fs-car backend).

    The climate entity's bare turn_on() calls start_climate_control with only
    temp_c. Before this test was added, isClimatisationAtUnlock and
    isMirrorHeatingEnabled were passed straight through unwrapped, so a call
    with only temp_c put a literal JSON `null` on the wire for both. The
    fs-car climater/actions endpoint rejects that payload outright with HTTP
    400, before the command is even queued as a trackable action -- so the
    failure never reaches check_request_succeeded and is invisible to its
    SUCCEEDED/FAILED handling. Reproduced live on 2026-09-22 against a real
    Audi A3 Sportback e-tron (API level 0 account).

    Unlike API level 1 (#849), API level 0 has never read the car's stored
    settings back before starting, so the contract here is simpler: every
    boolean field is a real True/False, exactly like the zone settings already
    are, never a bare None turning into `null`.
    """
    service, api = _service(api_level=0, country="US")
    _start(service, temp_c=21)

    raw = api.calls[0]["data"]
    assert "null" not in raw, f"literal JSON null on the wire: {raw}"

    body = json.loads(raw)
    element_settings = body["action"]["settings"]["climaterElementSettings"]
    assert element_settings["isClimatisationAtUnlock"] is False
    assert element_settings["isMirrorHeatingEnabled"] is False
    assert body["action"]["settings"]["targetTemperature"] == 2941  # 21degC in deciKelvin


def test_api_level_0_explicit_booleans_are_preserved() -> None:
    # An explicit instruction (as Arsenal's climatisation_distante.yaml sends)
    # must still come through as-is, not be flattened by the None -> False fix.
    service, api = _service(api_level=0, country="US")
    _start(
        service,
        temp_c=21,
        climatisation_at_unlock=True,
        glass_heating=True,
    )

    body = json.loads(api.calls[0]["data"])
    element_settings = body["action"]["settings"]["climaterElementSettings"]
    assert element_settings["isClimatisationAtUnlock"] is True
    assert element_settings["isMirrorHeatingEnabled"] is True
