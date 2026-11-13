"""Optional Audi owner-portal sign-in; independent of native Audi auth.

Protocol reference: mikrohard/hass-vw-eu-data-act (MIT), api.py and const.py.
No consent submission, browser-cookie import, token exchange or native tokens.
Only the official portal's registered Audi OIDC client and reviewed hosts.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from urllib.parse import urlencode, urljoin, urlsplit, parse_qs

from aiohttp import ClientError
from bs4 import BeautifulSoup

from .data_act import (
    DataActAuthorizationRequired,
    DataActUnavailable,
    PORTAL,
    read_bounded,
)

IDENTITY = "https://identity.vwgroup.io"
CLIENT_ID = "cc29b87a-5e9a-4362-aecf-5adea6b01bbb@apps_vw-dilab_com"
CALLBACK = "/services/callbacklogin"


def _host(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.hostname
        not in (
            "identity.vwgroup.io",
            "eu-data-act.drivesomethinggreater.com",
        )
    ):
        raise DataActUnavailable("Unexpected Data Act login destination")
    return parsed.hostname


def _form(html, url, step):
    """Read only the identity provider's actual sign-in form fields."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    fields = {}
    if form is not None:
        for item in form.find_all("input", attrs={"type": "hidden"}):
            if item.get("name") in ("hmac", "relayState", "_csrf"):
                fields[item["name"]] = item.get("value", "")
    match = re.search(r"templateModel\s*:\s*\{", html)
    if match:
        try:
            model, _ = json.JSONDecoder().raw_decode(html[match.end() - 1 :])
        except ValueError:
            model = {}
        if isinstance(model, dict):
            for key in ("hmac", "relayState"):
                if isinstance(model.get(key), str):
                    fields[key] = model[key]
    csrf = re.search(r"csrf_token\s*[:=]\s*['\"]([^'\"]+)['\"]", html)
    if csrf:
        fields.setdefault("_csrf", csrf.group(1))
    action = form.get("action") if form else None
    target = urljoin(url, action or url.split("?", 1)[0])
    if (
        _host(target) != "identity.vwgroup.io"
        or not urlsplit(target).path.startswith("/signin-service/")
        or not urlsplit(target).path.endswith("/login/" + step)
        or not all(fields.get(key) for key in ("hmac", "_csrf"))
    ):
        raise DataActAuthorizationRequired(
            "Data Act interactive authorization required"
        )
    return target, fields


class DataActPortalLogin:
    """Bounded standard owner login on its own cookie jar."""

    def __init__(self, session, email, password, country):
        self.session = session
        self.email = email
        self.password = password
        self.state = f"{country.lower()}__en__AUDI"

    async def _request(self, method, url, quota, data=None, referer=None):
        for _ in range(10):
            host = _host(url)
            parsed = urlsplit(url)
            if method == "POST" and (
                host != "identity.vwgroup.io"
                or not parsed.path.startswith("/signin-service/")
                or not parsed.path.endswith(("/login/identifier", "/login/authenticate"))
            ):
                raise DataActAuthorizationRequired("Unexpected credential destination")
            if host == "eu-data-act.drivesomethinggreater.com" and parsed.path not in (
                "/login",
                CALLBACK,
            ):
                raise DataActAuthorizationRequired("Unexpected portal callback")
            if host == "eu-data-act.drivesomethinggreater.com" and (
                parsed.path == "/login"
                and parse_qs(parsed.query).get("state") != [self.state]
            ):
                raise DataActUnavailable("Invalid Data Act authorization state")
            quota.authorize(datetime.now(UTC), read_only=True)
            quota.reserve_request()
            async with self.session.request(
                method,
                url,
                data=data,
                headers={"Referer": referer} if referer else None,
                allow_redirects=False,
            ) as response:
                quota.observe(response.status, response.headers, datetime.now(UTC))
                if response.status in (400, 401, 403):
                    raise DataActAuthorizationRequired("Data Act sign-in rejected")
                if response.status >= 400:
                    raise DataActUnavailable("Data Act sign-in unavailable")
                if (
                    host == "eu-data-act.drivesomethinggreater.com"
                    and parsed.path == CALLBACK
                ):
                    if not response.cookies.get("access_token"):
                        raise DataActUnavailable("Data Act session not established")
                    return url, None
                if response.status in (301, 302, 303):
                    location = response.headers.get("Location")
                    if not location:
                        raise DataActUnavailable("Invalid Data Act redirect")
                    referer, url = url, urljoin(url, location)
                    method, data = "GET", None
                    continue
                raw = await read_bounded(response, 1_000_000)
                return url, raw.decode("utf-8", errors="replace")
        raise DataActUnavailable("Data Act redirect limit")

    async def authenticate(self, quota):
        try:
            async with asyncio.timeout(45):
                query = urlencode(
                    {
                        "client_id": CLIENT_ID,
                        "response_type": "code",
                        "scope": "openid cars profile",
                        "state": self.state,
                        "redirect_uri": PORTAL + "/login",
                        "prompt": "login",
                    }
                )
                url, html = await self._request(
                    "GET", IDENTITY + "/oidc/v1/authorize?" + query, quota
                )
                target, fields = _form(html or "", url, "identifier")
                fields["email"] = self.email
                url, html = await self._request("POST", target, quota, fields, url)
                target, fields = _form(html or "", url, "authenticate")
                fields.update(email=self.email, password=self.password)
                url, html = await self._request("POST", target, quota, fields, url)
                if urlsplit(url).path != CALLBACK or html is not None:
                    raise DataActAuthorizationRequired(
                        "Data Act interactive authorization required"
                    )
        except (ClientError, OSError, TimeoutError, ValueError, RuntimeError) as err:
            if isinstance(err, DataActUnavailable):
                raise
            raise DataActUnavailable("Data Act sign-in unavailable") from err
