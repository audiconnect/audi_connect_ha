"""Pinned source inventory and immutable V2 business files."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "docs/V2_V3_PARITY_BASELINE.json").read_text())
COMPARISON = json.loads((ROOT / "docs/V2_V3_SOURCE_COMPARISON.json").read_text())


def test_pinned_source_declarations_are_accounted_for():
    ids = {r["id"] for r in BASE["entities"]} | {
        r["id"] for r in BASE["fixbranch_additional_entities"]
    }
    services = set(BASE["v2_services"]) | set(
        COMPARISON["excluded_engineering_services"]
    )
    for source in COMPARISON["sources"].values():
        for platform, keys in source["keys"].items():
            assert {f"{platform}.{key}" for key in keys} <= ids
        assert set(source["services"]) <= services


def test_v2_business_blobs_remain_unchanged():
    for module, sha in COMPARISON["unchanged_v2_business_blob_sha1"].items():
        data = (ROOT / "custom_components/audiconnect" / f"{module}.py").read_bytes()
        assert (
            hashlib.sha1(
                b"blob " + str(len(data)).encode() + b"\x00" + data
            ).hexdigest()
            == sha
        ), module
