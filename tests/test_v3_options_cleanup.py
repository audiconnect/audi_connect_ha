"""Legacy V2 and experimental V3 controls must not drift into each other's UI."""

from pathlib import Path
from types import SimpleNamespace
from custom_components.audiconnect.config_flow import OptionsFlowHandler

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "audiconnect"


def test_v2_settings_exclude_experimental_and_bodyless_options():
    flow = OptionsFlowHandler()
    flow.handler = "test-audi-entry"
    flow._test_entry = SimpleNamespace(data={}, options={})
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _id: flow._test_entry
        )
    )
    fields = [k.schema for k in flow._options_schema({"runtime_version": "v2"}).schema]
    for name in ("climate_quick_start", "experimental_commands", "edit_local_dealer"):
        assert name not in fields


def test_v3_development_mode_has_correct_user_label_not_climate_only():
    import json

    data = json.loads((ROOT / "strings.json").read_text())
    assert (
        "V3 — Experimental"
        in data["options"]["step"]["init"]["data_description"]["runtime_version"]
    )
    assert "not description.experimental" in (ROOT / "button.py").read_text()
    assert (
        "entities.append(AudiClimateQuickSwitch" not in (ROOT / "switch.py").read_text()
    )
