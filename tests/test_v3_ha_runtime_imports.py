"""Test that experimental V3 HA modules are importable on pinned HA build.

Plain source checks and hassfest do not import the websocket dashboard, so
this catches misspelled imports and unsupported runtime APIs before release.
"""

from __future__ import annotations

import ast
import importlib
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
