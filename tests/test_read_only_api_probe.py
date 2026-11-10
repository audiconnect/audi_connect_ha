"""Tests for bounded, privacy-safe, explicit read-only API path probes."""

from __future__ import annotations

import asyncio

from aiohttp import ClientResponseError

from custom_components.audiconnect.api_probe import (
    MAX_PROBES,
    MAX_EXTENDED_PROBES,
    EXTENDED_READ_ONLY_PROBES,
    READ_ONLY_PROBES,
    classify_payload,
    run_read_only_probes,
)

VIN = "EXAMPLEVIN0000001"
SECRET = "PRIVATE_TOKEN"


class FakeApi:
    def __init__(self, status=None, rate_limit=None):
        self.status = status
        self.vcf_remaining_calls = rate_limit
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if self.status is not None:
            raise ClientResponseError(None, (), status=self.status)
        if "selectivestatus?jobs=" in url:
            job = url.split("selectivestatus?jobs=", 1)[1]
            return {job: {"value": {"someSensitiveValue": "not exported"}}}
        return {"data": [{"gps": {"latitude": 50.5, "longitude": 4.5}}]}


def _url_for(suffix):
    return f"https://emea.bff.cariad.digital/vehicle/v1/vehicles/{VIN}/{suffix}"


def test_all_get_no_mutations_and_no_secrets():
    api = FakeApi()
    result = asyncio.run(run_read_only_probes(api, SECRET, _url_for))
    assert result["attempted"] == MAX_PROBES == len(READ_ONLY_PROBES)
    assert all(method == "GET" and kwargs == {} for method, _url, kwargs in api.calls)
    output = repr(result)
    assert VIN not in output
    assert SECRET not in output
    assert "someSensitiveValue" not in output
    assert "50.5" not in output
    assert result["mutating_requests"] == 0


def test_extended_mode_adds_five_get_only_experimental_probes():
    api = FakeApi()
    result = asyncio.run(run_read_only_probes(api, SECRET, _url_for, extended=True))
    assert result["attempted"] == MAX_EXTENDED_PROBES == 13
    assert len(EXTENDED_READ_ONLY_PROBES) == 5
    assert result["mode"] == "extended"
    assert len(api.calls) == 13
    assert all(method == "GET" for method, _url, _kwargs in api.calls)
    assert "PRIVATE_TOKEN" not in repr(result)
    assert VIN not in repr(result)


def test_auth_rejection_stops_probe_burst():
    api = FakeApi(status=401)
    report = asyncio.run(run_read_only_probes(api, SECRET, _url_for))
    assert len(api.calls) == 1
    assert report["attempted"] == 1
    assert report["results"][0]["outcome"] == "authentication_rejected"
    assert all(x["outcome"] == "skipped" for x in report["results"][1:])


def test_rate_limit_stops_without_network():
    api = FakeApi(rate_limit=6)
    report = asyncio.run(run_read_only_probes(api, SECRET, _url_for))
    assert api.calls == []
    assert report["attempted"] == 0
    assert all(x["reason"] == "low_rate_limit_budget" for x in report["results"])


def test_http_404_is_not_called_incapable():
    api = FakeApi(status=404)
    report = asyncio.run(run_read_only_probes(api, SECRET, _url_for))
    assert report["results"][0]["outcome"] == "route_not_found_or_not_provisioned"
    assert report["results"][0]["outcome"] != "vehicle_unsupported"


def test_job_error_inside_http_200_is_not_usable():
    assert (
        classify_payload(
            {"charging": {"chargingStatus": {"error": {"status": 404}}}}, "charging"
        )
        == "job_returned_error"
    )


def test_missing_job_does_not_become_false_positive():
    assert (
        classify_payload({"otherJob": {"value": 12}}, "charging")
        == "job_missing_from_response"
    )


def test_unavailable_access_token_is_rejected():
    try:
        asyncio.run(run_read_only_probes(FakeApi(), "", _url_for))
    except ValueError:
        pass
    else:
        raise AssertionError("Missing token should never start probes")
