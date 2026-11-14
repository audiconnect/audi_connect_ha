"""Legacy Audi vehicle uses MBB executor without importing V2 polling."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3.transport import V3Response
from custom_components.audiconnect.v3.registry import CapabilityRegistry
from custom_components.audiconnect.v3.runtime import catalog_path


def test_v3_vehicle_context_represents_real_auth_family():
    car = V3Vehicle(
        vin="WAUZZZ4M0MD123456",
        name="Audi",
        model="Audi A4",
        model_family="",
        country="DE",
        auth_family="legacy",
    )
    assert car.context.auth == "legacy"
    routes = CapabilityRegistry.from_json_file(catalog_path()).resolve(
        "climate", "status", car.context
    )["available_operations"]
    assert "mbb.climate.status" in routes
    assert all(route.startswith("mbb.") for route in routes)


def test_v3_full_catalog_uses_mbb_executor_metadata_and_keeps_location_manual():
    catalog = CapabilityRegistry.from_json_file(catalog_path())
    assert catalog.families["mbb"]["executor"] == "mbb_legacy_v1"
    assert catalog.families["cariad"]["executor"] == "cariad_v1"
    for op in catalog.capabilities["mobility"]["status"]["operations"]:
        assert catalog.operations[op]["delivery"] == "manual"


@pytest.mark.asyncio
async def test_legacy_context_selects_only_mbb_route_in_engine_poll():
    from custom_components.audiconnect.v3.engine import V3Engine
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile

    legacy = V3Vehicle(
        vin="WAUZZZ4M0MD123456",
        name="Audi",
        model="Audi A4",
        model_family="",
        country="DE",
        auth_family="legacy",
    )
    catalog = CapabilityRegistry.from_json_file(catalog_path())
    called = []

    class FakeTransport:
        request_count = 0
        remaining_calls = 100

        async def request(self, family, method, path, **kw):
            called.append((family, method, path))
            return V3Response(
                200,
                {
                    "climater": {
                        "status": {
                            "climatisationStatusData": {
                                "climatisationState": {"content": "off"}
                            }
                        }
                    }
                },
                datetime.now(UTC),
            )

    class FakeStore:
        async def async_save(self, profiles):
            return None

    dummy = SimpleNamespace(entry_id="test-audi", data={}, options={})
    engine = V3Engine(
        None,
        dummy,
        catalog,
        auth=SimpleNamespace(country="DE", uses_auth0=False),
        transport=FakeTransport(),
        storage=FakeStore(),
    )
    engine.vehicles[legacy.vin.lower()] = legacy
    engine.profiles[legacy.vin.lower()] = DevelopmentProfile(catalog, legacy.context)
    engine._known_vehicle_inventory = True
    await engine.poll()
    assert len(called) == 5
    assert all(x[0:2] == ("mbb", "GET") for x in called)
    assert sum("/fs-car/bs/climatisation/" in x[2] for x in called) == 1
    assert legacy.climate_state == "off"
    assert legacy.climate_captured is None


@pytest.mark.asyncio
async def test_shared_mbb_climater_get_is_reused_for_selected_attribute():
    from custom_components.audiconnect.v3.engine import V3Engine
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile

    legacy = V3Vehicle(
        vin="WAUZZZ4M0MD123456",
        name="Audi",
        model="Audi A4",
        model_family="",
        country="DE",
        auth_family="legacy",
    )
    catalog = CapabilityRegistry.from_json_file(catalog_path())
    calls = []

    class FakeTransport:
        request_count = 0
        remaining_calls = 100

        async def request(self, family, method, path, **kw):
            calls.append((family, method, path))
            return V3Response(
                200,
                {
                    "climater": {
                        "status": {
                            "climatisationStatusData": {
                                "climatisationState": {"content": "off"}
                            }
                        }
                    }
                },
                datetime.now(UTC),
            )

    class FakeStore:
        async def async_save(self, profiles):
            return None

    engine = V3Engine(
        None,
        SimpleNamespace(entry_id="test-audi", data={}, options={}),
        catalog,
        auth=SimpleNamespace(country="DE", uses_auth0=False),
        transport=FakeTransport(),
        storage=FakeStore(),
    )
    engine.vehicles[legacy.vin.lower()] = legacy
    profile = DevelopmentProfile(catalog, legacy.context)
    profile.attribute_routes["climatisationState"] = "mbb.climater.readonly"
    engine.profiles[legacy.vin.lower()] = profile
    engine._known_vehicle_inventory = True
    await engine.poll()
    assert len(calls) == 5
    assert sum("/fs-car/bs/climatisation/" in x[2] for x in calls) == 1
    assert legacy.readings["climatisationState"]["value"] == "off"
    assert legacy.readings["climatisationState"]["family"] == "mbb"
    assert profile.attribute_evidence["climatisationState"]["source"] == "mbb.legacy"
