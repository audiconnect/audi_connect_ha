"""Support for Audi Connect sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfLength,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudiRuntimeData
from .audi_entity import AudiEntity, is_entity_supported
from .coordinator import AudiDataUpdateCoordinator
from .util import parse_datetime


@dataclass(frozen=True, kw_only=True)
class AudiSensorEntityDescription(SensorEntityDescription):
    """Describes an Audi sensor entity."""

    attr_key: str
    value_fn: Callable[[Any], Any] | None = None
    extra_attrs_fn: Callable[[Any], dict[str, Any]] | None = None


def _trip_data_value(vehicle: Any, attr_key: str) -> Any:
    """Extract timestamp from trip data dict as the sensor state."""
    td = getattr(vehicle, attr_key, None)
    if td and isinstance(td, dict):
        return parse_datetime(td.get("timestamp"))
    return None


def _trip_data_attrs(vehicle: Any, attr_key: str) -> dict[str, Any]:
    """Extract extra attributes from trip data dict."""
    td = getattr(vehicle, attr_key, None)
    if not td or not isinstance(td, dict):
        return {}
    return {
        "averageElectricEngineConsumption": td.get(
            "averageElectricEngineConsumption"
        ),
        "averageFuelConsumption": td.get("averageFuelConsumption"),
        "averageSpeed": td.get("averageSpeed"),
        "mileage": td.get("mileage"),
        "overallMileage": td.get("overallMileage"),
        "startMileage": td.get("startMileage"),
        "traveltime": td.get("traveltime"),
        "tripID": td.get("tripID"),
        "zeroEmissionDistance": td.get("zeroEmissionDistance"),
    }


SENSOR_DESCRIPTIONS: tuple[AudiSensorEntityDescription, ...] = (
    AudiSensorEntityDescription(
        key="last_update_time",
        attr_key="last_update_time",
        name="Last Update",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    AudiSensorEntityDescription(
        key="shortterm_current",
        attr_key="shortterm_current",
        name="ShortTerm Trip Data",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda v: _trip_data_value(v, "shortterm_current"),
        extra_attrs_fn=lambda v: _trip_data_attrs(v, "shortterm_current"),
    ),
    AudiSensorEntityDescription(
        key="shortterm_reset",
        attr_key="shortterm_reset",
        name="ShortTerm Trip User Reset",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda v: _trip_data_value(v, "shortterm_reset"),
        extra_attrs_fn=lambda v: _trip_data_attrs(v, "shortterm_reset"),
    ),
    AudiSensorEntityDescription(
        key="longterm_current",
        attr_key="longterm_current",
        name="LongTerm Trip Data",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda v: _trip_data_value(v, "longterm_current"),
        extra_attrs_fn=lambda v: _trip_data_attrs(v, "longterm_current"),
    ),
    AudiSensorEntityDescription(
        key="longterm_reset",
        attr_key="longterm_reset",
        name="LongTerm Trip User Reset",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda v: _trip_data_value(v, "longterm_reset"),
        extra_attrs_fn=lambda v: _trip_data_attrs(v, "longterm_reset"),
    ),
    AudiSensorEntityDescription(
        key="model",
        attr_key="model",
        name="Model",
        icon="mdi:car-info",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiSensorEntityDescription(
        key="mileage",
        attr_key="mileage",
        name="Mileage",
        icon="mdi:counter",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.DISTANCE,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
    ),
    AudiSensorEntityDescription(
        key="service_adblue_distance",
        attr_key="service_adblue_distance",
        name="AdBlue range",
        icon="mdi:map-marker-distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=0,
    ),
    AudiSensorEntityDescription(
        key="range",
        attr_key="range",
        name="Range",
        icon="mdi:map-marker-distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=0,
    ),
    AudiSensorEntityDescription(
        key="hybrid_range",
        attr_key="hybrid_range",
        name="hybrid Range",
        icon="mdi:map-marker-distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=0,
    ),
    AudiSensorEntityDescription(
        key="service_inspection_time",
        attr_key="service_inspection_time",
        name="Service inspection time",
        icon="mdi:room-service-outline",
        native_unit_of_measurement=UnitOfTime.DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiSensorEntityDescription(
        key="service_inspection_distance",
        attr_key="service_inspection_distance",
        name="Service inspection distance",
        icon="mdi:room-service-outline",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
    ),
    AudiSensorEntityDescription(
        key="oil_change_time",
        attr_key="oil_change_time",
        name="Oil change time",
        icon="mdi:oil",
        native_unit_of_measurement=UnitOfTime.DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiSensorEntityDescription(
        key="oil_change_distance",
        attr_key="oil_change_distance",
        name="Oil change distance",
        icon="mdi:oil",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
    ),
    AudiSensorEntityDescription(
        key="oil_level",
        attr_key="oil_level",
        name="Oil level",
        icon="mdi:oil",
        native_unit_of_measurement=PERCENTAGE,
    ),
    AudiSensorEntityDescription(
        key="charging_state",
        attr_key="charging_state",
        name="Charging state",
        icon="mdi:car-battery",
    ),
    AudiSensorEntityDescription(
        key="charging_mode",
        attr_key="charging_mode",
        name="Charging mode",
    ),
    AudiSensorEntityDescription(
        key="charging_type",
        attr_key="charging_type",
        name="Charging type",
    ),
    AudiSensorEntityDescription(
        key="energy_flow",
        attr_key="energy_flow",
        name="Energy flow",
    ),
    AudiSensorEntityDescription(
        key="max_charge_current",
        attr_key="max_charge_current",
        name="Max charge current",
        icon="mdi:current-ac",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
    ),
    AudiSensorEntityDescription(
        key="primary_engine_type",
        attr_key="primary_engine_type",
        name="Primary engine type",
        icon="mdi:engine",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiSensorEntityDescription(
        key="secondary_engine_type",
        attr_key="secondary_engine_type",
        name="Secondary engine type",
        icon="mdi:engine",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiSensorEntityDescription(
        key="primary_engine_range",
        attr_key="primary_engine_range",
        name="Primary engine range",
        icon="mdi:map-marker-distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=0,
    ),
    AudiSensorEntityDescription(
        key="secondary_engine_range",
        attr_key="secondary_engine_range",
        name="Secondary engine range",
        icon="mdi:map-marker-distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=0,
    ),
    AudiSensorEntityDescription(
        key="primary_engine_range_percent",
        attr_key="primary_engine_range_percent",
        name="Primary engine Percent",
        icon="mdi:gauge",
        native_unit_of_measurement=PERCENTAGE,
    ),
    AudiSensorEntityDescription(
        key="car_type",
        attr_key="car_type",
        name="Car Type",
        icon="mdi:car-info",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiSensorEntityDescription(
        key="secondary_engine_range_percent",
        attr_key="secondary_engine_range_percent",
        name="Secondary engine Percent",
        icon="mdi:gauge",
        native_unit_of_measurement=PERCENTAGE,
    ),
    AudiSensorEntityDescription(
        key="charging_power",
        attr_key="charging_power",
        name="Charging power",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
    ),
    AudiSensorEntityDescription(
        key="actual_charge_rate",
        attr_key="actual_charge_rate",
        name="Charging rate",
        icon="mdi:electron-framework",
    ),
    AudiSensorEntityDescription(
        key="tank_level",
        attr_key="tank_level",
        name="Tank level",
        icon="mdi:gauge",
        native_unit_of_measurement=PERCENTAGE,
    ),
    AudiSensorEntityDescription(
        key="state_of_charge",
        attr_key="state_of_charge",
        name="State of charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
    ),
    AudiSensorEntityDescription(
        key="remaining_charging_time",
        attr_key="remaining_charging_time",
        name="Remaining charge time",
        icon="mdi:battery-charging",
    ),
    AudiSensorEntityDescription(
        key="charging_complete_time",
        attr_key="charging_complete_time",
        name="Charging Complete Time",
        icon="mdi:battery-charging",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    AudiSensorEntityDescription(
        key="target_state_of_charge",
        attr_key="target_state_of_charge",
        name="Target State of charge",
        icon="mdi:ev-station",
        native_unit_of_measurement=PERCENTAGE,
    ),
    AudiSensorEntityDescription(
        key="external_power",
        attr_key="external_power",
        name="External Power",
        icon="mdi:ev-station",
    ),
    AudiSensorEntityDescription(
        key="plug_led_color",
        attr_key="plug_led_color",
        name="Plug LED Color",
        icon="mdi:ev-plug-type1",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AudiSensorEntityDescription(
        key="doors_trunk_status",
        attr_key="doors_trunk_status",
        name="Doors/trunk state",
        icon="mdi:car-door",
    ),
    AudiSensorEntityDescription(
        key="climatisation_state",
        attr_key="climatisation_state",
        name="Climatisation state",
        icon="mdi:air-conditioner",
    ),
    AudiSensorEntityDescription(
        key="outdoor_temperature",
        attr_key="outdoor_temperature",
        name="Outdoor Temperature",
        icon="mdi:temperature-celsius",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    AudiSensorEntityDescription(
        key="park_time",
        attr_key="park_time",
        name="Park Time",
        icon="mdi:car-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    AudiSensorEntityDescription(
        key="remaining_climatisation_time",
        attr_key="remaining_climatisation_time",
        name="Remaining Climatisation Time",
        icon="mdi:fan-clock",
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    AudiSensorEntityDescription(
        key="preheater_duration",
        attr_key="preheater_duration",
        name="Preheater runtime",
        icon="mdi:clock",
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    AudiSensorEntityDescription(
        key="preheater_remaining",
        attr_key="preheater_remaining",
        name="Preheater remaining",
        icon="mdi:clock",
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: AudiRuntimeData = config_entry.runtime_data
    entities: list[SensorEntity] = []

    for config_vehicle in runtime_data.account.config_vehicles:
        vehicle = config_vehicle.vehicle
        for description in SENSOR_DESCRIPTIONS:
            if is_entity_supported(vehicle, description.attr_key):
                entities.append(
                    AudiSensor(runtime_data.coordinator, description, vehicle)
                )

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

    entity_description: AudiSensorEntityDescription

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        description: AudiSensorEntityDescription,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self.entity_description = description
        self._attr_unique_id = (
            f"{vehicle.vin.lower()}_sensor_{description.key}"
        )

    @property
    def native_value(self) -> Any:
        if self.entity_description.value_fn is not None:
            return self.entity_description.value_fn(self._vehicle)
        return getattr(self._vehicle, self.entity_description.attr_key, None)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.extra_attrs_fn is not None:
            return self.entity_description.extra_attrs_fn(self._vehicle)
        return None


class AudiApiRateLimitSensor(
    AudiEntity, SensorEntity
):
    """Account-level sensor exposing the Vcf-Remaining-Calls API rate limit."""

    _attr_name = "API requests remaining"
    _attr_icon = "mdi:api"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: AudiDataUpdateCoordinator,
        entry_id: str,
        vehicle: Any,
    ) -> None:
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{entry_id}_api_requests_remaining"

    @property
    def native_value(self) -> int | None:
        api = self.coordinator.account.connection._audi_service._api
        return api.vcf_remaining_calls


__all__ = ["AudiApiRateLimitSensor", "AudiSensor", "async_setup_entry"]
