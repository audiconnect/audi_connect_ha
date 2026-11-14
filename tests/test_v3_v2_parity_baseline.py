"""V2 → V3 parity source inventory, not a false live-ready acceptance test.

These tests deliberately fail on V2 additions until the parity baseline is
updated. A green baseline test means all declarations are inventoried, *not*
that V3 may be promoted: real-car and HA migration gates remain separate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from custom_components.audiconnect.v3.historical_catalog import INVENTORY
from custom_components.audiconnect.v3.attribute_contracts import attribute_contracts

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "custom_components" / "audiconnect"
BASE = json.loads((ROOT / "docs" / "V2_V3_PARITY_BASELINE.json").read_text())


def _source_keys(filename: str) -> set[str]:
    source = (SRC / filename).read_text()
    declarations = source.split("async def async_setup_entry", 1)[0]
    return set(re.findall(r'\bkey\s*=\s*["\']([^"\']+)["\']', declarations))


def _rows(platform: str) -> set[str]:
    return {row["key"] for row in BASE["entities"] if row["platform"] == platform}


@pytest.mark.parametrize(
    "platform,filename",
    [
        ("sensor", "sensor.py"),
        ("binary_sensor", "binary_sensor.py"),
        ("button", "button.py"),
        ("number", "number.py"),
    ],
)
def test_every_v2_declared_entity_is_in_matrix(platform, filename):
    assert _source_keys(filename) <= _rows(platform)
    for key in _source_keys(filename):
        matches = [
            r for r in BASE["entities"] if r["platform"] == platform and r["key"] == key
        ]
        assert len(matches) == 1
        assert matches[0]["source"] == filename


def test_all_seven_v2_switch_controls_including_generated_settings():
    text = (SRC / "switch.py").read_text()
    part = text.split("_CLIMATISATION_SETTINGS", 1)[1].split("def _setting_switch", 1)[
        0
    ]
    generated = set(
        re.findall(
            r'\(\s*"([^"]+)"\s*,\s*"[^"]+"\s*,\s*"[^"]+"\s*,\s*"[^"]+"\s*,?\s*\)',
            part,
        )
    )
    expected = generated | _source_keys("switch.py")
    assert len(expected) == 7
    assert expected <= _rows("switch")
    assert len([x for x in BASE["entities"] if x["platform"] == "switch"]) == 7


def test_full_v2_platform_and_dynamic_number_inventory():
    from custom_components.audiconnect.const import PLATFORMS

    assert set(BASE["v2_platforms"]) == {p.value for p in PLATFORMS}
    assert len(BASE["v2_platforms"]) == 9
    assert len(BASE["v3_platforms"]) == 9
    assert set(BASE["v3_platforms"]) == set(BASE["v2_platforms"])
    assert (
        BASE["ha_identity_and_presentation"]["all_nine_ha_platforms_forwarded_in_v3"]
        is True
    )
    assert (
        BASE["ha_identity_and_presentation"][
            "all_nine_ha_platforms_functional_parity_proven"
        ]
        is False
    )
    assert "charge_profile_{profile_id}_target_soc" in _rows("number")
    assert {"charge_mode"} == _rows("select")
    assert {"climatisation"} == _rows("climate")
    assert {"lock"} == _rows("lock")
    assert {"position"} == _rows("device_tracker")


def test_v2_service_ids_and_all_execute_action_options_are_captured():
    source = (SRC / "services.yaml").read_text()
    declared = set(re.findall(r"^([a-z][a-z_]+):\s*$", source, re.M))
    # Runtime probes from the experimental fixbranch are not product services.
    assert {"probe_vehicle_health", "probe_trip_data", "refresh_trip_data"}.isdisjoint(
        declared
    )
    assert declared | {"refresh_cloud_data"} == set(BASE["v2_services"]) | {
        "probe_api_paths"
    }
    section = source.split("execute_vehicle_action:", 1)[1].split(
        "start_climate_control:", 1
    )[0]
    options = set(re.findall(r"^\s{12}- ([a-z_]+)\s*$", section, re.M))
    assert len(options) == 11
    assert options == set(BASE["v2_execute_vehicle_actions"])
    assert (
        len(BASE["control_workstreams"]) == BASE["counts"]["control_workstreams"] == 19
    )
    assert all(x["status"] == "open_not_q8_proven" for x in BASE["control_workstreams"])


def test_110_raw_v2_attribute_refs_with_paths_and_jobs_are_stable():
    refs = BASE["source_references"]
    original = INVENTORY["attributes"]
    assert [x["id"] for x in refs] == [x["id"] for x in original]
    assert len(refs) == 110
    assert sum(x["has_explicit_path"] for x in refs) == 53
    assert sum(not x["has_explicit_path"] for x in refs) == 57
    assert set(BASE["api_jobs"]) == {x["id"] for x in INVENTORY["jobs"]}
    assert len(BASE["api_jobs"]) == 23


def test_native_sensor_metadata_coverage_and_recorder_repair_inventory():
    contracts = attribute_contracts()
    assert len(contracts) == BASE["counts"]["metadata_contracts"] == 72
    assert len(BASE["recorder_repair_entity_keys"]) == 13
    assert len(set(BASE["recorder_repair_entity_keys"])) == 13
    assert set(BASE["recorder_repair_entity_keys"]) <= _rows("sensor")
    assert set(BASE["recorder_repair_entity_keys"]) <= set(contracts)
    # Repairs need correct recorder migration, not fictitious state classes.
    assert all(
        "state_class" in contracts[k] for k in BASE["recorder_repair_entity_keys"]
    )


def test_parity_matrix_never_promotes_candidates_to_proven_controls():
    gate = BASE["release_gate"]
    assert gate["v2_source_inventory_complete"] is True
    assert gate["v3_static_parity_proven"] is False
    assert gate["v3_live_q8_parity_proven"] is False
    assert gate["v3_v2_v3_v2_registry_rollback_proven"] is False
    assert gate["full_release_allowed"] is False
    assert not any(row["q8_v3_verified"] for row in BASE["entities"])
    ids = [row["id"] for row in BASE["entities"]]
    assert len(ids) == len(set(ids)) == BASE["counts"]["entity_rows"] == 109


def test_operation_inventory_matches_active_catalog_exactly():
    catalog = json.loads((SRC / "v3/full_catalog.json").read_text())
    expected = [
        {
            "id": ident,
            "method": op["method"],
            "family": op["family"],
            "path": op["path"],
            "request_mode": op.get("request_mode"),
            "delivery": op["delivery"],
        }
        for ident, op in catalog["operations"].items()
    ]
    assert BASE["v3_operations"] == expected
    assert BASE["counts"]["v3_api_operations"] == len(expected)


def test_upstream_probe_service_preserved_without_v3_to_v2_dispatch():
    assert (SRC / "api_probe.py").exists()
    source = (SRC / "__init__.py").read_text()
    handler = source.split("async def _handle_probe_api_paths", 1)[1].split(
        "async def _handle_set_local_dealer", 1
    )[0]
    assert "isinstance(account, V3Engine)" in handler
    assert "raise HomeAssistantError" in handler
    assert "account.connection.probe_read_only_api" in handler
