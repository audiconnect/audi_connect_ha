"""Independent V3 MBB command payloads and bounded request-status readback.

The historical V2 lock uses a security challenge, not the CARIAD PIN body.
Secrets stay in memory. No failed command is retried or routed to CARIAD.
"""

from __future__ import annotations
import asyncio
import hashlib
import re
from .registry import read_json_path
from .command_parameters import CLIMATE_INPUTS, temperature_celsius, validate_inputs

_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def climate_body(mode, params):
    if mode == "mbb_climate_stop":
        if params:
            raise ValueError("Legacy climate stop has no parameters")
        return {"action": {"type": "stopClimatisation"}}
    validate_inputs(
        params,
        {**CLIMATE_INPUTS, "climatisation_mode": {"type": "string", "enum": ["comfort"]}},
    )
    temp = temperature_celsius(params, 21)
    return {
        "action": {
            "type": "startClimatisation",
            "settings": {
                "targetTemperature": int(temp * 10 + 2731),
                "climatisationWithoutHVpower": True,
                "heaterSource": "electric",
                "climaterElementSettings": {
                    "isClimatisationAtUnlock": bool(
                        params.get("climatisation_at_unlock")
                    ),
                    "isMirrorHeatingEnabled": bool(params.get("glass_heating")),
                    "zoneSettings": {
                        "zoneSetting": [
                            {
                                "value": {
                                    "isEnabled": bool(params.get(key)),
                                    "position": position,
                                }
                            }
                            for key, position in (
                                ("seat_fl", "frontLeft"),
                                ("seat_fr", "frontRight"),
                                ("seat_rl", "rearLeft"),
                                ("seat_rr", "rearRight"),
                            )
                        ]
                    },
                },
            },
        }
    }


async def security_token(transport, vin, action, spin):
    if (
        action not in ("lock", "unlock")
        or not isinstance(spin, str)
        or not re.fullmatch(r"[0-9]{4}", spin)
    ):
        raise ValueError("Configured four-digit S-PIN required for legacy access")
    base = f"/api/rolesrights/authorization/v2/vehicles/{vin}/services/rlu_v1/operations/{action.upper()}"
    reply = await transport.request(
        "mbb", "GET", base + "/security-pin-auth-requested", explicit_action=True
    )
    challenge = read_json_path(
        reply.data, "securityPinAuthInfo.securityPinTransmission.challenge"
    )
    token = read_json_path(reply.data, "securityPinAuthInfo.securityToken")
    if (
        not 200 <= reply.status < 300
        or not isinstance(challenge, str)
        or not re.fullmatch(r"[0-9A-Fa-f]{2,512}", challenge)
        or len(challenge) % 2
        or not isinstance(token, str)
        or not token
    ):
        raise ValueError("Audi legacy challenge unavailable")
    # Original Audi protocol uses the hexadecimal PIN bytes and challenge bytes.
    digest = (
        hashlib.sha512(bytes.fromhex(spin) + bytes.fromhex(challenge))
        .hexdigest()
        .upper()
    )
    reply = await transport.request(
        "mbb",
        "POST",
        "/api/rolesrights/authorization/v2/security-pin-auth-completed",
        body={
            "securityPinAuthentication": {
                "securityPin": {"challenge": challenge, "securityPinHash": digest},
                "securityToken": token,
            }
        },
        explicit_action=True,
        region_vin=vin,
    )
    final = reply.data.get("securityToken") if isinstance(reply.data, dict) else None
    if (
        not 200 <= reply.status < 300
        or not isinstance(final, str)
        or not final
        or len(final) > 4096
        or any(ord(c) < 32 for c in final)
    ):
        raise ValueError("Audi legacy S-PIN authentication failed")
    return final


async def confirm(transport, path, payload, *, delay=4, max_reads=3):
    if path.endswith("/climater/actions"):
        request_id = read_json_path(payload, "action.actionId")
        if isinstance(request_id, int):
            request_id = str(request_id)
        status_path = "action.actionState"
        endpoint = path + "/" + str(request_id)
    else:
        request_id = read_json_path(payload, "rluActionResponse.requestId")
        if isinstance(request_id, int):
            request_id = str(request_id)
        status_path = "requestStatusResponse.status"
        endpoint = path.rsplit("/", 1)[0] + "/requests/" + str(request_id) + "/status"
    if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
        return "accepted_unconfirmed"
    for n in range(max_reads):
        if transport.remaining_calls is not None and transport.remaining_calls <= 12:
            return "quota_limited"
        if n:
            await asyncio.sleep(delay)
        try:
            reply = await transport.request(
                "mbb", "GET", endpoint, explicit_action=True
            )
        except (RuntimeError, ValueError, OSError, TimeoutError):
            return "accepted_unconfirmed"
        if not 200 <= reply.status < 300:
            return "accepted_unconfirmed"
        state = read_json_path(reply.data, status_path)
        if state in ("succeeded", "request_successful"):
            return "backend_completed"
        if state in ("failed", "request_failed"):
            return "rejected"
    return "accepted_unconfirmed"


async def configure_home_region(transport, auth, car):
    """Resolve a legacy region once, never follow arbitrary OEM URLs."""
    executor = transport.executors["mbb"]
    if car.vin.upper() in executor._trusted_hosts:
        return
    level = getattr(getattr(auth, "service", None), "_api_level", None)
    if car.country != "US" and level == 1:
        executor.set_vehicle_home_region(
            car.vin, "https://mal-3a.prd.eu.dp.vwg-connect.com"
        )
        return
    try:
        response = await transport.request(
            "mbb", "GET", f"/api/cs/vds/v1/vehicles/{car.vin}/homeRegion"
        )
        base = read_json_path(response.data, "homeRegion.baseUri.content")
        if isinstance(base, str) and base.endswith("/api"):
            base = base[:-4]
        if (
            200 <= response.status < 300
            and isinstance(base, str)
            and base != "https://mal-1a.prd.ece.vwg-connect.com"
        ):
            executor.set_vehicle_home_region(car.vin, base)
            return
    except (RuntimeError, ValueError, OSError, TimeoutError):
        pass
    executor.set_vehicle_home_region(car.vin, "https://msg.volkswagen.de")
