"""#829: the home-region lookup can return a ha-5a.prd.<region>.vwg.vwautocloud.net
base URI, which fails with CERTIFICATE_VERIFY_FAILED. It has to be discarded in
favour of the static default rather than routed to.

The existing guard only covers non-US accounts on API level 1, which is why US
accounts (#829) and API level 0 accounts in Europe still reached that host.

No network: the API layer is replaced with a stub.
"""

from __future__ import annotations

import asyncio

from custom_components.audiconnect.audi_services import AudiService

VIN = "WAUZZZ00000000000"


class _StubAPI:
    """Returns a canned homeRegion response."""

    def __init__(self, base_uri: str | None) -> None:
        self._base_uri = base_uri

    def use_token(self, token) -> None:
        pass

    async def get(self, url):
        if self._base_uri is None:
            raise RuntimeError("home region lookup unavailable")
        return {"homeRegion": {"baseUri": {"content": self._base_uri}}}


def _resolve(base_uri: str | None, country: str, api_level: int) -> tuple[str, str]:
    api = _StubAPI(base_uri)
    service = AudiService(api, country, None, api_level)
    service.vwToken = {"access_token": "test-token"}
    asyncio.run(service._fill_home_region(VIN))
    return service._homeRegion[VIN], service._homeRegionSetter[VIN]


def test_us_account_does_not_route_to_vwautocloud() -> None:
    # The reported case: a US account fails the "not US" half of the old guard.
    region, setter = _resolve("https://ha-5a.prd.nar.vwg.vwautocloud.net/api", "US", 1)
    assert "vwautocloud" not in region
    assert "vwautocloud" not in setter


def test_api_level_0_in_europe_does_not_route_to_vwautocloud() -> None:
    # The other half: an API level 0 account in Europe fails the "level 1" half.
    region, setter = _resolve("https://ha-5a.prd.eu.vwg.vwautocloud.net/api", "DE", 0)
    assert "vwautocloud" not in region
    assert "vwautocloud" not in setter


def test_a_usable_base_uri_is_still_adopted() -> None:
    # The lookup is not disabled, only the known-bad host is refused.
    region, setter = _resolve("https://mal-3a.prd.eu.dp.vwg-connect.com/api", "US", 0)
    assert setter == "https://mal-3a.prd.eu.dp.vwg-connect.com"
    assert region == "https://fal-3a.prd.eu.dp.vwg-connect.com"


def test_lookup_failure_leaves_the_default_in_place() -> None:
    region, setter = _resolve(None, "US", 0)
    assert region == "https://msg.volkswagen.de"
    assert setter == "https://mal-1a.prd.ece.vwg-connect.com"


def test_non_us_api_level_1_keeps_its_existing_shortcut() -> None:
    # Unchanged behaviour: that path returns before the lookup happens at all.
    region, setter = _resolve("https://ha-5a.prd.eu.vwg.vwautocloud.net/api", "DE", 1)
    assert region == "https://mal-3a.prd.eu.dp.vwg-connect.com"
    assert setter == "https://mal-3a.prd.eu.dp.vwg-connect.com"
