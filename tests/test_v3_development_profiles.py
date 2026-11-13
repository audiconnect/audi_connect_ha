"""Custom V3 API operations and verified selection: pure development contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.audiconnect.v3.development_profiles import (
    DevelopmentProfile,
    DevelopmentProfileError,
)
from custom_components.audiconnect.v3.registry import (
    CapabilityRegistry,
    VehicleContext,
)

CATALOG = Path(__file__).resolve().parents[1] / "tests/fixtures/v3_climate_catalog.json"


def workspace(*, family="q8"):
    return DevelopmentProfile(
        CapabilityRegistry(json.loads(CATALOG.read_text())),
        VehicleContext(auth="auth0", region="DE", model_family=family),
        cooldown_seconds=0,
    )


def custom_start(**overrides):
    route = {
        "id": "user.climate.start.custom_body",
        "capability": "climate",
        "aspect": "start",
        "family": "cariad",
        "method": "POST",
        "path": "/vehicle/v1/vehicles/{VIN}/climatisation/start?mode={MODE}",
        "variables": {"MODE": "string", "TARGET": "integer"},
        "body": {"targetTemperature": "{TARGET}", "enabled": True},
        "scope": {"region": "DE"},
        "description": "Developer test using vehicle control settings",
    }
    route.update(overrides)
    return route


def test_custom_path_is_added_as_overlay_not_global_catalog():
    p = workspace()
    ident = p.add(custom_start())
    assert ident in [x["operation"] for x in p.candidates("climate", "start")]
    assert "user.climate.start.custom_body" in p.registry.operations
    assert p._base["operations"].get(ident) is None
    assert p.snapshot()["active"] == {}


def test_preview_expands_vin_and_typed_settings_without_dispatch():
    p = workspace()
    ident = p.add(custom_start())
    preview = p.preview_request(
        ident,
        vehicle_values={"VIN": "TESTVIN00000000001"},
        user_values={"MODE": "eco mode", "TARGET": 22},
    )
    assert preview["relative_path"].endswith("/climatisation/start?mode=eco%20mode")
    assert preview["json_body"] == {"targetTemperature": 22, "enabled": True}
    assert preview["experimental_only"] is True
    assert p.snapshot()["discovery"]["attempts"] == []


def test_selecting_route_requires_confirmed_success_on_real_vehicle():
    p = workspace()
    op = p.add(custom_start())
    with pytest.raises(DevelopmentProfileError, match="test"):
        p.choose_working("climate", "start", op)
    first = p.begin_test("climate", "start", op, now=10)
    p.observe_http(first.sequence, 202)
    p.confirm(first.sequence, worked=None, inspected_vehicle=False, now=12)
    with pytest.raises(DevelopmentProfileError, match="test"):
        p.choose_working("climate", "start", op)
    p.confirm(first.sequence, worked=True, inspected_vehicle=True, now=25)
    p.choose_working("climate", "start", op)
    assert p.snapshot()["active"] == {"climate.start": op}


def test_failed_path_remains_in_history_but_cannot_be_activated():
    p = workspace()
    op = p.add(custom_start())
    attempt = p.begin_test("climate", "start", op, now=10)
    p.observe_http(attempt.sequence, 404)
    p.confirm(attempt.sequence, worked=False, inspected_vehicle=True, now=30)
    with pytest.raises(DevelopmentProfileError, match="test"):
        p.choose_working("climate", "start", op)
    candidates = p.candidates("climate", "start")
    selected = next(x for x in candidates if x["operation"] == op)
    assert selected["evidence"] == "previously_failed"


def test_one_vehicle_works_but_another_vehicle_does_not_inherit_selection():
    car_a = workspace()
    car_b = workspace()
    op = car_a.add(custom_start())
    attempt = car_a.begin_test("climate", "start", op, now=1)
    car_a.confirm(attempt.sequence, worked=True, inspected_vehicle=True, now=2)
    car_a.choose_working("climate", "start", op)
    assert car_b.snapshot()["active"] == {}
    assert op not in car_b.registry.operations


def test_disabling_action_removes_active_selection_but_not_status():
    p = workspace()
    op = p.add(custom_start())
    attempt = p.begin_test("climate", "start", op, now=1)
    p.confirm(attempt.sequence, worked=True, inspected_vehicle=True, now=2)
    p.choose_working("climate", "start", op)
    p.disable("climate", "start")
    assert not p.snapshot()["active"]
    assert p.registry.resolve("climate", "status", p.discovery.context)["operation"]


@pytest.mark.parametrize(
    "bad",
    [
        {"path": "https://evil.example/vehicles/{VIN}/climatisation/start"},
        {"path": "//evil.example/vehicles/{VIN}/climatisation/start"},
        {"path": "/vehicles/WAUZZZZZ9JA123456/climatisation/start"},
        {"path": "/vehicles/{VIN}/../secrets"},
        {"path": "/vehicles/{VIN}/%2E%2E/climate"},
        {"path": "/vehicles/{VIN}/climate#{MODE}"},
        {"path": "/vehicles/{VIN}/climate/{TOKEN}"},
        {"family": "unknown"},
        {"method": "GET"},
        {"scope": {"auth": "legacy"}},
        {"variables": {"VIN": "string"}},
        {"variables": {"MODE": "executable"}},
        {"body": {"token": "{ACCESS_TOKEN}"}},
        {"id": "cariad.climate.start.stored"},
    ],
)
def test_invalid_or_dangerous_user_api_routes_are_rejected(bad):
    p = workspace()
    with pytest.raises(DevelopmentProfileError):
        p.add(custom_start(**bad))
    assert not p.custom


def test_read_only_status_path_can_be_added_without_a_control():
    p = workspace()
    op = p.add(
        {
            "id": "user.climate.status.extra",
            "capability": "climate",
            "aspect": "status",
            "family": "cariad",
            "method": "GET",
            "path": "/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=climatisation",
            "response_paths": [
                "climatisation.climatisationStatus.value.climatisationState"
            ],
        }
    )
    assert p.registry.operations[op]["method"] == "GET"
    assert op in p.registry.operations_for("climate", "status")
    assert p.registry.operations[op]["delivery"] == "manual"


def test_missing_or_incorrect_parameter_rejected_in_preview():
    p = workspace()
    op = p.add(custom_start())
    with pytest.raises(DevelopmentProfileError, match="Missing custom"):
        p.preview_request(op, vehicle_values={"VIN": "TEST"}, user_values={"MODE": "a"})
    with pytest.raises(DevelopmentProfileError, match="invalid typed"):
        p.preview_request(
            op,
            vehicle_values={"VIN": "TEST"},
            user_values={"MODE": "a", "TARGET": "22"},
        )


def test_user_operation_never_overwrites_existing_id():
    p = workspace()
    p.add(custom_start())
    with pytest.raises(DevelopmentProfileError, match="already exists"):
        p.add(custom_start())


def test_latest_failed_result_withdraws_previously_active_route():
    profile = workspace()
    op = profile.add(custom_start())
    first = profile.begin_test("climate", "start", op, now=1)
    profile.confirm(first.sequence, worked=True, inspected_vehicle=True, now=2)
    profile.choose_working("climate", "start", op)
    failed = profile.begin_test("climate", "start", op, now=3)
    profile.confirm(failed.sequence, worked=False, inspected_vehicle=True, now=4)
    assert profile.snapshot()["active"] == {}
    with pytest.raises(DevelopmentProfileError, match="Latest"):
        profile.choose_working("climate", "start", op)


def test_nested_or_format_modified_path_placeholders_are_blocked():
    profile = workspace()
    with pytest.raises(DevelopmentProfileError):
        profile.add(custom_start(path="/vehicles/{VIN.__class__}/start"))
    with pytest.raises(DevelopmentProfileError):
        profile.add(custom_start(path="/vehicles/{VIN!r}/start"))
    with pytest.raises(DevelopmentProfileError):
        profile.add(custom_start(path="/vehicles/{VIN:40}/start"))


def test_status_get_can_be_chosen_only_after_fresh_valid_response():
    p = workspace()
    op = p.add(
        {
            "id": "user.climate.status.probe",
            "capability": "climate",
            "aspect": "status",
            "family": "cariad",
            "method": "GET",
            "path": "/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=climatisation",
            "response_paths": [
                "climatisation.climatisationStatus.value.climatisationState"
            ],
        }
    )
    assert (
        p.record_status("climate", op, http_status=200, schema_valid=True, fresh=False)
        == "readable_but_stale"
    )
    with pytest.raises(DevelopmentProfileError, match="fresh"):
        p.choose_working("climate", "status", op)
    assert (
        p.record_status("climate", op, http_status=200, schema_valid=True, fresh=True)
        == "worked"
    )
    p.choose_working("climate", "status", op)
    assert p.snapshot()["active"]["climate.status"] == op
    assert (
        p.record_status("climate", op, http_status=404, schema_valid=False, fresh=False)
        == "failed"
    )
    assert "climate.status" not in p.snapshot()["active"]


def test_rate_limit_does_not_count_as_confirmed_unsupported():
    p = workspace()
    result = p.record_status(
        "climate",
        "cariad.climate.status.batch",
        http_status=429,
        schema_valid=False,
        fresh=False,
    )
    assert result == "inconclusive"
    assert (
        p.snapshot()["read_evidence"]["cariad.climate.status.batch"]["outcome"]
        == "inconclusive"
    )


def test_route_cannot_include_bearer_or_password_in_json_keys():
    p = workspace()
    with pytest.raises(DevelopmentProfileError, match="Invalid JSON"):
        p.add(custom_start(body={"Authorization": "Bearer bad"}))
    assert not p.custom


def test_development_candidate_save_is_not_equivalent_to_verified_activation():
    p = workspace()
    route = "cariad.climate.start.stored"
    p.save_candidate("climate", "start", route)
    assert p.snapshot()["draft_selected"]["climate.start"] == route
    assert "climate.start" not in p.active
    with pytest.raises(DevelopmentProfileError, match="confirm"):
        p.choose_working("climate", "start", route)


def test_shared_definition_roundtrip_does_not_transfer_evidence_or_activation():
    p = workspace()
    ident = p.add(custom_start())
    attempt = p.begin_test("climate", "start", ident, now=10)
    p.observe_http(attempt.sequence, 202)
    p.confirm(attempt.sequence, worked=True, inspected_vehicle=True, now=25)
    p.choose_working("climate", "start", ident)
    shared = p.share_definition(ident)
    target = workspace()
    assert target.add(shared) == ident
    assert target.custom[ident] == p.custom[ident]
    assert not target.active
    assert not target.control_results
    assert not target.discovery.history


@pytest.mark.parametrize(
    "description",
    ["Contact example@example.org", "Private value topsecret123", "WAUZZZ4M0MD123456"],
)
def test_share_rejects_private_definition_literals(description):
    p = workspace()
    ident = p.add(custom_start(description=description))
    with pytest.raises(DevelopmentProfileError, match="private"):
        p.share_definition(ident, secrets=("topsecret123",))


def test_share_local_read_includes_definition_not_observations():
    p = workspace()
    ident = "user.read.pressure"
    attribute = "user.attribute.pressure"
    p.attribute_custom[ident] = {
        "id": ident,
        "attribute": attribute,
        "family": "cariad",
        "method": "GET",
        "path": "/vehicle/v1/vehicles/{VIN}/example",
        "response_path": "pressure",
    }
    p.attribute_definitions[attribute] = {
        "id": attribute,
        "capability": "vehicle_status",
        "name": "Pressure",
        "type": "number",
    }
    p.attribute_routes[attribute] = ident
    shared = p.share_definition(ident)
    assert shared["attribute_definition"] == p.attribute_definitions[attribute]
    assert "active" not in shared and "attribute_routes" not in shared


@pytest.mark.parametrize("value", [1234, 1234.0])
def test_share_rejects_numeric_pin_under_generic_field(value):
    p = workspace()
    ident = p.add(custom_start(body={"value": value}))
    with pytest.raises(DevelopmentProfileError, match="private"):
        p.share_definition(ident, spin="1234")
