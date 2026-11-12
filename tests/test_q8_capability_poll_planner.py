"""Audi capability-driven polling never removes known features on a thin poll."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlsplit

from custom_components.audiconnect.capability_jobs import (
    BASE_SELECTIVE_JOBS,
    capability_snapshot,
    select_jobs,
)
from custom_components.audiconnect.audi_services import AudiService


def caps(*items):
    return {
        "userCapabilities": {
            "capabilitiesStatus": {
                "value": [{"id": name, "status": status} for name, status in items]
            }
        }
    }


def test_first_poll_is_full_and_keeps_known_jobs():
    assert select_jobs() == BASE_SELECTIVE_JOBS
    assert "userCapabilities" in BASE_SELECTIVE_JOBS
    assert "climatisationTimers" in BASE_SELECTIVE_JOBS
    assert "chargingProfiles" in BASE_SELECTIVE_JOBS


def test_unknown_capabilities_are_not_treated_as_unsupported():
    assert capability_snapshot({}) is None
    assert capability_snapshot(caps()) is None
    assert select_jobs(frozenset()) == BASE_SELECTIVE_JOBS


def test_explicit_disabled_and_missing_jobs_are_skipped():
    reported, impaired = capability_snapshot(
        caps(
            ("charging", []),
            ("climatisation", []),
            ("climatisationTimers", []),
            ("access", []),
            ("chargingProfiles", [4001]),
            ("unknownBrandJob", []),
        )
    )
    jobs = select_jobs(reported, impaired)
    assert jobs == (
        "access",
        "charging",
        "climatisation",
        "climatisationTimers",
        "userCapabilities",
    )
    assert "unknownBrandJob" not in jobs


class API:
    def __init__(self):
        self.urls = []
        self.payloads = [
            caps(
                ("access", []),
                ("charging", []),
                ("climatisation", []),
                ("climatisationTimers", []),
            ),
            {},  # A later thin response cannot erase known capabilities.
        ]

    def use_token(self, token):
        pass

    async def get(self, url):
        self.urls.append(url)
        return self.payloads.pop(0)


def test_live_service_reuses_capabilities_without_any_extra_get():
    api = API()
    service = AudiService(api, "BE", None, 1)
    service._bearer_token_json = {"access_token": "NOT_A_TOKEN"}
    asyncio.run(service.get_stored_vehicle_data("TESTVIN00000000001"))
    asyncio.run(service.get_stored_vehicle_data("TESTVIN00000000001"))
    assert len(api.urls) == 2
    initial = parse_qs(urlsplit(api.urls[0]).query)["jobs"][0].split(",")
    later = parse_qs(urlsplit(api.urls[1]).query)["jobs"][0].split(",")
    assert tuple(initial) == BASE_SELECTIVE_JOBS
    assert later == [
        "access",
        "charging",
        "climatisation",
        "climatisationTimers",
        "userCapabilities",
    ]
    assert "chargingProfiles" not in later
    assert len(service._cariad_capabilities) == 1
