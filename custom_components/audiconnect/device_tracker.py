"""Support for tracking an Audi."""

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TRACKER_UPDATE

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Audi device tracker entities."""
    account = config_entry.data.get(CONF_USERNAME)
    audi_data = hass.data.get(DOMAIN, {}).get(account)

    if not audi_data:
        _LOGGER.error("Audi Connect data not found for account: %s", account)
        return

    if "devices" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["devices"] = set()

    async def add_vehicle_tracker(instrument: Any) -> None:
        """Add a tracker entity when data is received."""
        unique_id = instrument.full_name
        if unique_id in hass.data[DOMAIN]["devices"]:
            return

        _LOGGER.debug("Adding new AudiDeviceTracker: %s", unique_id)
        hass.data[DOMAIN]["devices"].add(unique_id)
        async_add_entities([AudiDeviceTracker(config_entry, instrument)], True)

    async_dispatcher_connect(hass, TRACKER_UPDATE, add_vehicle_tracker)

    for config_vehicle in getattr(audi_data, "config_vehicles", []):
        for tracker in getattr(config_vehicle, "device_trackers", []):
            async_dispatcher_send(hass, TRACKER_UPDATE, tracker)


class AudiDeviceTracker(TrackerEntity):
    """Representation of an Audi device tracker."""

    _attr_icon = "mdi:car"
    _attr_should_poll = False
    _attr_source_type = SourceType.GPS

    def __init__(self, config_entry: ConfigEntry, instrument: Any) -> None:
        """Initialize tracker."""
        self._instrument = instrument
        self._config_entry = config_entry
        self._attr_unique_id = instrument.full_name
        self._latitude = None
        self._longitude = None
        self._update_state_from_instrument()

        self._attr_device_info = {
            "identifiers": {(DOMAIN, instrument.vehicle_name)},
            "manufacturer": "Audi",
            "name": instrument.vehicle_name,
            "model": getattr(instrument, "vehicle_model", None),
        }

    def _update_state_from_instrument(self) -> None:
        """Update internal lat/lon state."""
        state = getattr(self._instrument, "state", None)
        if isinstance(state, (list, tuple)) and len(state) >= 2:
            try:
                self._latitude = float(state[0])
                self._longitude = float(state[1])
            except (ValueError, TypeError):
                _LOGGER.warning("Invalid GPS coordinates: %s", state)
                self._latitude = self._longitude = None
        else:
            _LOGGER.debug("Missing or invalid state for: %s", self._attr_unique_id)

    @property
    def latitude(self) -> float | None:
        return self._latitude

    @property
    def longitude(self) -> float | None:
        return self._longitude

    @property
    def name(self) -> str:
        return f"{self._instrument.vehicle_name} {self._instrument.name}"

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

    async def async_added_to_hass(self) -> None:
        """Register update dispatcher."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, TRACKER_UPDATE, self._async_receive_data
            )
        )
        _LOGGER.debug("%s registered for updates", self.entity_id)

    @callback
    def _async_receive_data(self, instrument: Any) -> None:
        """Receive new tracker data."""
        if instrument.full_name != self._attr_unique_id:
            return

        _LOGGER.debug("Update received for %s", self.entity_id)
        self._instrument = instrument
        self._update_state_from_instrument()
        self.async_write_ha_state()
