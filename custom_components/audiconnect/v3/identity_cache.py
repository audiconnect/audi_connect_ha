"""Private VIN-scoped manufacturer metadata; never an authorization source."""

import re
from datetime import datetime
from .vehicle import model_family_from_name, select_vehicle_image


def validated_image(url, vin=None):
    return select_vehicle_image(
        {"renderPictures": [{"url": url, "mediaType": "MYAPN8NB"}]},
        vin or "{VIN_NOT_AVAILABLE}",
    )


def validate_identity(row, region, vin=None):
    if not isinstance(row, dict) or row.get("region") != region:
        return {}
    model, source, year = row.get("model"), row.get("source"), row.get("year", "")
    stamp = row.get("observed_at")
    from .data_act import IDENTITY_OPERATION

    optional = (
        row.get("operation") == IDENTITY_OPERATION
        and isinstance(source, str)
        and bool(re.fullmatch(r"eu_data_act_[A-Za-z0-9_./~-]{1,220}", source))
    )
    if (
        not isinstance(model, str)
        or not 0 < len(model) <= 120
        or model.strip().lower()
        in ("", "unknown", "invalid", "unavailable", "unsupported", "error", "vehicle")
        or (
            not optional
            and source
            not in (
                "audi_long_name",
                "audi_short_name",
                "cariad_model",
                "cariad_carModel",
                "eu_data_act_modelName",
            )
        )
        or not isinstance(year, str)
        or (
            year
            and (not year.isdigit() or len(year) != 4 or not 1980 <= int(year) <= 2100)
        )
    ):
        return {}
    try:
        if datetime.fromisoformat(stamp).tzinfo is None:
            return {}
    except (TypeError, ValueError):
        return {}
    from .transport import IDENTITY_OPERATIONS, INVENTORY_OPERATION, GARAGE_OPERATION

    operations = IDENTITY_OPERATIONS | {IDENTITY_OPERATION}
    operation = row.get("operation", INVENTORY_OPERATION)
    if optional or source == "eu_data_act_modelName":
        operation = IDENTITY_OPERATION
    elif operation not in IDENTITY_OPERATIONS or operation.endswith(".images"):
        operation = (
            GARAGE_OPERATION if source.startswith("cariad_") else INVENTORY_OPERATION
        )
    year_operation = row.get("year_operation")
    if year_operation not in operations or year_operation.endswith(".images"):
        year_operation = operation if year else None
    return {
        "model": model,
        "source": source,
        "year": year,
        "region": region,
        "operation": operation,
        "family": model_family_from_name(model),
        "observed_at": stamp,
        "year_operation": year_operation,
        **(
            {"image_url": image}
            if (image := validated_image(row.get("image_url"), vin))
            else {}
        ),
    }


def without_optional_identity(row):
    """Keep native manufacturer metadata; optional fields require portal access."""
    from .data_act import IDENTITY_OPERATION

    if (
        row.get("operation") == IDENTITY_OPERATION
        or row.get("source") == "eu_data_act_modelName"
    ):
        return {}
    if row.get("year_operation") == IDENTITY_OPERATION:
        return {**row, "year": "", "year_operation": None}
    return row


def withdraw_optional_identity(car, profile):
    """Withdraw only portal-owned identity, never native observations or trips."""
    from .data_act import IDENTITY_OPERATION

    before = car.context
    changed = False
    if (
        car.identity_operation == IDENTITY_OPERATION
        or car.model_source == "eu_data_act_modelName"
    ):
        if car.name == car.model:
            car.name = "Audi vehicle"
        car.model = car.model_family = car.model_source = ""
        car.identity_operation = car.identity_observed_at = None
        car.identity_restored = False
        car.registry_model = None
        car.readings.pop("model", None)
        car.family_readings.pop("model", None)
        changed = True
    if car.year_operation == IDENTITY_OPERATION:
        car.model_year = ""
        car.year_operation = None
        changed = True
    saved = profile.manufacturer_identity
    retained = without_optional_identity(saved)
    if retained != saved:
        profile.manufacturer_identity = retained
        changed = True
    if before != car.context:
        # Applicability is context-scoped; archive old control evidence without
        # discarding independent native telemetry or the VIN trip archive.
        profile.rebind_context(car.context)
    return changed


def apply_cached_identity(car, row):
    identity = validate_identity(row, car.country, car.vin)
    if (
        identity
        and (not car.model or car.model == identity["model"])
        and identity.get("image_url")
    ):
        car.image_url = identity["image_url"]
        car.image_status = "observed"
    if not car.model and identity:
        car.model = identity["model"]
        car.model_family = identity["family"]
        if not car.model_year:
            car.model_year = identity["year"]
            car.year_operation = identity["year_operation"]
        car.model_source = identity["source"]
        car.identity_restored = True
        car.identity_observed_at = identity["observed_at"]
        car.identity_operation = identity["operation"]
        if car.name == "Audi vehicle":
            car.name = car.model


def capture_identity(car):
    if car.identity_restored or not car.model or not car.identity_observed_at:
        return {}
    return validate_identity(
        {
            "model": car.model,
            "source": car.model_source,
            "year": car.model_year,
            "region": car.country,
            "observed_at": car.identity_observed_at,
            "operation": car.identity_operation,
            "year_operation": car.year_operation,
            "image_url": car.image_url,
        },
        car.country,
        car.vin,
    )


def previous_registry_model(hass, entry, vin):
    """Presentation-only migration aid. No other integration or user label."""
    from homeassistant.helpers import device_registry as dr
    from ..const import DOMAIN

    try:
        registry = dr.async_get(hass)
        device = registry.async_get_device(identifiers={(DOMAIN, vin.lower())})
    except (AttributeError, KeyError, RuntimeError):
        return None
    if (
        device is None
        or entry.entry_id not in device.config_entries
        or device.manufacturer != "Audi"
    ):
        return None
    model = device.model
    if (
        isinstance(model, str)
        and 0 < len(model.strip()) <= 120
        and model.strip().lower()
        not in ("audi", "audi vehicle", "unknown", "unavailable", "none")
    ):
        return model.strip()
    return None
