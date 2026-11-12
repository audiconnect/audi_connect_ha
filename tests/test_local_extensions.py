"""Local dealer privacy, validation, and multi-car isolation."""

import importlib.util
from pathlib import Path
import pytest

src = (
    Path(__file__).resolve().parents[1]
    / "custom_components/audiconnect/local_extensions.py"
)
spec = importlib.util.spec_from_file_location("audi_local", src)
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


def test_local_options_update_and_clear():
    a = local.update_local_dealer_options(
        {"scan_interval": 15}, "VIN1", {"dealer_name": "A"}
    )
    b = local.update_local_dealer_options(a, "VIN2", {"dealer_name": "B"})
    assert local.get_local_dealer(b, "VIN1")["dealer_name"] == "A"
    assert local.get_local_dealer(b, "VIN2")["dealer_name"] == "B"
    c = local.update_local_dealer_options(
        b, "VIN1", {"next_service_date": "2027-03-01"}
    )
    assert c["scan_interval"] == 15
    d = local.update_local_dealer_options(c, "VIN1", {}, clear=True)
    assert not local.get_local_dealer(d, "VIN1")
    assert local.get_local_dealer(d, "VIN2")["dealer_name"] == "B"


@pytest.mark.parametrize(
    "fields",
    [
        {"dealer_name": "x" * 256},
        {"dealer_website": "javascript:alert(1)"},
        {"dealer_website": "https://user:password@example.org"},
        {"next_service_date": "not-a-date"},
        {"warranty_expiry": "2026-02-30"},
        {"unsupported": "value"},
    ],
)
def test_bad_values_are_rejected(fields):
    with pytest.raises(ValueError):
        local.update_local_dealer_options({}, "VIN1", fields)


def test_optional_values():
    x = local.update_local_dealer_options(
        {},
        "VIN1",
        {"dealer_website": "https://example.org", "warranty_expiry": "2028-12-31"},
    )
    assert local.get_local_dealer(x, "VIN1")["warranty_expiry"] == "2028-12-31"
