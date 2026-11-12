"""Eligibility for historical CARIAD commands; no model-only permission."""
from __future__ import annotations


def eligible_operation(car, auth, capability, aspect):
    reported = car.advertised_capabilities
    impaired = car.impaired_capabilities
    def supports(*keys):
        return any(k in reported and k not in impaired for k in keys)
    def readable(key):
        return key in car.readings and car.readings[key].get("value") is not None
    if not auth.uses_auth0:
        if capability == "access" and aspect in ("lock", "unlock"):
            if (readable("doorLockStatus") or readable("any_door_unlocked")) and getattr(auth.service,"_spin",None):
                return "mbb.access." + aspect
            return None
        if capability == "climate" and aspect in ("start", "start_with_settings", "stop") and (
                not car.legacy_cariad or car.legacy_api_level != 1):
            if car.climate_state is not None:
                return "mbb.climate.stop" if aspect == "stop" else "mbb.climate.start"
            return None
        if not car.legacy_cariad or (capability=="remote" and aspect=="wake"):
            return None
        # Other historical commands already use the legacy IDK bearer against CARIAD.
    if capability == "remote" and aspect in ("engine_start", "engine_stop"):
        # Retain the historical remote-engine capability restriction. Never
        # infer permission from an engine, region, or PIN alone.
        model = (car.model or "").strip().lower()
        family = (car.model_family or "").strip().lower()
        from .vehicle import powertrain_identity
        identity = powertrain_identity(car)
        if (getattr(car, "identity_restored", False) or not model or not (car.car_type or "").strip() or identity["value"] != "combustion" or
                (not auth.uses_auth0 and not car.legacy_cariad) or model.startswith(("q8", "audi q8"))
                or family.startswith(("q8", "audi q8"))
                or (car.car_type or "").strip().lower() in {
                    "electric", "hybrid", "phev", "plug-in hybrid", "plug_in_hybrid"
                }
                or not supports("remoteEngineStart")
                or not getattr(auth.service, "_spin", None)):
            return None
        return "cariad.remote." + aspect
    if capability == "access" and aspect in ("lock", "unlock"):
        if (supports("access", "remoteLockUnlock") or
                (readable("doorLockStatus") and "access" not in impaired)):
            if getattr(auth.service, "_spin", None):
                return "cariad.access." + aspect
    if capability == "climate":
        if aspect.startswith("preheater_"):
            if supports("auxiliaryHeating", "hybridCarAuxiliaryHeating"):
                if aspect == "preheater_stop" or getattr(auth.service, "_spin", None):
                    return "cariad.climate." + aspect
        elif supports("climatisation") or (
            car.climate_state is not None and "climatisation" not in impaired
        ):
            return {
                "start": "cariad.climate.start.stored",
                "stop": "cariad.climate.stop",
                "start_with_settings": "cariad.climate.start.vehicle_settings",
                "set_settings": "cariad.climate.settings",
                "window_heating_start": "cariad.climate.window_heating_start",
                "window_heating_stop": "cariad.climate.window_heating_stop",
            }.get(aspect)
    if capability == "charging" and (supports("charging") or (
        readable("chargingState") and "charging" not in impaired
    )):
        # A generic charging capability does not prove all parameter writes.
        if aspect == "set_target_soc":
            value = car.readings.get("targetstateOfCharge", {}).get("value")
            if type(value) not in (int, float) or not 0 <= value <= 100:
                return None
        elif aspect == "set_charge_mode":
            modes = car.readings.get("availableChargeModes", {}).get("value")
            if not isinstance(modes, list) or not any(mode in ("manual", "timer") for mode in modes):
                return None
        elif aspect == "set_location_charge_target":
            if not any(type(row.get("id")) is int and type(row.get("targetSOC_pct")) in (int, float)
                       and 0 <= row["targetSOC_pct"] <= 100
                       for row in getattr(car, "charging_profiles", ()) if isinstance(row, dict)):
                return None
        return {
            "start": "cariad.charging.start", "stop": "cariad.charging.stop",
            "set_target_soc": "cariad.charging.settings",
            "set_charge_mode": "cariad.charging.mode",
            "set_location_charge_target": "cariad.charging.profiles",
        }.get(aspect)
    if capability == "remote":
        if aspect == "wake" and supports("vehicleWakeUp", "vehicleWakeUpTrigger"):
            return "cariad.remote.wake"
        if aspect == "refresh" and supports("vehicleWakeUp", "vehicleWakeUpTrigger", "vehicleStatus"):
            return "cariad.remote.refresh"
        if aspect == "flash" and supports("honkAndFlash") and car.position is not None:
            return "cariad.remote.flash"
    return None
