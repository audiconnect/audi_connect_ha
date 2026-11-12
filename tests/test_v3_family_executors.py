from custom_components.audiconnect.v3.transport import _GRAPHQL_QUERY

"""API family isolation: host, token, operation and proof policy differ."""
import pytest
from types import SimpleNamespace
from custom_components.audiconnect.v3.family_executors import (
    build_family_executors,
    CARIADExecutor,
    MBBLegacyExecutor,
    GraphQLExecutor,
)


class FakeAuth:
    country = "DE"

    def __init__(self, legacy=False):
        self.uses_auth0 = not legacy
        self.requested = []

    def access_token(self, family):
        self.requested.append(family)
        return f"token-{family}"


def test_family_executor_registry_is_explicit():
    items = build_family_executors()
    assert set(items) == {"cariad", "mbb", "graphql"}
    assert type(items["cariad"]) is CARIADExecutor
    assert type(items["mbb"]) is MBBLegacyExecutor
    assert type(items["graphql"]) is GraphQLExecutor


def test_cariad_executor_auth0_get_and_manual_only_post():
    e = CARIADExecutor()
    a = FakeAuth()
    p = e.plan(
        a, "GET", "/vehicle/v1/vehicles/WAUZZZ4M0MD123456/selectivestatus?jobs=charging"
    )
    assert p.url.startswith("https://emea.bff.cariad.digital/")
    assert a.requested == ["cariad"]
    with pytest.raises(ValueError, match="direct user intent"):
        e.plan(a, "POST", "/vehicle/v1/vehicles/WAUZZZ4M0MD123456/climatisation/start")
    with pytest.raises(ValueError, match="Auth0"):
        e.plan(
            FakeAuth(legacy=True),
            "GET",
            "/vehicle/v1/vehicles/WAUZZZ4M0MD123456/selectivestatus",
        )


def test_mbb_legacy_executor_uses_separate_token_and_trusted_home_region():
    e = MBBLegacyExecutor()
    a = FakeAuth(legacy=True)
    path = "/fs-car/bs/batterycharge/v1/Audi/DE/vehicles/WAUZZZ4M0MD123456/charger"
    result = e.plan(a, "GET", path)
    assert result.url.startswith("https://msg.volkswagen.de")
    assert a.requested == ["mbb"]
    e.set_vehicle_home_region(
        "WAUZZZ4M0MD123456", "https://mal-3a.prd.eu.dp.vwg-connect.com"
    )
    assert e.plan(a, "GET", path).url.startswith(
        "https://mal-3a.prd.eu.dp.vwg-connect.com"
    )
    with pytest.raises(ValueError):
        e.set_vehicle_home_region("WAUZZZ4M0MD123456", "https://evil.invalid")
    with pytest.raises(ValueError, match="GET only"):
        e.plan(a, "POST", path, explicit_action=True)
    with pytest.raises(ValueError, match="Auth0"):
        e.plan(FakeAuth(), "GET", path)


def test_graphql_executor_can_only_use_fixed_audi_vehicle_list():
    e = GraphQLExecutor()
    a = FakeAuth()
    path = "/vgql/v1/graphql"
    response = e.plan(a, "POST", path, {"query": _GRAPHQL_QUERY}, explicit_action=True)
    assert response.url == "https://app-api.live-my.audi.com/vgql/v1/graphql"
    assert a.requested == ["graphql"]
    with pytest.raises(ValueError):
        e.plan(a, "GET", path)
    with pytest.raises(ValueError):
        e.plan(a, "POST", path, {"query": "{}", "extra": "oops"})


@pytest.mark.parametrize(
    "bad",
    [
        "https://evil.invalid/vehicle/v1/vehicles/abc",
        "//evil.invalid",
        "/vehicle/v1/vehicles/x/../y",
        "/vehicle/v1/vehicles/x/%2e%2e/y",
    ],
)
def test_cariad_rejects_unsafe_paths(bad):
    with pytest.raises(ValueError):
        CARIADExecutor().plan(FakeAuth(), "GET", bad)


@pytest.mark.parametrize(
    "country,language,expected",
    [
        ("DE", None, "de-DE"),
        ("BE", "fr", "fr-BE"),
        ("US", None, "en-US"),
        ("DE", "de_DE", "de-DE"),
        ("NL", "invalid\r\n", "nl-NL"),
    ],
)
def test_graphql_inventory_locale_uses_market_language_and_safe_fallback(
    country, language, expected
):
    auth = FakeAuth()
    auth.country = country
    auth.service = SimpleNamespace(_language=language)
    plan = GraphQLExecutor().plan(
        auth, "POST", "/vgql/v1/graphql", {"query": _GRAPHQL_QUERY}
    )
    assert plan.headers["Accept-Language"] == expected
    assert plan.headers["X-User-Country"] == country


def test_graphql_rejects_unreviewed_mutation():
    with pytest.raises(ValueError, match="Unreviewed"):
        GraphQLExecutor().plan(
            FakeAuth(),
            "POST",
            "/vgql/v1/graphql",
            {"query": "mutation { anything }"},
            explicit_action=True,
        )
