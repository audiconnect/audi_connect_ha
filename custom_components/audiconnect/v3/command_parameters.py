"""Canonical input binding for local, physically reviewed command variants.

The mapping is configuration; semantic limits and protected settings handlers
remain code-owned. Unbound experimental parameters never become HA controls.
"""

from __future__ import annotations

import math


# Shared input contracts for built-in command preparation and Workbench fields.
# Settings updates with heterogeneous OEM field types retain their reviewed handler.
SOC = {"type": "integer", "minimum": 20, "maximum": 100, "step": 5, "required": True}
DURATION = {"type": "integer", "minimum": 10, "maximum": 60, "step": 10, "default": 30}
TEMPERATURE = {
    "temp_c": {"type": "number", "minimum": 15, "maximum": 30},
    "temp_f": {"type": "number", "minimum": 59, "maximum": 86},
}
# Only these semantic parameters may bind to a raw template. Settings PUTs
# retain their reviewed read-modify-write handlers.
_BINDABLE = {("climate", "start_with_settings"): TEMPERATURE}

CLIMATE_FLAGS = {
    key: {"type": "boolean"}
    for key in (
        "glass_heating",
        "climatisation_at_unlock",
        "seat_fl",
        "seat_fr",
        "seat_rl",
        "seat_rr",
    )
}
CLIMATE_INPUTS = {
    **TEMPERATURE,
    **CLIMATE_FLAGS,
    "climatisation_mode": {"type": "string", "enum": ["comfort", "economy"]},
}
LEGACY_CLIMATE_INPUTS = {
    **CLIMATE_INPUTS,
    "climatisation_mode": {"type": "string", "enum": ["comfort"]},
}
CLIMATE_SETTINGS_INPUTS = {
    "targetTemperature": {"type": "number"},
    "targetTemperature_C": TEMPERATURE["temp_c"],
    "targetTemperature_F": TEMPERATURE["temp_f"],
    "targetTemperatureUnit": {"type": "string"},
    "heaterSource": {"type": "string"},
    **{
        name: {"type": "boolean"}
        for name in (
            "climatisationWithoutExternalPower",
            "climatizationAtUnlock",
            "windowHeatingEnabled",
            "zoneFrontLeftEnabled",
            "zoneFrontRightEnabled",
            "zoneRearLeftEnabled",
            "zoneRearRightEnabled",
        )
    },
}


def validate_parameter(value, schema):
    kind = schema["type"]
    valid = (
        (kind == "integer" and type(value) is int)
        or (kind == "number" and type(value) in (int, float) and math.isfinite(value))
        or (kind == "string" and isinstance(value, str))
        or (kind == "boolean" and type(value) is bool)
    )
    if not valid:
        raise ValueError("Invalid typed command parameter")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Command parameter is outside its approved enum")
    if ("minimum" in schema and value < schema["minimum"]) or (
        "maximum" in schema and value > schema["maximum"]
    ):
        raise ValueError("Command parameter is outside its approved range")
    if "step" in schema and (value - schema.get("minimum", 0)) % schema["step"]:
        raise ValueError("Command parameter is outside its approved step")
    return value


def validate_inputs(params, schema):
    """Validate only supplied, declared parameters; never discard extra inputs."""
    if set(params) - set(schema):
        raise ValueError("Unknown command parameter")
    for name, contract in schema.items():
        if name in params:
            validate_parameter(params[name], contract)
        elif contract.get("required"):
            raise ValueError("Missing required command parameter")


def temperature_celsius(params, default):
    value = params.get("temp_c")
    if params.get("temp_f") is not None:
        if value is not None:
            raise ValueError("Supply only one temperature unit")
        from .api_value_mappings import normalize_api_value

        value = normalize_api_value(
            validate_parameter(params["temp_f"], TEMPERATURE["temp_f"]),
            {"unit_class": "temperature", "from": "°F", "to": "°C"},
        )
    if value is None:
        value = default
    return validate_parameter(value, TEMPERATURE["temp_c"])


def parameter_schema(operation, route):
    """Expose the existing input contract; no credentials or vehicle values."""
    if operation.get("input_schema"):
        return operation["input_schema"]
    variables = operation.get("request_variables", {})
    if variables:
        bindings = route.get("parameter_bindings", {})
        if bindings:
            cap, action = route["capability"], route["aspect"]
            schema = _BINDABLE[(cap, action)]
            return {
                name: {
                    "type": variables[var],
                    "minimum": schema[name]["minimum"],
                    "maximum": schema[name]["maximum"],
                    "required": True,
                }
                for var, name in bindings.items()
            }
        return {
            name: {"type": kind, "required": True} for name, kind in variables.items()
        }
    return {
        "charging_settings_update": {"value": SOC},
        "charging_profile_update": {"value": SOC, "profile_id": {"type": "integer"}},
        "auxiliary_start": {"duration": DURATION},
        "climate_start_settings": CLIMATE_INPUTS,
        "mbb_climate_start": LEGACY_CLIMATE_INPUTS,
        "climate_settings_update": CLIMATE_SETTINGS_INPUTS,
    }.get(operation.get("request_mode"), {})


def validate_bindings(capability, aspect, variables, bindings):
    if not isinstance(bindings, dict) or set(bindings) != set(variables):
        raise ValueError("Runtime parameter bindings must cover every variable")
    schema = _BINDABLE.get((capability, aspect), {})
    if not bindings or len(bindings) != len(set(bindings.values())):
        raise ValueError("Invalid runtime parameter binding")
    if len(bindings) != 1:
        raise ValueError("Choose exactly one canonical temperature input")
    for variable, semantic in bindings.items():
        if semantic not in schema or variables[variable] not in ("integer", "number"):
            raise ValueError("Unapproved semantic parameter binding")
    return dict(bindings)


def map_parameters(route, supplied):
    bindings = route.get("parameter_bindings", {})
    if not bindings:
        return supplied
    schema = (
        route.get("input_schema") or _BINDABLE[(route["capability"], route["aspect"])]
    )
    variables = route.get("request_variables", route.get("variables", {}))
    supplied = supplied or {}
    if set(supplied) != set(bindings.values()):
        raise ValueError("Supply the exact declared semantic command parameters")
    rendered = {}
    for variable, semantic in bindings.items():
        value = supplied[semantic]
        validate_parameter(value, schema[semantic])
        if variables[variable] == "integer":
            if int(value) != value:
                raise ValueError("Command parameter requires an integer")
            value = int(value)
        rendered[variable] = value
    return rendered


def runtime_ready(route):
    return not route.get("variables") or bool(route.get("parameter_bindings"))
