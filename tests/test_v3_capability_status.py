"""V3 capability dashboard: prove support is not invented from V2 routes."""

import json
from pathlib import Path

from custom_components.audiconnect.v3.capability_status import build_status_report
from custom_components.audiconnect.v3.development_profiles import DevelopmentProfile
from custom_components.audiconnect.v3.registry import CapabilityRegistry, VehicleContext
from custom_components.audiconnect.v3.vehicle import V3Vehicle

CATALOG = Path(__file__).resolve().parents[1] / "tests/fixtures/v3_climate_catalog.json"


def _fixture():
    registry = CapabilityRegistry(json.loads(CATALOG.read_text()))
    vehicle = V3Vehicle(
        vin="TESTVIN1234567890",
        name="My Audi",
        model="Audi Q8",
        model_family="q8",
        country="DE",
    )
    profile = DevelopmentProfile(
        registry,
        VehicleContext(auth="auth0", region="DE", model_family="q8"),
        cooldown_seconds=0,
    )
    return vehicle, profile


def test_all_v2_reference_routes_are_explicitly_unmigrated():
    car, profile = _fixture()
    report = build_status_report(car, profile)
    refs = [r for r in report["rows"] if r["source"] == "v2_reference_only"]
    assert len(refs) >= 20
    assert all(r["status"] == "known_v2_not_migrated" for r in refs)
    assert all(r["api_family"] == "cariad" and "{VIN}" in r["path"] for r in refs)
    assert report["counts"]["verified_working"] == 0
    assert "TESTVIN1234567890" not in json.dumps(report)


def test_discovery_status_and_path_are_independent_from_capability():
    car, profile = _fixture()
    route = "cariad.climate.status.batch"
    profile.record_status(
        "climate",
        route,
        http_status=200,
        schema_valid=True,
        fresh=False,
    )
    result = build_status_report(car, profile)
    matched = [x for x in result["rows"] if x["operation"] == route]
    assert matched and all(x["status"] == "readable_but_stale" for x in matched)
    assert all(x["api_family"] == "cariad" for x in matched)


def test_only_actual_extracted_attribute_counts_as_discovered():
    car, profile = _fixture()
    route = "cariad.climate.status.batch"
    profile.record_status(
        "climate",
        route,
        http_status=200,
        schema_valid=True,
        fresh=True,
    )
    car.readings["climatisationState"] = {
        "path": "climatisation.climatisationStatus.value.climatisationState",
    }
    rows = [
        x for x in build_status_report(car, profile)["rows"] if x["operation"] == route
    ]
    assert [r["status"] for r in rows].count("worked") == 1
    assert [r["status"] for r in rows].count("mapped_not_confirmed") == 1


def test_draft_selection_does_not_mark_control_as_working():
    car, profile = _fixture()
    route = "cariad.climate.start.stored"
    profile.save_candidate("climate", "start", route)
    report = build_status_report(car, profile)
    candidate = next(r for r in report["rows"] if r["operation"] == route)
    assert candidate["saved_candidate"] is True
    assert candidate["selected"] is False
    assert candidate["status"] == "not_tested"


def test_cockpit_does_not_confuse_http_success_with_physical_or_schema_proof():
    from custom_components.audiconnect.v3.api_observations import (
        record_for,
        save_record,
    )

    car, profile = _fixture()
    route = "cariad.climate.start.stored"
    save_record(
        profile,
        route,
        record_for(
            family="cariad", method="POST", http_status=204, vin=car.vin, payload=None
        ),
    )
    profile.fast_bindings["climate.start"] = {
        "status": "catalog_matched",
        "operation": route,
    }
    report = build_status_report(car, profile)
    item = next(o for o in report["operations"] if o["operation"] == route)
    assert item["tested"] and item["active"] and item["physical"] == "not_tested"
    assert "accepted_not_physically_verified" in item["attention"]
    action = next(c for c in report["control_actions"] if c["action"] == "start")
    assert action["enabled"] and action["physical_evidence"] == "not_verified"
    assert len(report["operations"]) == len(
        {o["operation"] for o in report["operations"]}
    )


def test_cockpit_exposes_oil_type_issue_and_schema_fields():
    from datetime import UTC, datetime
    from custom_components.audiconnect.v3.attribute_runtime import observe_read_only
    from custom_components.audiconnect.v3.api_observations import (
        record_for,
        save_record,
    )

    car, profile = _fixture()
    now = datetime.now(UTC)
    payload = {
        "oilLevel": {
            "oilLevelStatus": {
                "value": {"value": True, "carCapturedTimestamp": now.isoformat()}
            }
        }
    }
    observe_read_only(car, profile, payload, now)
    route = "cariad.climate.status.batch"
    save_record(
        profile,
        route,
        record_for(
            family="cariad", method="GET", http_status=207, vin=car.vin, payload=payload
        ),
    )
    report = build_status_report(car, profile)
    assert any(
        f["reason"] == "boolean_oil_level_use_binary" for f in report["findings"]
    )
    operation = next(o for o in report["operations"] if o["operation"] == route)
    assert operation["partial_http"]
    assert any(f["mapping"] == "derived_binary" for f in operation["fields"])


def test_diagnostic_jobs_follow_canonical_capability_ownership():
    from custom_components.audiconnect.v3.historical_catalog import INVENTORY
    from custom_components.audiconnect.v3.capability_status import _V2_SELECTIVE_JOBS

    assert {
        row["id"]: row["capability"] for row in INVENTORY["jobs"]
    } == _V2_SELECTIVE_JOBS
    assert _V2_SELECTIVE_JOBS["access"] == "access"
    assert _V2_SELECTIVE_JOBS["vehicleHealthInspection"] == "service"


def test_discovery_coverage_matches_dashboard_for_derived_and_invalid_attributes():
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from custom_components.audiconnect.v3.read_discovery import user_progress

    car, profile = _fixture()
    now = datetime.now(UTC).isoformat()
    # Runtime-derived data need not have a separate persisted GET observation.
    car.readings["stateOfCharge"] = {"value": 75, "captured": now}
    profile.attribute_evidence["stateOfCharge"] = {"status": "readable_but_stale"}
    car.readings["remainingClimatisationTime"] = {"value": -1, "captured": now}
    report = build_status_report(car, profile)
    auth = SimpleNamespace(uses_auth0=True, service=SimpleNamespace(_spin=None))
    progress = user_progress(car, profile, auth)
    summary = next(
        row for row in report["capability_summary"] if row["capability"] == "climate"
    )
    assert (
        progress["capabilities"]["climate"]["attribute_evidence"]
        == summary["read_status"]
    )
    assert (
        next(row for row in report["rows"] if row.get("attribute") == "stateOfCharge")[
            "status"
        ]
        == "verified"
    )


def test_untested_read_candidates_are_linked_to_entities_before_any_api_call():
    from custom_components.audiconnect.v3.custom_attributes import validate_definition

    car, profile = _fixture()
    profile.attribute_definitions["user.attribute.pressure"] = validate_definition(
        {
            "id": "user.attribute.pressure",
            "capability": "local",
            "name": "Pressure",
            "type": "number",
            "unit": "bar",
            "device_class": "pressure",
        }
    )
    profile.attribute_custom["user.read.pressure"] = {
        "id": "user.read.pressure",
        "attribute": "user.attribute.pressure",
        "family": "cariad",
        "method": "GET",
        "path": "/vehicle/v1/vehicles/{VIN}/pressure",
        "response_path": "pressure.value",
    }
    report = build_status_report(car, profile)
    operations = {o["operation"]: o for o in report["operations"]}
    custom = operations["user.read.pressure"]
    assert custom["capabilities"] == ["local"]
    assert not custom["tested"] and not custom["active"]
    assert custom["mappings"][0]["entity_key"] == "sensor.v3_custom_pressure"
    assert custom["mappings"][0]["status"] == "not_tested"
    charging = operations["cariad.status.charging"]
    assert any(
        m["attribute"] == "stateOfCharge" and not m["active"]
        for m in charging["mappings"]
    )


def test_next_actions_prioritizes_missing_identity_without_repeating_known_mapping_notes():
    from datetime import UTC, datetime
    from custom_components.audiconnect.v3.attribute_runtime import observe_read_only

    car, profile = _fixture()
    car.model = car.model_family = ""
    now = datetime.now(UTC)
    observe_read_only(
        car,
        profile,
        {
            "oilLevel": {
                "oilLevelStatus": {
                    "value": {"value": True, "carCapturedTimestamp": now.isoformat()}
                }
            }
        },
        now,
    )
    car.readings["remainingClimatisationTime"] = {
        "value": -1,
        "captured": now.isoformat(),
    }
    car.readings["climatisationState"] = {"value": "off", "captured": now.isoformat()}
    report = build_status_report(car, profile)
    assert report["next_actions"][0]["reason"] == "manufacturer_identity_missing"
    assert not report["identity_summary"]["manufacturer_model"]
    assert any(
        f["reason"] == "boolean_oil_level_use_binary" for f in report["findings"]
    )
    assert not any(
        f["reason"] in ("boolean_oil_level_use_binary", "negative_duration")
        for f in report["next_actions"]
    )


def test_old_failed_route_is_not_next_action_when_control_has_working_binding():
    from custom_components.audiconnect.v3.command_journal import CommandRecord

    car, profile = _fixture()
    failed = CommandRecord.begin("climate", "start", "cariad.climate.start.stored", 1)
    failed.state = "physical_failed"
    profile.command_journal.append(failed)
    profile.control_results[failed.operation] = "failed"
    profile.fast_bindings["climate.start"] = {
        "status": "local_verified",
        "operation": "cariad.climate.start.settings",
    }
    report = build_status_report(car, profile)
    assert any(
        f["reason"] == "physical_control_physical_failed" for f in report["findings"]
    )
    assert not any(
        f["reason"] == "physical_control_physical_failed"
        for f in report["next_actions"]
    )


def test_current_control_action_and_reconciled_hybrid_do_not_require_inventory_model():
    car, profile = _fixture()
    car.model = car.model_family = ""
    car.readings["carType"] = {"value": "hybrid", "status": "verified"}
    profile.fast_bindings["climate.start"] = {
        "status": "no_working_route",
        "operation": None,
    }
    report = build_status_report(car, profile)
    assert report["identity_summary"]["powertrain"] == "hybrid"
    assert not report["identity_summary"]["oem_drivetrain"]
    assert not report["identity_summary"]["manufacturer_model"]
    assert any(
        f.get("action") == "start" and f["reason"] == "no_working_route"
        for f in report["next_actions"]
    )
    profile.fast_bindings["climate.start"] = {
        "status": "local_verified",
        "operation": "cariad.climate.start.stored",
    }
    assert not any(
        f.get("action") == "start"
        for f in build_status_report(car, profile)["next_actions"]
    )


def test_retired_identity_experiments_are_historical_only():
    car, profile = _fixture()
    report = build_status_report(car, profile)
    operations = {op["operation"]: op for op in report["operations"]}
    for key in (
        "graphql.inventory.extended",
        "graphql.inventory.modern",
        "graphql.inventory.webOrdered",
        "cariad.inventory.vehicles",
    ):
        assert operations[key]["reference_only"]
        assert operations[key]["retired_experiment"]
        assert not operations[key]["active"]
    assert not operations["graphql.inventory.vehicleList"].get("retired_experiment")
    assert not operations["graphql.inventory.images"].get("retired_experiment")
