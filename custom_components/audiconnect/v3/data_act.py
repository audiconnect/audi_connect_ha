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
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any


PORTAL = "https://eu-data-act.drivesomethinggreater.com"
MAX_ZIP_BYTES = 5_000_000
MAX_JSON_BYTES = 10_000_000
MAX_FIELDS = 10000
_VIN = re.compile(r"[A-Za-z0-9]{17}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")
_FILENAME = re.compile(r"[A-Za-z0-9_.-]{1,180}\.zip", re.IGNORECASE)


class DataActUnavailable(RuntimeError):
    """Bounded optional provider failure; never shared-account reauthentication."""


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


class DataActClient:
    """Read existing subscriptions with an isolated, already authorized session."""

    def __init__(self, session):
        self.session = session
        self._identifiers = {}
        self._last_file = {}

    async def _get(self, path, *, limit, headers=None, allow_empty=False):
        async with (
            asyncio.timeout(20),
            self.session.get(
                PORTAL + path, headers=headers, allow_redirects=False
            ) as response,
        ):
            if response.status == 404 and allow_empty:
                return None
            if response.status != 200:
                raise DataActUnavailable("Data Act read unavailable")
            if response.content_length is not None and response.content_length > limit:
                raise DataActUnavailable("Data Act response too large")
            chunks = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                chunks.extend(chunk)
                if len(chunks) > limit:
                    raise DataActUnavailable("Data Act response too large")
            return bytes(chunks)

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
        prefix = "/proxy_api/euda-apim/"
        identifier = self._identifiers.get(vin)
        if identifier is None:
            meta = await self._json(
                prefix + f"datarequest/vehicles/{vin}/metadata/partial"
            )
            identifier = meta.get("Identifier") if isinstance(meta, dict) else None
            if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
                raise DataActUnavailable("No authorized Data Act subscription")
            self._identifiers[vin] = identifier
        path = prefix + f"datadelivery/vehicles/{vin}/{identifier}/"
        result = await self._json(
            path + "list", headers={"type": "partial"}, allow_empty=True
        )
        files = result.get("files") if isinstance(result, dict) else result
        if files is None:
            return None
        if not isinstance(files, list) or len(files) > 2000:
            raise DataActUnavailable("Invalid Data Act listing")
        content = []
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
            ):
                content.append((delivered, name))
        if not content:
            return None
        delivered, name = max(content)
        previous = self._last_file.get(vin)
        if previous is not None and (delivered, name) <= previous:
            return None
        raw = await self._get(
            path + "download",
            limit=MAX_ZIP_BYTES,
            headers={"filename": name, "type": "partial"},
        )
        payload = decode_dataset(raw, vin)
        self._last_file[vin] = (delivered, name)
        return payload, delivered.isoformat()
