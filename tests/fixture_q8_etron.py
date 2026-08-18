"""Real selectivestatus payload from a 2024 Q8 Sportback e-tron, 2026-08-18.

Captured from the integration's own debug log. Home coordinates scrubbed to
0.0/0.0; every other value is verbatim from the car.
"""

import datetime

PAYLOAD = {
    "access": {
        "accessStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 9, 17, tzinfo=datetime.UTC
                ),
                "doorLockStatus": "locked",
                "doors": [
                    {"name": "bonnet", "status": ["closed"]},
                    {"name": "frontLeft", "status": ["locked", "closed"]},
                    {"name": "frontRight", "status": ["locked", "closed"]},
                    {"name": "rearLeft", "status": ["locked", "closed"]},
                    {"name": "rearRight", "status": ["locked", "closed"]},
                    {"name": "trunk", "status": ["locked", "closed"]},
                ],
                "overallStatus": "safe",
                "windows": [
                    {"name": "frontLeft", "status": ["closed"]},
                    {"name": "frontRight", "status": ["closed"]},
                    {"name": "rearLeft", "status": ["closed"]},
                    {"name": "rearRight", "status": ["closed"]},
                    {"name": "roofCover", "status": ["unsupported"]},
                    {"name": "sunRoof", "status": ["unsupported"]},
                    {"name": "sunRoofRear", "status": ["unsupported"]},
                ],
            }
        }
    },
    "charging": {
        "batteryStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 9, 17, tzinfo=datetime.UTC
                ),
                "cruisingRangeElectric_km": 300,
                "currentSOC_pct": 69,
            }
        },
        "chargeMode": {
            "value": {"availableChargeModes": [], "preferredChargeMode": "manual"}
        },
        "chargingSettings": {
            "value": {
                "autoUnlockPlugWhenChargedDC": "off",
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 1, 3, tzinfo=datetime.UTC
                ),
                "targetSOC_pct": 70,
            }
        },
        "chargingStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 9, 17, tzinfo=datetime.UTC
                ),
                "chargeMode": "manual",
                "chargePower_kW": 0,
                "chargeRate_kmph": 0,
                "chargeType": "off",
                "chargingState": "readyForCharging",
                "remainingChargingTimeToComplete_min": 0,
            }
        },
        "plugStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 9, 17, tzinfo=datetime.UTC
                ),
                "externalPower": "ready",
                "ledColor": "green",
                "plugConnectionState": "connected",
                "plugLockState": "locked",
            }
        },
    },
    "chargingProfiles": {
        "chargingProfilesStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 1, 4, tzinfo=datetime.UTC
                ),
                "nextChargingTimer": {"id": 0, "targetSOCreachable": ""},
                "profiles": [
                    {
                        "id": 1,
                        "minSOC_enabled": False,
                        "minSOC_pct": 2,
                        "name": "Home",
                        "options": {"autoUnlockPlugWhenCharged": "unsupported"},
                        "position": {"lat": 0.0, "lon": 0.0},
                        "preferredChargingTimes": [
                            {
                                "enabled": False,
                                "endTimeLocal": "02:09",
                                "id": 1,
                                "startTimeLocal": "23:13",
                            }
                        ],
                        "targetSOC_pct": 60,
                        "timers": [],
                    },
                    {
                        "id": 2,
                        "minSOC_enabled": False,
                        "minSOC_pct": 2,
                        "name": "Work",
                        "options": {"autoUnlockPlugWhenCharged": "unsupported"},
                        "position": {"lat": 0.0, "lon": 0.0},
                        "preferredChargingTimes": [
                            {
                                "enabled": False,
                                "endTimeLocal": "00:00",
                                "id": 1,
                                "startTimeLocal": "00:00",
                            }
                        ],
                        "targetSOC_pct": 100,
                        "timers": [],
                    },
                ],
                "vehiclePositionedInProfileID": 1,
            }
        }
    },
    "chargingTimers": {
        "chargingTimersStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 17, 57, 12, tzinfo=datetime.UTC
                ),
                "timeInCar": "",
                "timers": [
                    {
                        "climatisation": False,
                        "enabled": False,
                        "id": 1,
                        "recurringTimer": {
                            "departureTimeLocal": "11:05",
                            "recurringOn": {
                                "fridays": False,
                                "mondays": False,
                                "saturdays": False,
                                "sundays": False,
                                "thursdays": True,
                                "tuesdays": False,
                                "wednesdays": False,
                            },
                            "repetitionDays": ["thursday"],
                            "targetTimeLocal": "11:05",
                        },
                    },
                    {
                        "climatisation": False,
                        "enabled": False,
                        "id": 2,
                        "recurringTimer": {
                            "departureTimeLocal": "12:00",
                            "recurringOn": {
                                "fridays": True,
                                "mondays": True,
                                "saturdays": True,
                                "sundays": True,
                                "thursdays": True,
                                "tuesdays": True,
                                "wednesdays": True,
                            },
                            "repetitionDays": [
                                "monday",
                                "tuesday",
                                "wednesday",
                                "thursday",
                                "friday",
                                "saturday",
                                "sunday",
                            ],
                            "targetTimeLocal": "12:00",
                        },
                    },
                    {
                        "climatisation": False,
                        "enabled": False,
                        "id": 3,
                        "recurringTimer": {
                            "departureTimeLocal": "12:00",
                            "recurringOn": {
                                "fridays": True,
                                "mondays": True,
                                "saturdays": True,
                                "sundays": True,
                                "thursdays": True,
                                "tuesdays": True,
                                "wednesdays": True,
                            },
                            "repetitionDays": [
                                "monday",
                                "tuesday",
                                "wednesday",
                                "thursday",
                                "friday",
                                "saturday",
                                "sunday",
                            ],
                            "targetTimeLocal": "12:00",
                        },
                    },
                    {
                        "climatisation": False,
                        "enabled": False,
                        "id": 4,
                        "recurringTimer": {
                            "departureTimeLocal": "12:00",
                            "recurringOn": {
                                "fridays": True,
                                "mondays": True,
                                "saturdays": True,
                                "sundays": True,
                                "thursdays": True,
                                "tuesdays": True,
                                "wednesdays": True,
                            },
                            "repetitionDays": [
                                "monday",
                                "tuesday",
                                "wednesday",
                                "thursday",
                                "friday",
                                "saturday",
                                "sunday",
                            ],
                            "targetTimeLocal": "12:00",
                        },
                    },
                    {
                        "climatisation": False,
                        "enabled": False,
                        "id": 5,
                        "recurringTimer": {
                            "departureTimeLocal": "12:00",
                            "recurringOn": {
                                "fridays": True,
                                "mondays": True,
                                "saturdays": True,
                                "sundays": True,
                                "thursdays": True,
                                "tuesdays": True,
                                "wednesdays": True,
                            },
                            "repetitionDays": [
                                "monday",
                                "tuesday",
                                "wednesday",
                                "thursday",
                                "friday",
                                "saturday",
                                "sunday",
                            ],
                            "targetTimeLocal": "12:00",
                        },
                    },
                ],
            }
        }
    },
    "climatisation": {
        "climatisationSettings": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 9, 2, tzinfo=datetime.UTC
                ),
                "climatisationWithoutExternalPower": True,
                "climatizationAtUnlock": False,
                "targetTemperature_C": 15.5,
                "targetTemperature_F": 59,
                "windowHeatingEnabled": False,
                "zoneFrontLeftEnabled": False,
                "zoneFrontRightEnabled": False,
            }
        },
        "climatisationStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 9, 17, tzinfo=datetime.UTC
                ),
                "climatisationState": "off",
                "remainingClimatisationTime_min": -256,
            }
        },
        "windowHeatingStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 31, 52, tzinfo=datetime.UTC
                ),
                "windowHeatingStatus": [
                    {"windowHeatingState": "invalid", "windowLocation": "front"},
                    {"windowHeatingState": "invalid", "windowLocation": "rear"},
                ],
            }
        },
    },
    "climatisationTimers": {
        "climatisationTimersStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 17, 57, 12, tzinfo=datetime.UTC
                ),
                "timers": [
                    {
                        "enabled": False,
                        "id": 1,
                        "singleTimer": {
                            "startDateTimeLocal": "2026-08-11T07:10:00",
                            "targetDateTimeLocal": "2026-08-11T07:10:00",
                        },
                    },
                    {
                        "enabled": False,
                        "id": 2,
                        "singleTimer": {
                            "startDateTimeLocal": "2026-08-11T09:10:00",
                            "targetDateTimeLocal": "2026-08-11T09:10:00",
                        },
                    },
                ],
            }
        }
    },
    "fuelStatus": {
        "rangeStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 9, 17, tzinfo=datetime.UTC
                ),
                "carType": "electric",
                "primaryEngine": {
                    "currentSOC_pct": 69,
                    "remainingRange_km": 300,
                    "type": "electric",
                },
                "totalRange_km": 300,
            }
        }
    },
    "measurements": {
        "fuelLevelStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 9, 17, tzinfo=datetime.UTC
                ),
                "carType": "electric",
                "currentSOC_pct": 69,
                "primaryEngineType": "electric",
            }
        },
        "odometerStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 9, 17, tzinfo=datetime.UTC
                ),
                "odometer": 43740,
            }
        },
        "rangeStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 9, 17, tzinfo=datetime.UTC
                ),
                "electricRange": 300,
                "totalRange_km": 300,
            }
        },
    },
    "vehicleHealthInspection": {
        "maintenanceStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 9, 15, tzinfo=datetime.UTC
                ),
                "inspectionDue_days": 381,
                "inspectionDue_km": 16898,
                "mileage_km": 43740,
            }
        }
    },
    "vehicleHealthWarnings": {"warningLights": {"value": {}}},
    "vehicleLights": {
        "lightsStatus": {
            "value": {
                "carCapturedTimestamp": datetime.datetime(
                    2026, 8, 18, 21, 9, 17, tzinfo=datetime.UTC
                ),
                "lights": [
                    {"name": "right", "status": "off"},
                    {"name": "left", "status": "off"},
                ],
            }
        }
    },
}
