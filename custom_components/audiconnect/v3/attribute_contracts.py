"""Home Assistant-standard sensor metadata stored as declarative V3 contracts.

Extracted from V2 sensor descriptions. Values with unknown/dynamic units are
intentionally not guessed; route definitions may later supply a proven unit.
"""
from __future__ import annotations
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

@lru_cache(maxsize=1)
def attribute_contracts() -> dict[str, dict[str, Any]]:
    document = json.loads(Path(__file__).with_name("attribute_contracts.json").read_text())
    if document.get("schema_version") != 1 or not isinstance(document.get("attributes"), dict):
        raise ValueError("Invalid Audi V3 attribute contract")
    return document["attributes"]

def contract_for(entity_key: str) -> dict[str, Any]:
    return attribute_contracts().get(entity_key, {})


def binary_contract_for(entity_key: str) -> dict[str, Any]:
    return binary_contracts().get(entity_key, {})


@lru_cache(maxsize=1)
def binary_contracts() -> dict[str, dict[str, Any]]:
    path = Path(__file__).with_name("binary_contracts.json")
    return json.loads(path.read_text(encoding="utf-8"))["attributes"]

def semantic_value_issue(entity_key: str, value: Any, contract: dict | None = None) -> str | None:
    """Validate numeric telemetry without coercing booleans to numbers."""
    import math

    contract = contract if contract is not None else contract_for(entity_key)
    if entity_key == "oil_level" and type(value) is bool:
        return "boolean_oil_level_use_binary"
    if value is None:
        return None
    numeric = (contract.get("unit") is not None
               or contract.get("state_class") in ("measurement", "total", "total_increasing")
               or entity_key == "remaining_charging_time")
    if numeric and (type(value) not in (int, float)
                    or abs(value) > 1e100 or not math.isfinite(value)):
        return "numeric_type_required"
    if contract.get("unit") == "%" and not 0 <= value <= 100:
        return "percentage_out_of_range"
    if entity_key in ("remaining_charging_time", "remaining_climatisation_time",
                      "preheater_duration", "preheater_remaining") and value < 0:
        return "negative_duration"
    if entity_key == "climatisation_state" and isinstance(value, str) and value.strip().lower() in (
        "", "invalid", "unknown", "unsupported", "unavailable", "error"
    ):
        return "invalid_climate_state"
    return None
