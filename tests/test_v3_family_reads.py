"""Family scan is explicitly read-only, bounded, and context-specific."""

from datetime import UTC, datetime
from types import SimpleNamespace
import pytest

from custom_components.audiconnect.v3.engine import V3Engine
from custom_components.audiconnect.v3.registry import CapabilityRegistry
from custom_components.audiconnect.v3.runtime import catalog_path
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
from custom_components.audiconnect.v3.transport import V3Response


@pytest.mark.asyncio
async def test_cariad_family_scan_uses_only_three_gets_and_records_last_results():
    model = CapabilityRegistry.from_json_file(catalog_path())
    car = V3Vehicle(
        vin="WAUZZZ4M0MD123456",
        name="Audi",
        model="Q8",
        model_family="",
        country="DE",
        auth_family="auth0",
    )
    calls = []

    class Transport:
        remaining_calls = 60

        async def request(self, family, method, path, **kwargs):
            calls.append((family, method, path))
            assert family == "cariad" and method == "GET"
            assert "location" not in path and "parking" not in path
            return V3Response(
                200,
                {"charging": {"batteryStatus": {"value": {"currentSOC_pct": 97}}}},
                datetime.now(UTC),
            )

    class Storage:
        async def async_save(self, profiles):
            pass

    engine = V3Engine(
        None,
        SimpleNamespace(entry_id="id", options={}, data={}),
        model,
        auth=SimpleNamespace(uses_auth0=True, country="DE"),
        transport=Transport(),
        storage=Storage(),
    )
    engine.vehicles[car.vin.lower()] = car
    engine.profiles[car.vin.lower()] = DevelopmentProfile(model, car.context)
    result = await engine.test_family_reads(car.vin, "cariad")
    assert len(calls) <= 3
    assert all(m == "GET" for _, m, _ in calls)
    assert result["family"] == "cariad"
    assert "cariad.discovery.full" in engine.profiles[car.vin.lower()].api_observations
    assert not car.readings
    assert not engine.profiles[car.vin.lower()].attribute_routes
    with pytest.raises(ValueError):
        await engine.test_family_reads(car.vin, "mbb")


@pytest.mark.asyncio
async def test_legacy_scan_never_attempts_modern_endpoint_or_post():
    model = CapabilityRegistry.from_json_file(catalog_path())
    car = V3Vehicle(
        vin="WAUZZZ4M0MD123456",
        name="Audi",
        model="A4",
        model_family="",
        country="DE",
        auth_family="legacy",
    )
    calls = []

    class Transport:
        remaining_calls = None

        async def request(self, family, method, path, **kwargs):
            calls.append((family, method, path))
            assert family == "mbb" and method == "GET" and path.startswith("/fs-car/")
            return V3Response(200, {}, datetime.now(UTC))

    class Storage:
        async def async_save(self, profiles):
            pass

    engine = V3Engine(
        None,
        SimpleNamespace(entry_id="id", options={}, data={}),
        model,
        auth=SimpleNamespace(uses_auth0=False, country="DE"),
        transport=Transport(),
        storage=Storage(),
    )
    engine.vehicles[car.vin.lower()] = car
    engine.profiles[car.vin.lower()] = DevelopmentProfile(model, car.context)
    result = await engine.test_family_reads(car.vin, "mbb")
    assert len(calls) == 5
    assert result["request_count"] == 5
    assert len({path for _, _, path in calls}) == 5


@pytest.mark.asyncio
async def test_full_scan_resumes_and_covers_unmapped_jobs_without_mutations():
    model = CapabilityRegistry.from_json_file(catalog_path())
    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "", "DE")
    calls = []

    class Transport:
        remaining_calls = 60

        async def request(self, family, method, path, **kwargs):
            calls.append(path)
            assert family == "cariad" and method == "GET"
            return V3Response(
                404 if "activeVentilation" in path else 207, {}, datetime.now(UTC)
            )

    class Storage:
        async def async_save(self, profiles):
            pass

    engine = V3Engine(
        None,
        SimpleNamespace(entry_id="id", options={}, data={}),
        model,
        auth=SimpleNamespace(uses_auth0=True, country="DE"),
        transport=Transport(),
        storage=Storage(),
    )
    engine.vehicles[car.vin.lower()] = car
    engine.profiles[car.vin.lower()] = DevelopmentProfile(model, car.context)
    first = await engine.test_family_reads(car.vin, "cariad", full=True)
    assert first["request_count"] == 12 and first["remaining_routes"]
    while first["remaining_routes"]:
        first = await engine.test_family_reads(car.vin, "cariad", full=True)
    assert len(calls) == len(set(calls)) == first["eligible_routes"]
    assert any("activeVentilation" in path for path in calls)
    assert any("batterySupport" in path for path in calls)
    assert any("parkingposition" in path for path in calls)
    assert {path for path in calls if "/vehicle/v1/trips/" in path} == {
        "/vehicle/v1/trips/" + car.vin + "/" + suffix
        for suffix in ("shortterm", "longterm", "shortterm/last")
    }
