"""EU Data Act read protocol: an independently authorized portal session only.

No login, consent creation, credential exchange, vehicle actions, scheduler or
HA entities here. The existing API owner supplies the authorized session.
Portal route shapes and field identities are evidence from the documented
research; they are not a public stable API contract.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from aiohttp import ClientError

from .quota import QuotaBudget

PORTAL = "https://eu-data-act.drivesomethinggreater.com"
MAX_ZIP_BYTES = 5_000_000
MAX_JSON_BYTES = 10_000_000
MAX_FIELDS = 10000
_VIN = re.compile(r"[A-Za-z0-9]{17}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")
_FILENAME = re.compile(r"[A-Za-z0-9_.-]{1,180}\.zip", re.IGNORECASE)


class DataActUnavailable(RuntimeError):
    """Bounded optional provider failure; never shared-account reauthentication."""


class DataActAuthorizationRequired(DataActUnavailable):
    """User interaction required; never retry credentials automatically."""


class DataActVehicleDenied(DataActUnavailable):
    """Explicit refusal of a vehicle-scoped portal resource."""


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(UTC) if stamp.tzinfo is not None else None


def decode_dataset(raw: bytes, vin: str) -> dict[str, Any]:
    """Never extract files; accept one bounded JSON member for the selected VIN."""
    if len(raw) > MAX_ZIP_BYTES or not _VIN.fullmatch(vin):
        raise DataActUnavailable("Invalid Data Act dataset envelope")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != 1:
                raise DataActUnavailable("Unexpected Data Act archive layout")
            member = members[0]
            name = PurePosixPath(member.filename)
            if (
                member.is_dir()
                or len(name.parts) != 1
                or "\\" in member.filename
                or name.suffix.lower() != ".json"
                or member.file_size > MAX_JSON_BYTES
            ):
                raise DataActUnavailable("Invalid Data Act archive member")
            with archive.open(member) as stream:
                decoded = stream.read(MAX_JSON_BYTES + 1)
                if len(decoded) > MAX_JSON_BYTES:
                    raise DataActUnavailable("Data Act member too large")
                payload = json.loads(decoded)
    except (zipfile.BadZipFile, ValueError, RuntimeError, OSError) as err:
        raise DataActUnavailable("Invalid Data Act dataset") from err
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("vin"), str)
        or payload["vin"].upper() != vin.upper()
        or not isinstance(payload.get("Data"), list)
        or len(payload["Data"]) > MAX_FIELDS
    ):
        raise DataActUnavailable("Invalid Data Act VIN or dataset schema")
    return payload


async def read_bounded(response, limit):
    """Read complete bounded bodies, even when the server chunks the response."""
    if response.content_length is not None and response.content_length > limit:
        raise DataActUnavailable("Data Act response too large")
    chunks = bytearray()
    async for chunk in response.content.iter_chunked(65536):
        chunks.extend(chunk)
        if len(chunks) > limit:
            raise DataActUnavailable("Data Act response too large")
    return bytes(chunks)


class DataActClient:
    """Read existing subscriptions with an isolated, already authorized session."""

    def __init__(self, session, login=None):
        self.session = session
        self._login = login
        self._logged_in = login is None
        self._reauth_path = None
        self.quota = QuotaBudget(reserve=0)
        self.authorization_required = False
        self._request_lock = asyncio.Lock()
        self._identifiers = {}
        self._last_file = {}
        self.delivery_states = {}

    @property
    def denied_vins(self):
        """A denial is a terminal delivery state, not a second mutable cache."""
        return {
            vin
            for vin, state in self.delivery_states.items()
            if state == "vehicle_access_denied"
        }

    async def _get(self, path, *, limit, headers=None, allow_empty=False):
        async with self._request_lock:
            if self.authorization_required:
                raise DataActUnavailable("Data Act authorization required")
            try:
                self.quota.authorize(datetime.now(UTC), read_only=True)
                self.quota.reserve_request()
                async with (
                    asyncio.timeout(20),
                    self.session.get(
                        PORTAL + path, headers=headers, allow_redirects=False
                    ) as response,
                ):
                    self.quota.observe(
                        response.status, response.headers, datetime.now(UTC)
                    )
                    if response.status == 401:
                        self.authorization_required = (
                            self._login is None or self._reauth_path is not None
                        )
                        self._reauth_path = path
                        self._logged_in = False
                        self.quota.retry_at = datetime.now(UTC) + timedelta(minutes=30)
                    elif response.status == 403:
                        raise DataActVehicleDenied("Data Act vehicle access denied")
                    if response.status == 404 and allow_empty:
                        return None
                    if response.status != 200:
                        raise DataActUnavailable("Data Act read unavailable")
                    raw = await read_bounded(response, limit)
                    if path == self._reauth_path:
                        self._reauth_path = None
                    return raw
            except (ClientError, OSError, TimeoutError, RuntimeError) as err:
                if isinstance(err, DataActUnavailable):
                    raise
                raise DataActUnavailable("Data Act request unavailable") from err

    async def _json(self, path, **kwargs):
        raw = await self._get(path, limit=MAX_JSON_BYTES, **kwargs)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError as err:
            raise DataActUnavailable("Invalid Data Act response") from err

    async def latest(self, vin):
        """One metadata lookup when needed, one list, at most one ZIP download."""
        if not isinstance(vin, str) or not _VIN.fullmatch(vin):
            raise DataActUnavailable("Invalid Data Act VIN")
        vin = vin.upper()
        if vin in self.denied_vins:
            return None
        self.delivery_states[vin] = "unavailable"
        try:
            result = await self._latest(vin)
        except DataActVehicleDenied:
            self.delivery_states[vin] = "vehicle_access_denied"
            self._identifiers.pop(vin, None)
            self._last_file.pop(vin, None)
            raise
        # Initial sign-in is proven only after a complete VIN read. A renewed
        # session must recover the actual failed resource, not another VIN.
        if self._reauth_path == "":
            self._reauth_path = None
        return result

    async def _latest(self, vin):
        if not self._logged_in:
            if self.authorization_required or self._login is None:
                raise DataActUnavailable("Data Act authorization required")
            try:
                await self._login(self.quota)
            except DataActAuthorizationRequired:
                self.authorization_required = True
                raise
            self._logged_in = True
            if self._reauth_path is None:
                self._reauth_path = ""
        prefix = "/proxy_api/euda-apim/"
        identifier = self._identifiers.get(vin)
        if identifier is None:
            meta = await self._json(
                prefix + f"datarequest/vehicles/{vin}/metadata/partial",
                allow_empty=True,
            )
            identifier = meta.get("Identifier") if isinstance(meta, dict) else None
            if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
                self.delivery_states[vin] = "subscription_unavailable"
                return None
            self._identifiers[vin] = identifier
        path = prefix + f"datadelivery/vehicles/{vin}/{identifier}/"
        result = await self._json(
            path + "list", headers={"type": "partial"}, allow_empty=True
        )
        if result is None:
            # A replaced or removed subscription can recover on the next due poll.
            self._identifiers.pop(vin, None)
            self._last_file.pop(vin, None)
            self.delivery_states[vin] = "subscription_unavailable"
            return None
        files = result.get("files") if isinstance(result, dict) else result
        if not isinstance(files, list) or len(files) > 2000:
            raise DataActUnavailable("Invalid Data Act listing")
        content = []
        now = datetime.now(UTC)
        for item in files:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            delivered = _timestamp(item.get("createdOn"))
            if (
                isinstance(name, str)
                and _FILENAME.fullmatch(name)
                and not name.lower().endswith("_no_content_found.zip")
                and delivered is not None
                and delivered <= now + timedelta(minutes=5)
            ):
                content.append((delivered, name))
        if not content:
            self.delivery_states[vin] = "no_nonempty_dataset"
            return None
        delivered, name = max(content)
        previous = self._last_file.get(vin)
        if previous is not None and (delivered, name) <= previous:
            self.delivery_states[vin] = "no_new_dataset"
            return None
        raw = await self._get(
            path + "download",
            limit=MAX_ZIP_BYTES,
            headers={"filename": name, "type": "partial"},
        )
        payload = await asyncio.to_thread(decode_dataset, raw, vin)
        self._last_file[vin] = (delivered, name)
        self.delivery_states[vin] = (
            "dataset_received" if payload["Data"] else "empty_dataset"
        )
        return payload, delivered.isoformat()
