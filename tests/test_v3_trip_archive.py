"""Persistent trip history is distinct from HA Recorder and raw API evidence."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.audiconnect.v3.trip_archive import V3TripArchive, merge_history
from custom_components.audiconnect.v3.trips import (
    normalize_cariad_history,
    observe_cariad_trip,
)
from custom_components.audiconnect.v3.vehicle import V3Vehicle

VIN = "WAUZZZ4M0MD123456"


def _row(stamp="2026-01-01T00:00:00Z", **extra):
    return {
        "tripEndTimestamp": stamp,
        "tripType": "shortTerm",
        "mileage_km": 16,
        "startMileage_km": 10,
        "overallMileage_km": 26,
        **extra,
    }


def test_archive_merge_preserves_fields_and_does_not_store_ids_or_raw_payload():
    a = normalize_cariad_history(
        {"data": [_row(id="private", totalFuelConsumption_L=0.5)]}
    )
    b = normalize_cariad_history({"data": [_row(totalElectricConsumption_kwh=4)]})
    merged = merge_history(a, b)
    assert len(merged) == 1
    assert merged[0]["totalFuelConsumption"] == 0.5
    assert merged[0]["totalElectricConsumption"] == 4
    assert merged[0]["tripID"] is None
    assert "private" not in str(merged)
    assert merge_history(merged, merged) == merged


def test_archive_roundtrip_restores_without_network_and_preserves_other_vehicles():
    async def scenario():
        car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
        key = VIN.lower()
        observe_cariad_trip(car, "cariad.mobility.status.lastTrip", {"data": _row()})
        store = SimpleNamespace(
            async_load=AsyncMock(return_value={"vehicles": {"other": []}}),
            async_save=AsyncMock(),
        )
        archive = V3TripArchive.__new__(V3TripArchive)
        archive._store, archive._lock = store, asyncio.Lock()
        await archive.save({key: car})
        saved = store.async_save.call_args.args[0]
        assert "other" in saved["vehicles"]
        store.async_load.return_value = saved
        restarted = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
        await archive.restore({key: restarted})
        assert restarted.trip_history == car.trip_history
        store.async_save.reset_mock()
        await archive.save({key: restarted})
        store.async_save.assert_not_awaited()
        observe_cariad_trip(
            restarted,
            "cariad.mobility.status.lastTrip",
            {
                "data": _row(
                    "2026-01-02T00:00:00Z", startMileage_km=26, overallMileage_km=42
                )
            },
        )
        assert len(restarted.trip_history) == 2

    asyncio.run(scenario())


def test_archive_rejects_bad_and_longterm_records():
    rows = normalize_cariad_history({"data": [_row()]})
    assert (
        len(
            merge_history(
                rows,
                [
                    {**rows[0], "tripType": "longTerm"},
                    {**rows[0], "timestamp": "invalid"},
                    {"source": "mbb_legacy"},
                    None,
                ],
            )
        )
        == 1
    )


def test_partial_odometer_duplicate_merges_only_unique_compatible_interval():
    full = normalize_cariad_history({"data": [_row(totalFuelConsumption_L=0.5)]})[0]
    partial = {
        **full,
        "startMileage": None,
        "totalFuelConsumption": None,
        "totalElectricConsumption": 4,
    }
    result = merge_history([partial], [full])
    assert len(result) == 1
    assert result[0]["startMileage"] == 10
    assert result[0]["totalElectricConsumption"] == 4
    assert result[0]["totalFuelConsumption"] == 0.5
    assert merge_history(result, result) == result
    conflicting = {**full, "startMileage": 11}
    assert len(merge_history([partial], [full, conflicting])) == 3


def test_duplicate_records_in_single_response_preserve_complementary_metrics():
    rows = normalize_cariad_history(
        {
            "data": [
                _row(totalFuelConsumption_L=0.5),
                _row(totalElectricConsumption_kwh=4),
            ]
        }
    )
    assert len(rows) == 1
    assert rows[0]["totalFuelConsumption"] == 0.5
    assert rows[0]["totalElectricConsumption"] == 4


def test_scoped_trip_snapshots_survive_restart_and_never_replace_longterm_with_history():
    async def scenario():
        car = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
        key = VIN.lower()
        observe_cariad_trip(
            car,
            "cariad.mobility.status.lastTrip",
            {"data": _row(totalFuelConsumption_L=0.5)},
        )
        observe_cariad_trip(
            car,
            "cariad.mobility.status.longTerm",
            {"data": _row(tripType="longTerm", mileage_km=4000)},
        )
        store = SimpleNamespace(
            async_load=AsyncMock(return_value={"vehicles": {}}), async_save=AsyncMock()
        )
        archive = V3TripArchive.__new__(V3TripArchive)
        archive._store, archive._lock = store, asyncio.Lock()
        await archive.save({key: car})
        store.async_load.return_value = store.async_save.call_args.args[0]
        restored = V3Vehicle(VIN, "Audi", "Q8", "q8", "DE")
        await archive.restore({key: restored})
        assert restored.trips["last_trip"]["totalFuelConsumption"] == 0.5
        assert restored.trips["longterm_current"]["mileage"] == 4000
        assert len(restored.trip_history) == 1
        observe_cariad_trip(
            restored, "cariad.mobility.status.lastTrip", {"data": _row()}
        )
        assert restored.trips["last_trip"]["totalFuelConsumption"] == 0.5

    asyncio.run(scenario())
