"""Support for tracking an Audi."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities = [
        AudiDeviceTracker(runtime_data.coordinator, tracker)
        for config_vehicle in runtime_data.account.config_vehicles
        for tracker in config_vehicle.device_trackers
    ]
    async_add_entities(entities)


class AudiDeviceTracker(AudiEntity, TrackerEntity):
    _attr_icon = "mdi:car"
    _attr_should_poll = False
    _attr_source_type = SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self._coords()[0]

    @property
    def longitude(self) -> float | None:
        return self._coords()[1]

    def _coords(self) -> tuple[float | None, float | None]:
        state = getattr(self._instrument, "state", None)
        if isinstance(state, (list, tuple)) and len(state) >= 2:
            try:
                return float(state[0]), float(state[1])
            except (TypeError, ValueError):
                return None, None
        return None, None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = dict(getattr(self._instrument, "attributes", {}))
        attrs.update(
            {
                "model": f"{getattr(self._instrument, 'vehicle_model', 'Unknown')}/{self._instrument.vehicle_name}",
                "model_year": getattr(self._instrument, "vehicle_model_year", None),
                "model_family": getattr(self._instrument, "vehicle_model_family", None),
                "csid": getattr(self._instrument, "vehicle_csid", None),
                "vin": getattr(self._instrument, "vehicle_vin", None),
            }
        )
        return {k: v for k, v in attrs.items() if v is not None}
