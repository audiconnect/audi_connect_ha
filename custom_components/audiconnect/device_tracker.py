"""Support for tracking an Audi."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, entity_unique_id, should_create_entity
from .coordinator import AudiDataUpdateCoordinator
from .freshness import vehicle_age_minutes, vehicle_freshness

_POSITION_ATTR_KEY = "position"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    from .v3.engine import V3Engine
    if isinstance(runtime_data.v3, V3Engine):
        from .v3.ha_platforms import setup as v3_setup
        v3_setup("device_tracker", config_entry, async_add_entities)
        return
    entities = [
        AudiDeviceTracker(runtime_data.coordinator, config_vehicle.vehicle)
        for config_vehicle in runtime_data.account.config_vehicles
        if should_create_entity(
            hass,
            "device_tracker",
            _POSITION_ATTR_KEY,
            config_vehicle.vehicle,
            _POSITION_ATTR_KEY,
            "parkingPosition",
        )
    ]
    async_add_entities(entities)


class AudiDeviceTracker(AudiEntity, TrackerEntity):
    """Representation of an Audi device tracker."""

    _attr_icon = "mdi:car"
    _attr_name = "Position"
    _attr_should_poll = False
    _attr_source_type = SourceType.GPS
    _backing_attr = _POSITION_ATTR_KEY

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = entity_unique_id(
            vehicle, "device_tracker", _POSITION_ATTR_KEY
        )

    def _position(self) -> dict[str, Any]:
        """Return the position dict from the vehicle, or empty dict."""
        value = getattr(self._vehicle, _POSITION_ATTR_KEY, None)
        return value if isinstance(value, dict) else {}

    @property
    def latitude(self) -> float | None:
        pos = self._position()
        val = pos.get("latitude")
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
        return None

    @property
    def longitude(self) -> float | None:
        pos = self._position()
        val = pos.get("longitude")
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        position = self._position()
        captured = position.get("timestamp")
        attrs = {
            "position_source": "Audi last-known parked location, not live driving GPS",
            "position_captured_at": (
                captured.isoformat() if hasattr(captured, "isoformat") else None
            ),
            "position_age_minutes": vehicle_age_minutes(captured),
            "position_freshness": vehicle_freshness(captured),
            "model": f"{self._vehicle.model or 'Unknown'}/{self._vehicle.title}",
            "model_year": getattr(self._vehicle, "model_year", None),
            "model_family": getattr(self._vehicle, "model_family", None),
            "csid": getattr(self._vehicle, "csid", None),
            "vin": getattr(self._vehicle, "vin", None),
        }
        return {k: v for k, v in attrs.items() if v is not None}


__all__ = ["AudiDeviceTracker", "async_setup_entry"]
