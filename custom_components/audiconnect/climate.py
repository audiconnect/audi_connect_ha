"""Support for Audi Connect climate entities."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
    HVACAction,
    HVACMode,
    ClimateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, is_entity_supported
from .coordinator import AudiDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class AudiClimateEntityDescription(ClimateEntityDescription):
    """Describes an Audi climate entity."""

    attr_key: str
    start_fn: Callable[[Any, str, dict[str, Any]], Coroutine[Any, Any, None]]
    stop_fn: Callable[[Any, str], Coroutine[Any, Any, None]]


async def _start_climate_control(
    conn: Any, vin: str, params: dict[str, Any]
) -> None:
    """Start climate control with parameters."""
    temp_c = params.get("target_temperature", 21)
    # Convert Celsius to Fahrenheit
    temp_f = int(temp_c * 9 / 5 + 32)
    
    await conn.start_climate_control(
        vin,
        temp_f,
        temp_c,
        params.get("glass_heating", False),
        params.get("seat_fl", False),
        params.get("seat_fr", False),
        params.get("seat_rl", False),
        params.get("seat_rr", False),
        params.get("climatisation_at_unlock", False),
        params.get("climatisation_mode", "comfort"),
    )


async def _stop_climate_control(conn: Any, vin: str) -> None:
    """Stop climate control."""
    await conn.set_vehicle_climatisation(vin, False)




CLIMATE_DESCRIPTIONS: tuple[AudiClimateEntityDescription, ...] = (
    AudiClimateEntityDescription(
        key="climatisation_active",
        attr_key="climatisation_active",
        name="Klimatisierung",
        icon="mdi:air-conditioner",
        start_fn=_start_climate_control,
        stop_fn=_stop_climate_control,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities = []
    
    for config_vehicle in runtime_data.account.config_vehicles:
        vehicle = config_vehicle.vehicle
        if vehicle is None:
            continue
        
        # Add Climate Control entity
        for description in CLIMATE_DESCRIPTIONS:
            entities.append(
                AudiClimate(
                    runtime_data.coordinator, 
                    description,
                    vehicle
                )
            )
    
    async_add_entities(entities)


class AudiClimate(AudiEntity, ClimateEntity):
    """Representation of an Audi climate entity."""

    entity_description: AudiClimateEntityDescription

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 15
    _attr_max_temp = 30
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        description: AudiClimateEntityDescription,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self.entity_description = description
        self._attr_unique_id = f"{vehicle.vin.lower()}_climate_{description.key}"
        self._target_temperature = 21.0
        self._is_on = False

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        # Check if we have the actual state attribute, otherwise return stored state
        is_active = getattr(self._vehicle, self.entity_description.attr_key, self._is_on)
        return HVACMode.HEAT_COOL if is_active else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return current HVAC action."""
        is_active = getattr(self._vehicle, self.entity_description.attr_key, self._is_on)
        if is_active:
            # Klimatisierung can cool or heat
            return HVACAction.COOLING
        return HVACAction.OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        # Try to get the current temperature from vehicle data
        temp = getattr(self._vehicle, "temperature", None)
        return float(temp) if temp is not None else None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self._target_temperature

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        connection = self.coordinator.account.connection

        if hvac_mode == HVACMode.OFF:
            await self.entity_description.stop_fn(connection, self._vehicle.vin)
            self._is_on = False
        elif hvac_mode == HVACMode.HEAT_COOL:
            params = {
                "target_temperature": self._target_temperature,
                "glass_heating": False,
                "seat_fl": False,
                "seat_fr": False,
                "seat_rl": False,
                "seat_rr": False,
                "climatisation_mode": "comfort",
                "duration": 30,
            }
            await self.entity_description.start_fn(
                connection, self._vehicle.vin, params
            )
            self._is_on = True

        # Force refresh to update status quickly
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        if ATTR_TEMPERATURE in kwargs:
            temperature = kwargs[ATTR_TEMPERATURE]
            self._target_temperature = float(temperature)

            # If already active, update with new temperature
            if self.hvac_mode == HVACMode.HEAT_COOL:
                connection = self.coordinator.account.connection
                params = {
                    "target_temperature": self._target_temperature,
                    "glass_heating": False,
                    "seat_fl": False,
                    "seat_fr": False,
                    "seat_rl": False,
                    "seat_rr": False,
                    "climatisation_mode": "comfort",
                    "duration": 30,
                }
                await self.entity_description.start_fn(
                    connection, self._vehicle.vin, params
                )
                # Force refresh to update status quickly
                await self.coordinator.async_request_refresh()


__all__ = ["AudiClimate", "async_setup_entry"]
