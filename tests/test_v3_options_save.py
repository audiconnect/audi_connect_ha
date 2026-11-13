"""A runtime mode selection must be saved without losing V2 settings."""

import pytest
from types import SimpleNamespace

from custom_components.audiconnect.config_flow import OptionsFlowHandler


@pytest.mark.asyncio
async def test_switch_v2_to_v3_saves_mode_and_preserves_legacy_options():
    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    flow._test_entry = SimpleNamespace(
        data={"scan_interval": 15},
        options={
            "runtime_version": "v2",
            "scan_interval": 15,
            "climate_quick_start": True,
            "experimental_commands": True,
            "local_dealers": {"EXAMPLE": {"name": "Dealer"}},
        },
    )
    result = await flow.async_step_init(
        {
            "runtime_version": "v3_climate",
            "scan_interval": 15,
            "scan_initial": True,
        }
    )
    assert result["type"] == "create_entry"
    saved = result["data"]
    assert saved["runtime_version"] == "v3_climate"
    assert saved["v3_development_workbench"] is False
    assert saved["climate_quick_start"] is True
    assert saved["experimental_commands"] is True
    assert "local_dealers" in saved


@pytest.mark.asyncio
async def test_switch_back_to_v2_preserves_legacy_configuration():
    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    flow._test_entry = SimpleNamespace(
        data={"scan_interval": 15},
        options={
            "runtime_version": "v3_climate",
            "v3_development_workbench": True,
            "climate_quick_start": True,
            "scan_interval": 15,
        },
    )
    result = await flow.async_step_init(
        {
            "runtime_version": "v2",
            "scan_interval": 15,
        }
    )
    assert result["type"] == "create_entry"
    saved = result["data"]
    assert saved["runtime_version"] == "v2"
    assert saved["v3_development_workbench"] is False
    assert saved["climate_quick_start"] is True


def test_form_can_render_v3_workbench_option_when_mode_is_v3():
    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    flow._test_entry = SimpleNamespace(
        data={"scan_interval": 15},
        options={"runtime_version": "v2"},
    )
    schema = flow._options_schema(
        {
            "runtime_version": "v3_climate",
            "scan_interval": 15,
        }
    )
    fields = [key.schema for key in schema.schema]
    assert "v3_development_workbench" in fields
    assert "climate_quick_start" not in fields
    assert "experimental_commands" not in fields
    assert "edit_local_dealer" in fields


@pytest.mark.asyncio
async def test_user_discovery_never_dispatches_without_exact_single_action_consent(
    monkeypatch,
):
    from unittest.mock import AsyncMock
    from custom_components.audiconnect.v3 import read_discovery

    flow = OptionsFlowHandler()
    car = SimpleNamespace(vin="WAUZZZ4M0MD123456", name="Synthetic test car")
    profile = SimpleNamespace(
        discovery=SimpleNamespace(_active=None), last_command=None
    )
    engine = SimpleNamespace(
        approved_control_discovery=AsyncMock(return_value={"sequence": 1})
    )
    flow._discovery_context = lambda: (engine, car, profile)
    flow._discovery_action = "climate.start"
    route = "cariad.climate.start.stored"
    original = ("Start cabin climate", "climate", "start", route, "non_spin")
    flow._discovery_candidate = original
    monkeypatch.setattr(
        read_discovery,
        "user_test_candidates",
        lambda *args: {"climate.start": original},
    )
    flow.async_step_discovery = AsyncMock(return_value={"step_id": "discovery"})
    flow.async_step_discovery_review = AsyncMock(return_value={"step_id": "review"})
    result = await flow.async_step_discovery_consent({"accept": False})
    assert result["step_id"] == "discovery"
    engine.approved_control_discovery.assert_not_awaited()
    flow._discovery_candidate = original
    monkeypatch.setattr(
        read_discovery,
        "user_test_candidates",
        lambda *args: {
            "climate.start": (
                "Start cabin climate",
                "climate",
                "start",
                "another.route",
                "non_spin",
            )
        },
    )
    result = await flow.async_step_discovery_consent({"accept": True})
    assert result["step_id"] == "discovery"
    engine.approved_control_discovery.assert_not_awaited()
    flow._discovery_candidate = original
    monkeypatch.setattr(
        read_discovery,
        "user_test_candidates",
        lambda *args: {"climate.start": original},
    )
    result = await flow.async_step_discovery_consent({"accept": True})
    assert result["step_id"] == "review"
    engine.approved_control_discovery.assert_awaited_once_with(
        car.vin, "start", route, approval="non_spin", capability="climate", guided=True
    )
    assert flow._discovery_candidate is None
    await flow.async_step_discovery_consent({"accept": True})
    assert engine.approved_control_discovery.await_count == 1


@pytest.mark.asyncio
async def test_optional_data_act_credentials_retained_only_for_same_email():
    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    flow._test_entry = SimpleNamespace(
        data={"scan_interval": 15},
        options={
            "runtime_version": "v3_climate",
            "v3_data_act_enabled": True,
            "v3_data_act_email": "example@invalid.test",
            "v3_data_act_password": "synthetic-password",
        },
    )
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    result = await flow.async_step_init(
        {"v3_data_act_enabled": True, "v3_data_act_password": ""}
    )
    assert result["data"]["v3_data_act_password"] == "synthetic-password"
    result = await flow.async_step_init(
        {"v3_data_act_enabled": True, "v3_data_act_email": "other@invalid.test"}
    )
    assert not result["data"]["v3_data_act_password"]
    result = await flow.async_step_init({"v3_data_act_enabled": False})
    assert not result["data"]["v3_data_act_enabled"]
    assert "v3_data_act_password" not in result["data"]
    assert "v3_data_act_email" not in result["data"]
