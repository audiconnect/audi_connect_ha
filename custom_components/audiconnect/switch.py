"""Support for Audi Connect switches."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, is_entity_supported
from .coordinator import AudiDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class AudiSwitchEntityDescription(SwitchEntityDescription):
    """Describes an Audi switch entity."""

    attr_key: str
    turn_on_fn: Callable[[Any, str], Coroutine[Any, Any, bool]]
    turn_off_fn: Callable[[Any, str], Coroutine[Any, Any, bool]]
    value_fn: Callable[[Any], bool] = bool


# Climatisation settings the car stores and reports back. Writable through
# PUT climatisation/settings without starting climatisation, unlike the myAudi
# app, which only offers them while starting the air conditioning.
_CLIMATISATION_SETTINGS: tuple[tuple[str, str, str, str], ...] = (
    (
        "climatisation_window_heating",
        "climatisation_window_heating_enabled",
        "windowHeatingEnabled",
        "Window heating",
    ),
    (
        "climatisation_at_unlock",
        "climatisation_at_unlock",
        "climatizationAtUnlock",
        "Climatisation at unlock",
    ),
    (
        "climatisation_zone_front_left",
        "climatisation_zone_front_left",
        "zoneFrontLeftEnabled",
        "Climatisation zone front left",
    ),
    (
        "climatisation_zone_front_right",
        "climatisation_zone_front_right",
        "zoneFrontRightEnabled",
        "Climatisation zone front right",
    ),
    (
        "climatisation_zone_rear_left",
        "climatisation_zone_rear_left",
        "zoneRearLeftEnabled",
        "Climatisation zone rear left",
    ),
    (
        "climatisation_zone_rear_right",
        "climatisation_zone_rear_right",
        "zoneRearRightEnabled",
        "Climatisation zone rear right",
    ),
)


def _setting_switch(key, attr_key, field, name) -> AudiSwitchEntityDescription:
    return AudiSwitchEntityDescription(
        key=key,
        attr_key=attr_key,
        name=name,
        icon="mdi:car-seat-heater" if "zone" in key else "mdi:car-defrost-front",
        entity_category=EntityCategory.CONFIG,
        turn_on_fn=lambda conn, vin, f=field: conn.set_climatisation_setting(
            vin, f, True
        ),
        turn_off_fn=lambda conn, vin, f=field: conn.set_climatisation_setting(
            vin, f, False
        ),
    )


SWITCH_DESCRIPTIONS: tuple[AudiSwitchEntityDescription, ...] = (
    AudiSwitchEntityDescription(
        key="preheater_active",
        attr_key="preheater_active",
        name="Preheater",
        icon="mdi:radiator",
        turn_on_fn=lambda conn, vin: conn.set_vehicle_pre_heater(vin, True),
        turn_off_fn=lambda conn, vin: conn.set_vehicle_pre_heater(vin, False),
    ),
    *(_setting_switch(*row) for row in _CLIMATISATION_SETTINGS),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities = [
        AudiSwitch(runtime_data.coordinator, description, vehicle)
        for config_vehicle in runtime_data.account.config_vehicles
        for description in SWITCH_DESCRIPTIONS
        if is_entity_supported(
            (vehicle := config_vehicle.vehicle), description.attr_key
        )
    ]
    async_add_entities(entities)


class AudiSwitch(AudiEntity, SwitchEntity):
    """Representation of an Audi switch."""

    entity_description: AudiSwitchEntityDescription

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        description: AudiSwitchEntityDescription,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self.entity_description = description
        self._attr_unique_id = f"{vehicle.vin.lower()}_switch_{description.key}"
        self._assumed: bool | None = None
        self._reported_at_write: bool | None = None

    def _reported(self) -> bool:
        value = getattr(self._vehicle, self.entity_description.attr_key, None)
        return self.entity_description.value_fn(value)

    @property
    def is_on(self) -> bool:
        if self._assumed is not None:
            return self._assumed
        return self._reported()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Stop assuming as soon as the car reports anything OTHER than what it
        # said before the write, whether or not that matches what was asked for.
        # Waiting for it to match our own value instead would mask a change made
        # elsewhere (the myAudi app), leaving the entity stuck on a stale guess.
        if self._assumed is not None and self._reported() != self._reported_at_write:
            self._assumed = None
            self._reported_at_write = None
        super()._handle_coordinator_update()

    async def _run(
        self, fn: Callable[[Any, str], Coroutine[Any, Any, bool]], target: bool
    ) -> None:
        connection = self.coordinator.account.connection
        if not await fn(connection, self._vehicle.vin):
            raise HomeAssistantError(
                f"Failed to switch {self.name}; see the log for details"
            )
        # The car acknowledges the write before it reports the new value, so the
        # refresh below usually re-reads the old one and the switch snaps back to
        # its previous position until the next poll: 15 minutes by default, which
        # reads as the command having failed. Found on a live vehicle, where the
        # car and the myAudi app both showed window heating enabled while the
        # entity still showed off.
        self._reported_at_write = self._reported()
        self._assumed = target
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._run(self.entity_description.turn_on_fn, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._run(self.entity_description.turn_off_fn, False)


__all__ = ["AudiSwitch", "async_setup_entry"]
