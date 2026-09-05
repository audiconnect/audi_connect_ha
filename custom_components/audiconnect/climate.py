"""Support for Audi Connect climate entities."""

from __future__ import annotations

import contextlib
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import AudiRuntimeData
from .audi_entity import AudiEntity, is_entity_supported
from .coordinator import AudiDataUpdateCoordinator

_ATTR_KEY = "climatisation_state"

# services.yaml bounds the temp_c field the same way.
_MIN_TEMP_C = 15
_MAX_TEMP_C = 30
_DEFAULT_TEMP_C = 21.0

# What the car reports when climatisation is doing nothing. Anything else is a
# running mode, so unknown modes read as on rather than silently as off.
_INACTIVE_STATES = frozenset({"off", "invalid", "unsupported", "error", ""})

_ACTIONS = {
    "heating": HVACAction.HEATING,
    "cooling": HVACAction.COOLING,
    "ventilation": HVACAction.FAN,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    async_add_entities(
        AudiClimate(runtime_data.coordinator, config_vehicle.vehicle)
        for config_vehicle in runtime_data.account.config_vehicles
        if is_entity_supported(config_vehicle.vehicle, _ATTR_KEY)
    )


class AudiClimate(AudiEntity, ClimateEntity, RestoreEntity):
    """Climatisation as a climate entity.

    The car reports whether climatisation is running and in which mode, but not
    the temperature it was asked for, so the target is held here and restored
    across restarts. Everything else comes from the vehicle.
    """

    _attr_name = "Climatisation"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = _MIN_TEMP_C
    _attr_max_temp = _MAX_TEMP_C

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_climate_climatisation"
        self._attr_target_temperature = _DEFAULT_TEMP_C

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._restore_target_temperature(await self.async_get_last_state())

    def _restore_target_temperature(self, last_state: Any) -> None:
        """Take the target back from the last recorded state, if there is one."""
        if last_state is None:
            return
        if (last := last_state.attributes.get(ATTR_TEMPERATURE)) is None:
            return
        # A recorded "unknown" must not wedge the entity on restart.
        with contextlib.suppress(TypeError, ValueError):
            self._attr_target_temperature = float(last)

    @property
    def _state(self) -> str:
        value = getattr(self._vehicle, _ATTR_KEY, None)
        return value.lower() if isinstance(value, str) else ""

    @property
    def _is_running(self) -> bool:
        return self._state not in _INACTIVE_STATES

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT_COOL if self._is_running else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        if not self._is_running:
            return HVACAction.OFF
        # A running mode the map does not name is still running; IDLE would read
        # as "on but doing nothing", which is the wrong thing to claim.
        return _ACTIONS.get(self._state, HVACAction.HEATING)

    # current_temperature is deliberately absent: the car reports outdoor
    # temperature, not cabin temperature, and showing the outside reading as the
    # climate entity's current temperature would misstate what it measures.

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "climatisation_state": getattr(self._vehicle, _ATTR_KEY, None),
            "remaining_climatisation_time": getattr(
                self._vehicle, "remaining_climatisation_time", None
            ),
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
        else:
            await self.async_turn_on()

    async def async_turn_on(self) -> None:
        connection = self.coordinator.account.connection
        # Only temp_c is sent: the service prefers temp_f when both are given,
        # so passing a converted Fahrenheit value would quantise the 0.5 step.
        if not await connection.start_climate_control(
            self._vehicle.vin, temp_c=self.target_temperature
        ):
            raise HomeAssistantError(
                "Failed to start climatisation; see the log for details"
            )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        connection = self.coordinator.account.connection
        if not await connection.set_vehicle_climatisation(self._vehicle.vin, False):
            raise HomeAssistantError(
                "Failed to stop climatisation; see the log for details"
            )
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        self._attr_target_temperature = float(temperature)
        self.async_write_ha_state()
        # Re-send only if it is already running, so setting a temperature while
        # off does not start the car climatising.
        if self._is_running:
            await self.async_turn_on()


__all__ = ["AudiClimate", "async_setup_entry"]
