from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AudiDataUpdateCoordinator


class AudiEntity(CoordinatorEntity[AudiDataUpdateCoordinator]):
    """Base class for all Audi entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AudiDataUpdateCoordinator, instrument: Any) -> None:
        super().__init__(coordinator)
        self._instrument = instrument
        self._attr_unique_id = f"{instrument.vehicle_vin.lower()}_{instrument.component}_{instrument.slug_attr}"
        self._attr_name = instrument.name

    @property
    def icon(self) -> str | None:
        return self._instrument.icon

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._instrument.attributes)

    @property
    def device_info(self) -> DeviceInfo:
        model_info = (self._instrument.vehicle_model or "Unknown").replace("Audi ", "")
        return DeviceInfo(
            identifiers={(DOMAIN, self._instrument.vehicle_vin.lower())},
            manufacturer="Audi",
            name=self._instrument.vehicle_name,
            model=f"{model_info} ({self._instrument.vehicle_model_year})",
        )


__all__ = ["AudiEntity"]
