"""#873: an action called from a dashboard (for example a picture-elements
action-button with ``data: {device_id: ...}``) arrives with device_id as a
list, which a plain cv.string rejected with "value should be a string".

No Home Assistant instance: only the service schemas are exercised.
"""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.audiconnect.audi_account import (
    SERVICE_REFRESH_VEHICLE_DATA_SCHEMA,
    SERVICE_START_CLIMATE_CONTROL_SCHEMA,
    SERVICE_STOP_ENGINE_SCHEMA,
)


def test_a_device_id_string_is_accepted_as_before() -> None:
    data = SERVICE_START_CLIMATE_CONTROL_SCHEMA({"device_id": "abc", "temp_c": 21})
    assert data["device_id"] == "abc"


def test_a_one_item_device_id_list_is_unwrapped() -> None:
    data = SERVICE_START_CLIMATE_CONTROL_SCHEMA({"device_id": ["abc"], "temp_c": 21})
    assert data["device_id"] == "abc"


@pytest.mark.parametrize("devices", [[], ["abc", "def"]])
def test_anything_but_exactly_one_device_is_refused(devices) -> None:
    # The actions target a single vehicle; picking one of several silently
    # would act on a car the user may not have meant.
    with pytest.raises(vol.Invalid):
        SERVICE_START_CLIMATE_CONTROL_SCHEMA({"device_id": devices})


@pytest.mark.parametrize(
    "schema", [SERVICE_REFRESH_VEHICLE_DATA_SCHEMA, SERVICE_STOP_ENGINE_SCHEMA]
)
def test_every_action_accepts_the_list_form(schema) -> None:
    assert schema({"device_id": ["abc"]})["device_id"] == "abc"
