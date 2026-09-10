from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AudiDataUpdateCoordinator


def is_entity_supported(
    vehicle: Any, attr_key: str, capability: str | None = None
) -> bool:
    """Check if a vehicle supports a given entity attribute.

    Without a capability, mirrors the legacy Instrument.is_supported logic:
    1. If a ``{attr_key}_supported`` property exists, return its truthiness.
    2. Otherwise, if the vehicle object has an ``attr_key`` attribute, return True.
    3. Otherwise, return False.

    That logic asks whether the value is present in the poll we happen to be
    holding, which is not the same question as whether the car has the feature.
    A rate-limited or partial poll therefore deletes entities: on one vehicle a
    429 removed sixteen of them, including a parking-position sensor for a car
    that plainly has parking position.

    So when a ``capability`` is named and the car reports its capability list,
    that list decides instead, and a missing value becomes an unavailable entity
    rather than a deleted one.

    The fallback is the important half. A car that reports no capability list
    gets exactly the old behaviour, because treating "did not say" as "not
    capable" would strip every entity from those vehicles.
    """
    if capability is not None:
        capable = (
            vehicle.has_capability(capability)
            if hasattr(vehicle, "has_capability")
            else None
        )
        if capable is True:
            return True
        if capable is False:
            return False
        # None: the car said nothing about capabilities. Fall through.

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
