"""Optional per-vehicle, locally maintained Audi service metadata.

No Audi API calls, no HAR credentials; values are HA config entry options.
"""
from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlsplit

CONF_LOCAL_DEALERS = "local_dealers"
DEALER_FIELDS = (
    "dealer_name", "dealer_city", "dealer_address", "dealer_phone",
    "dealer_website", "next_service_date", "warranty_expiry",
)

def get_local_dealer(options: dict[str, Any], vin: str) -> dict[str, str]:
    """Retrieve manual data. VIN remains private, never exported in diagnostics."""
    dealers = options.get(CONF_LOCAL_DEALERS, {})
    if not isinstance(dealers, dict):
        return {}
    record = dealers.get(vin.lower(), {})
    if not isinstance(record, dict):
        return {}
    return {k: v for k, v in record.items()
            if k in DEALER_FIELDS and isinstance(v, str) and v}

def update_local_dealer_options(
    options: dict[str, Any], vin: str, updates: dict[str, Any], *, clear: bool = False,
) -> dict[str, Any]:
    """Validate a partial update without affecting other vehicle settings."""
    if not isinstance(vin, str) or not vin.strip():
        raise ValueError("Unknown vehicle")
    if set(updates) - set(DEALER_FIELDS):
        raise ValueError("Unsupported dealer field")
    existing = options.get(CONF_LOCAL_DEALERS, {})
    dealers = dict(existing) if isinstance(existing, dict) else {}
    key = vin.lower()
    if clear:
        dealers.pop(key, None)
    else:
        record = get_local_dealer(options, vin)
        for field, value in updates.items():
            if not isinstance(value, str):
                raise ValueError("Dealer values must be text")
            value = value.strip()
            if len(value) > 255 or any(ch in value for ch in "\r\n"):
                raise ValueError("Invalid dealer field")
            if field in ("next_service_date", "warranty_expiry") and value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError("Use YYYY-MM-DD") from exc
            if field == "dealer_website" and value:
                url = urlsplit(value)
                if (url.scheme not in ("https", "http") or not url.hostname
                    or url.username is not None or url.password is not None):
                    raise ValueError("Dealer URL must be http(s) with no credentials")
            if value:
                record[field] = value
            else:
                record.pop(field, None)
        if record:
            dealers[key] = record
        else:
            dealers.pop(key, None)
    out = dict(options)
    if dealers:
        out[CONF_LOCAL_DEALERS] = dealers
    else:
        out.pop(CONF_LOCAL_DEALERS, None)
    return out
