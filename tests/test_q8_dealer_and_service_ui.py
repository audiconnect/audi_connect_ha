"""Dealer should exist as a visible HA entity before manual configuration."""
from __future__ import annotations

from types import SimpleNamespace as NS

from custom_components.audiconnect.local_extensions import (
    get_local_dealer, update_local_dealer_options,
)
from custom_components.audiconnect.sensor import (
    AudiLocalDealerSensor, AudiServiceOverviewSensor,
)


class Coordinator:
    last_update_success = True


def make():
    car = NS(
        vin="TESTVIN00000000001", title="Audi Q8", model="Q8", model_year="2023",
        service_inspection_time=90, service_inspection_distance=12000,
        oil_change_time=60, oil_change_distance=7000,
    )
    entry = NS(options={"scan_interval": 15})
    return car, entry


def test_dealer_exists_and_is_not_diagnostic_even_before_setup():
    car, entry = make()
    dealer = AudiLocalDealerSensor(Coordinator(), car, entry)
    assert dealer.available
    assert dealer.native_value == "Not configured"
    assert dealer.extra_state_attributes["configured"] is False
    assert dealer.unique_id.endswith("_sensor_local_dealer")
    assert getattr(dealer, "_attr_entity_category", None) is None


def test_dealer_options_updates_without_losing_vehicle_or_polling_settings():
    car, entry = make()
    dealer = AudiLocalDealerSensor(Coordinator(), car, entry)
    entry.options = update_local_dealer_options(
        entry.options, car.vin, {
            "dealer_name": "Example dealer",
            "dealer_city": "Brussels",
            "next_service_date": "2027-01-20",
        }
    )
    assert entry.options["scan_interval"] == 15
    assert dealer.native_value == "Example dealer"
    assert dealer.extra_state_attributes["dealer_city"] == "Brussels"
    assert dealer.extra_state_attributes["configured"] is True
    assert "Audi" in dealer.extra_state_attributes["source"]
    assert len(get_local_dealer(entry.options, "SOMEOTHER_VIN")) == 0
    entry.options = update_local_dealer_options(entry.options, car.vin, {}, clear=True)
    assert dealer.native_value == "Not configured"


def test_service_overview_distinguishes_car_inspection_and_local_booking():
    car, entry = make()
    summary = AudiServiceOverviewSensor(Coordinator(), car, entry)
    assert summary.available
    assert summary.native_value == "scheduled"
    assert summary.extra_state_attributes["inspection_due_days"] == 90
    assert summary.extra_state_attributes["next_appointment_local"] is None
    car.service_inspection_time = 14
    assert summary.native_value == "due_soon"
    car.oil_change_time = -1
    assert summary.native_value == "overdue"
    car.service_inspection_time = None
    car.oil_change_time = None
    entry.options = update_local_dealer_options(
        entry.options, car.vin, {"next_service_date": "2027-01-20"}
    )
    assert summary.native_value == "appointment_recorded"
    assert summary.extra_state_attributes["next_appointment_local"] == "2027-01-20"


def test_options_flow_translations_have_manual_dealer_steps():
    from pathlib import Path
    import json
    root = Path(__file__).resolve().parents[1] / "custom_components/audiconnect"
    for name in ("strings.json", "translations/en.json", "translations/nl.json"):
        data = json.loads((root / name).read_text())
        assert "edit_local_dealer" in data["options"]["step"]["init"]["data"]
        assert "dealer_vehicle" in data["options"]["step"]
        assert "dealer" in data["options"]["step"]
        assert "experimental_commands" in data["options"]["step"]["init"]["data"]
