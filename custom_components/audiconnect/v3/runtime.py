"""Persisted runtime selection and active catalog location.

The stored v3_climate value is retained for in-place config-entry compatibility.
It selects the clean V3 runtime, not a climate-only pilot.
"""

from pathlib import Path

V3_RUNTIME_OPTION = "runtime_version"
V3_ENABLED = "v3_climate"
V3_DEFAULT = "v2"
V3_DASHBOARD_OPTION = "v3_vehicle_dashboard"
V3_WORKBENCH_OPTION = "v3_development_workbench"


def dashboard_enabled(options) -> bool:
    """Preserve existing V3 visibility; explicit opt-out leaves native HA intact."""
    return (
        options.get(V3_RUNTIME_OPTION, V3_DEFAULT) == V3_ENABLED
        and options.get(V3_DASHBOARD_OPTION, True) is True
    )


def workbench_enabled(options) -> bool:
    return (
        dashboard_enabled(options) and options.get(V3_WORKBENCH_OPTION, False) is True
    )


def catalog_path() -> Path:
    return Path(__file__).with_name("full_catalog.json")
