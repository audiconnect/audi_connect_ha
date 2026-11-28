"""V3 command payload normalization, based on reviewed historical Audi routes."""

from __future__ import annotations

from typing import Any
from .auth import configured_spin
from .registry import read_json_path, selective_status_path
from .command_parameters import (
    SOC,
    PROFILE_CURRENT,
    DURATION,
    TEMPERATURE,
    CLIMATE_INPUTS,
    CLIMATE_SETTINGS_INPUTS,
    validate_inputs,
    validate_parameter,
    temperature_celsius,
    CLIMATE_SETTING_FIELDS,
    CLIMATE_START_OVERRIDES,
)

CHARGE_FIELDS = frozenset(
    {
        "maxChargeCurrentAC_A",
        "maxChargeCurrentAC",
        "autoUnlockPlugWhenChargedAC",
        "targetSOC_pct",
    }
)
CLIMATE_FIELDS = frozenset(CLIMATE_SETTINGS_INPUTS) - TEMPERATURE.keys()
OVERRIDES = CLIMATE_START_OVERRIDES
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
        selective_status_path(vin, job),
        command_preparation=1,
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
    if strict:
        validate_inputs(params, {"value": SOC})
    else:
        validate_inputs(params, CLIMATE_SETTINGS_INPUTS)
    updates = {"targetSOC_pct": params["value"]} if strict else dict(params)
    if not updates:
        raise ValueError("Unknown climatisation setting")
    current = await settings(transport, vin, job, path)
    if not strict and TEMPERATURE.keys() & updates.keys():
        target = temperature_celsius(updates, None)
        if "targetTemperature_C" not in current:
            raise ValueError("Vehicle has not reported a Celsius setpoint")
        for key in TEMPERATURE:
            updates.pop(key, None)
        updates["targetTemperature_C"] = target
        if type(current.get("targetTemperature_F")) in (int, float):
            fahrenheit = target * 9 / 5 + 32
            updates["targetTemperature_F"] = (
                round(fahrenheit)
                if type(current["targetTemperature_F"]) is int
                else round(fahrenheit, 1)
            )
    if set(updates) - allowed:
        raise ValueError("Unknown climatisation setting")
    if strict and set(current) - allowed - {"carCapturedTimestamp"}:
        raise ValueError("Unrecognized charging settings; refusing destructive PUT")
    if not strict and any(
        key not in current
        or current[key] is None
        or (key in CLIMATE_SETTING_FIELDS and type(current[key]) is not bool)
        for key in updates
    ):
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
    if mode in ("charging_profile_update", "charging_profile_current_update"):
        from .vehicle import PROFILE_CURRENT_OPTIONS, unique_charging_profile

        current_mode = mode == "charging_profile_current_update"
        # None is the existing native active-location number's optional ID.
        params = {k: v for k, v in params.items() if k != "profile_id" or v is not None}
        validate_inputs(
            params,
            {
                "value": PROFILE_CURRENT if current_mode else SOC,
                "profile_id": {"type": "integer"},
            },
        )
        value = params["value"]
        current = await settings(
            transport,
            vin,
            "chargingProfiles",
            "chargingProfiles.chargingProfilesStatus.value",
        )
        active_id = current.get("vehiclePositionedInProfileID")
        ident = params.get("profile_id", active_id)
        if current_mode and (
            type(active_id) is not int
            or active_id != ident
            or active_id != car.active_charging_profile_id
        ):
            raise ValueError("Audi charging location changed; no mutation sent")
        profile = unique_charging_profile(current.get("profiles"), ident)
        if profile is None:
            raise ValueError("Audi charging profile not found or ambiguous")
        field = "maxChargingCurrent" if current_mode else "targetSOC_pct"
        if current_mode and profile.get(field) not in PROFILE_CURRENT_OPTIONS:
            raise ValueError("Location AC current is not reported by this vehicle")
        return {"profile": {**profile, field: value}}
    if mode == "climate_start_settings":
        validate_inputs(params, CLIMATE_INPUTS)
        current = await settings(
            transport, vin, "climatisation", "climatisation.climatisationSettings.value"
        )
        target = temperature_celsius(params, current.get("targetTemperature_C"))
        body = {
            k: current[k]
            for k in PASSTHROUGH
            if k in current
            and current[k] is not None
            and (k not in CLIMATE_SETTING_FIELDS or type(current[k]) is bool)
        }
        body.update(targetTemperature=target, targetTemperatureUnit="celsius")
        reported_mode = current.get("climatisationMode")
        requested_mode = params.get("climatisation_mode")
        if requested_mode is not None and requested_mode != reported_mode:
            raise ValueError("Climate mode is not reported by this vehicle")
        # Retain the reviewed historical default for the existing standard
        # start route; do not offer it as evidence of selectable modes.
        body["climatisationMode"] = (
            reported_mode if reported_mode in ("comfort", "economy") else "comfort"
        )
        for name, field in OVERRIDES.items():
            if name in params:
                if type(current.get(field)) is not bool:
                    raise ValueError("Climate setting not supported")
                body[field] = params[name]
        return body
    if mode == "flash":
        validate_inputs(params, {})
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
        spin = configured_spin(engine.auth)
        reply = await transport.request(
            "cariad",
            "PUT",
            f"/vehicle/v1/engine/{vin}/userpromptproof",
            body={"spin": spin},
            explicit_action=True,
            command_preparation=1,
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
        validate_inputs(params, {"duration": DURATION})
        spin = configured_spin(engine.auth)
        if not spin:
            raise ValueError("Auxiliary heating needs S-PIN")
        duration = validate_parameter(
            params.get("duration", DURATION["default"]), DURATION
        )
        return {"duration_min": duration, "spin": spin}
    raise ValueError("Unrecognized V3 request mode")


def resolve_secure_body(
    auth,
    profile,
    vehicle,
    ident: str,
    family: str,
    method: str,
    path: str,
    body: Any,
) -> Any:
    """Resolve credentials last, exclusively for reviewed door controls.

    Secret values are never part of route definitions, local profiles,
    response previews or WebSocket payloads. No URL substitutions.
    """
    if "{SPIN}" not in str(body):
        return body
    built_in = ident in ("cariad.access.lock", "cariad.access.unlock")
    custom = profile.custom.get(ident)
    is_reviewed = built_in or (
        custom is not None
        and custom["capability"] == "access"
        and custom["aspect"] in ("lock", "unlock")
    )
    allowed_paths = {
        f"/vehicle/v1/vehicles/{vehicle.vin}/access/lock",
        f"/vehicle/v1/vehicles/{vehicle.vin}/access/unlock",
    }
    if (
        not is_reviewed
        or family != "cariad"
        or method != "POST"
        or path not in allowed_paths
        or body != {"spin": "{SPIN}"}
    ):
        raise ValueError("Secure S-PIN template is not permitted for this command")
    spin = configured_spin(auth)
    if not isinstance(spin, str) or not spin:
        raise ValueError("Configure an Audi S-PIN to use remote door controls")
    return {"spin": spin}
