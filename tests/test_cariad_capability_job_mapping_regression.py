"""Regression: CARIAD capability IDs, jobs and partial HTTP 207 payloads differ."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS
from urllib.parse import parse_qs, urlsplit

from custom_components.audiconnect.audi_connect_account import AudiConnectVehicle
from custom_components.audiconnect.audi_services import AudiService
from custom_components.audiconnect.capability_jobs import (
    BASE_SELECTIVE_JOBS,
    capability_snapshot,
    observed_readable_jobs,
    select_jobs,
)


def _caps(*names: tuple[str, list[int]]) -> dict:
    return {
        "userCapabilities": {
            "capabilitiesStatus": {
                "value": [{"id": name, "status": status} for name, status in names]
            }
        }
    }


def test_oil_level_status_capability_selects_the_different_oil_level_job():
    reported, impaired = capability_snapshot(_caps(("oilLevelStatus", [])))
    jobs = select_jobs(reported, impaired)
    assert "oilLevel" in jobs
    assert "userCapabilities" in jobs
    assert "tripStatistics" not in jobs
    assert "parkingPosition" not in jobs


def test_impaired_unobserved_job_is_not_enabled_by_alias():
    reported, impaired = capability_snapshot(_caps(("oilLevelStatus", [4001])))
    assert "oilLevel" not in select_jobs(reported, impaired)
    assert "oilLevel" in select_jobs(
        reported, impaired, observed=frozenset({"oilLevel"})
    )


def test_mixed_207_style_job_payload_learns_only_real_readable_values():
    requested = ("oilLevel", "measurements", "batterySupport", "charging")
    response = {
        "oilLevel": {"oilLevelStatus": {"value": {"oilLevel": 90}}},
        "measurements": {
            "odometerStatus": {"value": {"odometer": 123}},
            "fuelLevelStatus": {"error": {"code": "TEMPORARY"}},
        },
        "batterySupport": {"error": {"code": "NOT_PROVISIONED"}},
        "charging": {"chargingStatus": {"value": {}}},
    }
    found = observed_readable_jobs(response, requested)
    assert found == {"oilLevel", "measurements"}
    assert "batterySupport" not in found
    assert "charging" not in found
    assert not observed_readable_jobs({"unknown": {"value": 1}}, ("unknown",))


class _API:
    def __init__(self):
        self.urls = []
        self.payloads = [
            {
                **_caps(
                    ("oilLevelStatus", []),
                    ("chargingProfiles", [4001]),
                ),
                "oilLevel": {"oilLevelStatus": {"value": {"oilLevel": 87}}},
                "measurements": {"odometerStatus": {"value": {"odometer": 12345}}},
                "chargingProfiles": {"error": {"code": "UNAVAILABLE"}},
            },
            {
                "oilLevel": {"oilLevelStatus": {"value": {"oilLevel": 86}}},
                "userCapabilities": _caps(("oilLevelStatus", []))["userCapabilities"],
            },
        ]

    def use_token(self, token):
        pass

    async def get(self, url):
        self.urls.append(url)
        return self.payloads.pop(0)


def _requested_jobs(url):
    return parse_qs(urlsplit(url).query)["jobs"][0].split(",")


def test_real_service_preserves_successful_jobs_even_if_capabilities_omit_them():
    api = _API()
    service = AudiService(api, "BE", None, 1)
    service._bearer_token_json = {"access_token": "SYNTHETIC"}
    first = asyncio.run(service.get_stored_vehicle_data("SYNTHETICVIN000001"))
    second = asyncio.run(service.get_stored_vehicle_data("SYNTHETICVIN000001"))
    assert len(api.urls) == 2
    assert tuple(_requested_jobs(api.urls[0])) == BASE_SELECTIVE_JOBS
    second_jobs = _requested_jobs(api.urls[1])
    assert second_jobs == ["measurements", "oilLevel", "userCapabilities"]
    assert "chargingProfiles" not in second_jobs
    assert first.partial_response is True
    assert second.partial_response is True
    assert service._cariad_observed_jobs["SYNTHETICVIN000001"] >= {
        "measurements",
        "oilLevel",
    }


def test_partial_207_status_merges_fields_instead_of_erasing_cached_values():
    class Service:
        async def get_stored_vehicle_data(self, vin):
            return NS(
                all_jobs_errored=False,
                error_count=0,
                partial_response=True,
                data_fields=[
                    NS(name="TANK_LEVEL_IN_PERCENTAGE", value=50, measure_time=None)
                ],
                states=[
                    {
                        "name": "chargingState",
                        "value": "not_charging",
                        "measure_time": None,
                    }
                ],
            )

    car = AudiConnectVehicle(Service(), NS(vin="SYNTHETICVIN000001"))
    car._vehicle.fields["OIL_LEVEL"] = 65
    car._vehicle.state["stateOfCharge"] = 34
    asyncio.run(car.update_vehicle_statusreport())
    assert car._vehicle.fields["OIL_LEVEL"] == 65
    assert car._vehicle.fields["TANK_LEVEL_IN_PERCENTAGE"] == 50
    assert car._vehicle.state["stateOfCharge"] == 34
    assert car._vehicle.state["chargingState"] == "not_charging"


def test_partial_empty_response_does_not_wipe_old_data_or_claim_success():
    class Service:
        async def get_stored_vehicle_data(self, vin):
            return NS(
                all_jobs_errored=False,
                error_count=0,
                partial_response=True,
                data_fields=[],
                states=[],
            )

    car = AudiConnectVehicle(Service(), NS(vin="SYNTHETICVIN000001"))
    car._vehicle.fields["OIL_LEVEL"] = 65
    car._vehicle.state["stateOfCharge"] = 34
    car._no_error = True
    asyncio.run(car.update_vehicle_statusreport())
    assert car._vehicle.fields["OIL_LEVEL"] == 65
    assert car._vehicle.state["stateOfCharge"] == 34
    assert car._no_error is False
