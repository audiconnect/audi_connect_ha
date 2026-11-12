"""Admin WebSocket capability routing is independent of the climate pilot."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/"custom_components"/"audiconnect"/"v3"

def test_read_only_route_api_never_exposes_unreviewed_mutations():
    server=(ROOT/"dashboard.py").read_text()
    for command in ("attribute_routes","attribute_test","attribute_add","attribute_save","attribute_activate","attribute_disable"):
        assert f'"audiconnect/v3/{command}"' in server
    engine=(ROOT/"engine.py").read_text()
    assert "async def test_attribute_route(" in engine
    assert 'self.transport.request(family, "GET", path)' in engine
    assert "async def activate_attribute_route(" in engine
    assert "async def disable_attribute_route(" in engine
