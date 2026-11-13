"""Only V3-owned Home Assistant entities. No V2 models or API adapters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.components.number import NumberEntity, NumberDeviceClass, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.lock import LockEntity
from homeassistant.components.switch import SwitchEntity
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
    RestoreSensor,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
    PERCENTAGE,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from .auth import configured_spin
from .freshness import reading_freshness_attributes
from .coordinator_clean import V3CleanCoordinator
from .vehicle import V3Vehicle, CLIMATE_ON_STATES, CLIMATE_OFF_STATES
from .command_readback import command_attributes, last_known_climate, projected_state
from .command_policy import supported_charge_modes
from .attribute_contracts import contract_for, binary_contract_for, semantic_value_issue
from .product_contract import (
    projection_reading,
    compatibility_hidden,
    canonical_entity_category,
    canonical_entity_name,
    stateful_controls,
    stateful_reading,
    superseded_control_button,
    trip_metric_contracts,
    trip_metric_value,
)


def _binding_status(profile, key):
    return (
        getattr(profile, "fast_bindings", {}).get(key, {}).get("status", "unknown")
        if profile is not None
        else "unknown"
    )


class V3BaseEntity(CoordinatorEntity[V3CleanCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: V3CleanCoordinator, vehicle: V3Vehicle):
        super().__init__(coordinator)
        self.vehicle = vehicle

    @property
    def available(self) -> bool:
        return getattr(self.vehicle, "inventory_present", True) and super().available

    def _control_attributes(
        self,
        capability,
        actions,
        *,
        attribute=None,
        reading=None,
        source=None,
        allow_last_known=False,
        correlate=True,
    ):
        """One metadata contract for all native vehicle controls."""
        engine = self.coordinator.engine
        profile = getattr(engine, "profiles", {}).get(self.vehicle.vin.lower())
        result = {
            "v3_capability": capability,
            **command_attributes(
                profile if correlate else None, capability, actions, attribute=attribute
            ),
            "control_actions": {
                action: engine.control_enabled(self.vehicle.vin, action, capability)
                for action in actions
            },
        }
        if reading is not None or attribute is not None:
            row = (
                reading if reading is not None else self.vehicle.readings.get(attribute)
            )
            result.update(
                reading_freshness_attributes(row, allow_last_known=allow_last_known),
                last_reported_state=(row or {}).get("value"),
                state_source=source or "unknown",
            )
        return result

    @property
    def device_info(self) -> DeviceInfo:
        name = self.vehicle.model.removeprefix("Audi ").strip()
        if name and self.vehicle.model_year:
            name = f"{name} {self.vehicle.model_year}"
        return DeviceInfo(
            identifiers={(DOMAIN, self.vehicle.vin.lower())},
            manufacturer="Audi",
            name=self.vehicle.name,
            model=name or None,
        )


_CLIMATE_OFF = frozenset(CLIMATE_OFF_STATES)
_CLIMATE_ON = frozenset(CLIMATE_ON_STATES)


def _command_projection(
    coordinator, vehicle, attribute, reported, captured, *, optimistic=True
):
    profile = getattr(getattr(coordinator, "engine", None), "profiles", {}).get(
        vehicle.vin.lower()
    )
    return projected_state(
        profile, attribute, reported, captured, optimistic=optimistic
    )


def _reading_projection(
    coordinator, vehicle, attribute, *, allow_last_known=False, optimistic=True
):
    row = vehicle.readings.get(attribute) or {}
    reported = (
        row.get("value")
        if _reading_available(row, allow_last_known=allow_last_known)
        else None
    )
    return _command_projection(
        coordinator,
        vehicle,
        attribute,
        reported,
        row.get("captured"),
        optimistic=optimistic,
    )


def _climate_projection(coordinator, vehicle):
    state = vehicle.climate_state
    age = vehicle.capture_age_minutes
    legacy = vehicle.context.auth == "legacy" and _reading_available(
        vehicle.readings.get("climatisationState")
    )
    if (
        state not in _CLIMATE_ON | _CLIMATE_OFF
        or (age is None and not legacy)
        or (age is not None and age > 60)
    ):
        state = None
    profile = getattr(getattr(coordinator, "engine", None), "profiles", {}).get(
        vehicle.vin.lower()
    )
    known, stamp, known_source = last_known_climate(profile)
    if stamp and vehicle.climate_captured:
        from .attribute_runtime import _capture_in_utc

        if vehicle.climate_captured < _capture_in_utc(stamp):
            state = None
    effective, source = _command_projection(
        coordinator, vehicle, "climate", state, vehicle.climate_captured
    )
    if effective is not None:
        return effective, source
    return known, known_source


def _climate_reported_state(coordinator, vehicle):
    return _climate_projection(coordinator, vehicle)[0]


async def _send_climate(coordinator, vehicle, action, params=None):
    engine = coordinator.engine
    if not getattr(vehicle, "inventory_present", True) or not engine.control_enabled(
        vehicle.vin, action, "climate"
    ):
        raise HomeAssistantError(
            "Climate action unavailable; review the route or pending command in Audi Engineering Dashboard"
        )
    try:
        if params is None:
            await engine.send_control(vehicle.vin, action, "climate")
        else:
            await engine.send_control(vehicle.vin, action, "climate", params=params)
    except (RuntimeError, ValueError) as err:
        raise HomeAssistantError(str(err)) from err


class V3ClimateEntity(V3BaseEntity, ClimateEntity):
    """Native cabin climate: actual state, explicit on/off, optional setpoint."""

    _attr_name = canonical_entity_name("climate.climatisation")
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 15
    _attr_max_temp = 30
    _attr_target_temperature_step = 0.5
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: V3CleanCoordinator, vehicle: V3Vehicle):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_climate_climatisation"
        self._requested_temperature = None
        self._dispatched_temperature = None
        self._dispatched_at = None

    def _enabled(self, action):
        return self.coordinator.engine.control_enabled(
            self.vehicle.vin, action, "climate"
        )

    @property
    def reported_target_temperature(self):
        value = self.vehicle.readings.get("climatisationTargetTemperatureC", {}).get(
            "value"
        )
        return value if type(value) in (int, float) and 15 <= value <= 30 else None

    @property
    def pending_dispatched_temperature(self):
        from .attribute_runtime import _capture_in_utc

        row = self.vehicle.readings.get("climatisationTargetTemperatureC", {})
        stamp = _capture_in_utc(row.get("captured"))
        if (
            self._dispatched_at is not None
            and self.reported_target_temperature is not None
            and stamp is not None
            and stamp >= self._dispatched_at
        ):
            return None
        return self._dispatched_temperature

    @property
    def native_target_temperature(self):
        if self._requested_temperature is not None and self._enabled(
            "start_with_settings"
        ):
            return self._requested_temperature
        pending = self.pending_dispatched_temperature
        return pending if pending is not None else self.reported_target_temperature

    @property
    def target_temperature(self):
        return self.native_target_temperature

    @property
    def supported_features(self) -> ClimateEntityFeature:
        value = ClimateEntityFeature(0)
        if self._enabled("start_with_settings") or self._can_set_temperature():
            value |= ClimateEntityFeature.TARGET_TEMPERATURE
        if self._enabled("start") or (
            self._enabled("start_with_settings")
            and self.native_target_temperature is not None
        ):
            value |= ClimateEntityFeature.TURN_ON
        if self._enabled("stop"):
            value |= ClimateEntityFeature.TURN_OFF
        return value

    @property
    def available(self) -> bool:
        return (
            getattr(self.vehicle, "inventory_present", True)
            and self.coordinator.last_update_success
            and (
                _climate_reported_state(self.coordinator, self.vehicle) is not None
                or bool(self.supported_features)
            )
        )

    @property
    def hvac_mode(self) -> HVACMode | None:
        state = _climate_reported_state(self.coordinator, self.vehicle)
        if state in _CLIMATE_OFF:
            return HVACMode.OFF
        if state in _CLIMATE_ON:
            return HVACMode.HEAT_COOL
        return None

    @property
    def hvac_action(self) -> HVACAction | None:
        state, source = _climate_projection(self.coordinator, self.vehicle)
        if source != "vehicle":
            return None
        if state in _CLIMATE_OFF:
            return HVACAction.OFF
        # A requested ON is not proof of heating rather than cooling.
        return {
            "heating": HVACAction.HEATING,
            "cooling": HVACAction.COOLING,
            "ventilation": HVACAction.FAN,
        }.get(state)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        engine = self.coordinator.engine
        profile = getattr(engine, "profiles", {}).get(self.vehicle.vin.lower())
        from .structured_details import details_for

        known, stamp, known_source = last_known_climate(profile)
        _, source = _climate_projection(self.coordinator, self.vehicle)
        return {
            **details_for(
                self.vehicle,
                "climate_timers_detail",
                "ventilation_timers_detail",
                "departure_climate_timers_detail",
                "window_heating_detail",
                "climate_requests_detail",
            ),
            "climatisation_without_external_power": (
                self.vehicle.readings.get("climatisationWithoutExternalPower", {}).get(
                    "value"
                )
                if type(
                    self.vehicle.readings.get(
                        "climatisationWithoutExternalPower", {}
                    ).get("value")
                )
                is bool
                else None
            ),
            "api_route": self.vehicle.climate_source,
            **self._control_attributes(
                "climate",
                ("start", "stop", "start_with_settings"),
                attribute="climate",
                reading=self.vehicle.readings.get("climatisationState") or {},
                source=source,
                allow_last_known=True,
            ),
            "start_enabled": bool(
                self.supported_features & ClimateEntityFeature.TURN_ON
            ),
            "stop_enabled": self._enabled("stop"),
            "start_evidence": _binding_status(profile, "climate.start"),
            "stop_evidence": _binding_status(profile, "climate.stop"),
            "last_command": self.vehicle.last_command_result,
            "reported_target_temperature": self.reported_target_temperature,
            "staged_target_temperature": self._requested_temperature,
            "pending_dispatched_temperature": self.pending_dispatched_temperature,
            "target_temperature_source": (
                "local_pending"
                if self._requested_temperature is not None
                and self._enabled("start_with_settings")
                else "command_pending_readback"
                if self.pending_dispatched_temperature is not None
                else "vehicle"
                if self.reported_target_temperature is not None
                else "unknown"
            ),
            "last_reported_climate_state": self.vehicle.climate_state,
            "state_source": source,
            "state_is_current": source == "vehicle",
            "last_known_climate_state": known,
            "last_known_climate_at": stamp,
            "last_known_climate_source": known_source,
            "active_paths": len(getattr(profile, "active", {})),
        }

    def _can_set_temperature(self):
        return self.reported_target_temperature is not None and self._enabled(
            "set_settings"
        )

    async def async_set_temperature(self, **kwargs):
        value = kwargs.get("temperature")
        mode = kwargs.get("hvac_mode")
        if type(value) not in (int, float) or not 15 <= value <= 30:
            raise HomeAssistantError("Climate temperature must be 15..30 C")
        if mode not in (None, HVACMode.OFF, HVACMode.HEAT_COOL):
            raise HomeAssistantError("Unsupported climate mode")
        if mode is None and self._can_set_temperature():
            # A setpoint write is not a request to start the cabin heater.
            await _send_climate(
                self.coordinator, self.vehicle, "set_settings", {"temp_c": value}
            )
            self._requested_temperature = None
            self._dispatched_temperature = None
            self._dispatched_at = None
            self.async_write_ha_state()
            return
        if not self._enabled("start_with_settings"):
            raise HomeAssistantError("Temperature-bearing start is not enabled")
        # Off/unknown: stage locally; do not implicitly start. Commit a
        # dispatched setpoint only after the command owner accepts the request.
        if mode == HVACMode.OFF:
            await self.async_turn_off()
            self._requested_temperature = float(value)
        elif mode == HVACMode.HEAT_COOL or (
            self.hvac_mode == HVACMode.HEAT_COOL
            and _climate_projection(self.coordinator, self.vehicle)[1] == "vehicle"
        ):
            await self._send_target(float(value))
        else:
            self._requested_temperature = float(value)
        self.async_write_ha_state()

    async def _send_target(self, value):
        started = datetime.now(UTC)
        await _send_climate(
            self.coordinator, self.vehicle, "start_with_settings", {"temp_c": value}
        )
        self._requested_temperature = None
        self._dispatched_temperature = value
        self._dispatched_at = started

    async def async_set_hvac_mode(self, mode: HVACMode) -> None:
        if mode == HVACMode.OFF:
            await self.async_turn_off()
        elif mode == HVACMode.HEAT_COOL:
            await self.async_turn_on()
        else:
            raise HomeAssistantError("Unsupported climate mode")

    async def async_turn_on(self) -> None:
        # Normal ON uses the exact bodyless start. Only an explicit staged
        # target (or absence of a bodyless route) selects a settings start.
        if self._enabled("start_with_settings") and (
            self._requested_temperature is not None or not self._enabled("start")
        ):
            value = self.native_target_temperature
            if value is None:
                raise HomeAssistantError(
                    "No reported or explicitly selected climate target"
                )
            await self._send_target(value)
        elif self._enabled("start"):
            await _send_climate(self.coordinator, self.vehicle, "start")
            self._requested_temperature = None
        else:
            raise HomeAssistantError("No enabled climate start route")
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        await _send_climate(self.coordinator, self.vehicle, "stop")
        self.async_write_ha_state()


class V3HealthSensor(V3BaseEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, vehicle, kind):
        super().__init__(coordinator, vehicle)
        self.kind = kind
        self._attr_unique_id = f"{vehicle.vin.lower()}_sensor_{kind}"
        self._attr_name = canonical_entity_name("sensor." + kind)

    @property
    def available(self):
        return True

    @property
    def device_class(self):
        return SensorDeviceClass.ENUM if self.kind == "integration_status" else None

    @property
    def options(self):
        from .integration_health import HEALTH_STATES

        return HEALTH_STATES if self.kind == "integration_status" else None

    def _health(self):
        return self.coordinator.engine.health.snapshot(
            self.coordinator.engine, self.vehicle
        )

    @property
    def native_value(self):
        data = self._health()
        if self.kind == "integration_status":
            return data["status"]
        return data["poll_error"] or (data["last_error"] or {}).get("code") or "none"

    @property
    def extra_state_attributes(self):
        return self._health()


class V3IntegrationProblem(V3BaseEntity, BinarySensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = canonical_entity_name("binary_sensor.integration_problem")

    def __init__(self, coordinator, vehicle):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = (
            f"{vehicle.vin.lower()}_binary_sensor_integration_problem"
        )

    @property
    def available(self):
        return True

    @property
    def is_on(self):
        return self.coordinator.engine.health.snapshot(
            self.coordinator.engine, self.vehicle
        )["problem"]


class V3ChargingReady(V3BaseEntity, BinarySensorEntity):
    """Explicit reported readiness, not charging active or authorization."""

    _attr_name = "Charging ready"
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, coordinator, vehicle):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_binary_sensor_charging_ready"

    @property
    def _reading(self):
        return self.vehicle.readings.get("chargingState", {})

    @property
    def is_on(self):
        from .vehicle import charging_ready

        return charging_ready(self._reading.get("value"))

    @property
    def available(self):
        return (
            super().available
            and _reading_available(self._reading)
            and self.is_on is not None
        )

    @property
    def extra_state_attributes(self):
        return {
            "source_attribute": "chargingState",
            **reading_freshness_attributes(self._reading),
            "semantics": "explicit_readiness_not_charging_active_or_permission",
        }


class V3AccessSummary(V3BaseEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["open", "closed", "stale", "unknown_data"]

    def __init__(self, coordinator, vehicle, kind):
        super().__init__(coordinator, vehicle)
        self.kind = kind
        self._attr_unique_id = f"{vehicle.vin.lower()}_sensor_{kind}_status"
        self._attr_name = canonical_entity_name("sensor." + kind + "_status")

    @property
    def available(self):
        return getattr(self.vehicle, "inventory_present", True)

    @property
    def native_value(self):
        from .access_summary import access_summary

        state, _ = access_summary(self.vehicle, self.kind)
        return "unknown_data" if state == "unknown" else state

    @property
    def extra_state_attributes(self):
        from .access_summary import access_summary

        return access_summary(self.vehicle, self.kind)[1]


class V3StatusSensor(V3BaseEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: V3CleanCoordinator, vehicle: V3Vehicle, kind: str):
        super().__init__(coordinator, vehicle)
        self.kind = kind
        identifiers = {
            "cloud": "cloud_last_successful_poll",
            "age": "vehicle_data_age",
            "freshness": "vehicle_data_freshness",
            "discovery": "discovery_coverage",
        }
        self._attr_unique_id = f"{vehicle.vin.lower()}_sensor_{identifiers[kind]}"
        self._attr_name = {
            "cloud": canonical_entity_name("sensor.cloud_last_successful_poll"),
            "age": canonical_entity_name("sensor.vehicle_data_age"),
            "freshness": canonical_entity_name("sensor.vehicle_data_freshness"),
            "discovery": canonical_entity_name("sensor.discovery_coverage"),
        }[kind]

    @property
    def device_class(self):
        return (
            SensorDeviceClass.TIMESTAMP
            if self.kind == "cloud"
            else SensorDeviceClass.ENUM
            if self.kind == "freshness"
            else None
        )

    @property
    def options(self):
        return (
            ["fresh", "partial", "delayed", "stale", "unknown"]
            if self.kind == "freshness"
            else None
        )

    @property
    def state_class(self):
        return SensorStateClass.MEASUREMENT if self.kind == "age" else None

    def _discovery_progress(self):
        from .read_discovery import user_progress

        engine = self.coordinator.engine
        profile = getattr(engine, "profiles", {}).get(self.vehicle.vin.lower())
        if profile is None:
            return {}
        if hasattr(engine, "discovery_progress"):
            return engine.discovery_progress(self.vehicle, profile)
        return user_progress(self.vehicle, profile, engine.auth)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.kind in ("age", "freshness"):
            self.async_on_remove(
                async_track_time_interval(
                    self.hass, self._async_clock_tick, timedelta(minutes=5)
                )
            )

    @callback
    def _async_clock_tick(self, _now: datetime) -> None:
        self.async_write_ha_state()

    def _vehicle_age(self):
        from .freshness import vehicle_capture_summary

        return vehicle_capture_summary(self.vehicle)["vehicle_age_minutes"]

    def _freshness(self):
        from .freshness import vehicle_capture_summary

        return vehicle_capture_summary(self.vehicle)["vehicle_freshness"]

    @property
    def native_unit_of_measurement(self):
        return (
            UnitOfTime.MINUTES
            if self.kind == "age"
            else PERCENTAGE
            if self.kind == "discovery"
            else None
        )

    @property
    def available(self) -> bool:
        return True  # Diagnostic sensors stay visible during outages.

    @property
    def native_value(self):
        if self.kind == "discovery":
            return self._discovery_progress().get("read_assessment_percent")
        if self.kind == "cloud":
            return self.coordinator.engine.last_cloud_poll_success
        if self.kind in ("age", "freshness"):
            age = self._vehicle_age()
            if self.kind == "age":
                return age
            return self._freshness()
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        engine = self.coordinator.engine
        if self.kind == "discovery":
            return self._discovery_progress()
        if self.kind in ("age", "freshness"):
            from .freshness import capture_coverage, vehicle_capture_summary
            from .structured_details import details_for

            now = datetime.now(UTC)
            coverage = capture_coverage(self.vehicle, now)
            result = {
                **vehicle_capture_summary(self.vehicle, now),
                "cloud_last_successful_poll": (
                    engine.last_cloud_poll_success.isoformat()
                    if engine.last_cloud_poll_success
                    else None
                ),
                "cloud_last_attempt": (
                    engine.last_cloud_poll_attempt.isoformat()
                    if engine.last_cloud_poll_attempt
                    else None
                ),
                "last_cloud_poll_succeeded": getattr(
                    engine,
                    "last_cloud_poll_succeeded",
                    self.coordinator.last_update_success,
                ),
                "job_capture_coverage": coverage,
            }
            if self.kind == "freshness":
                result.update(
                    details_for(self.vehicle, "readiness_detail"),
                    discovery=self._discovery_progress(),
                )
            return result
        if self.kind == "cloud":
            return {
                "cloud_poll_succeeded": getattr(
                    engine,
                    "last_cloud_poll_succeeded",
                    self.coordinator.last_update_success,
                ),
                "last_attempt": engine.last_cloud_poll_attempt.isoformat()
                if engine.last_cloud_poll_attempt
                else None,
                "requests": engine.transport.request_count
                if hasattr(engine.transport, "request_count")
                else None,
            }
        return {}


class V3LocalServiceSensor(V3BaseEntity, SensorEntity):
    """Historical local dealer/service entities, not Audi cloud diagnostics."""

    def __init__(self, coordinator, vehicle, kind):
        super().__init__(coordinator, vehicle)
        self.kind = kind
        self._attr_unique_id = f"{vehicle.vin.lower()}_sensor_{kind}"
        self._attr_name = canonical_entity_name("sensor." + kind)
        self._attr_icon = "mdi:store" if kind == "local_dealer" else "mdi:car-wrench"

    @property
    def available(self):
        return True

    def _local(self):
        # Shared config-only helper; no V2 model or business API.
        from ..local_extensions import get_local_dealer

        return get_local_dealer(self.coordinator.engine.entry.options, self.vehicle.vin)

    def _value(self, ident):
        row = self.vehicle.readings.get(ident)
        return (
            row.get("value") if _reading_available(row, allow_last_known=True) else None
        )

    @property
    def native_value(self):
        if self.kind == "local_dealer":
            return self._local().get("dealer_name", "Not configured")
        numbers = [
            x
            for x in (
                self._value("MAINTENANCE_INTERVAL_TIME_TO_INSPECTION"),
                self._value("MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE"),
            )
            if type(x) in (int, float)
        ]
        if any(x <= 0 for x in numbers):
            return "overdue"
        if any(x <= 30 for x in numbers):
            return "due_soon"
        if numbers:
            return "scheduled"
        return (
            "appointment_recorded"
            if self._local().get("next_service_date")
            else "unknown"
        )

    @property
    def extra_state_attributes(self):
        data = self._local()
        if self.kind == "local_dealer":
            return {
                "source": "Home Assistant local configuration (not Audi)",
                "configured": bool(data),
                "configuration_path": "Audi Connect > Configure > Edit dealer and local service details",
                **{k: v for k, v in data.items() if k != "dealer_name"},
            }
        from .structured_details import details_for

        return {
            **details_for(
                self.vehicle,
                "health_warning_evidence_detail",
                "low_voltage_battery_detail",
                "battery_support_detail",
            ),
            "inspection_due_days": self._value(
                "MAINTENANCE_INTERVAL_TIME_TO_INSPECTION"
            ),
            "inspection_due_km": self._value(
                "MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION"
            ),
            "oil_service_due_days": self._value(
                "MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE"
            ),
            "oil_service_due_km": self._value(
                "MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE"
            ),
            "next_appointment_local": data.get("next_service_date"),
            "warranty_expiry_local": data.get("warranty_expiry"),
            "maintenance_source": "Audi vehicleHealthInspection when reported",
            "appointment_source": "Home Assistant local configuration, not Audi",
        }


class V3ApiQuotaSensor(V3BaseEntity, RestoreSensor):
    """One account-level HA entity; never multiply quota sensors per VIN."""

    _attr_name = canonical_entity_name("sensor.api_requests_remaining")
    _attr_icon = "mdi:api"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, vehicle, entry_id):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{entry_id}_api_requests_remaining"
        self._restored_native_value: int | None = None
        self._restored_last_observed: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.engine.transport.remaining_calls is not None:
            return
        restored = await self.async_get_last_sensor_data()
        if (
            restored is not None
            and type(restored.native_value) is int
            and restored.native_value >= 0
        ):
            self._restored_native_value = restored.native_value
        last_state = await self.async_get_last_state()
        if last_state is not None:
            if self._restored_native_value is None and last_state.state.isdigit():
                self._restored_native_value = int(last_state.state)
            stamp = last_state.attributes.get("last_observed")
            if isinstance(stamp, str):
                self._restored_last_observed = stamp

    @property
    def available(self):
        return True

    @property
    def native_value(self):
        # Restored quota is display-only; never seed V3 transport budgeting.
        current = self.coordinator.engine.transport.remaining_calls
        return current if current is not None else self._restored_native_value

    @property
    def extra_state_attributes(self):
        transport = self.coordinator.engine.transport
        stamp = getattr(transport, "remaining_calls_observed_at", None)
        if transport.remaining_calls is not None:
            return {
                "last_observed": stamp.isoformat() if stamp else None,
                "value_restored": False,
                "value_source": "live_header",
                "value_is_current": True,
            }
        return {
            "last_observed": self._restored_last_observed,
            "value_restored": self._restored_native_value is not None,
            "value_source": "last_known"
            if self._restored_native_value is not None
            else "unknown",
            "value_is_current": False,
            "current_remaining": None,
        }


class V3CloudRefreshButton(V3BaseEntity, ButtonEntity):
    _attr_name = canonical_entity_name("button.v3_refresh_cloud")
    _attr_icon = "mdi:cloud-refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: V3CleanCoordinator, vehicle: V3Vehicle):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_button_v3_refresh_cloud"

    @property
    def available(self) -> bool:
        # An account refresh is independent of one VIN or a failed cloud poll.
        return True

    async def async_press(self) -> None:
        # GET refresh; not a vehicle-wake POST. Polling budget stays enforced.
        await self.coordinator.async_request_refresh()


def _reading_age_minutes(captured: str | None) -> float | None:
    from .freshness import capture_age_minutes

    return capture_age_minutes(captured)


def _reading_available(
    reading: dict[str, Any] | None,
    *,
    allow_last_known: bool = False,
) -> bool:
    if (
        not reading
        or reading.get("value") is None
        or reading.get("status") == "invalid_value"
    ):
        return False
    if allow_last_known:
        # Display only. Command projections keep their independent freshness gate.
        return reading.get("status") in ("verified", "readable_but_stale")
    captured_age = _reading_age_minutes(reading.get("captured"))
    if captured_age is not None:
        return captured_age <= 60
    # MBB legacy responses may not include a vehicle capture timestamp.
    # Expose only *recently observed cloud values*, with explicitly unknown
    # vehicle freshness; never call them verified-fresh vehicle data.
    observed_age = _reading_age_minutes(reading.get("observed"))
    return bool(
        reading.get("family") == "mbb"
        and reading.get("status") == "readable_but_stale"
        and observed_age is not None
        and observed_age <= 60
    )


class V3ReadOnlySensor(V3BaseEntity, SensorEntity):
    """Read-only V3 entity reusing a historical V2 unique ID where mapped."""

    def __init__(
        self,
        coordinator: V3CleanCoordinator,
        vehicle: V3Vehicle,
        attribute: dict[str, Any],
    ):
        super().__init__(coordinator, vehicle)
        self.attribute = attribute
        self._attr_unique_id = f"{vehicle.vin.lower()}_sensor_{attribute['entity_key']}"
        contract = attribute.get("contract") or contract_for(attribute["entity_key"])
        self._attr_entity_registry_visible_default = not compatibility_hidden(
            vehicle, "sensor." + attribute["entity_key"]
        )
        self._semantic_contract = contract
        self._allow_last_known = contract.get("display_last_known", False) is True
        self._attr_name = (
            contract.get("name")
            if attribute.get("local")
            else canonical_entity_name("sensor." + attribute["entity_key"], vehicle)
        ) or attribute["entity_key"].replace("_", " ").capitalize()
        self._attr_native_unit_of_measurement = contract.get("unit")
        self._attr_icon = contract.get("icon")
        if contract.get("device_class"):
            self._attr_device_class = SensorDeviceClass(contract["device_class"])
        if contract.get("state_class"):
            self._attr_state_class = SensorStateClass(contract["state_class"])
        if contract.get("precision") is not None:
            self._attr_suggested_display_precision = contract["precision"]
        if contract.get("category") == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        if not getattr(self.vehicle, "inventory_present", True):
            return False
        if self.attribute.get("entity_key") == "car_type" and not self.attribute.get(
            "local"
        ):
            from .vehicle import powertrain_identity

            return powertrain_identity(self.vehicle)["value"] is not None
        profile = getattr(
            getattr(self.coordinator, "engine", None), "profiles", {}
        ).get(self.vehicle.vin.lower())
        if profile and self.attribute["id"] in getattr(
            profile, "attribute_disabled", ()
        ):
            return False
        if self.attribute.get("local") and (
            not profile or self.attribute["id"] not in profile.attribute_routes
        ):
            return False
        reading = projection_reading(self.vehicle, self.attribute)[1]
        return _reading_available(
            reading, allow_last_known=self._allow_last_known
        ) and not semantic_value_issue(
            self.attribute["entity_key"], reading.get("value"), self._semantic_contract
        )

    @property
    def native_value(self):
        if self.attribute.get("entity_key") == "car_type" and not self.attribute.get(
            "local"
        ):
            from .vehicle import powertrain_identity

            return powertrain_identity(self.vehicle)["value"]
        reading = projection_reading(self.vehicle, self.attribute)[1]
        value = reading.get("value") if reading else None
        if semantic_value_issue(
            self.attribute["entity_key"], value, self._semantic_contract
        ):
            return None
        if self.device_class == SensorDeviceClass.TIMESTAMP:
            from .attribute_runtime import _capture_in_utc

            return _capture_in_utc(value)
        if (
            self.attribute["id"] in ("vehicleReportedOnline", "vehicleReportedActive")
            and type(value) is bool
        ):
            return (
                ("online" if value else "offline")
                if self.attribute["id"] == "vehicleReportedOnline"
                else ("active" if value else "inactive")
            )
        if self.attribute["id"] == "externalPower":
            return {"ready": "Ready", "unavailable": "Not Ready"}.get(value, value)
        if self.attribute["id"] == "chargingPlugAutoUnlock":
            return {"on": "enabled", "off": "disabled"}.get(value, value)
        return value if isinstance(value, (str, int, float, bool)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.attribute.get("entity_key") == "car_type" and not self.attribute.get(
            "local"
        ):
            from .vehicle import powertrain_identity

            evidence = powertrain_identity(self.vehicle)
            from .structured_details import details_for

            return {
                "classification_sources": evidence["sources"],
                "classification_conflict": evidence["conflict"],
                **details_for(self.vehicle, "connected_services_detail"),
            }
        source, reading = projection_reading(self.vehicle, self.attribute)
        reading = reading or {}
        from .structured_details import details_for

        detail_keys = {
            "doors_trunk_status": (
                "door_detail",
                "window_detail",
                "access_overall_detail",
                "light_detail",
                "access_requests_detail",
            ),
            "charging_timer_enabled_count": (
                "charging_timers_detail",
                "departure_charging_timers_detail",
                "battery_care_detail",
                "charging_profile_context_detail",
            ),
            "climatisation_timer_enabled_count": (
                "climate_timers_detail",
                "ventilation_timers_detail",
            ),
            "charging_state": (
                "charging_timers_detail",
                "departure_charging_timers_detail",
                "battery_care_detail",
                "charging_profile_context_detail",
            ),
            "charging_mode": (
                "charging_timers_detail",
                "departure_charging_timers_detail",
                "battery_care_detail",
                "charging_profile_context_detail",
            ),
            "vehicle_reported_online": ("readiness_detail",),
            "vehicle_reported_active": ("readiness_detail",),
        }
        details = details_for(
            self.vehicle, *detail_keys.get(self.attribute.get("entity_key"), ())
        )
        if self.attribute.get("entity_key") in (
            "charging_mode",
            "charging_state",
            "charging_timer_enabled_count",
        ):
            preferred = self.vehicle.readings.get("preferredChargeMode", {})
            details["preferred_charge_mode"] = (
                preferred.get("value")
                if preferred.get("value") in ("manual", "timer")
                else None
            )
            details["preferred_charge_mode_captured"] = preferred.get("captured")
        if self.attribute.get("entity_key") == "charging_timer_enabled_count":
            details.update(
                {
                    "charging_profiles": self.vehicle.charging_profiles,
                    "active_charging_profile_id": self.vehicle.active_charging_profile_id,
                    "charging_profiles_captured": self.vehicle.charging_profiles_captured,
                }
            )
        if self.attribute.get("entity_key") == "range":
            from .product_contract import normalized_range_details

            details = normalized_range_details(self.vehicle)
        return {
            **details,
            "v3_capability": self.attribute["capability"],
            "v2_attribute": self.attribute["id"],
            "observed_source": source,
            "api_family": reading.get("family", "cariad"),
            "response_mapping": reading.get("path"),
            **reading_freshness_attributes(
                reading, allow_last_known=self._allow_last_known
            ),
        }


class V3TripSensor(V3BaseEntity, SensorEntity):
    """Historical V2 trip timestamp plus normalized, unit-explicit attributes."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, vehicle, key):
        super().__init__(coordinator, vehicle)
        self.key = key
        self._attr_unique_id = f"{vehicle.vin.lower()}_sensor_{key}"
        self._attr_name = canonical_entity_name("sensor." + key)

    @property
    def native_value(self):
        from .attribute_runtime import _capture_in_utc

        return _capture_in_utc(self.vehicle.trips.get(self.key, {}).get("timestamp"))

    @property
    def available(self):
        if not getattr(self.vehicle, "inventory_present", True):
            return False
        return self.native_value is not None

    @property
    def extra_state_attributes(self):
        return {
            k: v
            for k, v in self.vehicle.trips.get(self.key, {}).items()
            if k not in ("tripID", "timestamp") and v is not None
        }


class V3TripHistorySensor(V3BaseEntity, SensorEntity):
    """Native access to normalized observed trips; not a lifetime meter."""

    _attr_name = canonical_entity_name("sensor.trip_history")
    _attr_icon = "mdi:map-clock-outline"
    _unrecorded_attributes = frozenset({"trips"})

    def __init__(self, coordinator, vehicle):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_sensor_trip_history"

    @property
    def available(self):
        return getattr(self.vehicle, "inventory_present", True) and bool(
            self.vehicle.trip_history
        )

    @property
    def native_value(self):
        return len(self.vehicle.trip_history) if self.vehicle.trip_history else None

    @property
    def extra_state_attributes(self):
        from .trips import MAX_TRIP_HISTORY, MAX_TRIP_ENTITY_ROWS

        rows = self.vehicle.trip_history
        return {
            "trips": [
                {
                    k: v
                    for k, v in row.items()
                    if k not in ("tripID", "source", "units") and v is not None
                }
                for row in rows[:MAX_TRIP_ENTITY_ROWS]
            ],
            "units": rows[0].get("units", {}) if rows else {},
            "newest_trip": rows[0]["timestamp"] if rows else None,
            "oldest_trip": rows[-1]["timestamp"] if rows else None,
            "history_limit": MAX_TRIP_HISTORY,
            "entity_row_limit": MAX_TRIP_ENTITY_ROWS,
            "archived_count": len(rows),
            "additional_rows_available": len(rows) > MAX_TRIP_ENTITY_ROWS,
            "coverage": "observed_records",
        }


class V3TripMetricSensor(V3BaseEntity, SensorEntity):
    """A completed-trip measurement, not a continuously accruing meter."""

    def __init__(self, coordinator, vehicle, key):
        super().__init__(coordinator, vehicle)
        self.key = key
        self.contract = trip_metric_contracts()[key]
        self._attr_unique_id = f"{vehicle.vin.lower()}_sensor_{key}"
        self._attr_name = canonical_entity_name("sensor." + key)
        self._attr_native_unit_of_measurement = self.contract["unit"]
        self._attr_suggested_display_precision = self.contract["precision"]
        if self.contract["device_class"]:
            self._attr_device_class = SensorDeviceClass(self.contract["device_class"])
        # Per-trip values must never be total_increasing. Long-term trip
        # counters can reset; do not promise lifetime-meter statistics yet.
        self._attr_state_class = None

    @property
    def native_value(self):
        return trip_metric_value(self.vehicle, self.key)

    @property
    def available(self):
        return (
            getattr(self.vehicle, "inventory_present", True)
            and self.native_value is not None
        )

    @property
    def extra_state_attributes(self):
        trip = self.vehicle.trips.get(self.contract["source"], {})
        return {
            "trip_ended": trip.get("timestamp"),
            "trip_scope": self.contract["source"],
        }


class V3ReadOnlyBinarySensor(V3BaseEntity, BinarySensorEntity):
    """Mirror V2's binary conversion for fields with an actual known mapping."""

    def __init__(
        self,
        coordinator: V3CleanCoordinator,
        vehicle: V3Vehicle,
        attribute: dict[str, Any],
    ):
        super().__init__(coordinator, vehicle)
        self.attribute = attribute
        self._attr_unique_id = (
            f"{vehicle.vin.lower()}_binary_sensor_{attribute['entity_key']}"
        )
        contract = attribute.get("contract") or binary_contract_for(
            attribute["entity_key"]
        )
        self._allow_last_known = (
            not attribute.get("local") and contract.get("display_last_known") is True
        )
        self._attr_name = (
            contract.get("name")
            if attribute.get("local")
            else canonical_entity_name(
                "binary_sensor." + attribute["entity_key"], vehicle
            )
        ) or attribute["entity_key"].replace("_", " ").capitalize()
        if contract.get("device_class"):
            self._attr_device_class = BinarySensorDeviceClass(contract["device_class"])
        self._attr_icon = contract.get("icon")
        if contract.get("category") == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        if not getattr(self.vehicle, "inventory_present", True):
            return False
        profile = getattr(
            getattr(self.coordinator, "engine", None), "profiles", {}
        ).get(self.vehicle.vin.lower())
        if profile and self.attribute["id"] in getattr(
            profile, "attribute_disabled", ()
        ):
            return False
        if self.attribute.get("local") and (
            not profile or self.attribute["id"] not in profile.attribute_routes
        ):
            return False
        reading = self.vehicle.readings.get(self.attribute["id"])
        if self.is_on is None:
            return False
        if self.attribute["id"] == "is_moving" and reading:
            # Historical parking endpoint indication, not a live GPS fix.
            age = _reading_age_minutes(reading.get("observed"))
            return (
                reading.get("path")
                in ("parkingposition HTTP 204", "parkingposition parked sample")
                and type(reading.get("value")) is bool
                and age is not None
                and age <= 60
            )
        return _reading_available(reading, allow_last_known=self._allow_last_known)

    @property
    def is_on(self) -> bool | None:
        reading = self.vehicle.readings.get(self.attribute["id"])
        if not reading:
            return None
        value = reading.get("value")
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            key = self.attribute["entity_key"]
            # V2 accessors normalize these raw Audi status enums before the
            # legacy binary platform sees them. V3 must do the same.
            if key == "plug_state":
                return {"connected": True, "disconnected": False}.get(normalized)
            if key == "plug_lock_state":
                return {"locked": False, "unlocked": True}.get(normalized)
            if normalized in ("normal", "false", "off", "inactive", "closed", "locked"):
                return False
            if normalized in ("true", "on", "active", "open", "unlocked"):
                return True
            return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        reading = self.vehicle.readings.get(self.attribute["id"]) or {}
        return {
            "v3_capability": self.attribute["capability"],
            "response_mapping": reading.get("path"),
            **reading_freshness_attributes(
                reading, allow_last_known=self._allow_last_known
            ),
        }


# Native HA controls are created only for personally verified route mappings.
# The workbench always shows unverified candidates without injecting unusable
# lock/button/switch entities into a customer's HA device.
class V3ControlButton(V3BaseEntity, ButtonEntity):
    def __init__(
        self,
        coordinator: V3CleanCoordinator,
        vehicle: V3Vehicle,
        descriptor: tuple[str, str, str, str, str],
    ):
        super().__init__(coordinator, vehicle)
        self.key, self._attr_name, self._attr_icon, self.capability, self.action = (
            descriptor
        )
        self._attr_unique_id = f"{vehicle.vin.lower()}_button_{self.key}"
        category = canonical_entity_category("button." + self.key)
        self._attr_entity_category = EntityCategory(category) if category else None
        if superseded_control_button(coordinator.engine, vehicle, "button." + self.key):
            self._attr_entity_registry_visible_default = False
        if self.key == "wake_vehicle_modern":
            self._attr_entity_registry_enabled_default = False

    @property
    def available(self) -> bool:
        if not getattr(self.vehicle, "inventory_present", True):
            return False
        return (
            self.coordinator.last_update_success
            and self.coordinator.engine.control_enabled(
                self.vehicle.vin, self.action, self.capability
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        profile = self.coordinator.engine.profiles.get(self.vehicle.vin.lower())
        return {
            **self._control_attributes(self.capability, (self.action,)),
            "api_route": (
                getattr(profile, "fast_bindings", {})
                .get(f"{self.capability}.{self.action}", {})
                .get("operation")
                if profile
                else None
            ),
            "binding_evidence": _binding_status(
                profile, f"{self.capability}.{self.action}"
            ),
            "last_command": self.vehicle.last_command_result,
        }

    async def async_press(self) -> None:
        if not self.available:
            raise HomeAssistantError(
                "Control unavailable; review Audi Engineering Dashboard"
            )
        try:
            await self.coordinator.engine.send_control(
                self.vehicle.vin, self.action, self.capability
            )
        except (ValueError, RuntimeError) as err:
            raise HomeAssistantError(str(err)) from err
        self.async_write_ha_state()


class V3OperationalSwitch(V3BaseEntity, SwitchEntity):
    """One normalized stateful control, using the same command owner as buttons."""

    def __init__(self, coordinator, vehicle, key):
        super().__init__(coordinator, vehicle)
        self.key = key
        self.definition = stateful_controls()[key]
        self._attr_unique_id = f"{vehicle.vin.lower()}_switch_{key}"
        self._attr_name = canonical_entity_name("switch." + key)
        self._attr_icon = self.definition["icon"]

    def _enabled(self, action):
        return self.coordinator.engine.control_enabled(
            self.vehicle.vin, self.definition[action], self.definition["capability"]
        )

    @property
    def available(self):
        return (
            getattr(self.vehicle, "inventory_present", True)
            and self.coordinator.last_update_success
            and self._enabled("on")
            and self._enabled("off")
        )

    def _projection(self):
        from .vehicle import charging_active

        value, source = _reading_projection(
            self.coordinator, self.vehicle, self.definition["attribute"]
        )
        state = (
            charging_active(value)
            if self.key == "charging"
            else value
            if type(value) is bool
            else None
        )
        return state, source

    @property
    def is_on(self):
        return self._projection()[0]

    @property
    def extra_state_attributes(self):
        row, state = stateful_reading(self.vehicle, self.key)
        return {
            **self._control_attributes(
                self.definition["capability"],
                (self.definition["on"], self.definition["off"]),
                attribute=self.definition["attribute"],
                reading=row or {},
                source=self._projection()[1],
            ),
            "last_reported_state": state,
            "on_enabled": self._enabled("on"),
            "off_enabled": self._enabled("off"),
        }

    async def _send(self, action):
        if not self.available or not self._enabled(action):
            raise HomeAssistantError(
                "Vehicle action unavailable; review Audi Engineering Dashboard"
            )
        try:
            await self.coordinator.engine.send_control(
                self.vehicle.vin, self.definition[action], self.definition["capability"]
            )
        except (ValueError, RuntimeError) as err:
            raise HomeAssistantError(str(err)) from err
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._send("on")

    async def async_turn_off(self, **kwargs):
        await self._send("off")


class V3ModelSensor(V3BaseEntity, SensorEntity):
    """Manufacturer inventory, not a vehicle capture or a nickname."""

    _unrecorded_attributes = frozenset({"vehicle_image_url", "entity_picture"})
    _attr_name = canonical_entity_name("sensor.model")
    _attr_icon = "mdi:car-info"

    def __init__(self, coordinator, vehicle):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_sensor_model"

    def _handle_coordinator_update(self):
        # Entity identity survives temporary missing inventory. Update the
        # existing HA device when a real manufacturer model arrives later.
        if self.hass is not None and self.vehicle.model:
            from homeassistant.helpers import device_registry as dr

            registry = dr.async_get(self.hass)
            device = registry.async_get_device(
                identifiers={(DOMAIN, self.vehicle.vin.lower())}
            )
            model = self.device_info.get("model")
            if device is not None and model and device.model != model:
                registry.async_update_device(device.id, model=model)
        super()._handle_coordinator_update()

    @property
    def entity_picture(self):
        return self.vehicle.image_url

    @property
    def native_value(self):
        return self.vehicle.model or self.vehicle.registry_model or None

    @property
    def available(self):
        return (
            getattr(self.vehicle, "inventory_present", True)
            and self.native_value is not None
        )

    @property
    def extra_state_attributes(self):
        from .vehicle import powertrain_identity

        identity = powertrain_identity(self.vehicle)
        from .structured_details import details_for

        return {
            **details_for(self.vehicle, "connected_services_detail"),
            "model_family": self.vehicle.model_family or None,
            "model_year": self.vehicle.model_year or None,
            "model_source": self.vehicle.model_source or None,
            "identity_restored": self.vehicle.identity_restored,
            "identity_observed_at": self.vehicle.identity_observed_at,
            "identity_operation": self.vehicle.identity_operation,
            "year_operation": self.vehicle.year_operation,
            "presentation_source": "manufacturer"
            if self.vehicle.model
            else "ha_registry_last_known"
            if self.vehicle.registry_model
            else None,
            "vehicle_image_url": self.vehicle.image_url,
            "vehicle_image_status": self.vehicle.image_status,
            "vehicle_type": identity["value"],
            "classification_sources": identity["sources"],
            "classification_conflict": identity["conflict"],
        }


class V3ClimateQuickSwitch(V3BaseEntity, SwitchEntity):
    _attr_name = canonical_entity_name("switch.climate_quick_control")
    _attr_entity_registry_visible_default = False
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:car-air-conditioner"

    def __init__(self, coordinator: V3CleanCoordinator, vehicle: V3Vehicle):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_switch_climate_quick_control"

    @property
    def is_on(self) -> bool | None:
        state = _climate_reported_state(self.coordinator, self.vehicle)
        return (
            True if state in _CLIMATE_ON else False if state in _CLIMATE_OFF else None
        )

    @property
    def available(self) -> bool:
        if not getattr(self.vehicle, "inventory_present", True):
            return False
        engine = self.coordinator.engine
        # A stale vehicle state is unknown, not a disabled explicit action.
        return (
            self.coordinator.last_update_success
            and engine.control_enabled(self.vehicle.vin, "start")
            and engine.control_enabled(self.vehicle.vin, "stop")
        )

    @property
    def extra_state_attributes(self):
        return self._control_attributes(
            "climate",
            ("start", "stop", "start_with_settings"),
            attribute="climate",
            reading=self.vehicle.readings.get("climatisationState") or {},
            source=_climate_projection(self.coordinator, self.vehicle)[1],
            allow_last_known=True,
        )

    async def async_turn_on(self, **kwargs) -> None:
        if not self.available:
            raise HomeAssistantError(
                "Climate ON/OFF requires available verified controls"
            )
        state, source = _climate_projection(self.coordinator, self.vehicle)
        if source not in ("vehicle", "command_pending") or state not in _CLIMATE_ON:
            await _send_climate(self.coordinator, self.vehicle, "start")
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        if not self.available:
            raise HomeAssistantError(
                "Climate ON/OFF requires available verified controls"
            )
        state, source = _climate_projection(self.coordinator, self.vehicle)
        if source not in ("vehicle", "command_pending") or state not in _CLIMATE_OFF:
            await _send_climate(self.coordinator, self.vehicle, "stop")
        self.async_write_ha_state()


class V3LockEntity(V3BaseEntity, LockEntity):
    _attr_name = canonical_entity_name("lock.lock")
    _attr_icon = "mdi:car-door-lock"

    def __init__(self, coordinator: V3CleanCoordinator, vehicle: V3Vehicle):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_lock_lock"
        self._pending_refresh = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_pending_refresh)
        self._schedule_pending_refresh()

    @callback
    def _cancel_pending_refresh(self):
        if self._pending_refresh is not None:
            self._pending_refresh()
            self._pending_refresh = None

    @callback
    def _schedule_pending_refresh(self):
        from .command_journal import TEMPORARY_ERROR_COOLDOWN_SECONDS
        from .command_readback import latest_readback_command

        self._cancel_pending_refresh()
        if self.hass is None or not (self.is_locking or self.is_unlocking):
            return
        profile = getattr(self.coordinator.engine, "profiles", {}).get(
            self.vehicle.vin.lower()
        )
        record = latest_readback_command(profile, "doorLockStatus")
        if record is None:
            return
        delay = record.started_at + TEMPORARY_ERROR_COOLDOWN_SECONDS
        delay -= datetime.now(UTC).timestamp()
        if delay > 0:
            self._pending_refresh = async_call_later(
                self.hass, delay, self._pending_expired
            )

    @callback
    def _pending_expired(self, _now):
        self._pending_refresh = None
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self):
        super()._handle_coordinator_update()
        self._schedule_pending_refresh()


    @property
    def is_locked(self) -> bool | None:
        # No silent assumption that an unavailable lock status means unlocked.
        raw, _ = _reading_projection(
            self.coordinator, self.vehicle, "doorLockStatus", optimistic=False
        )
        if not isinstance(raw, str):
            return None
        value = raw.strip().lower()
        if value == "locked":
            return True
        if value == "unlocked":
            return False
        return None

    @property
    def available(self) -> bool:
        if not getattr(self.vehicle, "inventory_present", True):
            return False
        engine = self.coordinator.engine
        pin = configured_spin(engine.auth)
        # Do not hide an authorized explicit command just because the car
        # is sleeping. is_locked still returns None for stale/unknown status.
        return (
            self.coordinator.last_update_success
            and bool(pin)
            and (
                engine.control_enabled(self.vehicle.vin, "lock", "access")
                or engine.control_enabled(self.vehicle.vin, "unlock", "access")
                or self.is_locking
                or self.is_unlocking
                or self.is_locked is not None
            )
        )

    @property
    def extra_state_attributes(self):
        _, source = _reading_projection(
            self.coordinator, self.vehicle, "doorLockStatus", optimistic=False
        )
        attrs = self._control_attributes(
            "access", ("lock", "unlock"), attribute="doorLockStatus", source=source
        )
        return {
            **attrs,
            "lock_enabled": attrs["control_actions"]["lock"],
            "unlock_enabled": attrs["control_actions"]["unlock"],
        }

    def _pending_action(self, action):
        from .command_readback import latest_readback_command

        profile = getattr(
            getattr(self.coordinator, "engine", None), "profiles", {}
        ).get(self.vehicle.vin.lower())
        record = latest_readback_command(profile, "doorLockStatus")
        _, source = _reading_projection(
            self.coordinator, self.vehicle, "doorLockStatus", optimistic=False
        )
        return bool(record and record.action == action and source == "command_pending")

    @property
    def is_locking(self):
        return self._pending_action("lock")

    @property
    def is_unlocking(self):
        return self._pending_action("unlock")

    async def _send_access(self, action):
        # Dispatch uses the same authoritative guard as Workbench. Do not
        # turn a pending review or cooldown into a false authorization error.
        if not getattr(self.vehicle, "inventory_present", True):
            raise HomeAssistantError("Audi vehicle is not present in inventory")
        if not self.coordinator.last_update_success:
            raise HomeAssistantError("Audi connection unavailable")
        if not configured_spin(self.coordinator.engine.auth):
            raise HomeAssistantError("Audi S-PIN is not configured")
        try:
            await self.coordinator.engine.send_control(
                self.vehicle.vin, action, "access"
            )
        except (ValueError, RuntimeError) as err:
            raise HomeAssistantError(str(err)) from err
        self.async_write_ha_state()
        self._schedule_pending_refresh()

    async def async_lock(self, **kwargs) -> None:
        if self.is_locked is not True:
            await self._send_access("lock")

    async def async_unlock(self, **kwargs) -> None:
        if self.is_locked is not False:
            await self._send_access("unlock")


class V3ParkedTracker(V3BaseEntity, TrackerEntity):
    """V2-compatible GPS entity for the car's last PARKED position, not live GPS."""

    _attr_name = canonical_entity_name("device_tracker.position")
    _attr_entity_category = None
    _attr_icon = "mdi:car"
    _attr_should_poll = False
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: V3CleanCoordinator, vehicle: V3Vehicle):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_device_tracker_position"

    def _coordinates(self) -> tuple[float, float] | None:
        position = self.vehicle.position
        if not isinstance(position, dict):
            return None
        lat, lon = position.get("latitude"), position.get("longitude")
        if isinstance(lat, bool) or isinstance(lon, bool):
            return None
        try:
            latitude, longitude = float(lat), float(lon)
        except (ValueError, TypeError):
            return None
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None
        return latitude, longitude

    @property
    def available(self) -> bool:
        if not getattr(self.vehicle, "inventory_present", True):
            return False
        return self._coordinates() is not None

    @property
    def latitude(self) -> float | None:
        coords = self._coordinates()
        return coords[0] if coords else None

    @property
    def longitude(self) -> float | None:
        coords = self._coordinates()
        return coords[1] if coords else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        position = self.vehicle.position or {}
        captured = position.get("timestamp")
        row = self.vehicle.readings.get("position_last_updated", {})
        attrs = reading_freshness_attributes(
            {
                "value": captured,
                "captured": captured,
                "observed": row.get("observed"),
                "status": row.get("status", "unknown"),
            },
            allow_last_known=True,
        )
        return {
            **attrs,
            "position_source": "Audi last-known parked location, not live driving GPS",
            "position_captured_at": captured,
            "position_age_minutes": attrs["age_minutes"],
            "position_freshness": (
                "stale"
                if attrs["vehicle_freshness"] == "stale_last_known"
                else attrs["vehicle_freshness"]
            ),
        }


class V3ChargeTargetNumber(V3BaseEntity, NumberEntity):
    """V2 global charge-target identity; command gated by V3 route evidence."""

    _attr_name = canonical_entity_name("number.target_state_of_charge")
    _attr_entity_category = EntityCategory(
        canonical_entity_category("number.target_state_of_charge")
    )
    _attr_device_class = NumberDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 20
    _attr_native_max_value = 100
    _attr_native_step = 5
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: V3CleanCoordinator, vehicle: V3Vehicle):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_number_target_state_of_charge"

    @property
    def available(self) -> bool:
        if not getattr(self.vehicle, "inventory_present", True):
            return False
        return _reading_available(
            self.vehicle.readings.get("targetstateOfCharge"), allow_last_known=True
        ) and self.coordinator.engine.control_enabled(
            self.vehicle.vin, "set_target_soc", "charging"
        )

    @property
    def native_value(self) -> float | None:
        value, _ = _reading_projection(
            self.coordinator, self.vehicle, "targetstateOfCharge", allow_last_known=True
        )
        return (
            float(value)
            if (isinstance(value, (int, float)) and not isinstance(value, bool))
            else None
        )

    @property
    def extra_state_attributes(self):
        return self._control_attributes(
            "charging",
            ("set_target_soc",),
            attribute="targetstateOfCharge",
            source=_reading_projection(
                self.coordinator,
                self.vehicle,
                "targetstateOfCharge",
                allow_last_known=True,
            )[1],
            allow_last_known=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        if not self.available:
            raise HomeAssistantError(
                "V3 charging target write not yet verified for this vehicle"
            )
        await self.coordinator.engine.send_setting(
            self.vehicle.vin, "set_target_soc", int(value)
        )
        self.async_write_ha_state()


class V3LocationChargeTargetNumber(V3ChargeTargetNumber):
    """V2 active or named charging profile target, using immutable profile ID."""

    def __init__(self, coordinator, vehicle, profile_id=None):
        super().__init__(coordinator, vehicle)
        self.profile_id = profile_id
        key = (
            "active_charging_profile_target_soc"
            if profile_id is None
            else f"charge_profile_{profile_id}_target_soc"
        )
        self._attr_unique_id = f"{vehicle.vin.lower()}_number_{key}"
        self._attr_name = (
            canonical_entity_name("number.active_charging_profile_target_soc")
            if profile_id is None
            else canonical_entity_name(
                "number.charge_profile_{profile_id}_target_soc"
            ).format(profile_id=profile_id)
        )

    @property
    def native_value(self):
        profile_id = (
            self.vehicle.active_charging_profile_id
            if self.profile_id is None
            else self.profile_id
        )
        profile = next(
            (x for x in self.vehicle.charging_profiles if x["id"] == profile_id), None
        )
        value = profile.get("targetSOC_pct") if profile else None
        return float(value) if type(value) in (int, float) else None

    @property
    def available(self):
        if not getattr(self.vehicle, "inventory_present", True):
            return False
        return (
            self.native_value is not None
            and self.coordinator.engine.control_enabled(
                self.vehicle.vin, "set_location_charge_target", "charging"
            )
        )

    @property
    def extra_state_attributes(self):
        # The profile target belongs to the profile snapshot, not global SoC.
        row = self.vehicle.readings.get("charging_profile_context_detail", {})
        return self._control_attributes(
            "charging",
            ("set_location_charge_target",),
            reading={
                "value": self.native_value,
                "captured": self.vehicle.charging_profiles_captured,
                "observed": row.get("observed"),
                "status": row.get("status", "unknown"),
            },
            source="vehicle" if self.native_value is not None else "unknown",
            allow_last_known=True,
            correlate=False,
        )

    async def async_set_native_value(self, value):
        if not self.available or not float(value).is_integer():
            raise HomeAssistantError("Audi charge profile not available")
        await self.coordinator.engine.send_control(
            self.vehicle.vin,
            "set_location_charge_target",
            "charging",
            params={"value": int(value), "profile_id": self.profile_id},
        )


class V3PreheaterSwitch(V3BaseEntity, SwitchEntity):
    """Historical preheater control, never infer state from cabin climate."""

    _attr_name = canonical_entity_name("switch.preheater_active")
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator, vehicle):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_switch_preheater_active"

    @property
    def is_on(self):
        value, _ = _reading_projection(
            self.coordinator, self.vehicle, "preheater_active"
        )
        return value if type(value) is bool else None

    @property
    def available(self):
        if not getattr(self.vehicle, "inventory_present", True):
            return False
        engine = self.coordinator.engine
        return self.coordinator.last_update_success and any(
            engine.control_enabled(self.vehicle.vin, aspect, "climate")
            for aspect in ("preheater_start", "preheater_stop")
        )

    @property
    def extra_state_attributes(self):
        return self._control_attributes(
            "climate",
            ("preheater_start", "preheater_stop"),
            attribute="preheater_active",
            source=_reading_projection(
                self.coordinator, self.vehicle, "preheater_active"
            )[1],
        )

    async def _send(self, aspect):
        try:
            await self.coordinator.engine.send_control(
                self.vehicle.vin, aspect, "climate"
            )
        except (RuntimeError, ValueError) as err:
            raise HomeAssistantError(str(err)) from err
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._send("preheater_start")

    async def async_turn_off(self, **kwargs):
        await self._send("preheater_stop")


class V3ClimateSettingSwitch(V3BaseEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, vehicle, descriptor):
        super().__init__(coordinator, vehicle)
        key, self.reading, self.field = descriptor
        self._attr_unique_id = f"{vehicle.vin.lower()}_switch_{key}"
        self._attr_name = canonical_entity_name("switch." + key)

    @property
    def is_on(self):
        value, _ = _reading_projection(
            self.coordinator, self.vehicle, self.reading, allow_last_known=True
        )
        return value if type(value) is bool else None

    @property
    def available(self):
        if not getattr(self.vehicle, "inventory_present", True):
            return False
        return self.is_on is not None and self.coordinator.engine.control_enabled(
            self.vehicle.vin, "set_settings", "climate"
        )

    @property
    def extra_state_attributes(self):
        return self._control_attributes(
            "climate",
            ("set_settings",),
            attribute=self.reading,
            source=_reading_projection(
                self.coordinator, self.vehicle, self.reading, allow_last_known=True
            )[1],
            allow_last_known=True,
        )

    async def _write(self, value):
        if not self.available:
            raise HomeAssistantError("Audi climate setting unavailable")
        await self.coordinator.engine.send_control(
            self.vehicle.vin,
            "set_settings",
            "climate",
            params={self.field: value},
        )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._write(True)

    async def async_turn_off(self, **kwargs):
        await self._write(False)


class V3ChargeModeSelect(V3BaseEntity, SelectEntity):
    """V2 select identity, independent preferred-mode source and command gate."""

    _attr_name = canonical_entity_name("select.charge_mode")
    _attr_entity_category = EntityCategory(
        canonical_entity_category("select.charge_mode")
    )
    _attr_icon = "mdi:battery-clock"

    def __init__(self, coordinator: V3CleanCoordinator, vehicle: V3Vehicle):
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = f"{vehicle.vin.lower()}_select_charge_mode"

    @property
    def available(self) -> bool:
        if not getattr(self.vehicle, "inventory_present", True):
            return False
        return (
            _reading_available(
                self.vehicle.readings.get("preferredChargeMode"), allow_last_known=True
            )
            and bool(self.options)
            and self.current_option in self.options
            and self.coordinator.engine.control_enabled(
                self.vehicle.vin, "set_charge_mode", "charging"
            )
        )

    @property
    def options(self) -> list[str]:
        return supported_charge_modes(self.vehicle)

    @property
    def current_option(self) -> str | None:
        value, _ = _reading_projection(
            self.coordinator, self.vehicle, "preferredChargeMode", allow_last_known=True
        )
        if not isinstance(value, str) or value.lower() in {
            "",
            "invalid",
            "unknown",
            "unsupported",
        }:
            return None
        return value

    @property
    def extra_state_attributes(self):
        return self._control_attributes(
            "charging",
            ("set_charge_mode",),
            attribute="preferredChargeMode",
            source=_reading_projection(
                self.coordinator,
                self.vehicle,
                "preferredChargeMode",
                allow_last_known=True,
            )[1],
            allow_last_known=True,
        )

    async def async_select_option(self, option: str) -> None:
        if not self.available or option not in self.options:
            raise HomeAssistantError(
                "V3 preferred charge mode is not verified for this vehicle"
            )
        await self.coordinator.engine.send_setting(
            self.vehicle.vin, "set_charge_mode", option
        )
        self.async_write_ha_state()
