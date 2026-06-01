from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AudiDataUpdateCoordinator


def is_entity_supported(vehicle: Any, attr_key: str) -> bool:
    """Check if a vehicle supports a given entity attribute.

    Mirrors the legacy Instrument.is_supported logic exactly:
    1. If a ``{attr_key}_supported`` property exists, return its truthiness.
    2. Otherwise, if the vehicle object has an ``attr_key`` attribute, return True.
    3. Otherwise, return False.
    """
    supported_attr = f"{attr_key}_supported"
    if hasattr(vehicle, supported_attr):
        return bool(getattr(vehicle, supported_attr))
    return hasattr(vehicle, attr_key)


class AudiEntity(CoordinatorEntity[AudiDataUpdateCoordinator]):
    """Base class for all Audi entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator)
        self._vehicle = vehicle

    @property
    def device_info(self) -> DeviceInfo:
        model_info = (self._vehicle.model or "Unknown").replace("Audi ", "")
        return DeviceInfo(
            identifiers={(DOMAIN, self._vehicle.vin.lower())},
            manufacturer="Audi",
            name=self._vehicle.title,
            model=f"{model_info} ({self._vehicle.model_year})",
        )


__all__ = ["AudiEntity", "is_entity_supported"]
