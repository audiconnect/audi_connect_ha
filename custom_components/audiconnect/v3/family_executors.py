"""Independent API-family request executors for Audi Connect V3.

All executors consume scoped tokens from V3Auth; none creates sessions, reads
HA config entries, calls the V2 vehicle API, or chooses arbitrary remote hosts.
MBB mutations are limited to the reviewed climate and RLU contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

APP_VERSION = "4.31.0"
APP_AGENT = "Android/4.31.0 (Build 800341641.root project 'myaudi_android'.ext.buildTime) Android/13"
LEGACY_BASE = "https://msg.volkswagen.de"
LEGACY_REGION_HOSTS = frozenset(
    {
        "msg.volkswagen.de",
        "mal-3a.prd.eu.dp.vwg-connect.com",
        "fal-3a.prd.eu.dp.vwg-connect.com",
        "mal-1a.prd.ece.vwg-connect.com",
    }
)


@dataclass(frozen=True)
class RequestPlan:
    family: str
    method: str
    url: str
    headers: dict[str, str]
    body: Any = None


class FamilyExecutor(Protocol):
    family: str

    def plan(
        self,
        auth: Any,
        method: str,
        path: str,
        body: Any = None,
        *,
        explicit_action: bool = False,
    ) -> RequestPlan: ...


def _checked_path(path: str) -> str:
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or path.startswith("//")
        or "://" in path
        or "\\" in path
        or ".." in path
        or "#" in path
        or any(ord(c) < 32 for c in path)
        or any(token in path.lower() for token in ("%2f", "%5c", "%00", "%2e"))
    ):
        raise ValueError("Unsafe Audi V3 relative API path")
    if urlsplit(path).netloc:
        raise ValueError("An API family cannot execute an arbitrary host")
    return urlsplit(path).path


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "X-App-Name": "myAudi",
        "X-App-Version": APP_VERSION,
        "User-Agent": APP_AGENT,
        "Authorization": "Bearer " + token,
    }


class CARIADExecutor:
    family = "cariad"

    def plan(
        self,
        auth: Any,
        method: str,
        path: str,
        body: Any = None,
        *,
        explicit_action: bool = False,
    ) -> RequestPlan:
        if method not in ("GET", "POST", "PUT"):
            raise ValueError("Unsupported CARIAD operation")
        if method != "GET" and not explicit_action:
            raise ValueError("CARIAD mutations need direct user intent")
        resource = _checked_path(path)
        if resource == "/vehicle/v1/vehicles":
            if method != "GET" or body is not None or path != resource:
                raise ValueError("Garage inventory is strictly read-only")
            if not auth.uses_auth0 and not getattr(auth, "has_cariad_bearer", False):
                raise ValueError("Garage inventory needs a CARIAD bearer")
            host = "na" if auth.country == "US" else "emea"
            return RequestPlan(
                self.family,
                method,
                f"https://{host}.bff.cariad.digital" + path,
                _headers(auth.access_token(self.family)),
                None,
            )
        if not auth.uses_auth0:
            import re

            if not getattr(auth, "has_cariad_bearer", False):
                raise ValueError(
                    "CARIAD operation requires Auth0 or a reviewed legacy bearer"
                )
            # Exact historical V2 routes only. No custom legacy CARIAD URL,
            # modern access challenge or explicit Auth0 wake trigger.
            match = re.fullmatch(r"/vehicle/v1/vehicles/[A-Za-z0-9]{17}/(.+)", resource)
            suffix = match[1] if match else ""
            allowed = method == "GET" and suffix in (
                "selectivestatus",
                "parkingposition",
                "pendingrequests",
            )
            allowed |= method == "POST" and suffix in (
                "charging/start",
                "charging/stop",
                "charging/start-stop",
                "climatisation/start",
                "climatisation/stop",
                "windowheating/start",
                "windowheating/stop",
                "vehiclewakeup",
                "honkandflash",
                "auxiliaryheating/start",
                "auxiliaryheating/stop",
            )
            allowed |= method == "PUT" and suffix in (
                "charging/settings",
                "charging/mode",
                "charging/profiles",
                "climatisation/settings",
            )
            allowed |= bool(
                re.fullmatch(
                    r"/vehicle/v1/engine/[A-Za-z0-9]{17}/(?:userpromptproof|start|stop)",
                    resource,
                )
            )
            if not allowed:
                raise ValueError("Unreviewed legacy-bearer CARIAD route")
        if resource.startswith("/vehicle/v1/trips/"):
            import re

            if (
                method != "GET"
                or body is not None
                or "?" in path
                or not re.fullmatch(
                    r"/vehicle/v1/trips/[A-Za-z0-9]{17}/(?:shortterm|longterm|shortterm/last)",
                    resource,
                )
            ):
                raise ValueError("Unreviewed Audi trip route")
        elif resource.startswith("/vehicle/v1/engine/"):
            import re

            match = re.fullmatch(
                r"/vehicle/v1/engine/[A-Za-z0-9]{17}/(userpromptproof|start|stop)",
                resource,
            )
            if (
                not match
                or "?" in path
                or not explicit_action
                or method != ("PUT" if match[1] == "userpromptproof" else "POST")
            ):
                raise ValueError("Unreviewed Audi engine route")
            action = match[1]
            expected = (
                {"spin"}
                if action == "userpromptproof"
                else {"spin", "securedActivationData"}
            )
            if action == "stop":
                if body is not None:
                    raise ValueError("Engine stop must be bodyless")
            elif (
                not isinstance(body, dict)
                or set(body) != expected
                or any(not isinstance(v, str) or not v for v in body.values())
            ):
                raise ValueError("Invalid secure engine payload")
        elif not resource.startswith("/vehicle/v1/vehicles/"):
            raise ValueError("Path is outside the vehicle CARIAD API")
        host = "na" if auth.country == "US" else "emea"
        headers = _headers(auth.access_token(self.family))
        if method in ("POST", "PUT") and body is not None:
            headers["Content-Type"] = "application/json"
        return RequestPlan(
            self.family,
            method,
            f"https://{host}.bff.cariad.digital" + path,
            headers,
            body,
        )


def _inventory_locale(auth: Any) -> str:
    """Use the shared Audi market language, not OS/browser locale."""
    import re

    country = str(auth.country).upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError("Invalid Audi inventory country")
    configured = getattr(getattr(auth, "service", None), "_language", None)
    defaults = {
        "DE": "de",
        "AT": "de",
        "CH": "de",
        "BE": "nl",
        "NL": "nl",
        "FR": "fr",
        "IT": "it",
        "ES": "es",
        "PT": "pt",
        "PL": "pl",
        "SE": "sv",
        "NO": "nb",
        "DK": "da",
        "FI": "fi",
        "CZ": "cs",
        "JP": "ja",
        "CN": "zh",
        "KR": "ko",
    }
    language = (
        configured.strip().replace("_", "-") if isinstance(configured, str) else ""
    )
    if re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z]{2})?", language):
        language = language.split("-")[0].lower()
    else:
        language = defaults.get(country, "en")
    return f"{language}-{country}"


class GraphQLExecutor:
    family = "graphql"

    def plan(
        self,
        auth: Any,
        method: str,
        path: str,
        body: Any = None,
        *,
        explicit_action: bool = False,
    ) -> RequestPlan:
        if method != "POST" or _checked_path(path) != "/vgql/v1/graphql" or "?" in path:
            raise ValueError(
                "GraphQL supports only the fixed Audi vehicle-list endpoint"
            )
        from .transport import (
            is_reviewed_identity_body,
            _GRAPHQL_MODERN_QUERY,
            validate_identity_body,
        )

        if not is_reviewed_identity_body(body):
            if not explicit_action:
                raise ValueError(
                    "Unexpected or unreviewed vehicle-list GraphQL request"
                )
            try:
                validate_identity_body(body)
            except ValueError as err:
                raise ValueError("Unreviewed GraphQL document") from err
        host = (
            "app-api.my.aoa.audi.com"
            if auth.country == "US"
            else "app-api.live-my.audi.com"
        )
        headers = _headers(auth.access_token(self.family))
        headers.update(
            {
                "X-User-Country": auth.country,
                "Accept-Language": _inventory_locale(auth),
                "Accept-Charset": "utf-8",
                "Content-Type": "application/json; charset=utf-8",
            }
        )
        if body["query"] == _GRAPHQL_MODERN_QUERY:
            headers.update(
                {"X-App-Version": "5.5.1", "User-Agent": "myAudi/5.5.1 Android/34"}
            )
        return RequestPlan(self.family, method, f"https://{host}{path}", headers, body)


class MBBLegacyExecutor:
    family = "mbb"

    def __init__(self) -> None:
        self._trusted_hosts: dict[str, str] = {}

    def set_vehicle_home_region(self, vin: str, base_url: str) -> None:
        """Only Audi-verified, hard-allowlisted home-region hosts may be accepted."""
        from urllib.parse import urlsplit as split

        parts = split(base_url)
        if (
            parts.scheme != "https"
            or parts.hostname not in LEGACY_REGION_HOSTS
            or parts.username
            or parts.password
            or parts.port
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError("Untrusted legacy MBB home region")
        if not isinstance(vin, str) or len(vin) != 17 or not vin.isalnum():
            raise ValueError("Invalid VIN for MBB host")
        self._trusted_hosts[vin.upper()] = "https://" + parts.hostname

    def plan(
        self,
        auth: Any,
        method: str,
        path: str,
        body: Any = None,
        *,
        explicit_action: bool = False,
        security_token: str | None = None,
        region_vin: str | None = None,
    ) -> RequestPlan:
        import re

        if auth.uses_auth0:
            raise ValueError("Legacy MBB must not be probed on an Auth0 vehicle")
        resource = _checked_path(path)
        trip = re.fullmatch(
            r"/api/bs/tripstatistics/v1/vehicles/[A-Za-z0-9]{17}/tripdata/(shortTerm|longTerm)",
            resource,
        )
        if ("?" in path and not trip) or method not in ("GET", "POST"):
            raise ValueError("Unreviewed MBB route")
        match = re.search(r"/vehicles/([A-Za-z0-9]{17})(?:/|$)", resource)
        if (
            not match
            and resource
            != "/api/rolesrights/authorization/v2/security-pin-auth-completed"
        ):
            raise ValueError("Invalid MBB vehicle route")
        vin = match[1].upper() if match else region_vin
        if region_vin is not None and (
            not re.fullmatch(r"[A-Za-z0-9]{17}", region_vin)
            or (match and region_vin.upper() != match[1].upper())
        ):
            raise ValueError("Invalid MBB region VIN")
        # Reads and setter requests are deliberately isolated. The default
        # region is the historical upstream default, never an arbitrary URL.
        host = self._trusted_hosts.get(vin, LEGACY_BASE)
        setter = self._trusted_hosts.get(vin, "https://mal-1a.prd.ece.vwg-connect.com")
        if setter == LEGACY_BASE:
            setter = "https://mal-1a.prd.ece.vwg-connect.com"
        if setter.startswith("https://fal-"):
            setter = setter.replace("https://fal-", "https://mal-", 1)
        if host == "https://mal-1a.prd.ece.vwg-connect.com":
            host = LEGACY_BASE
        headers = _headers(auth.access_token(self.family))
        climate = re.fullmatch(
            r"/(?:fs-car/bs/climatisation/v1/Audi/[A-Z]{2}/vehicles|api/bs/climatisation/v1/vehicles)/[A-Za-z0-9]{17}/climater/actions(?:/[A-Za-z0-9_-]{1,100})?",
            resource,
        )
        rlu = re.fullmatch(
            r"/api/bs/rlu/v1/vehicles/[A-Za-z0-9]{17}/(?:lock|unlock|requests/[A-Za-z0-9_-]{1,100}/status)",
            resource,
        )
        challenge = re.fullmatch(
            r"/api/rolesrights/authorization/v2/vehicles/[A-Za-z0-9]{17}/services/rlu_v1/operations/(LOCK|UNLOCK)/security-pin-auth-requested",
            resource,
        )
        complete = (
            resource == "/api/rolesrights/authorization/v2/security-pin-auth-completed"
        )
        home = re.fullmatch(
            r"/api/cs/vds/v1/vehicles/[A-Za-z0-9]{17}/homeRegion", resource
        )
        if home:
            if method != "GET" or body is not None:
                raise ValueError("Unreviewed MBB home-region request")
            host = "https://mal-1a.prd.ece.vwg-connect.com"
        elif trip:
            from urllib.parse import parse_qs

            query = parse_qs(urlsplit(path).query)
            if (
                method != "GET"
                or body is not None
                or set(query) != {"type", "from", "to"}
                or query["type"] != ["list"]
                or any(len(v) != 1 for v in query.values())
            ):
                raise ValueError("Unreviewed MBB trip query")
            host = setter
        elif challenge or complete or rlu:
            host = setter
            if not explicit_action:
                raise ValueError(
                    "MBB security/action routes require explicit user intent"
                )
            if challenge and (method != "GET" or body is not None):
                raise ValueError("Invalid MBB challenge")
            if complete:
                if not region_vin:
                    raise ValueError(
                        "MBB challenge completion requires its originating VIN"
                    )
                if (
                    method != "POST"
                    or not isinstance(body, dict)
                    or set(body) != {"securityPinAuthentication"}
                ):
                    raise ValueError("Invalid MBB security completion")
                headers["Content-Type"] = "application/json"
            if rlu:
                if resource.endswith(("/lock", "/unlock")):
                    if method != "POST" or body is not None or not security_token:
                        raise ValueError(
                            "MBB lock requires a completed S-PIN challenge"
                        )
                    headers["Content-Type"] = (
                        "application/vnd.vwg.mbb.RemoteLockUnlock_v1_0_0+xml"
                    )
                    headers["x-securityToken"] = security_token
                elif method != "GET" or body is not None:
                    raise ValueError("Invalid MBB RLU status request")
        elif climate:
            if resource.startswith("/api/"):
                host = "https://mal-3a.prd.eu.dp.vwg-connect.com"
            if resource.endswith("/actions"):
                if (
                    method != "POST"
                    or not explicit_action
                    or not isinstance(body, dict)
                    or set(body) != {"action"}
                    or not isinstance(body["action"], dict)
                    or body["action"].get("type")
                    not in ("startClimatisation", "stopClimatisation")
                ):
                    raise ValueError("Invalid MBB climate action")
                headers["Content-Type"] = "application/json"
            elif method != "GET" or body is not None:
                raise ValueError("Invalid MBB climate status")
        elif (
            method != "GET"
            or body is not None
            or not resource.startswith(("/fs-car/bs/", "/fs-car/vehicleMgmt/"))
        ):
            raise ValueError("Unreviewed MBB route; GET only outside approved controls")
        if security_token and not (rlu and resource.endswith(("/lock", "/unlock"))):
            raise ValueError("MBB security token outside approved lock command")
        return RequestPlan(self.family, method, host + path, headers, body)


def build_family_executors() -> dict[str, FamilyExecutor]:
    return {
        "cariad": CARIADExecutor(),
        "graphql": GraphQLExecutor(),
        "mbb": MBBLegacyExecutor(),
    }
