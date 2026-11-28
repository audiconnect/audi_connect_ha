"""Test that experimental V3 HA modules are importable on pinned HA build.

Plain source checks and hassfest do not import the websocket dashboard, so
this catches misspelled imports and unsupported runtime APIs before release.
"""

from __future__ import annotations

import ast
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pathlib import Path


def test_all_clean_v3_modules_import_under_pinned_homeassistant():
    for module in (
        "auth",
        "transport",
        "vehicle",
        "engine",
        "entities",
        "coordinator_clean",
        "profile_store",
        "response_preview",
        "registry_lifecycle",
        "dashboard",
        "vehicle_dashboard",
        "ha_platforms",
        "parking",
        "service_commands",
    ):
        loaded = importlib.import_module(f"custom_components.audiconnect.v3.{module}")
        assert loaded is not None


def test_v3_dashboard_exists_in_package_not_only_in_repo_documentation():
    path = Path(__file__).resolve().parents[1] / (
        "custom_components/audiconnect/v3/frontend/panel.js"
    )
    script = path.read_text(encoding="utf-8")
    assert "customElements.define(" in script
    assert "audiconnect-v3-panel" in script
    for action in ("add_route", "test", "select", "disable", "review"):
        assert action in script


def test_v3_dashboard_cache_key_follows_packaged_script(tmp_path):
    from custom_components.audiconnect.v3.dashboard import _panel_module_url

    script = tmp_path / "panel.js"
    script.write_text("first", encoding="utf-8")
    first = _panel_module_url(tmp_path)
    assert first.startswith("/audiconnect_v3/panel.js?v=")
    assert _panel_module_url(tmp_path) == first

    script.write_text("second", encoding="utf-8")
    assert _panel_module_url(tmp_path) != first


def test_required_v3_platforms_forwarded_in_v3():
    init = (
        Path(__file__).resolve().parents[1]
        / "custom_components/audiconnect/__init__.py"
    ).read_text()
    normalized = ast.unparse(ast.parse(init))
    assert "loaded_platforms=list(PLATFORMS)" in normalized
    platforms = (
        Path(__file__).resolve().parents[1]
        / "custom_components/audiconnect/v3/ha_platforms.py"
    ).read_text()
    for domain in (
        "climate",
        "sensor",
        "binary_sensor",
        "button",
        "switch",
        "lock",
        "number",
        "select",
        "device_tracker",
    ):
        assert f'platform == "{domain}"' in platforms or f'"{domain}"' in platforms
    assert "AudiDataUpdateCoordinator.from_entry" in init
    assert "coordinator = V3CleanCoordinator(hass, engine, config_entry)" in init
    assert "account=account, coordinator=coordinator, v3=engine" in normalized
    assert "auth=V3Auth(hass, config_entry, shared_account=account)" in init


@pytest.mark.parametrize("portal_enabled", [True, False])
@pytest.mark.parametrize("platform_failure", [True, False])
@pytest.mark.parametrize("panel_failure", [True, False])
async def test_v3_setup_keeps_optional_channel_only_after_valid_inventory(
    monkeypatch, portal_enabled, platform_failure, panel_failure
):
    from homeassistant.exceptions import ConfigEntryNotReady

    from custom_components import audiconnect as integration
    from custom_components.audiconnect.v3 import auth, dashboard, registry_lifecycle

    first_failure = ConfigEntryNotReady("native status unavailable")
    first_failure.__cause__ = integration.NativeStatusUnavailable("native poll failed")
    coordinator = SimpleNamespace(
        async_config_entry_first_refresh=AsyncMock(side_effect=first_failure),
        last_update_success=False,
    )
    portal = SimpleNamespace(
        data_act_client=object() if portal_enabled else None,
        async_close_data_act=AsyncMock(),
    )
    engine = SimpleNamespace(
        auth=portal,
        status=SimpleNamespace(async_stop_data_act=AsyncMock()),
        vehicles={"test": SimpleNamespace(inventory_present=True)},
    )
    entry = SimpleNamespace(
        entry_id="test",
        data={integration.CONF_REFRESH_TOKEN: "test-token"},
        options={integration.V3_RUNTIME_OPTION: integration.V3_ENABLED},
        async_on_unload=Mock(),
        add_update_listener=Mock(),
    )
    forward = AsyncMock(
        side_effect=RuntimeError("platform setup failed") if platform_failure else None
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_forward_entry_setups=forward),
        async_add_executor_job=AsyncMock(return_value=object()),
    )
    setup_panel = AsyncMock(
        side_effect=RuntimeError("panel unavailable") if panel_failure else None
    )
    monkeypatch.setattr(dashboard, "async_setup_vehicle_dashboard", setup_panel)
    monkeypatch.setattr(integration, "AudiAccount", Mock())
    monkeypatch.setattr(integration, "V3Engine", Mock(return_value=engine))
    monkeypatch.setattr(
        integration, "V3CleanCoordinator", Mock(return_value=coordinator)
    )
    monkeypatch.setattr(auth, "V3Auth", Mock(return_value=portal))
    monkeypatch.setattr(integration, "_async_cleanup_orphaned_devices", Mock())
    monkeypatch.setattr(integration, "_async_register_services", Mock())
    monkeypatch.setattr(
        registry_lifecycle, "async_apply_v3_entity_visibility", AsyncMock()
    )

    if not portal_enabled:
        with pytest.raises(ConfigEntryNotReady):
            await integration.async_setup_entry(hass, entry)
        forward.assert_not_awaited()
    elif platform_failure:
        with pytest.raises(RuntimeError, match="platform setup failed"):
            await integration.async_setup_entry(hass, entry)
        forward.assert_awaited_once()
    else:
        assert await integration.async_setup_entry(hass, entry)
        forward.assert_awaited_once()
        assert not coordinator.last_update_success
        setup_panel.assert_awaited_once_with(hass)

    if not portal_enabled or platform_failure:
        setup_panel.assert_not_awaited()
        engine.status.async_stop_data_act.assert_awaited_once()
        portal.async_close_data_act.assert_awaited_once()
    else:
        portal.async_close_data_act.assert_not_awaited()


@pytest.mark.parametrize("other_change", [None, "options", "data", "v2"])
async def test_local_service_only_update_preserves_v3_runtime(other_change):
    from custom_components import audiconnect as integration

    coordinator = SimpleNamespace(async_update_listeners=Mock())
    original = {integration.V3_RUNTIME_OPTION: integration.V3_ENABLED}
    data = {"region": "DE"}
    runtime = integration.AudiRuntimeData(
        account=None,
        coordinator=coordinator,
        v3=None if other_change == "v2" else object(),
        options_snapshot=original,
        data_snapshot=dict(data),
    )
    options = {**original, "local_dealers": {"test": {"dealer_name": "New dealer"}}}
    if other_change == "options":
        options["scan_interval"] = 30
    if other_change == "data":
        data["region"] = "FR"
    entry = SimpleNamespace(
        entry_id="test", data=data, options=options, runtime_data=runtime
    )
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_reload=AsyncMock()))
    await integration._async_update_listener(hass, entry)
    if other_change is None:
        hass.config_entries.async_reload.assert_not_awaited()
        coordinator.async_update_listeners.assert_called_once_with()
        assert runtime.options_snapshot == options
        await integration._async_update_listener(hass, entry)
        coordinator.async_update_listeners.assert_called_once_with()
    else:
        hass.config_entries.async_reload.assert_awaited_once_with("test")
        coordinator.async_update_listeners.assert_not_called()


async def test_panel_resource_registration_can_retry_without_duplicate_static_path(
    monkeypatch,
):
    from custom_components.audiconnect.v3 import dashboard

    hass = SimpleNamespace(
        data={}, http=SimpleNamespace(async_register_static_paths=AsyncMock())
    )
    register = Mock(side_effect=RuntimeError("handler registration unavailable"))
    monkeypatch.setattr(dashboard.websocket_api, "async_register_command", register)
    with pytest.raises(RuntimeError):
        await dashboard._async_setup_panel_resources(hass)
    hass.http.async_register_static_paths.assert_not_awaited()
    register.side_effect = None
    await dashboard._async_setup_panel_resources(hass)
    calls = register.call_count
    await dashboard._async_setup_panel_resources(hass)
    assert register.call_count == calls
    hass.http.async_register_static_paths.assert_awaited_once()


async def test_single_application_registration_and_multi_account_unload(monkeypatch):
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.audiconnect.v3 import dashboard

    engine = Mock(spec=dashboard.V3Engine)
    entries = [
        SimpleNamespace(
            entry_id=ident,
            state=ConfigEntryState.LOADED,
            options={"runtime_version": "v3_climate"},
            runtime_data=SimpleNamespace(v3=engine),
        )
        for ident in ("first", "second")
    ]
    hass = SimpleNamespace(
        data={},
        config_entries=SimpleNamespace(async_entries=lambda domain: entries),
        async_add_executor_job=AsyncMock(return_value="/audiconnect_v3/script.js"),
    )
    monkeypatch.setattr(dashboard, "_async_setup_panel_resources", AsyncMock())
    register = AsyncMock()
    remove = Mock()
    monkeypatch.setattr(dashboard.panel_custom, "async_register_panel", register)
    monkeypatch.setattr(dashboard.frontend, "async_remove_panel", remove)
    await dashboard.async_setup_vehicle_dashboard(hass)
    await dashboard.async_setup_vehicle_dashboard(hass)
    register.assert_awaited_once()
    assert register.call_args.kwargs["sidebar_title"] == "Audi Connect"
    await dashboard.async_remove_vehicle_dashboard(hass, "first")
    remove.assert_not_called()
    entries[0].options["v3_vehicle_dashboard"] = False
    await dashboard.async_remove_vehicle_dashboard(hass, "second")
    remove.assert_called_once_with(hass, "audiconnect-vehicles", warn_if_unknown=False)
