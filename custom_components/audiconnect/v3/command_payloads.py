"""V3 command payload normalization, based on reviewed historical Audi routes."""

from __future__ import annotations

from typing import Any
from .registry import read_json_path
from .command_parameters import SOC, DURATION, validate_parameter, temperature_celsius

CHARGE_FIELDS = frozenset(
    {
        "maxChargeCurrentAC_A",
        "maxChargeCurrentAC",
        "autoUnlockPlugWhenChargedAC",
        "targetSOC_pct",
    }
)
CLIMATE_FIELDS = frozenset(
    {
        "targetTemperature",
        "targetTemperature_C",
        "targetTemperature_F",
        "targetTemperatureUnit",
        "climatisationWithoutExternalPower",
        "climatizationAtUnlock",
        "windowHeatingEnabled",
        "heaterSource",
        "zoneFrontLeftEnabled",
        "zoneFrontRightEnabled",
        "zoneRearLeftEnabled",
        "zoneRearRightEnabled",
    }
)
OVERRIDES = {
    "climatisation_at_unlock": "climatizationAtUnlock",
    "glass_heating": "windowHeatingEnabled",
    "seat_fl": "zoneFrontLeftEnabled",
    "seat_fr": "zoneFrontRightEnabled",
    "seat_rl": "zoneRearLeftEnabled",
    "seat_rr": "zoneRearRightEnabled",
}
PASSTHROUGH = CLIMATE_FIELDS - {
    "targetTemperature",
    "targetTemperature_C",
    "targetTemperature_F",
    "targetTemperatureUnit",
}


def target_soc(value: Any) -> int:
    return validate_parameter(value, SOC)


async def settings(transport: Any, vin: str, job: str, path: str) -> dict:
    reply = await transport.request(
        "cariad",
        "GET",
        f"/vehicle/v1/vehicles/{vin}/selectivestatus?jobs={job}",
    )
    value = read_json_path(reply.data, path)
    if not 200 <= reply.status < 300 or not isinstance(value, dict) or not value:
        raise ValueError("Audi settings unavailable; no mutation sent")
    return value


# Reviewed settings contracts: preserve all unrelated fields according to the
# OEM endpoint's established behavior; never allow arbitrary replacement PUTs.
_SETTINGS_PATCHES = {
    "charging_settings_update": (
        "charging",
        "charging.chargingSettings.value",
        CHARGE_FIELDS,
        True,
    ),
    "climate_settings_update": (
        "climatisation",
        "climatisation.climatisationSettings.value",
        CLIMATE_FIELDS,
        False,
    ),
}


async def patch_settings(transport, vin, mode, params):
    job, path, allowed, strict = _SETTINGS_PATCHES[mode]
    updates = {"targetSOC_pct": target_soc(params.get("value"))} if strict else params
    current = await settings(transport, vin, job, path)
    if not updates or set(updates) - allowed:
        raise ValueError("Unknown climatisation setting")
    if strict and set(current) - allowed - {"carCapturedTimestamp"}:
        raise ValueError("Unrecognized charging settings; refusing destructive PUT")
    if not strict and any(key not in current for key in updates):
        raise ValueError("Setting is not reported by this vehicle")
    return {
        **{
            key: value
            for key, value in current.items()
            if key != "carCapturedTimestamp"
            and (not strict or key in allowed and value is not None)
        },
        **updates,
    }


async def build(engine: Any, car: Any, mode: str, params: dict) -> Any:
    vin, transport = car.vin, engine.transport
    if mode in _SETTINGS_PATCHES:
        return await patch_settings(transport, vin, mode, params)
    if mode == "charging_profile_update":
        value = target_soc(params.get("value"))
        current = await settings(
            transport,
            vin,
            "chargingProfiles",
            "chargingProfiles.chargingProfilesStatus.value",
        )
        ident = params.get("profile_id")
        if ident is None:
            ident = current.get("vehiclePositionedInProfileID")
        profiles = current.get("profiles")
        if type(ident) is not int or not isinstance(profiles, list):
            raise ValueError("No confirmed Audi charging profile")
        profile = next(
            (p for p in profiles if isinstance(p, dict) and p.get("id") == ident), None
        )
        if profile is None:
            raise ValueError("Audi charging profile not found")
        return {"profile": {**profile, "targetSOC_pct": value}}
    if mode == "climate_start_settings":
        current = await settings(
            transport, vin, "climatisation", "climatisation.climatisationSettings.value"
        )
        if set(params) - set(OVERRIDES) - {"temp_c", "temp_f", "climatisation_mode"}:
            raise ValueError("Unknown climate start parameter")
        target = temperature_celsius(params, current.get("targetTemperature_C"))
        body = {k: current[k] for k in PASSTHROUGH if k in current}
        body.update(
            targetTemperature=target,
            targetTemperatureUnit="celsius",
            climatisationMode=params.get("climatisation_mode")
            or current.get("climatisationMode")
            or "comfort",
        )
        for name, field in OVERRIDES.items():
            if params.get(name) is not None:
                if type(params[name]) is not bool or field not in current:
                    raise ValueError("Climate setting not supported")
                body[field] = params[name]
        return body
    if mode == "flash":
        point = car.position
        if not isinstance(point, dict) or not all(
            isinstance(point.get(k), (int, float)) for k in ("latitude", "longitude")
        ):
            raise ValueError("Audi parking position unavailable")
        return {
            "duration_s": 10,
            "mode": "flash",
            "userPosition": {
                "latitude": point["latitude"],
                "longitude": point["longitude"],
            },
        }
    if mode == "engine_start":
        # Only the OEM two-step proof sequence, for the already authorized VIN.
        # The proof is transient and never stored, logged or returned by HA.
        from .command_policy import eligible_operation

        if eligible_operation(car, engine.auth, "remote", "engine_start") is None:
            raise ValueError("Remote engine start not supported for this vehicle")
        if params:
            raise ValueError("Unexpected engine start parameters")
        spin = engine.auth.service._spin
        reply = await transport.request(
            "cariad",
            "PUT",
            f"/vehicle/v1/engine/{vin}/userpromptproof",
            body={"spin": spin},
            explicit_action=True,
        )
        proof = (
            reply.data.get("userPromptProof") if isinstance(reply.data, dict) else None
        )
        if (
            not 200 <= reply.status < 300
            or not isinstance(proof, str)
            or not proof
            or len(proof) > 4096
        ):
            raise ValueError(
                "Audi did not provide an engine start proof; no start sent"
            )
        return {"securedActivationData": proof, "spin": spin}
    if mode == "auxiliary_start":
        spin = getattr(engine.auth.service, "_spin", None)
        if not spin:
            raise ValueError("Auxiliary heating needs S-PIN")
        duration = validate_parameter(
            params.get("duration", DURATION["default"]), DURATION
        )
        return {"duration_min": duration, "spin": spin}
    raise ValueError("Unrecognized V3 request mode")
