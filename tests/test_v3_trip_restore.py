"""V3 previous fixbranch trip routes and safe normalization."""

from types import SimpleNamespace as NS
from datetime import UTC, datetime
import pytest

from custom_components.audiconnect.v3.trips import normalize_cariad_trip
from custom_components.audiconnect.v3.family_executors import CARIADExecutor

VIN = "WAUZZZ4M0MD123456"


def test_trip_routes_read_only_allowlist():
    auth = NS(uses_auth0=True, country="DE", access_token=lambda family: "test")
    for suffix in ("shortterm", "longterm", "shortterm/last"):
        path = f"/vehicle/v1/trips/{VIN}/{suffix}"
        assert CARIADExecutor().plan(auth, "GET", path).url.endswith(path)
        with pytest.raises(ValueError):
            CARIADExecutor().plan(auth, "POST", path, {}, explicit_action=True)
    with pytest.raises(ValueError):
        CARIADExecutor().plan(auth, "GET", f"/vehicle/v1/trips/{VIN}/unknown")


def test_trip_normalization_never_invents_units_or_timestamp():
    stamp = datetime.now(UTC).isoformat()
    trip, verdict = normalize_cariad_trip(
        {
            "data": [
                {
                    "tripEndTimestamp": stamp,
                    "mileage_km": 35,
                    "averageFuelConsumption_L_per_100km": 7.3,
                }
            ]
        }
    )
    assert verdict == "normalized"
    assert trip["mileage"] == 35
    assert trip["averageFuelConsumption"] == 7.3
    assert trip["tripID"] is None
    assert normalize_cariad_trip({"mileage_km": 20})[0] is None
    assert (
        normalize_cariad_trip({"timestamp": stamp, "averageFuelConsumption": 81})[0]
        is None
    )


def test_no_v3_probe_services_in_public_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "custom_components" / "audiconnect"
    yaml = (root / "services.yaml").read_text()
    for name in ("probe_vehicle_health", "probe_trip_data", "refresh_trip_data"):
        assert f"\n{name}:" not in yaml
    init = (root / "__init__.py").read_text()
    assert "SERVICE_PROBE_API_PATHS" in init
    assert (
        'for obsolete in ("probe_vehicle_health", "probe_trip_data", "refresh_trip_data"):'
        in init
    )
    assert "probe_read_only_api(" not in (root / "v3" / "engine.py").read_text()
    engine = (root / "v3" / "engine.py").read_text()
    assert "async def restore_reads(" not in engine
    status = (root / "v3" / "status_engine.py").read_text()
    assert "await self._poll_trips(car)" in status


def test_trip_data_poll_uses_one_cadence_and_retains_existing_data():
    import asyncio
    from unittest.mock import AsyncMock
    from custom_components.audiconnect.v3.status_engine import StatusEngine
    from custom_components.audiconnect.v3.vehicle import V3Vehicle

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    stamp = datetime.now(UTC).isoformat()
    transport = NS(
        remaining_calls=100,
        request=AsyncMock(
            return_value=NS(
                status=200,
                observed_at=datetime.now(UTC),
                data={"data": [{"tripEndTimestamp": stamp, "mileage_km": 35}]},
            )
        ),
    )
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
    from custom_components.audiconnect.v3.registry import CapabilityRegistry
    from custom_components.audiconnect.v3.runtime import catalog_path
    from custom_components.audiconnect.v3.trips import CARIAD_TRIP_OPERATIONS

    registry = CapabilityRegistry.from_json_file(catalog_path())
    profile = DevelopmentProfile(registry, car.context)
    records = []

    def request(car, ident):
        op = registry.operations[ident]
        return op["family"], op["method"], op["path"].format(VIN=car.vin), None

    engine = NS(
        transport=transport,
        _trip_poll_at={},
        profiles={VIN.lower(): profile},
        _operation_request=request,
        _api_record=lambda profile, ident, *args: records.append(ident),
    )
    asyncio.run(StatusEngine._poll_trips(engine, car))
    assert records == [*CARIAD_TRIP_OPERATIONS, "cariad.mobility.status.tripStatistics"]
    assert transport.request.await_count == 4
    assert car.trips["shortterm_current"]["mileage"] == 35
    asyncio.run(StatusEngine._poll_trips(engine, car))
    assert transport.request.await_count == 4


def test_trip_observation_rejects_older_capture():
    from datetime import timedelta
    from custom_components.audiconnect.v3.vehicle import V3Vehicle
    from custom_components.audiconnect.v3.trips import observe_cariad_trip

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    now = datetime.now(UTC)
    op = "cariad.mobility.status.lastTrip"
    assert observe_cariad_trip(
        car, op, {"data": [{"tripEndTimestamp": now.isoformat(), "mileage_km": 35}]}
    )
    assert not observe_cariad_trip(
        car,
        op,
        {
            "data": [
                {
                    "tripEndTimestamp": (now - timedelta(days=1)).isoformat(),
                    "mileage_km": 10,
                }
            ]
        },
    )
    assert car.trips["last_trip"]["mileage"] == 35


@pytest.mark.parametrize(
    "distance,avg_electric,total_electric,avg_fuel,total_fuel",
    [
        (16, 38.5, 6.16, 2.6, 0.416),
        (14087, 16.5, 2324.355, 7.1, 1000.177),
        (48, 29.8, 14.304, 2.3, 1.104),
    ],
)
def test_modern_trip_energy_and_fuel_from_observed_response_shape(
    distance, avg_electric, total_electric, avg_fuel, total_fuel
):
    # Sanitized b12 response shape; no real vehicle or trip identifiers.
    row = {
        "tripEndTimestamp": "2026-11-12T06:11:53Z",
        "mileage_km": distance,
        "averageElectricConsumption": avg_electric,
        "totalElectricConsumption_kwh": total_electric,
        "averageFuelConsumption": avg_fuel,
        "totalFuelConsumption_L": total_fuel,
    }
    trip, verdict = normalize_cariad_trip({"data": row})
    assert verdict == "normalized"
    assert trip["averageElectricEngineConsumption"] == avg_electric
    assert trip["totalElectricConsumption"] == total_electric
    assert trip["totalFuelConsumption"] == total_fuel
    assert trip["units"]["totalElectricConsumption"] == "kWh"
    assert trip["units"]["totalFuelConsumption"] == "L"
    assert trip["tripID"] is None


def test_ambiguous_modern_electric_rate_and_zero_values():
    row = {
        "tripEndTimestamp": "2026-11-12T06:11:53Z",
        "mileage_km": 16,
        "averageElectricConsumption": 38.5,
        "totalElectricConsumption_kwh": 0.616,
        "totalFuelConsumption_L": 0,
    }
    trip, _ = normalize_cariad_trip({"data": row})
    assert trip["averageElectricEngineConsumption"] is None
    assert trip["totalElectricConsumption"] == 0.616
    assert trip["totalFuelConsumption"] == 0
    row["totalElectricConsumption_kwh"] = True
    assert normalize_cariad_trip({"data": row})[0]["totalElectricConsumption"] is None
    row.update(averageElectricConsumption=0, totalElectricConsumption_kwh=0)
    trip, _ = normalize_cariad_trip({"data": row})
    assert trip["averageElectricEngineConsumption"] == 0
    assert trip["totalElectricConsumption"] == 0


def test_trip_history_is_sorted_deduplicated_and_excludes_long_term():
    from custom_components.audiconnect.v3.trips import observe_cariad_trip
    from custom_components.audiconnect.v3.vehicle import V3Vehicle

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    older = {
        "tripEndTimestamp": "2025-09-18T06:06:14Z",
        "tripType": "shortTerm",
        "mileage_km": 18,
        "startMileage_km": 10,
        "overallMileage_km": 28,
    }
    latest = {
        "tripEndTimestamp": "2026-11-12T06:11:53Z",
        "tripType": "shortTerm",
        "mileage_km": 16,
        "startMileage_km": 28,
        "overallMileage_km": 44,
    }
    observe_cariad_trip(
        car, "cariad.mobility.status.shortTerm", {"data": [older, latest, older]}
    )
    observe_cariad_trip(car, "cariad.mobility.status.lastTrip", {"data": latest})
    observe_cariad_trip(
        car,
        "cariad.mobility.status.longTerm",
        {"data": {**latest, "tripType": "longTerm", "mileage_km": 44}},
    )
    assert [row["mileage"] for row in car.trip_history] == [16, 18]
    assert car.trips["shortterm_current"]["mileage"] == 16
    assert all(row["tripID"] is None for row in car.trip_history)


def test_native_trip_metrics_only_project_real_values_and_never_accrue_per_trip():
    from custom_components.audiconnect.v3.vehicle import V3Vehicle
    from custom_components.audiconnect.v3.trips import observe_cariad_trip
    from custom_components.audiconnect.v3.ha_platforms import setup
    from custom_components.audiconnect.v3.entities import V3TripMetricSensor

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    offered, listeners = [], []
    engine = NS(vehicles={VIN.lower(): car}, profiles={})
    co = NS(engine=engine, async_add_listener=lambda cb: listeners.append(cb))
    entry = NS(
        entry_id="entry",
        runtime_data=NS(v3=engine, coordinator=co),
        async_on_unload=lambda cb: None,
    )
    setup("sensor", entry, offered.extend)
    assert not any(isinstance(e, V3TripMetricSensor) for e in offered)
    row = {
        "tripEndTimestamp": "2026-11-12T06:11:53Z",
        "mileage_km": 16,
        "travelTime": 28,
        "averageSpeed_kmph": 34,
        "averageFuelConsumption": 2.6,
        "averageElectricConsumption": 38.5,
        "totalElectricConsumption_kwh": 6.16,
        "totalFuelConsumption_L": 0.416,
    }
    observe_cariad_trip(car, "cariad.mobility.status.lastTrip", {"data": row})
    listeners[0]()
    listeners[0]()
    sensors = {e.key: e for e in offered if isinstance(e, V3TripMetricSensor)}
    assert len(sensors) == 7
    assert sensors["last_trip_electric_consumption"].native_value == 6.16
    assert sensors["last_trip_electric_consumption"].native_unit_of_measurement == "kWh"
    assert sensors["last_trip_fuel_consumption"].native_unit_of_measurement == "L"
    assert sensors["last_trip_distance"].native_value == 16
    assert all(e.state_class is None for e in sensors.values())
    assert all(e.entity_category is None for e in sensors.values())
    assert len([e for e in offered if isinstance(e, V3TripMetricSensor)]) == 7


def test_native_trip_history_exposes_rows_without_recording_large_attribute():
    from custom_components.audiconnect.v3.vehicle import V3Vehicle
    from custom_components.audiconnect.v3.trips import observe_cariad_trip
    from custom_components.audiconnect.v3.ha_platforms import setup
    from custom_components.audiconnect.v3.entities import V3TripHistorySensor

    car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
    offered, listeners = [], []
    engine = NS(vehicles={VIN.lower(): car}, profiles={})
    co = NS(engine=engine, async_add_listener=lambda cb: listeners.append(cb))
    entry = NS(
        entry_id="entry",
        runtime_data=NS(v3=engine, coordinator=co),
        async_on_unload=lambda cb: None,
    )
    setup("sensor", entry, offered.extend)
    observe_cariad_trip(
        car,
        "cariad.mobility.status.shortTerm",
        {
            "data": [
                {
                    "tripEndTimestamp": "2026-11-12T06:11:53Z",
                    "tripType": "shortTerm",
                    "vehicleType": "hybrid",
                    "mileage_km": 16,
                    "zeroEmissionDistance_km": 5,
                    "startMileage_km": 10,
                    "overallMileage_km": 26,
                }
            ]
        },
    )
    listeners[0]()
    listeners[0]()
    sensors = [e for e in offered if isinstance(e, V3TripHistorySensor)]
    assert len(sensors) == 1
    entity = sensors[0]
    assert entity.native_value == 1 and entity.available
    assert entity.extra_state_attributes["trips"][0]["vehicleType"] == "hybrid"
    assert entity.extra_state_attributes["trips"][0]["zeroEmissionDistance"] == 5
    assert "tripID" not in entity.extra_state_attributes["trips"][0]
    assert "trips" in entity._unrecorded_attributes
    assert any(
        e.unique_id.endswith("_sensor_shortterm_trip_zero_emission_distance")
        for e in offered
    )
