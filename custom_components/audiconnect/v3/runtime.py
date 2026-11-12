"""Persisted runtime selection and active catalog location.

The stored v3_climate value is retained for in-place config-entry compatibility.
It selects the clean V3 runtime, not a climate-only pilot.
"""
from pathlib import Path

V3_RUNTIME_OPTION = "runtime_version"
V3_ENABLED = "v3_climate"
V3_DEFAULT = "v2"


def catalog_path() -> Path:
    return Path(__file__).with_name("full_catalog.json")
