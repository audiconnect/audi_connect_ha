"""Source-derived historical V2 capability inventory for V3 discovery.

Generated from V2 audi_models.py field mappings, sensor/binary_sensor descriptors,
and the V2 selective-status job allowlist. No runtime dependency on V2 code.
An inventory entry is NOT a proven V3 response or an authorized vehicle action.
"""

from __future__ import annotations
import json
from typing import Any

INVENTORY: dict[str, Any] = json.loads(r"""{
  "schema_version": 1,
  "source": "audiconnect_v2_source_inventory",
  "jobs": [
    {
      "id": "access",
      "capability": "access"
    },
    {
      "id": "activeVentilation",
      "capability": "climate"
    },
    {
      "id": "auxiliaryHeating",
      "capability": "climate"
    },
    {
      "id": "batteryChargingCare",
      "capability": "charging"
    },
    {
      "id": "batterySupport",
      "capability": "charging"
    },
    {
      "id": "charging",
      "capability": "charging"
    },
    {
      "id": "chargingProfiles",
      "capability": "charging"
    },
    {
      "id": "chargingTimers",
      "capability": "charging"
    },
    {
      "id": "climatisation",
      "capability": "climate"
    },
    {
      "id": "climatisationTimers",
      "capability": "climate"
    },
    {
      "id": "departureProfiles",
      "capability": "charging"
    },
    {
      "id": "departureTimers",
      "capability": "charging"
    },
    {
      "id": "fuelStatus",
      "capability": "vehicle_status"
    },
    {
      "id": "honkAndFlash",
      "capability": "remote"
    },
    {
      "id": "hybridCarAuxiliaryHeating",
      "capability": "climate"
    },
    {
      "id": "lvBattery",
      "capability": "vehicle_status"
    },
    {
      "id": "measurements",
      "capability": "vehicle_status"
    },
    {
      "id": "oilLevel",
      "capability": "vehicle_status"
    },
    {
      "id": "readiness",
      "capability": "vehicle_status"
    },
    {
      "id": "userCapabilities",
      "capability": "vehicle_status"
    },
    {
      "id": "vehicleHealthInspection",
      "capability": "service"
    },
    {
      "id": "vehicleHealthWarnings",
      "capability": "vehicle_status"
    },
    {
      "id": "vehicleLights",
      "capability": "vehicle_status"
    }
  ],
  "attributes": [
    {
      "id": "TOTAL_RANGE",
      "capability": "vehicle_status",
      "v2_state": "TOTAL_RANGE",
      "job": "fuelStatus",
      "entity_key": "range",
      "platform": "sensor",
      "paths": [
        "fuelStatus.rangeStatus.value.totalRange_km"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "TANK_LEVEL_IN_PERCENTAGE",
      "capability": "vehicle_status",
      "v2_state": "TANK_LEVEL_IN_PERCENTAGE",
      "job": "measurements",
      "entity_key": "tank_level",
      "platform": "sensor",
      "paths": [
        "measurements.fuelLevelStatus.value.currentFuelLevel_pct"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "UTC_TIME_AND_KILOMETER_STATUS",
      "capability": "vehicle_status",
      "v2_state": "UTC_TIME_AND_KILOMETER_STATUS",
      "job": "measurements",
      "entity_key": "mileage",
      "platform": "sensor",
      "paths": [
        "measurements.odometerStatus.value.odometer"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "MAINTENANCE_INTERVAL_TIME_TO_INSPECTION",
      "capability": "service",
      "v2_state": "MAINTENANCE_INTERVAL_TIME_TO_INSPECTION",
      "job": "vehicleHealthInspection",
      "entity_key": "service_inspection_time",
      "platform": "sensor",
      "paths": [
        "vehicleHealthInspection.maintenanceStatus.value.inspectionDue_days"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION",
      "capability": "service",
      "v2_state": "MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION",
      "job": "vehicleHealthInspection",
      "entity_key": "service_inspection_distance",
      "platform": "sensor",
      "paths": [
        "vehicleHealthInspection.maintenanceStatus.value.inspectionDue_km"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE",
      "capability": "service",
      "v2_state": "MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE",
      "job": "vehicleHealthInspection",
      "entity_key": "oil_change_time",
      "platform": "sensor",
      "paths": [
        "vehicleHealthInspection.maintenanceStatus.value.oilServiceDue_days"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE",
      "capability": "service",
      "v2_state": "MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE",
      "job": "vehicleHealthInspection",
      "entity_key": "oil_change_distance",
      "platform": "sensor",
      "paths": [
        "vehicleHealthInspection.maintenanceStatus.value.oilServiceDue_km"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "OIL_LEVEL_DIPSTICKS_PERCENTAGE",
      "capability": "vehicle_status",
      "v2_state": "OIL_LEVEL_DIPSTICKS_PERCENTAGE",
      "job": "oilLevel",
      "entity_key": "oil_level",
      "platform": "sensor",
      "paths": [
        "oilLevel.oilLevelStatus.value.value"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "ADBLUE_RANGE",
      "capability": "vehicle_status",
      "v2_state": "ADBLUE_RANGE",
      "job": "measurements",
      "entity_key": "service_adblue_distance",
      "platform": "sensor",
      "paths": [
        "measurements.rangeStatus.value.adBlueRange"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "LIGHT_STATUS",
      "capability": "vehicle_status",
      "v2_state": "LIGHT_STATUS",
      "job": "vehicleLights",
      "entity_key": "vehicle_lights",
      "platform": "sensor",
      "paths": [
        "vehicleLights.lightsStatus.value.lights"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "doorLockStatus",
      "capability": "access",
      "v2_state": "doorLockStatus",
      "job": "access",
      "entity_key": "door_lock_status",
      "platform": "sensor",
      "paths": [
        "access.accessStatus.value.doorLockStatus"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "carType",
      "capability": "vehicle_status",
      "v2_state": "carType",
      "job": "fuelStatus",
      "entity_key": "car_type",
      "platform": "sensor",
      "paths": [
        "fuelStatus.rangeStatus.value.carType"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "engineTypeFirstEngine",
      "capability": "vehicle_status",
      "v2_state": "engineTypeFirstEngine",
      "job": "fuelStatus",
      "entity_key": "engine_type_first_engine",
      "platform": "sensor",
      "paths": [
        "fuelStatus.rangeStatus.value.primaryEngine.type"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "primaryEngineRange",
      "capability": "vehicle_status",
      "v2_state": "primaryEngineRange",
      "job": "fuelStatus",
      "entity_key": "primary_engine_range",
      "platform": "sensor",
      "paths": [
        "fuelStatus.rangeStatus.value.primaryEngine.remainingRange_km"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "primaryEngineRangePercent",
      "capability": "vehicle_status",
      "v2_state": "primaryEngineRangePercent",
      "job": "fuelStatus",
      "entity_key": "primary_engine_range_percent",
      "platform": "sensor",
      "paths": [
        "fuelStatus.rangeStatus.value.primaryEngine.currentSOC_pct"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "engineTypeSecondEngine",
      "capability": "vehicle_status",
      "v2_state": "engineTypeSecondEngine",
      "job": "fuelStatus",
      "entity_key": "engine_type_second_engine",
      "platform": "sensor",
      "paths": [
        "fuelStatus.rangeStatus.value.secondaryEngine.type"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "secondaryEngineRange",
      "capability": "vehicle_status",
      "v2_state": "secondaryEngineRange",
      "job": "fuelStatus",
      "entity_key": "secondary_engine_range",
      "platform": "sensor",
      "paths": [
        "fuelStatus.rangeStatus.value.secondaryEngine.remainingRange_km"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "secondaryEngineRangePercent",
      "capability": "vehicle_status",
      "v2_state": "secondaryEngineRangePercent",
      "job": "fuelStatus",
      "entity_key": "secondary_engine_range_percent",
      "platform": "sensor",
      "paths": [
        "fuelStatus.rangeStatus.value.secondaryEngine.currentSOC_pct"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "hybridRange",
      "capability": "vehicle_status",
      "v2_state": "hybridRange",
      "job": "fuelStatus",
      "entity_key": "hybrid_range",
      "platform": "sensor",
      "paths": [
        "fuelStatus.rangeStatus.value.totalRange_km"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "stateOfCharge",
      "capability": "charging",
      "v2_state": "stateOfCharge",
      "job": "charging",
      "entity_key": "state_of_charge",
      "platform": "sensor",
      "paths": [
        "charging.batteryStatus.value.currentSOC_pct"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "chargingState",
      "capability": "charging",
      "v2_state": "chargingState",
      "job": "charging",
      "entity_key": "charging_state",
      "platform": "sensor",
      "paths": [
        "charging.chargingStatus.value.chargingState"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "chargeMode",
      "capability": "charging",
      "v2_state": "chargeMode",
      "job": "charging",
      "entity_key": "charging_mode",
      "platform": "sensor",
      "paths": [
        "charging.chargingStatus.value.chargeMode"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "chargingPower",
      "capability": "charging",
      "v2_state": "chargingPower",
      "job": "charging",
      "entity_key": "charging_power",
      "platform": "sensor",
      "paths": [
        "charging.chargingStatus.value.chargePower_kW"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "actualChargeRate",
      "capability": "charging",
      "v2_state": "actualChargeRate",
      "job": "charging",
      "entity_key": "actual_charge_rate",
      "platform": "sensor",
      "paths": [
        "charging.chargingStatus.value.chargeRate_kmph"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "chargeType",
      "capability": "charging",
      "v2_state": "chargeType",
      "job": "charging",
      "entity_key": "charge_type",
      "platform": "sensor",
      "paths": [
        "charging.chargingStatus.value.chargeType"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "targetstateOfCharge",
      "capability": "charging",
      "v2_state": "targetstateOfCharge",
      "job": "charging",
      "entity_key": "target_state_of_charge",
      "platform": "sensor",
      "paths": [
        "charging.chargingSettings.value.targetSOC_pct"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "plugState",
      "capability": "charging",
      "v2_state": "plugState",
      "job": "charging",
      "entity_key": "plug_state",
      "platform": "binary_sensor",
      "paths": [
        "charging.plugStatus.value.plugConnectionState"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "remainingChargingTime",
      "capability": "charging",
      "v2_state": "remainingChargingTime",
      "job": "charging",
      "entity_key": "remaining_charging_time",
      "platform": "sensor",
      "paths": [
        "charging.chargingStatus.value.remainingChargingTimeToComplete_min"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "plugLockState",
      "capability": "charging",
      "v2_state": "plugLockState",
      "job": "charging",
      "entity_key": "plug_lock_state",
      "platform": "binary_sensor",
      "paths": [
        "charging.plugStatus.value.plugLockState"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "externalPower",
      "capability": "charging",
      "v2_state": "externalPower",
      "job": "charging",
      "entity_key": "external_power",
      "platform": "sensor",
      "paths": [
        "charging.plugStatus.value.externalPower"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "plugledColor",
      "capability": "charging",
      "v2_state": "plugledColor",
      "job": "charging",
      "entity_key": "plugled_color",
      "platform": "sensor",
      "paths": [
        "charging.plugStatus.value.ledColor"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "climatisationState",
      "capability": "climate",
      "v2_state": "climatisationState",
      "job": "climatisation",
      "entity_key": "climatisation_state",
      "platform": "sensor",
      "paths": [
        "climatisation.climatisationStatus.value.climatisationState",
        "climatisation.auxiliaryHeatingStatus.value.climatisationState"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "remainingClimatisationTime",
      "capability": "climate",
      "v2_state": "remainingClimatisationTime",
      "job": "climatisation",
      "entity_key": "remaining_climatisation_time",
      "platform": "sensor",
      "paths": [
        "climatisation.climatisationStatus.value.remainingClimatisationTime_min"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "preferredChargeMode",
      "capability": "charging",
      "v2_state": "preferredChargeMode",
      "job": "charging",
      "entity_key": "charging_mode",
      "platform": "sensor",
      "paths": [
        "charging.chargeMode.value.preferredChargeMode"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "availableChargeModes",
      "capability": "charging",
      "v2_state": "availableChargeModes",
      "job": "charging",
      "entity_key": "charging_mode",
      "platform": "diagnostic_only",
      "paths": [
        "charging.chargeMode.value.availableChargeModes"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "climatisationTargetTemperatureC",
      "capability": "climate",
      "v2_state": "climatisationTargetTemperatureC",
      "job": "climatisation",
      "entity_key": "climatisation_target_temperature_c",
      "platform": "sensor",
      "paths": [
        "climatisation.climatisationSettings.value.targetTemperature_C"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "climatisationTargetTemperatureF",
      "capability": "climate",
      "v2_state": "climatisationTargetTemperatureF",
      "job": "climatisation",
      "entity_key": "climatisation_target_temperature_f",
      "platform": "sensor",
      "paths": [
        "climatisation.climatisationSettings.value.targetTemperature_F"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "climatisationWindowHeatingEnabled",
      "capability": "climate",
      "v2_state": "climatisationWindowHeatingEnabled",
      "job": "climatisation",
      "entity_key": "climatisation_window_heating_enabled",
      "platform": "sensor",
      "paths": [
        "climatisation.climatisationSettings.value.windowHeatingEnabled"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "climatisationAtUnlock",
      "capability": "climate",
      "v2_state": "climatisationAtUnlock",
      "job": "climatisation",
      "entity_key": "climatisation_at_unlock",
      "platform": "sensor",
      "paths": [
        "climatisation.climatisationSettings.value.climatizationAtUnlock"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "climatisationWithoutExternalPower",
      "capability": "climate",
      "v2_state": "climatisationWithoutExternalPower",
      "job": "climatisation",
      "entity_key": "climatisation_without_external_power",
      "platform": "sensor",
      "paths": [
        "climatisation.climatisationSettings.value.climatisationWithoutExternalPower"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "climatisationZoneFrontLeft",
      "capability": "climate",
      "v2_state": "climatisationZoneFrontLeft",
      "job": "climatisation",
      "entity_key": "climatisation_zone_front_left",
      "platform": "sensor",
      "paths": [
        "climatisation.climatisationSettings.value.zoneFrontLeftEnabled"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "climatisationZoneFrontRight",
      "capability": "climate",
      "v2_state": "climatisationZoneFrontRight",
      "job": "climatisation",
      "entity_key": "climatisation_zone_front_right",
      "platform": "sensor",
      "paths": [
        "climatisation.climatisationSettings.value.zoneFrontRightEnabled"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "climatisationZoneRearLeft",
      "capability": "climate",
      "v2_state": "climatisationZoneRearLeft",
      "job": "climatisation",
      "entity_key": "climatisation_zone_rear_left",
      "platform": "sensor",
      "paths": [
        "climatisation.climatisationSettings.value.zoneRearLeftEnabled"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "climatisationZoneRearRight",
      "capability": "climate",
      "v2_state": "climatisationZoneRearRight",
      "job": "climatisation",
      "entity_key": "climatisation_zone_rear_right",
      "platform": "sensor",
      "paths": [
        "climatisation.climatisationSettings.value.zoneRearRightEnabled"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "chargingCurrentLimitA",
      "capability": "charging",
      "v2_state": "chargingCurrentLimitA",
      "job": "charging",
      "entity_key": "charging_current_limit_a",
      "platform": "sensor",
      "paths": [
        "charging.chargingSettings.value.maxChargeCurrentAC_A"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "chargingCurrentLimitMode",
      "capability": "charging",
      "v2_state": "chargingCurrentLimitMode",
      "job": "charging",
      "entity_key": "charging_current_limit_mode",
      "platform": "sensor",
      "paths": [
        "charging.chargingSettings.value.maxChargeCurrentAC"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "chargingPlugAutoUnlock",
      "capability": "charging",
      "v2_state": "chargingPlugAutoUnlock",
      "job": "charging",
      "entity_key": "charging_plug_auto_unlock",
      "platform": "sensor",
      "paths": [
        "charging.chargingSettings.value.autoUnlockPlugWhenChargedAC"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "vehicleReportedOnline",
      "capability": "vehicle_status",
      "v2_state": "vehicleReportedOnline",
      "job": "readiness",
      "entity_key": "vehicle_reported_online",
      "platform": "sensor",
      "paths": [
        "readiness.readinessStatus.value.connectionState.isOnline"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "vehicleReportedActive",
      "capability": "vehicle_status",
      "v2_state": "vehicleReportedActive",
      "job": "readiness",
      "entity_key": "vehicle_reported_active",
      "platform": "sensor",
      "paths": [
        "readiness.readinessStatus.value.connectionState.isActive"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "chargingProfiles",
      "capability": "charging",
      "v2_state": "chargingProfiles",
      "job": "chargingProfiles",
      "entity_key": "charging_profiles",
      "platform": "diagnostic_only",
      "paths": [
        "chargingProfiles.chargingProfilesStatus.value.profiles"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "chargingTimers",
      "capability": "charging",
      "v2_state": "chargingTimers",
      "job": "chargingTimers",
      "entity_key": "charging_timers",
      "platform": "diagnostic_only",
      "paths": [
        "chargingTimers.chargingTimersStatus.value.timers"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "climatisationTimers",
      "capability": "climate",
      "v2_state": "climatisationTimers",
      "job": "climatisationTimers",
      "entity_key": "climatisation_timers",
      "platform": "diagnostic_only",
      "paths": [
        "climatisationTimers.climatisationTimersStatus.value.timers"
      ],
      "source": "v2_audi_models",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "userCapabilities",
      "capability": "vehicle_status",
      "v2_state": "userCapabilities",
      "job": "userCapabilities",
      "entity_key": "user_capabilities",
      "platform": "diagnostic_only",
      "paths": [
        "userCapabilities.capabilitiesStatus.value"
      ],
      "source": "v2_audi_models",
      "sensitivity": "metadata"
    },
    {
      "id": "last_update_time",
      "capability": "vehicle_status",
      "v2_state": "last_update_time",
      "job": null,
      "entity_key": "last_update_time",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "shortterm_current",
      "capability": "vehicle_status",
      "v2_state": "shortterm_current",
      "job": null,
      "entity_key": "shortterm_current",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "shortterm_reset",
      "capability": "vehicle_status",
      "v2_state": "shortterm_reset",
      "job": null,
      "entity_key": "shortterm_reset",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "longterm_current",
      "capability": "vehicle_status",
      "v2_state": "longterm_current",
      "job": null,
      "entity_key": "longterm_current",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "longterm_reset",
      "capability": "vehicle_status",
      "v2_state": "longterm_reset",
      "job": null,
      "entity_key": "longterm_reset",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "model",
      "capability": "vehicle_status",
      "v2_state": "model",
      "job": null,
      "entity_key": "model",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "mileage",
      "capability": "vehicle_status",
      "v2_state": "mileage",
      "job": null,
      "entity_key": "mileage",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "service_adblue_distance",
      "capability": "service",
      "v2_state": "service_adblue_distance",
      "job": null,
      "entity_key": "service_adblue_distance",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "range",
      "capability": "vehicle_status",
      "v2_state": "range",
      "job": null,
      "entity_key": "range",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "service_inspection_time",
      "capability": "service",
      "v2_state": "service_inspection_time",
      "job": null,
      "entity_key": "service_inspection_time",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "service_inspection_distance",
      "capability": "service",
      "v2_state": "service_inspection_distance",
      "job": null,
      "entity_key": "service_inspection_distance",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "oil_change_time",
      "capability": "service",
      "v2_state": "oil_change_time",
      "job": null,
      "entity_key": "oil_change_time",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "oil_change_distance",
      "capability": "service",
      "v2_state": "oil_change_distance",
      "job": null,
      "entity_key": "oil_change_distance",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "oil_level",
      "capability": "service",
      "v2_state": "oil_level",
      "job": null,
      "entity_key": "oil_level",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "charging_type",
      "capability": "vehicle_status",
      "v2_state": "charging_type",
      "job": null,
      "entity_key": "charging_type",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "energy_flow",
      "capability": "vehicle_status",
      "v2_state": "energy_flow",
      "job": null,
      "entity_key": "energy_flow",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "max_charge_current",
      "capability": "charging",
      "v2_state": "max_charge_current",
      "job": null,
      "entity_key": "max_charge_current",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "primary_engine_type",
      "capability": "vehicle_status",
      "v2_state": "primary_engine_type",
      "job": null,
      "entity_key": "primary_engine_type",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "secondary_engine_type",
      "capability": "vehicle_status",
      "v2_state": "secondary_engine_type",
      "job": null,
      "entity_key": "secondary_engine_type",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "tank_level",
      "capability": "vehicle_status",
      "v2_state": "tank_level",
      "job": null,
      "entity_key": "tank_level",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "charging_complete_time",
      "capability": "vehicle_status",
      "v2_state": "charging_complete_time",
      "job": null,
      "entity_key": "charging_complete_time",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "plug_led_color",
      "capability": "charging",
      "v2_state": "plug_led_color",
      "job": null,
      "entity_key": "plug_led_color",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "doors_trunk_status",
      "capability": "access",
      "v2_state": "doors_trunk_status",
      "job": null,
      "entity_key": "doors_trunk_status",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "outdoor_temperature",
      "capability": "access",
      "v2_state": "outdoor_temperature",
      "job": null,
      "entity_key": "outdoor_temperature",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "park_time",
      "capability": "mobility",
      "v2_state": "park_time",
      "job": null,
      "entity_key": "park_time",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "location"
    },
    {
      "id": "position_last_updated",
      "capability": "mobility",
      "v2_state": "position_last_updated",
      "job": null,
      "entity_key": "position_last_updated",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "location"
    },
    {
      "id": "preheater_duration",
      "capability": "climate",
      "v2_state": "preheater_duration",
      "job": null,
      "entity_key": "preheater_duration",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "preheater_remaining",
      "capability": "climate",
      "v2_state": "preheater_remaining",
      "job": null,
      "entity_key": "preheater_remaining",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "active_charging_profile_target_soc",
      "capability": "vehicle_status",
      "v2_state": "active_charging_profile_target_soc",
      "job": null,
      "entity_key": "active_charging_profile_target_soc",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "active_charging_profile_name",
      "capability": "vehicle_status",
      "v2_state": "active_charging_profile_name",
      "job": null,
      "entity_key": "active_charging_profile_name",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "active_charging_profile_min_soc",
      "capability": "vehicle_status",
      "v2_state": "active_charging_profile_min_soc",
      "job": null,
      "entity_key": "active_charging_profile_min_soc",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "preferred_charging_time_start",
      "capability": "vehicle_status",
      "v2_state": "preferred_charging_time_start",
      "job": null,
      "entity_key": "preferred_charging_time_start",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "preferred_charging_time_end",
      "capability": "vehicle_status",
      "v2_state": "preferred_charging_time_end",
      "job": null,
      "entity_key": "preferred_charging_time_end",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "climatisation_timer_enabled_count",
      "capability": "climate",
      "v2_state": "climatisation_timer_enabled_count",
      "job": null,
      "entity_key": "climatisation_timer_enabled_count",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "next_climatisation_timer_local",
      "capability": "climate",
      "v2_state": "next_climatisation_timer_local",
      "job": null,
      "entity_key": "next_climatisation_timer_local",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "charging_timer_enabled_count",
      "capability": "vehicle_status",
      "v2_state": "charging_timer_enabled_count",
      "job": null,
      "entity_key": "charging_timer_enabled_count",
      "platform": "sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "glass_surface_heating",
      "capability": "climate",
      "v2_state": "glass_surface_heating",
      "job": null,
      "entity_key": "glass_surface_heating",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "sun_roof",
      "capability": "access",
      "v2_state": "sun_roof",
      "job": null,
      "entity_key": "sun_roof",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "roof_cover",
      "capability": "access",
      "v2_state": "roof_cover",
      "job": null,
      "entity_key": "roof_cover",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "parking_light",
      "capability": "access",
      "v2_state": "parking_light",
      "job": null,
      "entity_key": "parking_light",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "location"
    },
    {
      "id": "any_window_open",
      "capability": "access",
      "v2_state": "any_window_open",
      "job": null,
      "entity_key": "any_window_open",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "any_door_open",
      "capability": "access",
      "v2_state": "any_door_open",
      "job": null,
      "entity_key": "any_door_open",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "trunk_unlocked",
      "capability": "access",
      "v2_state": "trunk_unlocked",
      "job": null,
      "entity_key": "trunk_unlocked",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "trunk_open",
      "capability": "access",
      "v2_state": "trunk_open",
      "job": null,
      "entity_key": "trunk_open",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "hood_open",
      "capability": "access",
      "v2_state": "hood_open",
      "job": null,
      "entity_key": "hood_open",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "left_front_door_open",
      "capability": "access",
      "v2_state": "left_front_door_open",
      "job": null,
      "entity_key": "left_front_door_open",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "right_front_door_open",
      "capability": "access",
      "v2_state": "right_front_door_open",
      "job": null,
      "entity_key": "right_front_door_open",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "left_rear_door_open",
      "capability": "access",
      "v2_state": "left_rear_door_open",
      "job": null,
      "entity_key": "left_rear_door_open",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "right_rear_door_open",
      "capability": "access",
      "v2_state": "right_rear_door_open",
      "job": null,
      "entity_key": "right_rear_door_open",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "left_front_window_open",
      "capability": "access",
      "v2_state": "left_front_window_open",
      "job": null,
      "entity_key": "left_front_window_open",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "right_front_window_open",
      "capability": "access",
      "v2_state": "right_front_window_open",
      "job": null,
      "entity_key": "right_front_window_open",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "left_rear_window_open",
      "capability": "access",
      "v2_state": "left_rear_window_open",
      "job": null,
      "entity_key": "left_rear_window_open",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "right_rear_window_open",
      "capability": "access",
      "v2_state": "right_rear_window_open",
      "job": null,
      "entity_key": "right_rear_window_open",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "braking_status",
      "capability": "vehicle_status",
      "v2_state": "braking_status",
      "job": null,
      "entity_key": "braking_status",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "oil_level_binary",
      "capability": "service",
      "v2_state": "oil_level_binary",
      "job": null,
      "entity_key": "oil_level_binary",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "is_moving",
      "capability": "vehicle_status",
      "v2_state": "is_moving",
      "job": null,
      "entity_key": "is_moving",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_reference",
      "sensitivity": "vehicle_state"
    },
    {
      "id": "any_door_unlocked",
      "capability": "access",
      "v2_state": "any_door_unlocked",
      "job": null,
      "entity_key": "any_door_unlocked",
      "platform": "binary_sensor",
      "paths": [],
      "source": "v2_entity_derived_reference",
      "sensitivity": "vehicle_state"
    }
  ],
  "controls": [
    {
      "id": "start_climate_control",
      "capability": "climate",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "requires_vehicle_test",
      "api_family": "cariad",
      "path": "/vehicle/v1/vehicles/{VIN}/climatisation/start"
    },
    {
      "id": "stop_climatisation",
      "capability": "climate",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "requires_vehicle_test",
      "api_family": "cariad",
      "path": "/vehicle/v1/vehicles/{VIN}/climatisation/stop"
    },
    {
      "id": "start_window_heating",
      "capability": "climate",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "requires_vehicle_test",
      "api_family": "cariad",
      "path": "/vehicle/v1/vehicles/{VIN}/windowheating/start"
    },
    {
      "id": "stop_window_heating",
      "capability": "climate",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "requires_vehicle_test",
      "api_family": "cariad",
      "path": "/vehicle/v1/vehicles/{VIN}/windowheating/stop"
    },
    {
      "id": "start_charging",
      "capability": "charging",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "stop_charging",
      "capability": "charging",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "set_target_state_of_charge",
      "capability": "charging",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "set_location_charge_target",
      "capability": "charging",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "set_charge_mode",
      "capability": "charging",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "set_climatisation_setting",
      "capability": "climate",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "trigger_vehicle_wakeup",
      "capability": "remote",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "requires_vehicle_test",
      "api_family": "cariad",
      "path": "/vehicle/v1/vehicles/{VIN}/vehiclewakeuptrigger"
    },
    {
      "id": "flash_lights",
      "capability": "remote",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "lock",
      "capability": "remote",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "unlock",
      "capability": "remote",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "start_auxiliary_heating",
      "capability": "climate",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "requires_vehicle_test",
      "api_family": "cariad",
      "path": "/vehicle/v1/vehicles/{VIN}/auxiliaryheating/start"
    },
    {
      "id": "stop_auxiliary_heating",
      "capability": "climate",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "requires_vehicle_test",
      "api_family": "cariad",
      "path": "/vehicle/v1/vehicles/{VIN}/auxiliaryheating/stop"
    },
    {
      "id": "start_preheater",
      "capability": "climate",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "stop_preheater",
      "capability": "climate",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "start_engine",
      "capability": "remote",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "stop_engine",
      "capability": "remote",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "refresh_vehicle_data",
      "capability": "vehicle_status",
      "source": "v2_control_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": null,
      "path": null
    },
    {
      "id": "preheater_active",
      "capability": "climate",
      "source": "v2_switch_reference",
      "verification": "required",
      "activation": "not_migrated",
      "api_family": "mbb",
      "path": null
    }
  ],
  "api_families": [
    "cariad",
    "mbb"
  ]
}""")
V2_JOBS = tuple(row["id"] for row in INVENTORY["jobs"])
ATTRIBUTES = {row["id"]: row for row in INVENTORY["attributes"]}
CONTROLS = {row["id"]: row for row in INVENTORY["controls"]}
# Preserve all raw historical references, but one Home Assistant unique ID
# must never be counted twice in the user-facing capability inventory.
_CANONICAL_BY_ENTITY = {
    row["entity_key"]: row["id"] for row in INVENTORY["attributes"] if row["paths"]
}
ALIAS_OF = {
    row["id"]: _CANONICAL_BY_ENTITY[row["entity_key"]]
    for row in INVENTORY["attributes"]
    if not row["paths"] and row["entity_key"] in _CANONICAL_BY_ENTITY
}
CANONICAL_ATTRIBUTES = {
    name: row for name, row in ATTRIBUTES.items() if name not in ALIAS_OF
}


from .registry import read_json_path as read_path, extract_first


def capture_time(payload: Any, dotted_path: str) -> str | None:
    """Use a vehicle capture timestamp, never substitute cloud receipt time."""
    pointer = dotted_path.startswith("/")
    parts = dotted_path[1:].split("/") if pointer else dotted_path.split(".")
    for size in range(len(parts) - 1, -1, -1):
        path = ("/" + "/".join(parts[:size])) if pointer else ".".join(parts[:size])
        node = read_path(payload, path) if size else payload
        if not isinstance(node, dict):
            continue
        stamp = node.get("carCapturedTimestamp") or node.get("timestamp")
        if isinstance(stamp, str):
            return stamp
    return None


def extract_attributes(payload: Any) -> list[dict[str, Any]]:
    """Extract only declared V2 mappings, preserving False/0 and source evidence."""
    if not isinstance(payload, dict):
        return []
    results = []
    for item in INVENTORY["attributes"]:
        value, path = extract_first(payload, item["paths"])
        if path is not None:
            results.append(
                {
                    "id": item["id"],
                    "capability": item["capability"],
                    "job": item["job"],
                    "platform": item["platform"],
                    "entity_key": item["entity_key"],
                    "path": path,
                    "value": value,
                    "captured": capture_time(payload, path),
                }
            )
    return results


def advertised_capabilities(payload: Any) -> tuple[set[str], set[str]]:
    items = read_path(payload, "userCapabilities.capabilitiesStatus.value")
    if not isinstance(items, list):
        return set(), set()
    reported, impaired = set(), set()
    for item in items[:200]:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            reported.add(item["id"])
            if item.get("status"):
                impaired.add(item["id"])
    return reported, impaired
