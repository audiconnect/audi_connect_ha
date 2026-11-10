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
from .audi_entity import AudiEntity, entity_unique_id, is_entity_supported, should_create_entity
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
        if should_create_entity(
            hass,
            "switch",
            description.key,
            vehicle := config_vehicle.vehicle,
            description.attr_key,
        )
    ]
    # One stateful ON/OFF control for the two physically verified Q8 climate
    # commands. Existing climate and button unique IDs are left untouched.
    for config_vehicle in runtime_data.account.config_vehicles:
        vehicle = config_vehicle.vehicle
        service = getattr(vehicle, "_audi_service", None)
        if (
            getattr(service, "uses_auth0", False)
            and is_entity_supported(vehicle, "climatisation_state", "climatisation")
            and should_create_entity(
                hass, "switch", "climate_quick_control",
                vehicle, "climatisation_state",
            )
        ):
            entities.append(AudiClimateQuickSwitch(runtime_data.coordinator, vehicle))
    async_add_entities(entities)


class AudiClimateQuickSwitch(AudiEntity, SwitchEntity):
    """A native switch around the Q8's proven bodyless climate start/stop.

    Do not present an HTTP 200 as a physical state: the source-of-truth is
    the vehicle's actual climatisationState, never a speculative toggle.
    Existing HA climate entity keeps temperature/mode controls.
    """

    _attr_name = "Climatisation ON/OFF"
    _attr_icon = "mdi:car-air-conditioner"
    _backing_attr = "climatisation_state"

    def __init__(
        self, coordinator: AudiDataUpdateCoordinator, vehicle: Any
    ) -> None:
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = entity_unique_id(
            vehicle, "switch", "climate_quick_control"
        )

    @property
    def is_on(self) -> bool | None:
        reported = getattr(self._vehicle, "climatisation_state", None)
        if not isinstance(reported, str):
            return None
        state = reported.strip().lower()
        if state in {"invalid", "unsupported", "error", ""}:
            return None
        return state not in {"off", "inactive", "stopped"}

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "vehicle_climatisation_state": getattr(
                self._vehicle, "climatisation_state", None
            ),
            "source": "Audi car reported state",
            "start_mode": "Use stored vehicle climate settings",
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self.is_on is True:
            return
        # Exactly the same bodyless start as the already proven HA button.
        if not await self.coordinator.account.connection.start_climate_control(
            self._vehicle.vin
        ):
            raise HomeAssistantError(
                "Audi climate start failed; check the integration log"
            )
        # The connection already schedules the post-command coordinator refresh.

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.is_on is False:
            return
        # Exactly the same stop route as the already proven HA button.
        if not await self.coordinator.account.connection.set_vehicle_climatisation(
            self._vehicle.vin, False
        ):
            raise HomeAssistantError(
                "Audi climate stop failed; check the integration log"
            )
        # No duplicate cloud GET: the account wrapper notifies the coordinator.


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
        self._attr_unique_id = entity_unique_id(vehicle, "switch", description.key)
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


__all__ = ["AudiSwitch", "AudiClimateQuickSwitch", "async_setup_entry"]
