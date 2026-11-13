from datetime import UTC, datetime
from types import SimpleNamespace
import pytest
from custom_components.audiconnect.v3.transport import (
    V3Response,
    selected_garage_response,
    GARAGE_OPERATION,
    identity_errors,
)
from custom_components.audiconnect.v3.vehicle import V3Vehicle
from custom_components.audiconnect.v3.identity_cache import (
    capture_identity,
    apply_cached_identity,
)
from custom_components.audiconnect.v3.family_executors import CARIADExecutor

VIN = "WAUZZZ4M0MD123456"
OTHER = "WAUZZZ4M0MD123457"


def test_garage_scoped_identity_and_cache():
    response = V3Response(
        200,
        {
            "data": [
                {
                    "vin": VIN,
                    "model": "Audi Q8",
                    "modelYear": 2022,
                    "nickname": "personal",
                    "carnetAllocationType": "unknown",
                },
                {"vin": OTHER, "model": "Other"},
            ]
        },
        datetime.now(UTC),
    )
    selected = selected_garage_response(response, VIN)
    assert OTHER not in str(selected.data) and "personal" not in str(selected.data)
    car = V3Vehicle.from_garage(selected.data["data"][0], "DE")
    assert car.model == "Audi Q8" and car.model_year == "2022"
    assert car.identity_operation == GARAGE_OPERATION and car.car_type == ""
    car.identity_observed_at = datetime.now(UTC).isoformat()
    saved = capture_identity(car)
    restored = V3Vehicle(VIN, "Audi vehicle", "", "", "DE")
    apply_cached_identity(restored, saved)
    assert (
        restored.model == car.model and restored.identity_operation == GARAGE_OPERATION
    )
    assert restored.identity_restored and not restored.car_type


def test_no_model_from_nickname_or_vin():
    car = V3Vehicle.from_garage(
        {"vin": VIN, "model": VIN, "nickname": "Q8", "modelYear": 2022}, "DE"
    )
    assert not car.model and car.model_year == "2022"


def test_garage_only_read():
    auth = SimpleNamespace(
        uses_auth0=True, country="DE", access_token=lambda family: "fake"
    )
    plan = CARIADExecutor().plan(auth, "GET", "/vehicle/v1/vehicles")
    assert plan.url == "https://emea.bff.cariad.digital/vehicle/v1/vehicles"
    for method, path in [
        ("POST", "/vehicle/v1/vehicles"),
        ("GET", "/vehicle/v1/vehicles?foo=1"),
    ]:
        with pytest.raises(ValueError):
            CARIADExecutor().plan(auth, method, path, explicit_action=True)


def test_graphql_exchange_denial_classification():
    result = identity_errors(
        {
            "errors": [
                {
                    "message": "client does not have access to the IDP for token exchange: private",
                    "extensions": {"code": "FORBIDDEN"},
                }
            ]
        },
        VIN,
    )
    assert result == [
        {"code": "FORBIDDEN", "field": "", "reason": "token_exchange_denied"}
    ]


def test_explicit_readiness_not_active_charging_or_unknown():
    from custom_components.audiconnect.v3.vehicle import charging_ready, charging_active

    assert charging_ready("readyForCharging") is True
    assert charging_ready("notReadyForCharging") is False
    assert charging_ready("charging") is None and charging_active("charging") is True
    assert charging_ready("invalid") is None


def test_identity_recovery_accumulates_independent_fields_and_operations():
    first = V3Vehicle.from_graphql(
        {
            "vin": VIN,
            "vehicle": {
                "core": {"modelYear": 2022},
                "classification": {"driveTrain": "PHEV"},
            },
        },
        "DE",
    )
    first.year_operation = "graphql.inventory.afterGarage"
    second = V3Vehicle.from_graphql(
        {
            "vin": VIN,
            "vehicle": {
                "media": {"longName": "Audi Q8 TFSI e"},
                "core": {"modelYear": 2023},
            },
        },
        "DE",
    )
    first.merge_identity_evidence(second, operation="graphql.inventory.extended")
    assert first.model == "Audi Q8 TFSI e" and first.model_family == "q8"
    assert first.model_year == "2022" and first.car_type == "phev"
    assert first.identity_operation == "graphql.inventory.extended"
    assert first.year_operation == "graphql.inventory.afterGarage"
    baseline = V3Vehicle.from_graphql({"vin": VIN, "nickname": "My vehicle"}, "DE")
    baseline.merge_identity_evidence(first)
    assert baseline.name == "My vehicle"
    assert baseline.model == first.model and baseline.model_year == first.model_year
    assert baseline.identity_operation == first.identity_operation
    assert baseline.year_operation == first.year_operation
    assert baseline.car_type == first.car_type


def test_identity_recovery_combines_graphql_and_garage_only_for_same_vin_market():
    car = V3Vehicle.from_graphql(
        {"vin": VIN, "vehicle": {"media": {"longName": "Audi Q8"}}}, "DE"
    )
    for vin, region in ((OTHER, "DE"), (VIN, "BE")):
        car.merge_identity_evidence(
            V3Vehicle.from_garage(
                {"vin": vin, "model": "Other", "modelYear": 2025}, region
            )
        )
    assert not car.model_year and car.model == "Audi Q8"
    garage = V3Vehicle.from_garage({"vin": VIN, "modelYear": 2022}, "DE")
    car.merge_identity_evidence(garage)
    assert car.model == "Audi Q8" and car.model_year == "2022"
    assert car.year_operation == GARAGE_OPERATION and not car.car_type


def test_identity_recovery_rejects_cached_as_fresh_evidence():
    car = V3Vehicle.from_graphql({"vin": VIN}, "DE")
    cached = V3Vehicle(
        VIN, "Audi Q8", "Audi Q8", "q8", "DE", model_year="2022", identity_restored=True
    )
    car.merge_identity_evidence(cached)
    assert not car.model and not car.model_year and not car.car_type


@pytest.mark.parametrize(
    "rows,errors,expected",
    [
        ([{"vin": VIN}, {"vin": OTHER}], [], True),
        ([{"vin": VIN}], [{"path": ["userVehicles", 0, "vehicle", "core"]}], True),
        ([{"vin": VIN}], [{"path": ["userVehicles"]}], False),
        ([{"vin": VIN}], [{"path": ["userVehicles", 0, "vin"]}], False),
        ([{"vin": VIN}], [{"message": "root failure"}], False),
        ([{"vin": VIN}, None], [], False),
        ([{"vin": VIN}, {"vin": VIN.lower()}], [], False),
        ([], [], False),
    ],
)
def test_inventory_absence_requires_complete_membership(rows, errors, expected):
    from custom_components.audiconnect.v3.transport import inventory_membership_complete

    assert (
        inventory_membership_complete(
            {"data": {"userVehicles": rows}, "errors": errors}
        )
        is expected
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [401, 403, 404, "missing_token", "malformed"])
async def test_native_inventory_fallback_is_bounded_and_does_not_revoke(failure):
    from unittest.mock import AsyncMock
    from custom_components.audiconnect.v3.auth import FamilyAuthUnavailable
    from custom_components.audiconnect.v3.quota import QuotaBudget
    from custom_components.audiconnect.v3.transport import V3Transport

    transport = object.__new__(V3Transport)
    transport.quota = QuotaBudget(remaining=50)
    now = datetime.now(UTC)
    primary = (
        FamilyAuthUnavailable("missing")
        if failure == "missing_token"
        else V3Response(200 if failure == "malformed" else failure, {}, now)
    )
    transport.request = AsyncMock(
        side_effect=[primary, V3Response(200, {"data": [{"vin": VIN}]}, now)]
    )
    assert await transport.discover_vehicles() == [{"vin": VIN}]
    assert transport.last_inventory_operation == GARAGE_OPERATION
    assert not transport.last_inventory_complete
    assert transport.last_inventory_fallback_reason
    assert transport.request.await_count == 2
    assert transport.request.await_args.args == (
        "cariad",
        "GET",
        "/vehicle/v1/vehicles",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 429, 503])
async def test_inventory_never_falls_back_for_valid_vin_or_rate_limit(status):
    from unittest.mock import AsyncMock
    from custom_components.audiconnect.v3.quota import QuotaBudget
    from custom_components.audiconnect.v3.transport import V3Transport

    transport = object.__new__(V3Transport)
    transport.quota = QuotaBudget(remaining=50)
    rows = [{"vin": VIN, "vehicle": None}]
    transport.request = AsyncMock(
        return_value=V3Response(
            status, {"data": {"userVehicles": rows}}, datetime.now(UTC)
        )
    )
    if status == 200:
        assert await transport.discover_vehicles() == rows
    else:
        with pytest.raises(RuntimeError):
            await transport.discover_vehicles()
    assert transport.request.await_count == 1
    assert not transport.last_inventory_fallback_reason


@pytest.mark.asyncio
async def test_garage_fallback_projects_identity_without_revoking_or_exposing_other_vins():
    from unittest.mock import AsyncMock, Mock
    from custom_components.audiconnect.v3.engine import V3Engine
    from custom_components.audiconnect.v3.registry import CapabilityRegistry
    from custom_components.audiconnect.v3.runtime import catalog_path
    from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile

    registry = CapabilityRegistry.from_json_file(catalog_path())
    now = datetime.now(UTC)
    transport = SimpleNamespace(
        discover_vehicles=AsyncMock(
            return_value=[{"vin": VIN, "model": "Audi Q8", "nickname": "private"}]
        ),
        last_inventory_operation=GARAGE_OPERATION,
        last_inventory_complete=False,
        last_inventory_metadata=V3Response(200, None, now),
        last_inventory_fallback_reason="graphql_inventory_rejected",
        discover_vehicle_images=AsyncMock(),
        remaining_calls=50,
    )

    async def load_profiles(registry, contexts):
        return {key: DevelopmentProfile(registry, ctx) for key, ctx in contexts.items()}

    engine = V3Engine(
        None,
        SimpleNamespace(entry_id="entry", options={}, data={}),
        registry,
        auth=SimpleNamespace(uses_auth0=True, country="DE"),
        transport=transport,
        storage=SimpleNamespace(async_load=load_profiles, async_save=AsyncMock()),
    )
    other = V3Vehicle(OTHER, "Audi", "", "", "DE")
    engine.vehicles[OTHER.lower()] = other
    engine._api_record = Mock()
    await engine.discover()
    car = engine.vehicles[VIN.lower()]
    assert car.model == "Audi Q8" and car.identity_operation == GARAGE_OPERATION
    assert other.inventory_present and not other.inventory_misses
    args = engine._api_record.call_args.args
    assert args[1:4] == (GARAGE_OPERATION, "cariad", "GET")
    assert "private" not in str(args[4].data) and OTHER not in str(args[4].data)
    transport.discover_vehicle_images.assert_not_awaited()
