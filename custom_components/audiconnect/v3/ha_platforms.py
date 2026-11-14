"""V3's nine Home Assistant platform entrypoints.

The root platform modules keep their original V2 behavior untouched apart
from one runtime-selector branch. This module and the V3 native entity
classes own every V3 platform; no V2 vehicle objects or business operations.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import entity_registry as er

from .entities import (
    V3ClimateEntity,
    V3ReadOnlyBinarySensor,
    V3TripSensor,
    V3ReadOnlySensor,
    V3StatusSensor,
    V3CloudRefreshButton,
    V3TripMetricSensor,
    V3TripHistorySensor,
    V3ControlButton,
    V3ClimateQuickSwitch,
    V3LockEntity,
    V3ParkedTracker,
    V3ChargeTargetNumber,
    V3ChargeModeSelect,
    V3LocationChargeTargetNumber,
    V3ClimateSettingSwitch,
    V3PreheaterSwitch,
    V3LocalServiceSensor,
    V3ApiQuotaSensor,
    V3OperationalSwitch,
    V3ModelSensor,
    V3HealthSensor,
    V3IntegrationProblem,
    V3AccessSummary,
)
from .command_policy import supported_charge_modes
from .custom_attributes import attributes_for
from .attribute_contracts import semantic_value_issue
from .product_contract import (
    CORE_STATUS_KINDS,
    control_buttons,
    climate_switches,
    account_cloud_refresh_vin,
    projection_descriptor,
    projection_reading,
    entity_key,
    stateful_controls,
    stateful_control_supported,
    trip_metric_contracts,
    trip_metric_value,
)


def setup(platform: str, entry: Any, async_add_entities: Any) -> None:
    """Forward exactly one V3 platform and watch new *proven* field discovery."""
    runtime = entry.runtime_data
    engine, coordinator = runtime.v3, runtime.coordinator
    if engine is None:
        raise ValueError("V3 platform forwarded without V3 engine")
    seen: set[str] = set()
    if not hasattr(engine, "projected_entities"):
        engine.projected_entities = {}
    projected = engine.projected_entities.setdefault(platform, set())

    # The account registry is existing evidence that an entity was offered.
    # Do not require a fresh OEM value to offer that same identity on reload.
    hass = getattr(coordinator, "hass", None)
    registered = (
        {
            entity.unique_id
            for entity in er.async_entries_for_config_entry(
                er.async_get(hass), entry.entry_id
            )
            if entity.domain == platform and entity.platform == "audiconnect"
        }
        if hass is not None
        else set()
    )

    if platform not in (
        "sensor",
        "binary_sensor",
        "button",
        "switch",
        "lock",
        "climate",
        "device_tracker",
        "number",
        "select",
    ):
        raise ValueError("Unknown Audi V3 Home Assistant platform")

    def add_verified() -> None:
        entities: list[Any] = []
        if platform == "button":
            anchor = getattr(
                engine, "cloud_refresh_vin", None
            ) or account_cloud_refresh_vin(engine.vehicles)
            if (
                anchor
                and anchor in engine.vehicles
                and "account:cloud_refresh" not in seen
            ):
                seen.add("account:cloud_refresh")
                engine.cloud_refresh_vin = anchor
                entities.append(
                    V3CloudRefreshButton(coordinator, engine.vehicles[anchor])
                )
        for car in engine.vehicles.values():
            if not car.inventory_present:
                continue
            vin = car.vin.lower()

            def retained(key, vin=vin):
                return f"{vin}_{platform}_{key}" in registered

            def add_once(tag: str, factory, *args, car=car) -> None:
                if tag not in seen:
                    seen.add(tag)
                    entities.append(factory(coordinator, car, *args))

            if platform == "sensor":
                # Manufacturer identity is universal, even when the OEM label
                # is temporarily absent. Preserve the existing model entity ID.
                add_once(f"{vin}:model", V3ModelSensor)
                for kind in ("integration_status", "last_error", "data_act_status"):
                    add_once(f"{vin}:health:{kind}", V3HealthSensor, kind)
                for kind in ("door", "window"):
                    add_once(f"{vin}:access:{kind}", V3AccessSummary, kind)
                for kind in CORE_STATUS_KINDS:
                    add_once(f"{vin}:core:{kind}", V3StatusSensor, kind)
                for kind in ("local_dealer", "service_overview"):
                    add_once(f"{vin}:local:{kind}", V3LocalServiceSensor, kind)
                if "account:quota" not in seen:
                    add_once("account:quota", V3ApiQuotaSensor, entry.entry_id)
            elif platform == "binary_sensor":
                add_once(f"{vin}:health:problem", V3IntegrationProblem)
            elif platform == "climate":
                if (
                    retained("climatisation")
                    or car.climate_state is not None
                    or any(
                        engine.control_enabled(car.vin, action)
                        for action in ("start", "stop", "start_with_settings")
                    )
                ):
                    add_once(f"{vin}:climate", V3ClimateEntity)
            elif platform == "device_tracker":
                add_once(f"{vin}:tracker", V3ParkedTracker)
            elif platform == "number":
                if retained("target_state_of_charge") or (
                    engine.control_enabled(car.vin, "set_target_soc", "charging")
                    and type(car.readings.get("targetstateOfCharge", {}).get("value"))
                    in (int, float)
                ):
                    add_once(f"{vin}:target_soc", V3ChargeTargetNumber)
            elif platform == "select" and (
                retained("charge_mode")
                or (
                    engine.control_enabled(car.vin, "set_charge_mode", "charging")
                    and supported_charge_modes(car, engine.profiles.get(vin))
                )
            ):
                add_once(f"{vin}:charge_mode", V3ChargeModeSelect)

            if platform in ("sensor", "binary_sensor"):
                if platform == "sensor":
                    if getattr(car, "trip_history", ()):
                        add_once(f"{vin}:trip_history", V3TripHistorySensor)
                    for key in trip_metric_contracts():
                        if trip_metric_value(car, key) is not None:
                            add_once(
                                f"{vin}:trip_metric:{key}", V3TripMetricSensor, key
                            )
                    for key in car.trips:
                        tag = f"{vin}:{key}"
                        if tag not in seen:
                            seen.add(tag)
                            entities.append(V3TripSensor(coordinator, car, key))
                profile = getattr(engine, "profiles", {}).get(vin)
                attributes = attributes_for(profile)
                # Canonical entities can be backed by declared alternative sources.
                candidates = set(car.readings)
                if platform == "sensor":
                    candidates.update(
                        (
                            "stateOfCharge",
                            "TOTAL_RANGE",
                            "TANK_LEVEL_IN_PERCENTAGE",
                            "carType",
                        )
                    )
                for ident, descriptor in sorted(attributes.items()):
                    if descriptor["platform"] != platform:
                        continue
                    if profile and ident in getattr(profile, "attribute_disabled", ()):
                        continue
                    if (
                        descriptor.get("local")
                        and ident not in profile.attribute_routes
                    ):
                        continue
                    descriptor = projection_descriptor(descriptor)
                    if descriptor is None:
                        continue
                    key = descriptor["entity_key"]
                    previously_offered = f"{vin}_{platform}_{key}" in registered
                    if ident not in candidates and (
                        ident != descriptor["id"] or not previously_offered
                    ):
                        continue
                    _source, reading = projection_reading(
                        car, descriptor, registry=getattr(profile, "registry", None)
                    )
                    if (
                        platform == "sensor"
                        and descriptor["entity_key"] == "car_type"
                        and not descriptor.get("local")
                    ):
                        from .vehicle import powertrain_identity

                        if (
                            previously_offered
                            or powertrain_identity(car)["value"] is not None
                        ):
                            add_once(f"{vin}:car_type", V3ReadOnlySensor, descriptor)
                        continue
                    if not previously_offered:
                        if not reading or not isinstance(
                            reading.get("value"), (str, int, float, bool)
                        ):
                            continue
                        if platform == "sensor" and semantic_value_issue(
                            descriptor["entity_key"],
                            reading["value"],
                            descriptor.get("contract"),
                        ):
                            continue
                    entity_type = (
                        V3ReadOnlySensor
                        if platform == "sensor"
                        else V3ReadOnlyBinarySensor
                    )
                    add_once(f"{vin}:{key}", entity_type, descriptor)
            elif platform == "button":
                for descriptor in control_buttons():
                    key, _, _, capability, action = descriptor
                    tag = f"{vin}:{key}"
                    if tag not in seen and (
                        retained(key)
                        or engine.control_enabled(car.vin, action, capability)
                    ):
                        seen.add(tag)
                        entities.append(V3ControlButton(coordinator, car, descriptor))
            elif platform == "number":
                profile_ids = {x["id"] for x in car.charging_profiles}
                prefix = f"{vin}_number_charge_profile_"
                for uid in registered:
                    if uid.startswith(prefix) and uid.endswith("_target_soc"):
                        ident = uid[len(prefix) : -len("_target_soc")]
                        if ident.isdecimal():
                            profile_ids.add(int(ident))
                for profile_id in [None, *sorted(profile_ids)]:
                    tag = f"{vin}:profile:{profile_id}"
                    key = (
                        "active_charging_profile_target_soc"
                        if profile_id is None
                        else f"charge_profile_{profile_id}_target_soc"
                    )
                    if tag not in seen and (
                        retained(key)
                        or (
                            car.charging_profiles
                            and (
                                profile_id is None
                                or any(
                                    x["id"] == profile_id for x in car.charging_profiles
                                )
                            )
                        )
                    ):
                        seen.add(tag)
                        entities.append(
                            V3LocationChargeTargetNumber(coordinator, car, profile_id)
                        )
            elif platform == "switch":
                for key in stateful_controls():
                    if retained(key) or stateful_control_supported(engine, car, key):
                        add_once(f"{vin}:{key}", V3OperationalSwitch, key)
                preheater = f"{vin}:preheater_active"
                if preheater not in seen and (
                    retained("preheater_active")
                    or any(
                        engine.control_enabled(car.vin, aspect, "climate")
                        for aspect in ("preheater_start", "preheater_stop")
                    )
                ):
                    seen.add(preheater)
                    entities.append(V3PreheaterSwitch(coordinator, car))
                for descriptor in climate_switches():
                    key, reading, _ = descriptor
                    tag = f"{vin}:{key}"
                    if tag not in seen and (retained(key) or reading in car.readings):
                        seen.add(tag)
                        entities.append(
                            V3ClimateSettingSwitch(coordinator, car, descriptor)
                        )
                if vin not in seen and (
                    retained("climate_quick_control")
                    or (
                        engine.control_enabled(car.vin, "start")
                        and engine.control_enabled(car.vin, "stop")
                    )
                ):
                    seen.add(vin)
                    entities.append(V3ClimateQuickSwitch(coordinator, car))
            elif (
                platform == "lock"
                and vin not in seen
                and (
                    retained("lock")
                    or engine.control_enabled(car.vin, "lock", "access")
                    or engine.control_enabled(car.vin, "unlock", "access")
                )
            ):
                seen.add(vin)
                entities.append(V3LockEntity(coordinator, car))
        if entities:
            for entity in entities:
                if entity_key(entity.unique_id, entry.entry_id) is None:
                    raise ValueError("V3 entity missing a product identity contract")
            projected.update(entity.unique_id for entity in entities)
            async_add_entities(entities)

    add_verified()
    entry.async_on_unload(coordinator.async_add_listener(add_verified))
