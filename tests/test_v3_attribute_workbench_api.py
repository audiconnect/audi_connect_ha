"""Admin WebSocket capability routing is independent of the climate pilot."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "audiconnect" / "v3"


def test_read_only_route_api_never_exposes_unreviewed_mutations():
    server = (ROOT / "dashboard.py").read_text()
    for command in (
        "attribute_routes",
        "attribute_test",
        "attribute_add",
        "attribute_save",
        "attribute_activate",
        "attribute_disable",
    ):
        assert f'"audiconnect/v3/{command}"' in server
    engine = (ROOT / "engine.py").read_text()
    assert "async def test_attribute_route(" in engine
    assert 'self.transport.request(family, "GET", path)' in engine
    assert "async def activate_attribute_route(" in engine
    assert "async def disable_attribute_route(" in engine


def test_workbench_requires_loaded_opted_in_runtime():
    from types import SimpleNamespace as NS
    from unittest.mock import Mock

    import pytest
    from homeassistant.config_entries import ConfigEntryState
    from custom_components.audiconnect.v3.dashboard import _workbench_engine
    from custom_components.audiconnect.v3.engine import V3Engine

    engine = Mock(spec=V3Engine)
    entry = NS(
        domain="audiconnect",
        options={"runtime_version": "v3_climate", "v3_development_workbench": True},
        state=ConfigEntryState.LOADED,
        runtime_data=NS(v3=engine),
    )
    assert _workbench_engine(entry) is engine
    entry.state = ConfigEntryState.NOT_LOADED
    with pytest.raises(ValueError, match="not loaded"):
        _workbench_engine(entry)
    entry.state = ConfigEntryState.LOADED
    entry.options["v3_development_workbench"] = False
    with pytest.raises(ValueError, match="not enabled"):
        _workbench_engine(entry)
    entry.options["v3_development_workbench"] = True
    entry.options["runtime_version"] = "v2"
    with pytest.raises(ValueError, match="not enabled"):
        _workbench_engine(entry)
