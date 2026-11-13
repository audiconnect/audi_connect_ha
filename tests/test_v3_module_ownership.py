"""Every V3 production artifact has an owner; enforce the core import boundary."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "custom_components/audiconnect/v3"


def test_production_paths_have_exactly_one_owner():
    config = json.loads((ROOT / "governance/OWNERSHIP.json").read_text())
    paths = [p for group in config["owners"].values() for p in group["paths"]]
    paths += config["migration_exclusions"]
    actual = {
        p.relative_to(V3).as_posix()
        for p in V3.rglob("*")
        if p.is_file() and p.suffix in (".py", ".json", ".js")
    }
    assert len(paths) == len(set(paths))
    assert set(paths) == actual


def test_domain_owners_do_not_import_composition_or_ha_projection():
    config = json.loads((ROOT / "governance/OWNERSHIP.json").read_text())
    forbidden = {
        "engine",
        "runtime",
        "dashboard",
        "ha_platforms",
        "entities",
        "coordinator_clean",
    }
    for owner in ("status", "command", "catalog", "profiles", "vehicle", "api"):
        for file in config["owners"][owner]["paths"]:
            if not file.endswith(".py"):
                continue
            for node in ast.walk(ast.parse((V3 / file).read_text())):
                if isinstance(node, ast.ImportFrom):
                    if node.level == 1:
                        names = (
                            [node.module]
                            if node.module
                            else [x.name for x in node.names]
                        )
                        assert not forbidden.intersection(names), (file, names)
                    if node.level == 0 and node.module:
                        assert not any(
                            node.module.endswith(".v3." + name) for name in forbidden
                        ), file


def test_canonical_policy_link_resolves():
    import re

    config = json.loads((ROOT / "governance/OWNERSHIP.json").read_text())
    path, anchor = config["change_policy"]["canonical_policy"].split("#", 1)
    headings = {
        re.sub(r"[^a-z0-9 -]", "", line.lstrip("# ").lower()).replace(" ", "-")
        for line in (ROOT / path).read_text().splitlines()
        if line.startswith("#")
    }
    assert anchor in headings


def test_diagnostics_never_import_native_entity_classes():
    """Reporting consumes the product contract, not concrete HA projections."""
    config = json.loads((ROOT / "governance/OWNERSHIP.json").read_text())
    for file in config["owners"]["diagnostics"]["paths"]:
        if not file.endswith(".py"):
            continue
        for node in ast.walk(ast.parse((V3 / file).read_text())):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in ("entities", "ha_platforms"), file


def test_engine_does_not_reach_into_status_or_command_private_state():
    tree = ast.parse((V3 / "engine.py").read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr in ("status", "commands")
        ):
            assert not node.attr.startswith("_"), node.attr


def test_only_auth_owner_reads_historical_credential_slots():
    slots = {"_spin", "_api_level", "_bearer_token_json", "audiToken", "vwToken"}
    for path in V3.glob("*.py"):
        if path.name == "auth.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute):
                assert node.attr not in slots, path.name
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in slots, path.name
