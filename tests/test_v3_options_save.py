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
    result = await flow.async_step_general(
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
    assert saved["v3_charging_stop_retry"] is False
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
            "v3_charging_stop_retry": True,
            "climate_quick_start": True,
            "scan_interval": 15,
        },
    )
    result = await flow.async_step_general(
        {
            "runtime_version": "v2",
            "scan_interval": 15,
        }
    )
    assert result["type"] == "create_entry"
    saved = result["data"]
    assert saved["runtime_version"] == "v2"
    assert saved["v3_charging_stop_retry"] is False
    assert saved["v3_development_workbench"] is False
    assert saved["climate_quick_start"] is True


@pytest.mark.asyncio
async def test_native_v3_menu_and_general_fields():
    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    flow._test_entry = SimpleNamespace(
        data={"scan_interval": 15}, options={"runtime_version": "v3_climate"}
    )
    menu = await flow.async_step_init()
    assert menu["type"] == "menu"
    assert menu["menu_options"] == [
        "general",
        "discovery_vehicle",
        "data_sources",
        "dealer_vehicle",
        "advanced",
    ]
    result = await flow.async_step_general()
    assert result["step_id"] == "general"
    assert {key.schema for key in result["data_schema"].schema} == {
        "runtime_version",
        "scan_interval",
        "filter_vins",
    }
    assert (await flow.async_step_data_sources())["menu_options"] == [
        "data_act",
        "reverse_geocoding",
    ]
    assert (await flow.async_step_advanced())["menu_options"] == [
        "stop_recovery",
        "workbench",
    ]
    flow._test_entry.options["runtime_version"] = "v2"
    result = await flow.async_step_init()
    assert result["type"] == "form"
    assert "scan_initial" in {key.schema for key in result["data_schema"].schema}
    assert (await flow.async_step_advanced())["step_id"] == "general"


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
    original = {
        "label": "Start cabin climate",
        "instructions": "Check climate starts.",
        "capability": "climate",
        "action": "start",
        "operation": route,
        "approval_group": "non_spin",
        "parameter_schema": {},
    }
    flow._discovery_candidate = original
    monkeypatch.setattr(
        read_discovery,
        "user_test_candidates",
        lambda *args, **kwargs: {"climate.start": original},
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
        lambda *args, **kwargs: {
            "climate.start": {**original, "operation": "another.route"}
        },
    )
    result = await flow.async_step_discovery_consent({"accept": True})
    assert result["step_id"] == "discovery"
    engine.approved_control_discovery.assert_not_awaited()
    flow._discovery_candidate = original
    monkeypatch.setattr(
        read_discovery,
        "user_test_candidates",
        lambda *args, **kwargs: {"climate.start": original},
    )
    result = await flow.async_step_discovery_consent({"accept": True})
    assert result["step_id"] == "review"
    engine.approved_control_discovery.assert_awaited_once_with(
        car.vin,
        "start",
        route,
        approval="non_spin",
        capability="climate",
        params=None,
        guided=True,
        expert=True,
    )
    assert flow._discovery_candidate is None
    await flow.async_step_discovery_consent({"accept": True})
    assert engine.approved_control_discovery.await_count == 1


@pytest.mark.asyncio
async def test_data_act_credentials_change_only_after_successful_source_auth():
    from unittest.mock import AsyncMock
    from custom_components.audiconnect.v3.data_act import DataActAuthorizationRequired

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
    result = await flow.async_step_general({"scan_interval": 20})
    assert result["data"]["v3_data_act_password"] == "synthetic-password"
    assert result["data"]["scan_interval"] == 20
    result = await flow.async_step_general({"v3_data_act_password": "bypass"})
    assert result["data"]["v3_data_act_password"] == "synthetic-password"
    result = await flow.async_step_data_act()
    assert result["step_id"] == "data_act"
    assert {key.schema for key in result["data_schema"].schema} == {"action"}
    result = await flow.async_step_data_act({"action": "connect"})
    assert result["step_id"] == "data_act_credentials"
    assert {key.schema for key in result["data_schema"].schema} == {"email", "password"}
    flow._validate_data_act_credentials = AsyncMock(
        side_effect=DataActAuthorizationRequired("rejected")
    )
    result = await flow.async_step_data_act_credentials(
        {"email": "other@invalid.test", "password": "wrong"}
    )
    assert result["errors"]["base"] == "data_act_authorization_required"
    assert flow.config_entry.options["v3_data_act_password"] == "synthetic-password"
    flow._validate_data_act_credentials = AsyncMock()
    result = await flow.async_step_data_act_credentials(
        {"email": "other@invalid.test", "password": "new-password"}
    )
    assert result["data"]["v3_data_act_email"] == "other@invalid.test"
    assert result["data"]["v3_data_act_password"] == "new-password"
    result = await flow.async_step_data_act({"action": "disconnect"})
    assert not result["data"]["v3_data_act_enabled"]
    assert "v3_data_act_password" not in result["data"]
    assert "v3_data_act_email" not in result["data"]


@pytest.mark.parametrize(
    "language", ["en", "nl", "de", "fr", "fi", "nb", "pt", "pt-BR"]
)
def test_v3_options_have_localized_labels_and_descriptions(language):
    import json
    from pathlib import Path

    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    flow._test_entry = SimpleNamespace(
        data={}, options={"runtime_version": "v3_climate"}
    )
    fields = {
        key.schema for key in flow._options_schema(flow._test_entry.options).schema
    }
    path = (
        Path(__file__).resolve().parents[1]
        / "custom_components/audiconnect/translations"
        / f"{language}.json"
    )
    form = json.loads(path.read_text())["options"]["step"]["general"]
    assert fields <= form["data"].keys()
    assert fields <= form["data_description"].keys()
    steps = json.loads(path.read_text())["options"]["step"]
    for menu in ("init", "data_sources", "advanced"):
        assert steps[menu]["menu_options"]
        assert set(steps[menu]["menu_options"]) <= set(steps)
    for step in (
        "stop_recovery",
        "stop_recovery_settings",
        "workbench",
        "reverse_geocoding",
        "geocoding_endpoint",
    ):
        assert steps[step]["data"].keys() == steps[step]["data_description"].keys()
    translations = json.loads(path.read_text())
    action = translations["options"]["step"]["data_act"]
    assert action["description"] and action["data"]["action"]
    assert set(translations["selector"]["data_act_action"]["options"]) == {
        "keep",
        "connect",
        "disconnect",
    }


@pytest.mark.asyncio
async def test_v3_save_preserves_hidden_v2_startup_preference():
    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    flow._test_entry = SimpleNamespace(
        data={"scan_interval": 15},
        options={"runtime_version": "v3_climate", "scan_initial": False},
    )
    result = await flow.async_step_general({"scan_interval": 20})
    assert result["data"]["scan_initial"] is False
    assert result["data"]["scan_interval"] == 20


@pytest.mark.asyncio
async def test_data_act_wizard_reuses_runtime_status_without_authentication():
    from unittest.mock import AsyncMock

    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    report = {"connection_state": "connected"}
    status = SimpleNamespace(data_act_poll_status=lambda: report)
    options = {
        "runtime_version": "v3_climate",
        "v3_data_act_enabled": True,
        "v3_data_act_email": "example@invalid.test",
        "v3_data_act_password": "synthetic-password",
    }
    flow._test_entry = SimpleNamespace(
        data={},
        options=options,
        runtime_data=SimpleNamespace(v3=SimpleNamespace(status=status)),
    )
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    flow._validate_data_act_credentials = AsyncMock()
    result = await flow.async_step_init()
    assert result["description_placeholders"]["data_act_status"] == (
        "EU Data Act: Connected"
    )
    result = await flow.async_step_data_act()
    assert result["description_placeholders"]["data_act_status"] == (
        "EU Data Act: Connected"
    )
    result = await flow.async_step_data_act({"action": "keep"})
    assert result["data"] == options
    flow._validate_data_act_credentials.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_is_explicit_and_does_not_dispatch_on_save():
    from unittest.mock import AsyncMock

    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    flow._test_entry = SimpleNamespace(
        data={"scan_interval": 15},
        options={"runtime_version": "v3_climate", "v3_charging_stop_retry": True},
        runtime_data=SimpleNamespace(v3=SimpleNamespace()),
    )
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    flow.async_step_discovery_vehicle = AsyncMock(return_value={"step_id": "discovery"})
    result = await flow.async_step_init()
    assert result["type"] == "menu"
    result = await flow.async_step_general(
        {"scan_interval": 20, "run_vehicle_discovery": True, "manage_data_act": True}
    )
    assert result["type"] == "create_entry"
    assert result["data"]["scan_interval"] == 20
    assert result["data"]["v3_charging_stop_retry"] is True
    assert "run_vehicle_discovery" not in result["data"]
    assert "manage_data_act" not in result["data"]
    flow.async_step_discovery_vehicle.assert_not_awaited()
    result = await flow.async_step_discovery_vehicle()
    assert result["step_id"] == "discovery"
    flow.async_step_discovery_vehicle.assert_awaited_once()


@pytest.mark.asyncio
async def test_native_selective_discovery_accepts_typed_temperature(monkeypatch):
    from unittest.mock import AsyncMock

    from custom_components.audiconnect.v3 import read_discovery

    flow = OptionsFlowHandler()
    car = SimpleNamespace(vin="WAUZZZ4M0MD123456", name="Synthetic test car")
    profile = SimpleNamespace(
        discovery=SimpleNamespace(_active=None), last_command=None
    )
    candidate = {
        "label": "Start climate with temperature",
        "instructions": "Stop climate first.",
        "capability": "climate",
        "action": "start_with_settings",
        "operation": "cariad.climate.start.vehicle_settings",
        "approval_group": "non_spin",
        "parameter_schema": {
            "temp_c": {"type": "number", "minimum": 15, "maximum": 30, "required": True}
        },
    }
    engine = SimpleNamespace(
        approved_control_discovery=AsyncMock(return_value={"sequence": 1}),
        discovery_progress=lambda *_: {
            "controls_physically_verified": 0,
            "controls_catalog_applicable": 1,
        },
    )
    flow._discovery_context = lambda: (engine, car, profile)
    monkeypatch.setattr(
        read_discovery,
        "user_test_candidates",
        lambda *args, **kwargs: {"climate.start_with_settings": candidate},
    )
    flow.async_step_discovery_review = AsyncMock(return_value={"step_id": "review"})
    result = await flow.async_step_discovery({"action": "climate.start_with_settings"})
    assert result["step_id"] == "discovery_consent"
    assert {key.schema for key in result["data_schema"].schema} == {"accept", "temp_c"}
    assert result["description_placeholders"]["instructions"] == "Stop climate first."
    engine.approved_control_discovery.assert_not_awaited()
    result = await flow.async_step_discovery_consent({"accept": "yes"})
    assert result["errors"]["base"] == "discovery_test_failed"
    engine.approved_control_discovery.assert_not_awaited()
    result = await flow.async_step_discovery_consent({"accept": "yes", "temp_c": 22})
    assert result["step_id"] == "review"
    engine.approved_control_discovery.assert_awaited_once_with(
        car.vin,
        "start_with_settings",
        candidate["operation"],
        approval="non_spin",
        capability="climate",
        params={"temp_c": 22},
        guided=True,
        expert=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_charging_stop_retry_requires_explicit_v3_option(enabled):
    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    flow._test_entry = SimpleNamespace(
        data={"scan_interval": 15},
        options={
            "runtime_version": "v3_climate",
            "v3_charging_stop_retry": not enabled,
        },
    )
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    result = await flow.async_step_stop_recovery()
    assert {key.schema for key in result["data_schema"].schema} == {
        "v3_charging_stop_retry"
    }
    result = await flow.async_step_stop_recovery({"v3_charging_stop_retry": enabled})
    if enabled:
        assert result["step_id"] == "stop_recovery_settings"
        assert flow._test_entry.options["v3_charging_stop_retry"] is False
        result = await flow.async_step_stop_recovery_settings(
            {"v3_stop_extra_retries": 0}
        )
        assert result["data"]["v3_stop_extra_retries"] == 0
    assert result["data"]["v3_charging_stop_retry"] is enabled


@pytest.mark.asyncio
async def test_reverse_geocoding_is_explicit_and_v3_only():
    from custom_components.audiconnect.v3.parking import (
        GEOCODING_ENDPOINT,
        REVERSE_GEOCODING,
    )

    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    flow._test_entry = SimpleNamespace(
        data={}, options={"runtime_version": "v3_climate"}
    )
    result = await flow.async_step_reverse_geocoding()
    schema = result["data_schema"].schema
    assert {key.schema for key in schema} == {REVERSE_GEOCODING}
    assert next(iter(schema)).default() is False
    result = await flow.async_step_reverse_geocoding({REVERSE_GEOCODING: True})
    assert result["step_id"] == "geocoding_endpoint"
    assert REVERSE_GEOCODING not in flow._test_entry.options
    result = await flow.async_step_geocoding_endpoint({GEOCODING_ENDPOINT: ""})
    assert result["errors"][GEOCODING_ENDPOINT] == "invalid_geocoding_endpoint"
    endpoint = "https://geocoder.example.invalid/reverse"
    result = await flow.async_step_geocoding_endpoint({GEOCODING_ENDPOINT: endpoint})
    assert result["data"][REVERSE_GEOCODING] is True
    flow._test_entry.options = result["data"]
    result = await flow.async_step_reverse_geocoding({REVERSE_GEOCODING: False})
    assert result["data"][REVERSE_GEOCODING] is False
    assert result["data"][GEOCODING_ENDPOINT] == endpoint
    result = await flow.async_step_general({"runtime_version": "v2"})
    assert result["data"][REVERSE_GEOCODING] is False
    flow._test_entry.options = result["data"]
    assert (await flow.async_step_reverse_geocoding())["step_id"] == "general"


@pytest.mark.asyncio
async def test_advanced_forms_preserve_saved_settings_and_reject_invalid_numbers():
    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    original = {
        "runtime_version": "v3_climate",
        "scan_interval": 25,
        "v3_charging_stop_retry": True,
        "v3_stop_extra_retries": 0,
        "v3_stop_confirmation_seconds": 120,
        "v3_stop_repoll_seconds": 60,
        "v3_stop_verification_seconds": 90,
        "v3_stop_final_notification": False,
        "v3_data_act_enabled": True,
        "local_dealers": {"EXAMPLE": {"name": "Dealer"}},
    }
    flow._test_entry = SimpleNamespace(data={}, options=original)
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    result = await flow.async_step_workbench({"v3_development_workbench": True})
    assert result["data"] == {**original, "v3_development_workbench": True}
    result = await flow.async_step_stop_recovery({"v3_charging_stop_retry": False})
    assert result["data"] == {**original, "v3_charging_stop_retry": False}
    flow._test_entry.options = result["data"]
    result = await flow.async_step_stop_recovery({"v3_charging_stop_retry": True})
    fields = {key.schema: key.default() for key in result["data_schema"].schema}
    assert fields["v3_stop_extra_retries"] == 0
    assert fields["v3_stop_confirmation_seconds"] == 120
    result = await flow.async_step_stop_recovery_settings(
        {"v3_stop_extra_retries": 0.5}
    )
    assert result["errors"]["base"] == "invalid_stop_recovery_settings"
    assert flow._test_entry.options["v3_charging_stop_retry"] is False
    result = await flow.async_step_stop_recovery_settings(fields)
    assert result["data"] == original


def test_stop_recovery_option_bounds_and_migration():
    from custom_components.audiconnect.const import stop_recovery_options

    defaults = stop_recovery_options({"v3_charging_stop_retry": True})
    assert defaults["v3_stop_extra_retries"] == 1
    assert defaults["v3_stop_confirmation_seconds"] == 300
    assert defaults["v3_stop_repoll_seconds"] == 30
    assert defaults["v3_stop_verification_seconds"] == 300
    assert defaults["v3_stop_final_notification"] is True
    selected = {
        "v3_stop_extra_retries": 0,
        "v3_stop_confirmation_seconds": 120,
        "v3_stop_repoll_seconds": 60,
        "v3_stop_verification_seconds": 90,
        "v3_stop_final_notification": False,
    }
    assert stop_recovery_options(selected) == selected
    assert stop_recovery_options({"v3_stop_extra_retries": 99}) == defaults
