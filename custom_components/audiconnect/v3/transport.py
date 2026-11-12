"""V3-owned Audi API transport and per-entry cloud request accounting.

Owns all V3 business GET/POSTs. Auth provider only supplies scoped bearer tokens.
Never execute a user-provided absolute URL or untrusted Authorization header.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .auth import V3Auth
from .family_executors import build_family_executors
from .quota import QuotaBudget

INVENTORY_OPERATION = "graphql.inventory.vehicleList"
GARAGE_OPERATION = "cariad.inventory.vehicles"
GARAGE_PATH = "/vehicle/v1/vehicles"
POST_GARAGE_OPERATION = "graphql.inventory.afterGarage"
_GRAPHQL_QUERY = """query vehicleList {
  userVehicles {
    vin
    nickname
    vehicle { core { modelYear } media { shortName longName }
              classification { driveTrain } }
  }
}"""


# Optional OEM render discovery is deliberately separate from identity.
# Public reference: vwgroup-connect-ha/cariad/api/graphql.py (renderPictures).
_GRAPHQL_IMAGES_QUERY = """query vehicleImages {
  userVehicles {
    vin
    vehicle { renderPictures { mediaType url } }
  }
}"""


# Fixed reviewed read-only queries, not arbitrary POSTs.
_GRAPHQL_EXTENDED_QUERY = """query vehicleList {
 userVehicles {
 vin mappingVin
 vehicle { core { modelYear } media { shortName longName } }
 csid commissionNumber type devicePlatform mbbConnect userRole { role }
 vehicle { classification { driveTrain } }
 nickname
 }
}"""
_GRAPHQL_MODERN_QUERY = _GRAPHQL_QUERY.replace(
    "query vehicleList", "query vehicleMetadata"
)
# HAR-observed myAudi web query. Test the document against the already
# authorized native GraphQL endpoint, NOT the browser-cookie web proxy.
# Fixed document and exact variables only; no browser credential import.
WEB_ORDERED_OPERATION = "graphql.inventory.webOrdered"
_WEB_ORDERED_QUERY = """query GET_USER_VEHICLES_ORDERED_BY($orderBy: VehicleSortOrder!) {
  userVehicles(orderBy: $orderBy) {
    csid
    userId
    vin
    owner
    nickname
    favorite
    devicePlatform
    mbbConnect
    userRole { role __typename }
    vehicle {
      brand { name __typename }
      classification { driveTrain __typename }
      core { vin modelYear modelCoding __typename }
      media { exteriorColor interiorColor shortName longName __typename }
      renderPictures(
        mediaTypes: ["MYAAN8NB", "MYAPN8NB", "MYAAN3NB", "MYAPN3NB", "MS_MYP3", "MS_MYP4", "MS_MYP5"]
      ) { mediaType url __typename }
      pdw { pdwVehicle __typename }
      __typename
    }
    __typename
  }
}"""

IDENTITY_QUERIES = {
    INVENTORY_OPERATION: _GRAPHQL_QUERY,
    "graphql.inventory.extended": _GRAPHQL_EXTENDED_QUERY,
    "graphql.inventory.modern": _GRAPHQL_MODERN_QUERY,
    "graphql.inventory.images": _GRAPHQL_IMAGES_QUERY,
    WEB_ORDERED_OPERATION: _WEB_ORDERED_QUERY,
}

IDENTITY_OPERATIONS = frozenset(
    (*IDENTITY_QUERIES, GARAGE_OPERATION, POST_GARAGE_OPERATION)
)
# afterGarage is retained only as a historical evidence/provenance identifier.


def identity_request_body(operation: str) -> dict[str, Any]:
    query = IDENTITY_QUERIES[operation]
    if operation == WEB_ORDERED_OPERATION:
        return {
            "operationName": "GET_USER_VEHICLES_ORDERED_BY",
            "variables": {"orderBy": "FAVORITE_AND_REGISTRATION"},
            "query": query,
        }
    return {"query": query}


def is_reviewed_identity_body(body: Any) -> bool:
    return isinstance(body, dict) and any(
        body == identity_request_body(op) for op in IDENTITY_QUERIES
    )


def validate_identity_query(
    query: str, variables: dict | None = None, operation_name: str | None = None
) -> None:
    """One bounded read-only userVehicles query, with reviewed argument forms.

    Field selection is editable at runtime. No aliases, mutations, fragments,
    directives, arbitrary hosts, account queries or credential-bearing arguments.
    Only the HAR-observed orderBy and renderPictures mediaTypes are parameterized.
    """
    if not isinstance(query, str) or not 0 < len(query) <= 4096:
        raise ValueError("Identity query length is invalid")
    variables = {} if variables is None else variables
    if not isinstance(variables, dict) or set(variables) - {"orderBy"}:
        raise ValueError("Unsupported identity variables")
    enum = r"[A-Z][A-Z0-9_]{0,63}"
    if "orderBy" in variables and (
        not isinstance(variables["orderBy"], str)
        or not re.fullmatch(enum, variables["orderBy"])
    ):
        raise ValueError("Invalid orderBy enum")
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|[A-Za-z_][A-Za-z0-9_]*|[^\s,]', query)
    index = count = 0
    declares_order = uses_order = False

    def take(expected=None):
        nonlocal index
        if index >= len(tokens):
            raise ValueError("Incomplete identity query")
        token = tokens[index]
        index += 1
        if expected is not None and token != expected:
            raise ValueError("Unsupported identity query syntax")
        return token

    def peek():
        return tokens[index] if index < len(tokens) else None

    def name(token):
        return bool(
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token)
        ) and not token.startswith("__")

    def arguments(path):
        nonlocal uses_order
        take("(")
        if path == ("userVehicles",):
            take("orderBy")
            take(":")
            if peek() == "$":
                take("$")
                take("orderBy")
                uses_order = True
            elif not re.fullmatch(enum, take()):
                raise ValueError("Invalid orderBy enum")
        elif path == ("userVehicles", "vehicle", "renderPictures"):
            take("mediaTypes")
            take(":")
            take("[")
            n = 0
            while peek() != "]":
                token = take()
                if not re.fullmatch(r'"[A-Z0-9_]{1,32}"', token) or n >= 16:
                    raise ValueError("Invalid media type")
                n += 1
            take("]")
            if not n:
                raise ValueError("Empty media types")
        else:
            raise ValueError("Unsupported identity argument")
        take(")")

    def selection(depth, path=()):
        nonlocal count
        if depth > 8:
            raise ValueError("Invalid identity selection")
        take("{")
        fields = {}
        while peek() != "}":
            field = take()
            count += 1
            if (
                not name(field)
                and not (field == "__typename" and depth > 1)
                or count > 64
                or field in fields
            ):
                raise ValueError("Invalid or duplicate identity field")
            child = (*path, field)
            if peek() == "(":
                arguments(child)
            fields[field] = selection(depth + 1, child) if peek() == "{" else None
        take("}")
        if not fields:
            raise ValueError("Empty identity selection")
        return fields

    query_name = None
    if peek() == "query":
        take("query")
        if peek() != "{":
            query_name = take()
            if not name(query_name):
                raise ValueError("Invalid query name")
        if peek() == "(":
            for token in ("(", "$", "orderBy", ":", "VehicleSortOrder", "!", ")"):
                take(token)
            declares_order = True
    tree = selection(1)
    if index != len(tokens) or set(tree) != {"userVehicles"}:
        raise ValueError("Only a single userVehicles query is supported")
    vehicle = tree["userVehicles"]
    if (
        not isinstance(vehicle, dict)
        or "vin" not in vehicle
        or vehicle["vin"] is not None
    ):
        raise ValueError(
            "Include the unaliased vin field for selected-vehicle isolation"
        )
    if declares_order != uses_order or declares_order != ("orderBy" in variables):
        raise ValueError("Declare and supply the orderBy variable exactly once")
    if operation_name is not None and (not query_name or operation_name != query_name):
        raise ValueError("operationName must match the query")


def validate_identity_body(body: Any) -> None:
    if (
        not isinstance(body, dict)
        or "query" not in body
        or set(body) - {"query", "variables", "operationName"}
        or ("variables" in body and not isinstance(body["variables"], dict))
        or ("operationName" in body and not isinstance(body["operationName"], str))
    ):
        raise ValueError("Unexpected identity request body")
    validate_identity_query(
        body["query"], body.get("variables"), body.get("operationName")
    )


def garage_rows(payload):
    rows = payload.get("data") if isinstance(payload, dict) else None
    return (
        [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    )


def selected_garage_response(response, vin):
    """Keep selected VIN and reviewed metadata only; no account inventory or nickname."""
    keys = (
        "vin",
        "model",
        "carModel",
        "modelYear",
        "model_year",
        "devicePlatform",
        "carnetAllocationType",
        "enrollmentStatus",
    )
    rows = [
        {
            key: row[key]
            for key in keys
            if key in row and (row[key] is None or type(row[key]) in (str, int))
        }
        for row in garage_rows(response.data)
        if isinstance(row.get("vin"), str) and row["vin"].lower() == vin.lower()
    ]
    return replace(response, data={"data": rows})


def identity_rows(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get("userVehicles") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def inventory_membership_complete(payload: Any) -> bool:
    """Only a complete, nonempty VIN inventory can support absence evidence.

    Optional metadata resolver failures do not invalidate known VINs. Root,
    membership and malformed-row errors cannot establish that a car is absent.
    """
    rows = identity_rows(payload)
    if not rows:
        return False
    seen = set()
    for row in rows:
        vin = row.get("vin") if isinstance(row, dict) else None
        if not isinstance(vin, str) or not re.fullmatch(r"[A-Za-z0-9]{17}", vin):
            return False
        key = vin.lower()
        if key in seen:
            return False
        seen.add(key)
    errors = payload.get("errors", [])
    if not isinstance(errors, list):
        return False
    for error in errors:
        path = error.get("path") if isinstance(error, dict) else None
        if (
            not isinstance(path, list)
            or len(path) < 3
            or path[0] != "userVehicles"
            or type(path[1]) is not int
            or not 0 <= path[1] < len(rows)
            or path[2] not in ("vehicle", "nickname")
        ):
            return False
    return True


def identity_errors(payload, vin):
    indexes = {
        i
        for i, row in enumerate(identity_rows(payload))
        if isinstance(row, dict) and str(row.get("vin", "")).lower() == vin.lower()
    }
    errors = payload.get("errors", []) if isinstance(payload, dict) else []
    result = []
    if not isinstance(errors, list):
        return result
    allowed = {
        "INTERNAL_SERVER_ERROR",
        "FORBIDDEN",
        "UNAUTHENTICATED",
        "BAD_USER_INPUT",
        "GRAPHQL_VALIDATION_FAILED",
        "NOT_FOUND",
        "SERVICE_UNAVAILABLE",
    }
    fields = {
        "userVehicles",
        "vehicle",
        "core",
        "media",
        "classification",
        "modelYear",
        "longName",
        "shortName",
        "driveTrain",
        "renderPictures",
        "nickname",
    }
    for error in errors[:32]:
        if not isinstance(error, dict):
            continue
        path = error.get("path")
        if (
            isinstance(path, list)
            and len(path) > 1
            and type(path[1]) is int
            and path[1] not in indexes
        ):
            continue
        ext = error.get("extensions")
        code = ext.get("code") if isinstance(ext, dict) else None
        message = error.get("message")
        reason = (
            "token_exchange_denied"
            if isinstance(message, str)
            and "client does not have access to the idp for token exchange"
            in message.lower()
            else None
        )
        result.append(
            {
                "code": code if isinstance(code, str) and code in allowed else "OTHER",
                **({"reason": reason} if reason else {}),
                "field": ".".join(x for x in path if isinstance(x, str) and x in fields)
                if isinstance(path, list)
                else "",
            }
        )
    return result


def selected_identity_response(response, vin):
    """Only selected vehicle, known fields, no image URLs or raw error messages."""
    rows = []
    for row in identity_rows(response.data):
        if not isinstance(row, dict) or str(row.get("vin", "")).lower() != vin.lower():
            continue
        vehicle = row.get("vehicle")
        safe = {}
        if isinstance(vehicle, dict):
            for group, keys in {
                "core": ("modelYear",),
                "media": ("shortName", "longName"),
                "classification": ("driveTrain",),
            }.items():
                if group not in vehicle:
                    continue
                value = vehicle[group]
                safe[group] = (
                    {
                        k: value[k]
                        for k in keys
                        if k in value
                        and (value[k] is None or type(value[k]) in (str, int))
                    }
                    if isinstance(value, dict)
                    else None
                )
            if "renderPictures" in vehicle:
                pictures = vehicle.get("renderPictures")
                safe["renderPictures"] = (
                    [
                        {
                            "mediaType": pic.get("mediaType"),
                            "url_present": bool(pic.get("url")),
                        }
                        for pic in pictures[:32]
                        if isinstance(pic, dict)
                        and isinstance(pic.get("mediaType"), str)
                        and len(pic["mediaType"]) <= 32
                    ]
                    if isinstance(pictures, list)
                    else None
                )
        rows.append(
            {
                "vin": row.get("vin"),
                "nickname": row.get("nickname"),
                "vehicle": safe if isinstance(vehicle, dict) else None,
            }
        )
    return replace(
        response,
        data={
            "data": {"userVehicles": rows},
            "errors": identity_errors(response.data, vin),
        },
    )


@dataclass(frozen=True)
class V3Response:
    status: int
    data: Any
    observed_at: datetime
    remaining_calls: int | None = None
    request: dict[str, Any] | None = field(default=None, repr=False, compare=False)


class V3Transport:
    """Audi region host allowlist and single-connection request budget."""

    def __init__(self, hass: Any, auth: V3Auth):
        self.auth = auth
        self.session = async_get_clientsession(hass)
        self.quota = QuotaBudget()
        self.last_cloud_poll: datetime | None = None
        self._request_lock = asyncio.Lock()
        self._request_count = 0
        self.executors = build_family_executors()
        self.last_inventory_metadata: V3Response | None = None
        self.last_inventory_errors: dict[str, list] = {}
        self.last_inventory_complete = False

    @property
    def remaining_calls(self) -> int | None:
        return self.quota.remaining

    @property
    def remaining_calls_observed_at(self) -> datetime | None:
        return self.quota.observed_at

    @property
    def request_count(self) -> int:
        return self._request_count

    async def request(
        self,
        family: str,
        method: str,
        path: str,
        *,
        body: Any = None,
        explicit_action: bool = False,
        security_token: str | None = None,
        region_vin: str | None = None,
    ) -> V3Response:
        if family not in self.executors:
            raise ValueError("Unknown or unsupported V3 executor")
        if security_token is not None and family != "mbb":
            raise ValueError("Security token is only valid for MBB RLU")
        kwargs = (
            {"security_token": security_token} if security_token is not None else {}
        )
        if region_vin is not None:
            if family != "mbb":
                raise ValueError("Region VIN is only valid for MBB")
            kwargs["region_vin"] = region_vin
        async with self._request_lock:
            # GraphQL inventory uses POST transport but is a fixed read-only query.
            read_only = method == "GET" or (
                family == "graphql"
                and method == "POST"
                and path == "/vgql/v1/graphql"
                and (
                    is_reviewed_identity_body(body)
                    or (explicit_action and isinstance(body, dict))
                )
            )
            if (
                family == "graphql"
                and read_only
                and not is_reviewed_identity_body(body)
            ):
                validate_identity_body(body)
            self.quota.authorize(datetime.now(UTC), read_only=read_only)
            await self.auth.ensure_ready()
            plan = self.executors[family].plan(
                self.auth, method, path, body, explicit_action=explicit_action, **kwargs
            )
            self.quota.reserve_request()
            async with asyncio.timeout(25):
                async with self.session.request(
                    plan.method,
                    plan.url,
                    headers=plan.headers,
                    json=plan.body if plan.body is not None else None,
                    allow_redirects=False,
                ) as response:
                    self._request_count += 1
                    self.quota.observe(
                        response.status, response.headers, datetime.now(UTC)
                    )
                    raw = await response.text()
                    try:
                        payload = (
                            await response.json(content_type=None)
                            if raw.strip()
                            else None
                        )
                    except (ValueError, TypeError):
                        payload = None
                    timestamp = datetime.now(UTC)
                    self.last_cloud_poll = timestamp
                    # 207 is partial and must not be interpreted as fully supported.
                    return V3Response(
                        status=response.status,
                        data=payload,
                        observed_at=timestamp,
                        remaining_calls=self.remaining_calls,
                        request={
                            "method": plan.method,
                            "url": plan.url,
                            "body": plan.body,
                            "auth_context": self.auth.identity_auth_evidence(family)
                            if hasattr(self.auth, "identity_auth_evidence")
                            else None,
                        },
                    )

    async def discover_vehicles(self) -> list[dict[str, Any]]:
        self.last_inventory_metadata = None
        self.last_inventory_errors = {}
        self.last_inventory_complete = False
        response = await self.request(
            "graphql",
            "POST",
            "/vgql/v1/graphql",
            body={"query": _GRAPHQL_QUERY},
            explicit_action=True,
        )
        if not 200 <= response.status < 300 or not isinstance(response.data, dict):
            raise RuntimeError("Audi vehicle discovery request failed")
        data = response.data.get("data")
        vehicles = data.get("userVehicles") if isinstance(data, dict) else None
        if not isinstance(vehicles, list):
            raise RuntimeError("Audi vehicle list unavailable (not an empty account)")
        self.last_inventory_complete = inventory_membership_complete(response.data)
        # Only request metadata is retained here, not an account-wide raw response.
        self.last_inventory_errors = {
            row["vin"].lower(): identity_errors(response.data, row["vin"])
            for row in vehicles
            if isinstance(row, dict) and isinstance(row.get("vin"), str)
        }
        self.last_inventory_metadata = replace(response, data=None)
        return [car for car in vehicles if isinstance(car, dict)]

    async def test_identity_query(self, operation: str) -> V3Response:
        if operation == GARAGE_OPERATION:
            return await self.request("cariad", "GET", GARAGE_PATH)
        if operation not in IDENTITY_QUERIES:
            raise ValueError("Unknown reviewed GraphQL read operation")
        return await self.request(
            "graphql",
            "POST",
            "/vgql/v1/graphql",
            body=identity_request_body(operation),
            explicit_action=True,
        )

    async def experiment_identity_query(
        self, query: str, variables: dict | None = None
    ) -> V3Response:
        body = {"query": query}
        if variables is not None:
            body["variables"] = variables
        validate_identity_body(body)
        return await self.request(
            "graphql", "POST", "/vgql/v1/graphql", body=body, explicit_action=True
        )

    async def discover_vehicle_images(self) -> dict[str, str]:
        """One optional fixed read query; no token exchange or fallback login."""
        response = await self.request(
            "graphql",
            "POST",
            "/vgql/v1/graphql",
            body={"query": _GRAPHQL_IMAGES_QUERY},
            explicit_action=True,
        )
        if not 200 <= response.status < 300 or not isinstance(response.data, dict):
            raise RuntimeError("Audi vehicle render query unavailable")
        data = response.data.get("data")
        rows = data.get("userVehicles") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("Audi vehicle render list unavailable")
        from .vehicle import select_vehicle_image

        result = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            vin = row.get("vin")
            if not isinstance(vin, str) or len(vin) != 17 or not vin.isalnum():
                continue
            vehicle = row.get("vehicle")
            url = select_vehicle_image(vehicle, vin)
            if url:
                result[vin.lower()] = url
        return result
