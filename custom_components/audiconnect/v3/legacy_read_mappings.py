"""Historical MBB read-only response mappings from the original V2 adapter.

MBB may omit vehicle capture clocks. A successful GET proves that a field is
readable, not that the car has recently refreshed it. Controls are excluded.
"""
from __future__ import annotations

ROUTES = {
    "charger": "/fs-car/bs/batterycharge/v1/{TYPE}/{COUNTRY}/vehicles/{VIN}/charger",
    "climater": "/fs-car/bs/climatisation/v1/{TYPE}/{COUNTRY}/vehicles/{VIN}/climater",
    "vehicle_data": "/fs-car/vehicleMgmt/vehicledata/v2/{TYPE}/{COUNTRY}/vehicles/{VIN}/",
    "preheater": "/fs-car/bs/rs/v1/{TYPE}/{COUNTRY}/vehicles/{VIN}/status",
    "timer": "/fs-car/bs/departuretimer/v1/{TYPE}/{COUNTRY}/vehicles/{VIN}/timer",
}
FIELDS: dict[str, tuple[str, str]] = {
    "stateOfCharge": ("charger", "charger.status.batteryStatusData.stateOfCharge.content"),
    "chargingState": ("charger", "charger.status.chargingStatusData.chargingState.content"),
    "actualChargeRate": ("charger", "charger.status.chargingStatusData.actualChargeRate.content"),
    "chargingPower": ("charger", "charger.status.chargingStatusData.chargingPower.content"),
    "chargeMode": ("charger", "charger.status.chargingStatusData.chargingMode.content"),
    "energy_flow": ("charger", "charger.status.chargingStatusData.energyFlow.content"),
    "max_charge_current": ("charger", "charger.settings.maxChargeCurrent.content"),
    "plugState": ("charger", "charger.status.plugStatusData.plugState.content"),
    "plugLockState": ("charger", "charger.status.plugStatusData.plugLockState.content"),
    "externalPower": ("charger", "charger.status.plugStatusData.externalPower.content"),
    "plugledColor": ("charger", "charger.status.plugStatusData.plugledColor.content"),
    "remainingChargingTime": ("charger", "charger.status.batteryStatusData.remainingChargingTime.content"),
    "hybridRange": ("charger", "charger.status.cruisingRangeStatusData.hybridRange.content"),
    "primaryEngineRange": ("charger", "charger.status.cruisingRangeStatusData.primaryEngineRange.content"),
    "secondaryEngineRange": ("charger", "charger.status.cruisingRangeStatusData.secondaryEngineRange.content"),
    "engineTypeFirstEngine": ("charger", "charger.status.cruisingRangeStatusData.engineTypeFirstEngine.content"),
    "engineTypeSecondEngine": ("charger", "charger.status.cruisingRangeStatusData.engineTypeSecondEngine.content"),
    "climatisationState": ("climater", "climater.status.climatisationStatusData.climatisationState.content"),
    "remainingClimatisationTime": ("climater", "climater.status.climatisationStatusData.remainingClimatisationTime.content"),
    "glass_surface_heating": ("climater", "climater.status.climatisationStatusData.climatisationElementStates.isMirrorHeatingActive.content"),
}


def variant_for(attribute: str) -> dict | None:
    item = FIELDS.get(attribute)
    if item is None:
        return None
    name, mapping = item
    return {
        "id": "mbb." + name + ".readonly",
        "family": "mbb", "method": "GET", "path": ROUTES[name],
        "response_paths": [mapping], "kind": "legacy",
    }

# Historical MBB field IDs from the fixbranch, not a V2 import.
FIELD_IDS = {
    "0x0": "UNKNOWN",
    "0x0101010002": "UTC_TIME_AND_KILOMETER_STATUS",
    "0x0203010001": "MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE",
    "0x0203010002": "MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE",
    "0x0203010003": "MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION",
    "0x0203010004": "MAINTENANCE_INTERVAL_TIME_TO_INSPECTION",
    "0x0203010006": "MAINTENANCE_INTERVAL_ALARM_INSPECTION",
    "0x0203010007": "MAINTENANCE_INTERVAL_MONTHLY_MILEAGE",
    "0x0203010005": "WARNING_OIL_CHANGE",
    "0x0204040001": "OIL_LEVEL_AMOUNT_IN_LITERS",
    "0x0204040002": "OIL_LEVEL_MINIMUM_WARNING",
    "0x0204040003": "OIL_LEVEL_DIPSTICKS_PERCENTAGE",
    "0x02040C0001": "ADBLUE_RANGE",
    "0x0301010001": "LIGHT_STATUS",
    "0x0301030001": "BRAKING_STATUS",
    "0x0301030005": "TOTAL_RANGE",
    "0x030103000A": "TANK_LEVEL_IN_PERCENTAGE",
    "0x0301040001": "LOCK_STATE_LEFT_FRONT_DOOR",
    "0x0301040002": "OPEN_STATE_LEFT_FRONT_DOOR",
    "0x0301040003": "SAFETY_STATE_LEFT_FRONT_DOOR",
    "0x0301040004": "LOCK_STATE_LEFT_REAR_DOOR",
    "0x0301040005": "OPEN_STATE_LEFT_REAR_DOOR",
    "0x0301040006": "SAFETY_STATE_LEFT_REAR_DOOR",
    "0x0301040007": "LOCK_STATE_RIGHT_FRONT_DOOR",
    "0x0301040008": "OPEN_STATE_RIGHT_FRONT_DOOR",
    "0x0301040009": "SAFETY_STATE_RIGHT_FRONT_DOOR",
    "0x030104000A": "LOCK_STATE_RIGHT_REAR_DOOR",
    "0x030104000B": "OPEN_STATE_RIGHT_REAR_DOOR",
    "0x030104000C": "SAFETY_STATE_RIGHT_REAR_DOOR",
    "0x030104000D": "LOCK_STATE_TRUNK_LID",
    "0x030104000E": "OPEN_STATE_TRUNK_LID",
    "0x030104000F": "SAFETY_STATE_TRUNK_LID",
    "0x0301040010": "LOCK_STATE_HOOD",
    "0x0301040011": "OPEN_STATE_HOOD",
    "0x0301040012": "SAFETY_STATE_HOOD",
    "0x0301050001": "STATE_LEFT_FRONT_WINDOW",
    "0x0301050003": "STATE_LEFT_REAR_WINDOW",
    "0x0301050005": "STATE_RIGHT_FRONT_WINDOW",
    "0x0301050007": "STATE_RIGHT_REAR_WINDOW",
    "0x0301050009": "STATE_DECK",
    "0x030105000B": "STATE_SUN_ROOF_MOTOR_COVER",
    "0x0301030006": "PRIMARY_RANGE",
    "0x0301030007": "PRIMARY_DRIVE",
    "0x0301030008": "SECONDARY_RANGE",
    "0x0301030009": "SECONDARY_DRIVE",
    "0x0301030002": "STATE_OF_CHARGE",
    "0x0301020001": "TEMPERATURE_OUTSIDE",
    "0x0202": "ACTIVE_INSTRUMENT_CLUSTER_WARNING"
}
