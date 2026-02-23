"""Support for myAudi switches."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
        AudiSwitch(runtime_data.coordinator, switch)
        for config_vehicle in runtime_data.account.config_vehicles
        for switch in config_vehicle.switches
    ]
    async_add_entities(entities)


class AudiSwitch(AudiEntity, SwitchEntity):
    @property
    def is_on(self):
        return self._instrument.state

    async def async_turn_on(self, **kwargs):
        await self._instrument.turn_on()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        await self._instrument.turn_off()
        await self.coordinator.async_request_refresh()
