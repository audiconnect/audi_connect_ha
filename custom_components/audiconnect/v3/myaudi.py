"""Experimental Belgian owner website session; never a native bearer provider."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from urllib.parse import urlencode, urljoin, urlsplit

from aiohttp import ClientError
from yarl import URL

from .data_act_auth import _form
from .quota import RateLimit
from .transport import read_bounded_body
from .vehicle import graphql_vehicle_metadata

ORIGIN = "https://www.audi.be"
IDENTITY_HOST = "identity.vwgroup.io"
PREFIX = "/userinfo-emea/v2"
OVERVIEW = "/nl/myaudi/overview/"
PROXY = PREFIX + "/myaudi/proxy/"
INVENTORY = """query GET_USER_VEHICLES_ORDERED_BY($orderBy: VehicleSortOrder!) {
  userVehicles(orderBy: $orderBy) {
    vin
    vehicle {
      brand { name }
      classification { driveTrain }
      core { vin modelYear modelCoding }
      media { exteriorColor interiorColor shortName longName }
      renderPictures(mediaTypes: ["MYAAN8NB", "MYAPN8NB", "MYAAN3NB",
        "MYAPN3NB", "MS_MYP3", "MS_MYP4", "MS_MYP5"]) { mediaType url }
    }
  }
}"""


class MyAudiUnavailable(RuntimeError):
    """The independent website source could not be read."""


def login_destination(url):
    """Allow only the observed provider login and callback destinations."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise MyAudiUnavailable("Unexpected myAudi login destination")
    if parsed.hostname == IDENTITY_HOST and parsed.path.startswith(
        ("/oidc/v1/", "/signin-service/v1/")
    ):
        return parsed
    if parsed.hostname == "www.audi.be" and parsed.path in (
        PREFIX + "/login",
        PREFIX + "/login/myaudi",
        PREFIX + "/login/oauth2/code/myaudi",
        PROXY,
        OVERVIEW,
    ):
        return parsed
    if parsed.hostname == "www.audi.de" and parsed.path in (
        PREFIX + "/hop/login/myaudi",
        PREFIX + "/legacy-sso/callback",
    ):
        return parsed
    raise MyAudiUnavailable("Unexpected myAudi login destination")


def inventory_rows(payload):
    """Require actual, nonconflicting manufacturer VIN membership."""
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get("userVehicles") if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) > 100:
        raise MyAudiUnavailable("myAudi inventory unavailable")
    result = {}
    for row in rows:
        vin = row.get("vin") if isinstance(row, dict) else None
        if not isinstance(vin, str) or len(vin) != 17 or not vin.isalnum():
            continue
        key = vin.upper()
        vehicle = graphql_vehicle_metadata(row.get("vehicle"), vin)
        core = vehicle.get("core") if vehicle else None
        if not isinstance(core, dict) or str(core.get("vin", "")).upper() != key:
            continue
        if key in result:
            raise MyAudiUnavailable("Ambiguous myAudi inventory")
        result[key] = row
    return result


class MyAudiPortal:
    """Normal website sign-in; no imported tokens, consent or challenge bypass."""

    def __init__(self, session, email, password):
        self.session = session
        self.email = email
        self.password = password
        self.quota = RateLimit()
        self.lock = asyncio.Lock()
        self.connected = False

    async def _login_request(self, method, url, data=None, referer=None):
        for _ in range(24):
            parsed = login_destination(url)
            if method == "POST" and (
                parsed.hostname != IDENTITY_HOST
                or not parsed.path.endswith(
                    ("/login/identifier", "/login/authenticate")
                )
                or not parsed.path.startswith("/signin-service/v1/")
            ):
                raise MyAudiUnavailable("Unexpected myAudi credential destination")
            headers = {}
            if method == "POST":
                headers["Origin"] = "https://" + IDENTITY_HOST
                if referer:
                    headers["Referer"] = referer
            self.quota.authorize(datetime.now(UTC))
            async with self.session.request(
                method, url, data=data, headers=headers, allow_redirects=False
            ) as response:
                self.quota.observe(
                    response.status,
                    response.headers,
                    datetime.now(UTC),
                    allow_redirect=True,
                )
                if response.status in (301, 302, 303):
                    location = response.headers.get("Location")
                    if not location:
                        raise MyAudiUnavailable("Invalid myAudi redirect")
                    url, method, data, referer = (
                        urljoin(url, location),
                        "GET",
                        None,
                        None,
                    )
                    continue
                if response.status != 200:
                    raise MyAudiUnavailable("myAudi sign-in rejected or unavailable")
                raw = await read_bounded_body(response, 2_000_000)
                return url, raw.decode("utf-8", errors="replace")
        raise MyAudiUnavailable("myAudi redirect limit")

    def _csrf(self):
        cookie = self.session.cookie_jar.filter_cookies(URL(ORIGIN + PROXY)).get(
            "csrf_token"
        )
        return cookie.value if cookie and cookie.value else None

    async def _authenticated(self):
        csrf = self._csrf()
        if not csrf:
            return False
        self.quota.authorize(datetime.now(UTC))
        async with self.session.get(
            ORIGIN + PREFIX + "/myaudi/authenticated",
            headers={"x-csrf-token": csrf},
            allow_redirects=False,
        ) as response:
            self.quota.observe(response.status, response.headers, datetime.now(UTC))
            if response.status == 200:
                return bool(self._csrf())
            if response.status in (401, 403):
                return False
            raise MyAudiUnavailable("myAudi session check unavailable")

    async def _login(self):
        self.session.cookie_jar.clear()
        query = urlencode(
            {
                "fag": "myaudi",
                "redirectUrl": ORIGIN + OVERVIEW,
                "ui_locales": "nl-BE",
                "ext-country_of_residence": "BE",
            }
        )
        url, html = await self._login_request(
            "GET", ORIGIN + PREFIX + "/login?" + query
        )
        target, fields = _form(html, url, "identifier")
        fields["email"] = self.email
        url, html = await self._login_request("POST", target, fields, url)
        target, fields = _form(html, url, "authenticate")
        fields.update(email=self.email, password=self.password)
        url, _ = await self._login_request("POST", target, fields, url)
        if urlsplit(url).path != OVERVIEW or not await self._authenticated():
            raise MyAudiUnavailable("myAudi interactive sign-in required")
        self.connected = True

    async def _ensure_session(self):
        if self.connected and await self._authenticated():
            return
        self.connected = False
        await self._login()

    async def _read(self, path, resource, *, params=None, body=None):
        csrf = self._csrf()
        if not csrf:
            raise MyAudiUnavailable("myAudi session unavailable")
        headers = {"x-csrf-token": csrf, "Accept": "application/json"}
        if body is not None:
            headers["Origin"] = ORIGIN
        self.quota.authorize(datetime.now(UTC))
        async with self.session.request(
            "POST" if body is not None else "GET",
            ORIGIN + PROXY + path,
            params={"resourceHost": resource, **(params or {})},
            json=body,
            headers=headers,
            allow_redirects=False,
        ) as response:
            self.quota.observe(response.status, response.headers, datetime.now(UTC))
            if response.status != 200:
                if response.status in (401, 403):
                    self.connected = False
                raise MyAudiUnavailable("myAudi read rejected or unavailable")
            return json.loads(await read_bounded_body(response, 2_000_000))

    async def _inventory(self):
        return inventory_rows(
            await self._read(
                "vgql/v1/graphql",
                "retailservices",
                body={
                    "operationName": "GET_USER_VEHICLES_ORDERED_BY",
                    "variables": {"orderBy": "FAVORITE_AND_REGISTRATION"},
                    "query": INVENTORY,
                },
            )
        )

    async def connect(self, native_vins):
        """Verify website access against the existing native account."""
        async with self.lock:
            try:
                async with asyncio.timeout(60):
                    await self._ensure_session()
                    rows = await self._inventory()
                    if not set(rows).intersection(v.upper() for v in native_vins):
                        raise MyAudiUnavailable("No matching native vehicle")
            except (ClientError, OSError, TimeoutError, ValueError, RuntimeError):
                raise MyAudiUnavailable(
                    "myAudi connection could not be verified"
                ) from None

    async def dossier(self, vin):
        """Read fixed routes only after fresh selected VIN membership."""
        vin = vin.upper()
        async with self.lock:
            try:
                async with asyncio.timeout(60):
                    await self._ensure_session()
                    row = (await self._inventory()).get(vin)
                    if row is None:
                        raise MyAudiUnavailable("Vehicle unavailable in myAudi")
                    result = {"identity": row}
                    routes = (
                        (
                            "service",
                            "service-record-overview/" + vin,
                            "fa-service-record-api",
                            None,
                        ),
                        (
                            "warranty",
                            "patp/v1/sprmyaudi/v1/cos/v1/vehicles/"
                            + vin
                            + "/follow-up-warranty",
                            "retailservices",
                            None,
                        ),
                        (
                            "oil",
                            "api/oil-norm/" + vin,
                            "cwat-oil-norm",
                            {"language": "nl-BE", "isNewPAT": "true"},
                        ),
                        (
                            "services",
                            "vehicles/" + vin + "/usercapabilities",
                            "cwat-vcf",
                            None,
                        ),
                    )
                    for name, path, resource, params in routes:
                        try:
                            result[name] = await self._read(
                                path, resource, params=params
                            )
                        except (ClientError, OSError, ValueError, RuntimeError):
                            result[name] = None
                            if not self.connected or self.quota.read_deferred(
                                datetime.now(UTC)
                            ):
                                break
                    return result
            except (ClientError, OSError, TimeoutError, ValueError, RuntimeError):
                raise MyAudiUnavailable("myAudi dossier unavailable") from None
