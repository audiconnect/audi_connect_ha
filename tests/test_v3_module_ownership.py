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
    actual = {p.relative_to(V3).as_posix() for p in V3.rglob("*")
              if p.is_file() and p.suffix in (".py", ".json", ".js")}
    assert len(paths) == len(set(paths))
    assert set(paths) == actual


def test_domain_owners_do_not_import_composition_or_ha_projection():
    config = json.loads((ROOT / "governance/OWNERSHIP.json").read_text())
    forbidden = {"engine", "runtime", "dashboard", "ha_platforms", "entities", "coordinator_clean"}
    for owner in ("status", "command", "catalog", "profiles", "vehicle", "api"):
        for file in config["owners"][owner]["paths"]:
            if not file.endswith(".py"):
                continue
            for node in ast.walk(ast.parse((V3 / file).read_text())):
                if isinstance(node, ast.ImportFrom):
                    if node.level == 1:
                        names = [node.module] if node.module else [x.name for x in node.names]
                        assert not forbidden.intersection(names), (file, names)
                    if node.level == 0 and node.module:
                        assert not any(node.module.endswith(".v3." + name) for name in forbidden), file
