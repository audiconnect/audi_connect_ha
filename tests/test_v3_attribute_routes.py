"""Per-vehicle read-only alternate route selection requires evidence."""

from __future__ import annotations
import pytest
from custom_components.audiconnect.v3.attribute_routes import (
    read_variants,
    get_read_variant,
    validate_custom_read_route,
)


def test_read_attribute_has_shared_and_targeted_variants():
    choices = read_variants("stateOfCharge", {})
    assert {r["id"] for r in choices} == {
        "cariad.selectivestatus.batch",
        "cariad.selectivestatus.targeted",
        "mbb.charger.readonly",
    }
    assert choices[1]["path"].endswith("jobs=charging")
    assert (
        get_read_variant("stateOfCharge", choices[0]["id"], {})["kind"]
        == "shared_batch"
    )


@pytest.mark.parametrize(
    "path",
    [
        "https://example.com/{VIN}",
        "/vehicle/v1/vehicles/X/fake",
        "/vehicle/v1/vehicles/{VIN}/../x",
        "/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs={EVIL}",
        "/vehicle/v1/vehicles/{VIN}/%2e%2e/abc",
    ],
)
def test_reject_unsafe_custom_paths(path):
    with pytest.raises(ValueError):
        validate_custom_read_route(
            {
                "id": "user.read.my_route",
                "attribute": "stateOfCharge",
                "family": "cariad",
                "method": "GET",
                "path": path,
                "response_path": "charging.batteryStatus.value.currentSOC_pct",
            }
        )


def test_safe_new_mapping_can_be_added_without_updating_python_implementation():
    data = {
        "id": "user.read.my_route",
        "attribute": "stateOfCharge",
        "family": "cariad",
        "method": "GET",
        "path": "/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=charging",
        "response_path": "charging.batteryStatus.value.currentSOC_pct",
    }
    validated = validate_custom_read_route(data)
    assert validated == data
    choices = read_variants("stateOfCharge", {data["id"]: validated})
    assert len(choices) == 4
    assert choices[-1]["response_paths"] == [data["response_path"]]
