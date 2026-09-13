from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AudiDataUpdateCoordinator


def entity_unique_id(vehicle: Any, platform: str, key: str) -> str:
    """The unique_id every platform builds, in one place.

    The registry lookup below only finds an existing entity if it asks for the
    exact string that entity was created with, so the format cannot be spelled
    out twice.
    """
    return f"{vehicle.vin.lower()}_{platform}_{key}"


def _capability_verdict(vehicle: Any, capability: str | None) -> bool | None:
    """What the car says about a capability: yes, no, or nothing at all."""
    if capability is None:
        return None
    if not hasattr(vehicle, "has_capability"):
        return None
    return vehicle.has_capability(capability)


def _present_in_this_poll(vehicle: Any, attr_key: str) -> bool:
    """The legacy Instrument.is_supported logic, unchanged.

    1. If a ``{attr_key}_supported`` property exists, return its truthiness.
    2. Otherwise, if the vehicle object has an ``attr_key`` attribute, True.
    3. Otherwise, False.
    """
    supported_attr = f"{attr_key}_supported"
    if hasattr(vehicle, supported_attr):
        return bool(getattr(vehicle, supported_attr))
    return hasattr(vehicle, attr_key)


def is_entity_supported(
    vehicle: Any, attr_key: str, capability: str | None = None
) -> bool:
    """Check if a vehicle supports a given entity attribute.

    Asks the car's capability list where one is named and the car reports it,
    and otherwise falls back to whether the value is in the poll we happen to
    be holding.

    That fallback asks the wrong question: a rate-limited or partial poll makes
    a car look like it lost a feature. On one vehicle a 429 removed sixteen
    entities, including a parking-position sensor for a car that plainly has
    parking position.

    The fallback survives anyway, because a car that reports no capability list
    must keep exactly the old behaviour: treating "did not say" as "not
    capable" would strip every entity from those vehicles. ``should_create_entity``
    is what covers the remaining gap, and is what the platforms call.
    """
    capable = _capability_verdict(vehicle, capability)
    if capable is not None:
        return capable
    return _present_in_this_poll(vehicle, attr_key)


def should_create_entity(
    hass: HomeAssistant,
    platform: str,
    key: str,
    vehicle: Any,
    attr_key: str,
    capability: str | None = None,
) -> bool:
    """Whether a platform should create this entity for this vehicle.

    The capability list is job-level: it answers "does this car do
    climatisation", never "does it report isMirrorHeatingActive". So an entity
    backed by a single field, inside a capability the car has, is still dropped
    when a poll arrives without that field, and a car with no capability list
    at all gets no protection from it whatsoever.

    An entity already in the registry is one this integration created for this
    car on an earlier, better poll. Recreating it costs nothing and it reports
    unavailable while the value is missing, which is the truthful state. Losing
    it deletes the user's history, their dashboard card and any automation
    referring to it.

    The car's own "no" still wins. A capability the car explicitly does not
    list is a statement about the vehicle rather than about this poll, so a
    stale registry entry does not resurrect an entity for a feature the car
    says it does not have.
    """
    if _capability_verdict(vehicle, capability) is False:
        return False
    if is_entity_supported(vehicle, attr_key, capability):
        return True
    registry = er.async_get(hass)
    unique_id = entity_unique_id(vehicle, platform, key)
    return registry.async_get_entity_id(platform, DOMAIN, unique_id) is not None


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


__all__ = [
    "AudiEntity",
    "entity_unique_id",
    "is_entity_supported",
    "should_create_entity",
]
