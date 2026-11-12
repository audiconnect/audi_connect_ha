"""Guided climate action discovery; network-free V3 contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.audiconnect.v3.action_discovery import (
    DiscoveryError,
    GuidedActionDiscovery,
)
from custom_components.audiconnect.v3.registry import (
    CapabilityRegistry, VehicleContext,
)

CATALOG = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/v3_climate_catalog.json"
)


def manager(*, family="q8", cooldown=0):
    catalog = CapabilityRegistry(json.loads(CATALOG.read_text()))
    return GuidedActionDiscovery(
        catalog,
        VehicleContext(auth="auth0", model_family=family, region="DE"),
        cooldown_seconds=cooldown,
    )


def test_actions_never_self_execute_and_require_user_gesture():
    m = manager()
    choices = m.candidates("climate", "start")
    assert choices[0]["operation"] == "cariad.climate.start.stored"
    assert all(item["selection_only"] == "true" for item in choices)
    with pytest.raises(DiscoveryError, match="user gesture"):
        m.begin(
            "climate", "start", choices[0]["operation"],
            user_initiated=False, now=10,
        )
    assert not m.history


def test_http_200_stays_unconfirmed_until_vehicle_feedback():
    m = manager()
    op = "cariad.climate.start.stored"
    attempt = m.begin("climate", "start", op, user_initiated=True, now=10)
    m.observe_transport(attempt.sequence, http_status=202)
    assert m.snapshot()["attempts"][0]["transport"] == "accepted_unconfirmed"
    assert m.snapshot()["preferred"] == {}
    with pytest.raises(DiscoveryError, match="vehicle confirmation"):
        m.review(attempt.sequence, result="worked", inspected_vehicle=False, now=12)
    m.review(attempt.sequence, result="worked", inspected_vehicle=True, now=13)
    assert m.snapshot()["preferred"]["climate.start"] == op


def test_failed_first_variant_can_be_followed_by_user_started_second_variant():
    m = manager()
    first = m.begin(
        "climate", "start", "cariad.climate.start.stored",
        user_initiated=True, now=10,
    )
    m.observe_transport(first.sequence, http_status=400)
    m.review(first.sequence, result="failed", inspected_vehicle=True, now=15)
    next_route = m.candidates("climate", "start")[0]
    assert next_route["operation"] == "cariad.climate.start.vehicle_settings"
    second = m.begin(
        "climate", "start", next_route["operation"],
        user_initiated=True, now=20,
    )
    m.observe_transport(second.sequence, http_status=200)
    m.review(second.sequence, result="worked", inspected_vehicle=True, now=30)
    assert m.snapshot()["preferred"]["climate.start"] == next_route["operation"]


def test_uncertain_command_blocks_next_variant_until_human_review():
    m = manager()
    attempt = m.begin(
        "climate", "start", "cariad.climate.start.stored",
        user_initiated=True, now=10,
    )
    m.observe_transport(attempt.sequence, http_status=None)
    m.review(attempt.sequence, result="uncertain", inspected_vehicle=False, now=20)
    with pytest.raises(DiscoveryError, match="previous action"):
        m.begin(
            "climate", "start", "cariad.climate.start.vehicle_settings",
            user_initiated=True, now=22,
        )
    m.review(attempt.sequence, result="failed", inspected_vehicle=True, now=30)
    assert m.snapshot()["active_sequence"] is None


def test_user_can_disable_control_without_disabling_status():
    m = manager()
    m.disable("climate", "start")
    with pytest.raises(DiscoveryError, match="disabled"):
        m.begin(
            "climate", "start", "cariad.climate.start.stored",
            user_initiated=True, now=10,
        )
    assert "climate.start" in m.snapshot()["disabled_controls"]
    assert m.registry.resolve(
        "climate", "status", m.context
    )["operation"] == "cariad.climate.status.batch"
    m.enable("climate", "start")
    assert not m.snapshot()["disabled_controls"]


def test_wrong_authentication_and_unreviewed_variants_cannot_be_tested():
    m = manager(family="")
    with pytest.raises(DiscoveryError, match="context-incompatible"):
        m.begin(
            "climate", "start", "cariad.climate.start.stored",
            user_initiated=True, now=10,
        )
    with pytest.raises(DiscoveryError, match="context-incompatible"):
        m.begin(
            "climate", "start", "mbb.climate.start",
            user_initiated=True, now=10,
        )


def test_cooldown_and_one_outstanding_action_are_enforced():
    m = manager(cooldown=60)
    first = m.begin(
        "climate", "start", "cariad.climate.start.stored",
        user_initiated=True, now=100,
    )
    with pytest.raises(DiscoveryError, match="previous action"):
        m.begin(
            "climate", "stop", "cariad.climate.stop",
            user_initiated=True, now=101,
        )
    m.review(first.sequence, result="failed", inspected_vehicle=True, now=110)
    with pytest.raises(DiscoveryError, match="cooldown"):
        m.begin(
            "climate", "start", "cariad.climate.start.vehicle_settings",
            user_initiated=True, now=112,
        )
    assert m.begin(
        "climate", "start", "cariad.climate.start.vehicle_settings",
        user_initiated=True, now=160,
    ).sequence == 2


def test_preferred_is_vehicle_local_and_summary_has_no_secrets():
    a = manager()
    b = manager()
    attempt = a.begin(
        "climate", "stop", "cariad.climate.stop",
        user_initiated=True, now=10,
    )
    a.review(attempt.sequence, result="worked", inspected_vehicle=True, now=12)
    assert a.snapshot()["preferred"]["climate.stop"] == "cariad.climate.stop"
    assert b.snapshot()["preferred"] == {}
    summary = json.dumps(a.snapshot()).lower()
    for sensitive in ("vin", "token", "authorization", "payload", "location"):
        assert sensitive not in summary
