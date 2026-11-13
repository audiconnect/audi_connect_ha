"""Regression tests for issues exposed by the b12 completeness diagnostics."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.audiconnect.v3.attribute_runtime import _accept_observation
from custom_components.audiconnect.v3.derived_values import observe_derived
from custom_components.audiconnect.v3.response_preview import (
    safe_schema_inventory,
    validate_schema_fields,
)
from custom_components.audiconnect.v3.structured_details import (
    observe_structured,
    details_for,
)
from custom_components.audiconnect.v3.vehicle import V3Vehicle

VIN = "WAUZZZ4M0MD123456"


def test_parking_light_never_uses_other_light_types():
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    now = datetime.now(UTC)

    def observe(lights):
        observe_derived(
            car,
            SimpleNamespace(),
            {
                "vehicleLights": {
                    "lightsStatus": {
                        "value": {
                            "carCapturedTimestamp": now.isoformat(),
                            "lights": lights,
                        }
                    }
                }
            },
            now,
            _accept_observation,
        )

    observe(
        [
            {"name": "parkingLight", "status": "off"},
            {"name": "headlight", "status": "on"},
        ]
    )
    assert car.readings["parking_light"]["value"] is False
    observe([{"name": "headlight", "status": "on"}])
    assert car.readings["parking_light"]["value"] is None
    observe([{"name": "left", "status": "off"}, {"name": "right", "status": "on"}])
    assert car.readings["parking_light"]["value"] is True
    observe([{"name": "left", "status": "off"}])
    assert car.readings["parking_light"]["value"] is None
    observe([{"name": "left", "status": "off"}, {"name": "right", "status": "off"}])
    assert car.readings["parking_light"]["value"] is False


def test_partial_access_retains_missing_and_invalidates_contradictory_components():
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    now = datetime.now(UTC)

    def observe(stamp, rows):
        observe_derived(
            car,
            SimpleNamespace(),
            {
                "access": {
                    "accessStatus": {
                        "value": {
                            "carCapturedTimestamp": stamp.isoformat(),
                            "doors": rows,
                        }
                    }
                }
            },
            stamp,
            _accept_observation,
        )

    observe(now, [{"name": "frontLeft", "status": ["closed", "locked"]}])
    assert car.readings["left_front_door_open"]["value"] is False
    observe(
        now + timedelta(seconds=1),
        [{"name": "frontRight", "status": ["open", "closed"]}],
    )
    assert car.readings["left_front_door_open"]["value"] is False
    assert car.readings["left_front_door_open"]["captured"] == now.isoformat()
    assert car.readings["right_front_door_open"]["value"] is None
    assert car.readings["right_front_door_open"]["status"] == "invalid_value"
    assert car.readings["any_door_open"]["value"] is None


def test_structured_timers_services_and_components_are_bounded_and_typed():
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    now = datetime.now(UTC)
    stamp = now.isoformat()
    payload = {
        "chargingTimers": {
            "chargingTimersStatus": {
                "value": {
                    "carCapturedTimestamp": stamp,
                    "timers": [
                        {
                            "id": 1,
                            "enabled": True,
                            "recurringTimer": {
                                "departureTimeLocal": "07:30",
                                "repetitionDays": ["monday"],
                            },
                            "latitude": 50.1,
                            "secret": "private",
                        },
                        {
                            "id": 2,
                            "enabled": False,
                            "singleTimer": {
                                "startDateTimeLocal": "2026-11-13T07:30:00"
                            },
                        },
                    ],
                }
            }
        },
        "userCapabilities": {
            "capabilitiesStatus": {
                "value": [
                    {
                        "id": "charging",
                        "expirationDate": "2027-01-01T00:00:00Z",
                        "userDisablingAllowed": False,
                        "secret": "private",
                    }
                ]
            }
        },
        "access": {
            "accessStatus": {
                "value": {
                    "carCapturedTimestamp": stamp,
                    "overallStatus": "safe",
                    "doors": [{"name": "frontLeft", "status": ["closed", "locked"]}],
                }
            }
        },
    }
    observe_structured(car, payload, now, _accept_observation)
    info = details_for(
        car, "charging_timers_detail", "connected_services_detail", "door_detail"
    )
    assert (
        info["charging_timers"]["data"]["items"][0]["departure_time_local"] == "07:30"
    )
    assert (
        info["charging_timers"]["data"]["items"][1]["start_datetime_local"]
        == "2026-11-13T07:30:00"
    )
    assert (
        info["connected_services"]["data"]["items"][0]["user_disabling_allowed"]
        is False
    )
    assert info["door"]["data"]["items"][0]["status"] == ["closed", "locked"]
    assert "private" not in str(info) and "latitude" not in str(info)
    assert info["connected_services"]["vehicle_captured"] is None
    assert info["charging_timers"]["vehicle_captured"] == stamp


def test_schema_per_job_preserves_window_location_enum_and_redacts_geography():
    fields, truncated = safe_schema_inventory(
        {
            "windowHeatingStatus": [
                {
                    "windowLocation": "front",
                    "windowHeatingState": "off",
                    "latitude": 50.1,
                }
            ]
        },
        all_items=True,
    )
    validate_schema_fields(fields)
    assert not truncated
    assert any(row["path"].endswith("windowLocation") for row in fields)
    assert not any("latitude" in row["path"] for row in fields)


def test_generic_charging_does_not_authorize_unobserved_parameter_writes():
    from custom_components.audiconnect.v3.command_policy import eligible_operation

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    car.advertised_capabilities.add("charging")
    auth = SimpleNamespace(uses_auth0=True, service=SimpleNamespace(_spin=None))
    for aspect in ("set_target_soc", "set_charge_mode", "set_location_charge_target"):
        assert eligible_operation(car, auth, "charging", aspect) is None
    assert eligible_operation(car, auth, "charging", "start") == "cariad.charging.start"
    car.readings["targetstateOfCharge"] = {"value": 80}
    car.readings["availableChargeModes"] = {"value": ["manual", "timer"]}
    car.charging_profiles = [{"id": 1, "targetSOC_pct": 70}]
    for aspect in ("set_target_soc", "set_charge_mode", "set_location_charge_target"):
        assert eligible_operation(car, auth, "charging", aspect) is not None


def test_climate_request_metadata_does_not_become_climate_state_or_fake_timestamp():
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    now = datetime.now(UTC)
    observe_structured(
        car,
        {
            "climatisation": {
                "climatisationStatus": {
                    "requests": [
                        {
                            "operation": "start",
                            "status": "accepted",
                            "requestId": "private",
                        }
                    ],
                    "value": {
                        "carCapturedTimestamp": now.isoformat(),
                        "climatisationState": "invalid",
                    },
                }
            }
        },
        now,
        _accept_observation,
    )
    detail = details_for(car, "climate_requests_detail")["climate_requests"]
    assert detail["data"]["items"] == [{"operation": "start", "status": "accepted"}]
    assert detail["vehicle_captured"] is None
    assert detail["cloud_observed"] == now.isoformat()
    assert car.climate_state is None
    assert "private" not in str(detail)


def test_public_audi_timer_variants_and_battery_care_are_read_only():
    # Synthetic values, public schema: upstream issue #760, July 2026.
    car = V3Vehicle(VIN, "Audi", "Test", "q8", "DE")
    now = datetime.now(UTC)
    stamp = now.isoformat()
    payload = {
        "departureTimers": {
            "climatisationTimersStatus": {
                "value": {
                    "carCapturedTimestamp": stamp,
                    "timeInCar": "2026-11-12T14:00:00+01:00",
                    "timers": [
                        {
                            "id": 1,
                            "enabled": True,
                            "recurringTimer": {
                                "startTime": "06:10",
                                "targetTime": "06:30",
                                "recurringOn": {"mondays": True, "tuesdays": False},
                                "repetitionDays": ["monday"],
                            },
                        },
                        {
                            "id": 2,
                            "enabled": False,
                            "singleTimer": {
                                "startDateTime": "2026-11-13T05:10:00Z",
                                "targetDateTime": "2026-11-13T05:30:00Z",
                            },
                        },
                    ],
                }
            }
        },
        "batteryChargingCare": {
            "chargingCareSettings": {"value": {"batteryCareMode": "deactivated"}}
        },
        "vehicleHealthWarnings": {"warningLights": {"value": {}}},
    }
    observe_structured(car, payload, now, _accept_observation)
    details = details_for(
        car,
        "departure_climate_timers_detail",
        "battery_care_detail",
        "health_warning_evidence_detail",
    )
    timers = details["departure_climate_timers"]["data"]
    assert timers["vehicle_time"] == "2026-11-12T14:00:00+01:00"
    assert timers["items"][0]["target_time_local"] == "06:30"
    assert timers["items"][0]["recurring_on"]["tuesdays"] is False
    assert timers["items"][1]["target_datetime"] == "2026-11-13T05:30:00+00:00"
    assert details["battery_care"]["data"]["mode"] == "deactivated"
    assert details["health_warning_evidence"]["data"]["warning_state"] == "unknown"
    assert not car.advertised_capabilities


def test_profile_variants_are_normalized_without_location_or_invalid_soc():
    car = V3Vehicle(VIN, "Audi", "Test", "q8", "DE")
    now = datetime.now(UTC)
    observe_derived(
        car,
        SimpleNamespace(),
        {
            "chargingProfiles": {
                "chargingProfilesStatus": {
                    "value": {
                        "carCapturedTimestamp": now.isoformat(),
                        "vehiclePositionedInProfileID": 1,
                        "timeInCar": "",
                        "nextChargingTimer": {"id": 0, "targetSOCreachable": "invalid"},
                        "profiles": [
                            {
                                "id": 1,
                                "name": "Example",
                                "targetSOC_pct": 120,
                                "minSOC_pct": 20,
                                "minSOC_enabled": False,
                                "maxChargingCurrent": "reduced",
                                "options": {
                                    "usePreferredChargingTimes": True,
                                    "secret": "private",
                                },
                                "preferredChargingTimes": [
                                    {
                                        "id": 1,
                                        "enabled": True,
                                        "startTime": "21:00",
                                        "endTime": "04:00",
                                    }
                                ],
                                "position": {"lat": 0, "lon": 0},
                            }
                        ],
                    }
                }
            }
        },
        now,
        _accept_observation,
    )
    row = car.charging_profiles[0]
    assert row["targetSOC_pct"] is None and row["minSOC_pct"] == 20
    assert row["minSOC_enabled"] is False and row["maxChargingCurrent"] == "reduced"
    assert row["preferredChargingTimes"][0]["startTimeLocal"] == "21:00"
    assert row["options"] == {"usePreferredChargingTimes": True}
    assert "position" not in row
    assert (
        car.readings["charging_profile_context_detail"]["value"]["vehicle_time"] is None
    )


def test_health_warning_and_campaign_details_keep_explicit_information_only():
    car = V3Vehicle(VIN, "Audi", "Test", "q8", "DE")
    now = datetime.now(UTC)
    observe_structured(
        car,
        {
            "vehicleHealthWarnings": {
                "warningLights": {
                    "value": {
                        "carCapturedTimestamp": now.isoformat(),
                        "mileage_km": 12345,
                        "warningLights": [
                            {
                                "messageId": "warning.example",
                                "text": "Example warning",
                                "iconColor": "YELLOW",
                                "icon": "data:image/svg+xml;base64,private",
                            }
                        ],
                        "campaigns": [
                            {
                                "eventId": "TEST",
                                "text": "Example campaign",
                                "type": "customerServiceCampaign",
                            }
                        ],
                    }
                }
            },
            "readiness": {
                "readinessStatus": {
                    "value": {
                        "connectionState": {
                            "isOnline": True,
                            "isActive": False,
                            "batteryPowerLevel": "comfort",
                            "dailyPowerBudgetAvailable": True,
                        },
                        "connectionWarning": {
                            "insufficientBatteryLevelWarning": False,
                            "dailyPowerBudgetWarning": False,
                        },
                    }
                }
            },
        },
        now,
        _accept_observation,
    )
    detail = details_for(car, "health_warning_evidence_detail", "readiness_detail")
    health = detail["health_warning_evidence"]["data"]
    assert health["warning_state"] == "reported"
    assert health["warnings"]["items"][0]["icon_color"] == "YELLOW"
    assert health["campaigns"]["items"][0]["event_id"] == "TEST"
    assert "base64" not in str(health)
    assert detail["readiness"]["data"]["insufficient_battery_warning"] is False
    assert detail["readiness"]["vehicle_captured"] is None


def test_extended_job_schema_is_not_limited_by_legacy_preview():
    payload = {
        "test": {f"block{i}": {f"field{n}": True for n in range(20)} for i in range(12)}
    }
    old, old_truncated = safe_schema_inventory(payload)
    new, new_truncated = safe_schema_inventory(
        payload, all_items=True, field_limit=512, char_limit=64000
    )
    assert old_truncated and len(old) <= 128
    assert not new_truncated and len(new) == 253


def test_shared_cariad_battery_support_is_read_only_and_does_not_invent_voltage():
    car = V3Vehicle(VIN, "Audi", "Test", "q8", "DE")
    now = datetime.now(UTC)
    observe_structured(
        car,
        {
            "lvBattery": {"lvBatteryStatus": {"value": {"batterySupport": "enabled"}}},
            "batterySupport": {
                "batterySupportStatus": {"value": {"batterySupport": "pendingDisable"}}
            },
        },
        now,
        _accept_observation,
    )
    detail = details_for(car, "low_voltage_battery_detail", "battery_support_detail")
    assert detail["low_voltage_battery"]["data"] == {"battery_support": "enabled"}
    assert detail["battery_support"]["data"] == {"battery_support": "pendingDisable"}
    assert not car.advertised_capabilities
    other = V3Vehicle(VIN, "Audi", "Test", "q8", "DE")
    observe_structured(
        other,
        {
            "lvBattery": {
                "lvBatteryStatus": {
                    "value": {"batterySupport": "invalid", "voltage": 12.4}
                }
            }
        },
        now,
        _accept_observation,
    )
    assert not details_for(other, "low_voltage_battery_detail")


def test_schema_union_keeps_observed_variants_and_never_leaks_configured_key():
    from custom_components.audiconnect.v3.response_preview import merge_schema_evidence

    a, trunc = safe_schema_inventory(
        {"job": {"first": 1, "PrivateSecret": 2}},
        all_items=True,
        secrets=("PrivateSecret",),
    )
    assert not trunc and not any("PrivateSecret" in row["path"] for row in a)
    prior = merge_schema_evidence(None, a, True, status=207, source="batch", at="first")
    b, trunc = safe_schema_inventory({"job": {"second": False}}, all_items=True)
    result = merge_schema_evidence(
        prior, b, trunc, status=200, source="target", at="second"
    )
    assert {row["path"] for row in result["fields"]} >= {"job.first", "job.second"}
    assert result["capture_truncated_seen"] and not result["latest_capture_truncated"]
    assert result["scope"] == "session_union_structural_only"


def test_structural_vin_redaction_does_not_drop_real_engine_type_fields():
    fields, truncated = safe_schema_inventory(
        {
            "measurements": {
                "primaryEngineType": "gasoline",
                "secondaryEngineType": "electric",
                VIN: {"value": 1},
            }
        },
        vehicle_vin=VIN,
        all_items=True,
    )
    assert not truncated
    validate_schema_fields(fields)
    paths = {row["path"] for row in fields}
    assert "measurements.primaryEngineType" in paths
    assert "measurements.secondaryEngineType" in paths
    assert not any(VIN in path for path in paths)


def test_advertised_flash_is_temporarily_blocked_not_unknown_without_position():
    from pathlib import Path
    from custom_components.audiconnect.v3.registry import CapabilityRegistry
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    from custom_components.audiconnect.v3.control_resolution import control_decision

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    car.advertised_capabilities.add("honkAndFlash")
    registry = CapabilityRegistry.from_json_file(
        Path(__file__).resolve().parents[1]
        / "custom_components/audiconnect/v3/full_catalog.json"
    )
    profile = DevelopmentProfile(registry, car.context)
    auth = SimpleNamespace(uses_auth0=True, service=SimpleNamespace(_spin=None))
    result = control_decision(car, profile, auth, "remote", "flash")
    assert result["status"] == "temporarily_blocked"
    assert result["reason"] == "parking_position_missing"
    car.position = {"latitude": 50.0, "longitude": 4.0}
    assert (
        control_decision(car, profile, auth, "remote", "flash")["operation"]
        == "cariad.remote.flash"
    )


def test_b13_observed_timer_windows_service_codes_and_access_requests():
    """Synthetic fixture matching the field types observed in Q8 b13."""
    car = V3Vehicle(VIN, "Audi", "Test", "q8", "DE")
    now = datetime.now(UTC)
    payload = {
        "chargingTimers": {
            "chargingTimersStatus": {
                "value": {
                    "timers": [
                        {
                            "id": 1,
                            "enabled": True,
                            "climatisation": False,
                            "singleTimer": {
                                "targetDateTimeLocal": "2026-11-13T07:30:00",
                                "departureDateTimeLocal": "2026-11-13T08:00:00",
                            },
                            "preferredChargingTimes": [
                                {
                                    "id": 2,
                                    "enabled": False,
                                    "startTimeLocal": "21:00",
                                    "endTimeLocal": "04:00",
                                },
                                {
                                    "id": 3,
                                    "enabled": True,
                                    "startTimeLocal": "bad",
                                    "endTimeLocal": "05:00",
                                    "privateField": "private",
                                },
                            ],
                        }
                    ]
                }
            }
        },
        "userCapabilities": {
            "capabilitiesStatus": {
                "value": [{"id": "charging", "status": [0, 2, True, "example", -1]}]
            }
        },
        "access": {
            "accessStatus": {
                "requests": [
                    {"operation": "lock", "status": "accepted", "requestId": "private"}
                ]
            }
        },
        "climatisation": {
            "climatisationStatus": {
                "requests": [
                    {
                        "operation": "start",
                        "status": "accepted",
                        "group": 2,
                        "info": "private",
                        "requestId": "private",
                    }
                ]
            }
        },
    }
    observe_structured(car, payload, now, _accept_observation)
    details = details_for(
        car,
        "charging_timers_detail",
        "connected_services_detail",
        "access_requests_detail",
        "climate_requests_detail",
    )
    timer = details["charging_timers"]["data"]["items"][0]
    assert timer["departure_datetime_local"] == "2026-11-13T08:00:00"
    windows = timer["preferred_charging_times"]["items"]
    assert windows[0] == {
        "id": 2,
        "enabled": False,
        "start_time_local": "21:00",
        "end_time_local": "04:00",
    }
    assert windows[1] == {"id": 3, "enabled": True, "end_time_local": "05:00"}
    service = details["connected_services"]["data"]["items"][0]
    assert service["status_codes"] == [0, 2]
    assert service["status"] == ["example"]
    assert details["access_requests"]["data"]["items"] == [
        {"operation": "lock", "status": "accepted"}
    ]
    assert details["climate_requests"]["data"]["items"] == [
        {"operation": "start", "status": "accepted", "group": 2}
    ]
    assert details["access_requests"]["vehicle_captured"] is None
    assert "private" not in str(details)
    assert not car.advertised_capabilities


def test_timer_projection_reuses_typed_data_and_rejects_older_cache():
    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    now = datetime.now(UTC)
    count = "climatisation_timer_enabled_count"
    next_timer = "next_climatisation_timer_local"

    def observe(stamp, timers):
        observe_derived(
            car,
            SimpleNamespace(),
            {
                "climatisationTimers": {
                    "climatisationTimersStatus": {
                        "value": {
                            "carCapturedTimestamp": stamp.isoformat(),
                            "timers": timers,
                        }
                    }
                }
            },
            stamp,
            _accept_observation,
        )

    enabled = {
        "id": 1,
        "enabled": True,
        "singleTimer": {"startDateTimeLocal": "2026-11-14T07:30:00"},
    }
    observe(now, [enabled])
    assert car.readings[count]["value"] == 1
    assert car.readings[next_timer]["value"] == "2026-11-14T07:30:00"
    later = now + timedelta(minutes=1)
    observe(later, [])
    assert car.readings[count]["value"] == 0
    assert next_timer not in car.readings
    observe(now, [enabled])
    assert car.readings[count]["value"] == 0
    assert next_timer not in car.readings

    latest = later + timedelta(minutes=1)
    observe(latest, [{"id": 2, "enabled": "unknown"}, enabled])
    assert car.readings[count]["status"] == "invalid_value"
    assert next_timer not in car.readings
    observe(
        latest + timedelta(minutes=1),
        [{"id": 3, "enabled": True, "singleTimer": {"startDateTimeLocal": "invalid"}}],
    )
    assert car.readings[count]["value"] == 1
    assert next_timer not in car.readings
    observe(latest + timedelta(minutes=2), [enabled] * 31)
    assert car.readings[count]["status"] == "invalid_value"
    assert next_timer not in car.readings
