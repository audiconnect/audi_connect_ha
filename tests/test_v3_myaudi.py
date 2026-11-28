"""Synthetic negative checks for the optional website source."""

from unittest.mock import AsyncMock

import pytest

from custom_components.audiconnect.v3.myaudi import (
    MyAudiPortal,
    MyAudiUnavailable,
    inventory_rows,
    login_destination,
)

VIN = "WAUZZZ4M0MD123456"
OTHER = "WAUZZZ4M0MD654321"


def row(vin=VIN, nested=VIN):
    return {"vin": vin, "vehicle": {"core": {"vin": nested, "modelYear": 2025}}}


def test_login_host_allowlist():
    assert (
        login_destination("https://www.audi.be/userinfo-emea/v2/login").hostname
        == "www.audi.be"
    )
    for url in (
        "http://www.audi.be/userinfo-emea/v2/login",
        "https://evil.example/userinfo-emea/v2/login",
        "https://www.audi.be/other",
        "https://www.audi.de/userinfo-emea/v2/login",
    ):
        with pytest.raises(MyAudiUnavailable):
            login_destination(url)


def test_inventory_requires_matching_core_vin():
    assert set(inventory_rows({"data": {"userVehicles": [row(), row(OTHER)]}})) == {VIN}
    with pytest.raises(MyAudiUnavailable):
        inventory_rows({"data": {"userVehicles": [row(), row()]}})


@pytest.mark.asyncio
async def test_selected_read_cannot_use_another_account():
    portal = MyAudiPortal(None, "test@example.invalid", "synthetic")
    portal._ensure_session = AsyncMock()
    portal._inventory = AsyncMock(return_value={OTHER: row(OTHER, OTHER)})
    portal._read = AsyncMock()
    with pytest.raises(MyAudiUnavailable):
        await portal.connect([VIN])
    with pytest.raises(MyAudiUnavailable):
        await portal.dossier(VIN)
    portal._read.assert_not_awaited()


def test_dossier_normalization_distinguishes_empty_unavailable_and_vin_conflict():
    from custom_components.audiconnect.v3.vehicle import normalize_myaudi_dossier

    selected = row()
    selected["vehicle"]["media"] = {"longName": "Audi Q8"}
    payload = {
        "identity": selected,
        "service": [],
        "oil": {"vin": OTHER, "unit": "L", "oilNorms": []},
    }
    result = normalize_myaudi_dossier(payload, VIN, "DE", "2026-11-28T00:00:00+00:00")
    assert result["identity"]["model"] == "Audi Q8"
    assert result["service"] == []
    assert result["warranty"] is None and result["oil"] is None
    assert VIN not in str(result)
    with pytest.raises(ValueError):
        normalize_myaudi_dossier({"identity": row(OTHER, OTHER)}, VIN, "DE", "")


@pytest.mark.asyncio
async def test_dossier_uses_only_observed_selected_vin_routes():
    portal = MyAudiPortal(None, "test@example.invalid", "synthetic")
    portal._ensure_session = AsyncMock()
    portal._inventory = AsyncMock(return_value={VIN: row()})
    portal._read = AsyncMock(side_effect=[[], {}, {"vin": VIN}, {"data": []}])
    portal.connected = True
    result = await portal.dossier(VIN)
    assert result["service"] == [] and result["identity"]["vin"] == VIN
    assert portal._read.await_count == 4
    for call in portal._read.await_args_list:
        assert VIN in call.args[0]
        assert call.args[1] in (
            "fa-service-record-api",
            "retailservices",
            "cwat-oil-norm",
            "cwat-vcf",
        )


@pytest.mark.asyncio
async def test_portal_normal_login_uses_provider_forms_and_csrf():
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock
    from urllib.parse import urlsplit

    class Response:
        def __init__(self, status, body="", location=None):
            self.status = status
            self.headers = {"Location": location} if location else {}
            self.body = body.encode()
            self.content_length = len(self.body)
            self.content = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def iter_chunked(self, size):
            yield self.body

    form = (
        '<form action="/signin-service/v1/synthetic/login/identifier">'
        '<input type="hidden" name="_csrf" value="synthetic-csrf">'
        '<input type="hidden" name="hmac" value="synthetic-hmac">'
        '<input type="hidden" name="relayState" value="synthetic-state">'
        "</form>"
    )
    password_form = (
        'templateModel: {"hmac":"synthetic-hmac","relayState":"synthetic-state"},'
        "csrf_token: 'synthetic-csrf'"
    )
    scripted = [
        (
            "GET",
            "/userinfo-emea/v2/login",
            Response(302, location="/userinfo-emea/v2/login/myaudi"),
        ),
        (
            "GET",
            "/userinfo-emea/v2/login/myaudi",
            Response(302, location="https://identity.vwgroup.io/oidc/v1/authorize"),
        ),
        (
            "GET",
            "/oidc/v1/authorize",
            Response(302, location="/signin-service/v1/signin/synthetic"),
        ),
        ("GET", "/signin-service/v1/signin/synthetic", Response(200, form)),
        (
            "POST",
            "/signin-service/v1/synthetic/login/identifier",
            Response(303, location="/signin-service/v1/synthetic/login/authenticate"),
        ),
        (
            "GET",
            "/signin-service/v1/synthetic/login/authenticate",
            Response(200, password_form),
        ),
        (
            "POST",
            "/signin-service/v1/synthetic/login/authenticate",
            Response(
                302, location="https://www.audi.de/userinfo-emea/v2/hop/login/myaudi"
            ),
        ),
        (
            "GET",
            "/userinfo-emea/v2/hop/login/myaudi",
            Response(
                302,
                location="https://www.audi.be/userinfo-emea/v2/login/oauth2/code/myaudi",
            ),
        ),
        (
            "GET",
            "/userinfo-emea/v2/login/oauth2/code/myaudi",
            Response(302, location="/userinfo-emea/v2/myaudi/proxy/"),
        ),
        (
            "GET",
            "/userinfo-emea/v2/myaudi/proxy/",
            Response(302, location="https://identity.vwgroup.io/oidc/v1/authorize"),
        ),
        (
            "GET",
            "/oidc/v1/authorize",
            Response(
                302, location="https://www.audi.de/userinfo-emea/v2/legacy-sso/callback"
            ),
        ),
        (
            "GET",
            "/userinfo-emea/v2/legacy-sso/callback",
            Response(302, location="https://www.audi.be/nl/myaudi/overview/"),
        ),
        ("GET", "/nl/myaudi/overview/", Response(200)),
        ("GET", "/userinfo-emea/v2/myaudi/authenticated", Response(200)),
        (
            "POST",
            "/userinfo-emea/v2/myaudi/proxy/vgql/v1/graphql",
            Response(200, json.dumps({"data": {"userVehicles": [row()]}})),
        ),
    ]
    calls = []

    def request(method, url, **kwargs):
        expected_method, path, response = scripted.pop(0)
        assert (method, urlsplit(url).path) == (expected_method, path)
        assert kwargs["allow_redirects"] is False
        calls.append((method, urlsplit(url).hostname, path, kwargs))
        return response

    jar = SimpleNamespace(
        clear=Mock(),
        filter_cookies=lambda url: {
            "csrf_token": SimpleNamespace(value="synthetic-session-csrf")
        },
    )
    session = SimpleNamespace(
        cookie_jar=jar, request=request, get=lambda url, **kw: request("GET", url, **kw)
    )
    portal = MyAudiPortal(session, "test@example.invalid", "synthetic-password")
    await portal.connect([VIN])
    assert portal.connected and not scripted
    jar.clear.assert_called_once()
    password_posts = [
        call for call in calls if (call[3].get("data") or {}).get("password")
    ]
    assert len(password_posts) == 1
    assert password_posts[0][1] == "identity.vwgroup.io"
    assert calls[-2][3]["headers"]["x-csrf-token"] == "synthetic-session-csrf"
    assert calls[-1][3]["headers"]["x-csrf-token"] == "synthetic-session-csrf"


def test_dossier_preserves_observed_capability_status_lists():
    from custom_components.audiconnect.v3.vehicle import normalize_myaudi_dossier

    result = normalize_myaudi_dossier(
        {
            "identity": row(),
            "services": {
                "data": [
                    {"id": "example_a", "status": [0, 1]},
                    {"id": "example_b", "status": []},
                    {"id": "example_c", "status": ["invalid"]},
                ]
            },
        },
        VIN,
        "DE",
        "2026-11-28T00:00:00+00:00",
    )
    assert [item["status"] for item in result["services"]] == [[0, 1], [], None]
