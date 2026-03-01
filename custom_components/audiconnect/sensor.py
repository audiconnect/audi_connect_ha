"""Support for Audi Connect sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AudiRuntimeData
from .audi_entity import AudiEntity
from .const import DOMAIN
from .coordinator import AudiDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities: list[SensorEntity] = [
        AudiSensor(runtime_data.coordinator, sensor)
        for config_vehicle in runtime_data.account.config_vehicles
        for sensor in config_vehicle.sensors
    ]

    # Add account-level API rate limit sensor, attached to the first vehicle.
    if runtime_data.account.config_vehicles:
        first_vehicle = runtime_data.account.config_vehicles[0].vehicle
        entities.append(
            AudiApiRateLimitSensor(
                runtime_data.coordinator,
                config_entry.entry_id,
                first_vehicle,
            )
        )

    async_add_entities(entities)


class AudiSensor(AudiEntity, SensorEntity):
    """Representation of an Audi sensor."""

    @property
    def native_value(self) -> Any:
        return self._instrument.state

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._instrument.unit

    @property
    def device_class(self) -> SensorDeviceClass | None:
        return self._instrument.device_class

    @property
    def state_class(self) -> SensorStateClass | None:
        return self._instrument.state_class

    @property
    def entity_category(self) -> EntityCategory | None:
        return self._instrument.entity_category

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self._instrument.extra_state_attributes

    @property
    def suggested_display_precision(self) -> int | None:
        return self._instrument.suggested_display_precision


class AudiApiRateLimitSensor(
    CoordinatorEntity[AudiDataUpdateCoordinator], SensorEntity
):
    """Account-level sensor exposing the Vcf-Remaining-Calls API rate limit."""

    _attr_has_entity_name = True
    _attr_name = "API requests remaining"
    _attr_icon = "mdi:api"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        entry_id: str,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_api_requests_remaining"
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

    @property
    def native_value(self) -> int | None:
        api = self.coordinator.account.connection._audi_service._api
        return api.vcf_remaining_calls


__all__ = ["AudiApiRateLimitSensor", "AudiSensor", "async_setup_entry"]
