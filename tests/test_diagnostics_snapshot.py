"""Privacy regression test for the native diagnostics export."""
import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "custom_components/audiconnect"


def _module(name, package=False):
    obj = types.ModuleType(name)
    if package:
        obj.__path__ = []
    return obj


class TestSnapshot(TestCase):
    def test_no_raw_personal_data_in_export(self):
        ha = _module("homeassistant", True)
        cfg = _module("homeassistant.config_entries")
        cfg.ConfigEntry = type("ConfigEntry", (), {})
        core = _module("homeassistant.core")
        core.HomeAssistant = type("HomeAssistant", (), {})
        helpers = _module("homeassistant.helpers", True)
        registry = _module("homeassistant.helpers.entity_registry")
        registry.async_get = lambda hass: None
        registry.async_entries_for_config_entry = lambda registry, entry_id: [
            NS(entity_id="sensor.EXAMPLEVIN0000001_battery", disabled_by=None),
            NS(entity_id="switch.EXAMPLEVIN0000001_charge", disabled_by="integration"),
        ]
        pkg = _module("test_audi_package", True)
        const = _module("test_audi_package.const")
        values = {
            "CONF_API_LEVEL": "api_level",
            "CONF_REFRESH_AFTER_ACTION": "refresh_vehicle_data_after_action",
            "CONF_REGION": "region",
            "CONF_SCAN_INTERVAL": "scan_interval",
            "DEFAULT_API_LEVEL": 0,
            "DEFAULT_UPDATE_INTERVAL": 15,
        }
        for key, value in values.items():
            setattr(const, key, value)
        catalog = _module("test_audi_package.capability_catalog")
        catalog.snapshot_capabilities = lambda vehicle: {
            "source": "vehicle_poll_not_browser_session",
            "groups": {}, "command_authorization_confirmed": False,
        }
        freshness = _module("test_audi_package.freshness")
        freshness.vehicle_age_minutes = lambda value: None
        freshness.vehicle_freshness = lambda value: "unknown"
        stubs = {
            "test_audi_package.freshness": freshness,
            "test_audi_package.capability_catalog": catalog,
            "homeassistant": ha,
            "homeassistant.config_entries": cfg,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.entity_registry": registry,
            "test_audi_package": pkg,
            "test_audi_package.const": const,
        }
        with patch.dict(sys.modules, stubs):
            spec = importlib.util.spec_from_file_location(
                "test_audi_package.diagnostics", ROOT / "diagnostics.py"
            )
            diagnostics = importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules, {spec.name: diagnostics}):
                spec.loader.exec_module(diagnostics)
                raw_car = NS(
                    state={"stateOfCharge": 60, "position": {"latitude": 50.12345, "longitude": 4.5678}},
                    fields={"FOO": "PERSONAL"},
                )
                car = NS(
                    _vehicle=raw_car,
                    vin="EXAMPLEVIN0000001",
                    support_status_report=True,
                    support_position=True,
                    support_trip_data=False,
                    support_charger=False,
                    support_preheater=False,
                    support_climater=False,
                )
                api = NS(
                    diagnostic_events=[{"method": "POST", "route": "legacy_climatisation", "http_status": 401}],
                    vcf_remaining_calls=10,
                    vcf_remaining_calls_last_observed=None,
                )
                connection = NS(
                    _loggedin=True, _audi_service=NS(uses_auth0=True, _api=api), vehicles=[car]
                )
                coordinator = NS(
                    last_update_success=True,
                    last_update_success_time=None,
                    last_exception=ValueError("VIN EXAMPLEVIN0000001 token SECRET"),
                )
                entry = NS(
                    data={"region": "DE", "api_level": 0, "refresh_token": "SECRET", "username": "person@example.test"},
                    options={},
                    entry_id="private-entry-id",
                    runtime_data=NS(account=NS(connection=connection), coordinator=coordinator),
                    state="ConfigEntryState.LOADED",
                )
                result = asyncio.run(diagnostics.async_get_config_entry_diagnostics(NS(), entry))
        rendered = repr(result)
        for secret in (
            "EXAMPLEVIN0000001",
            "SECRET",
            "person@example.test",
            "50.12345",
            "4.5678",
            "private-entry-id",
        ):
            self.assertNotIn(secret, rendered)
        self.assertEqual(result["runtime"]["last_poll_exception_type"], "ValueError")
        self.assertEqual(
            result["runtime"]["vehicles"][0]["feature_flags"]["support_trip_data"],
            "legacy_poll_disabled_for_auth0_session",
        )
        self.assertEqual(result["entities"]["total"], 2)
        self.assertEqual(result["entities"]["disabled_per_platform"]["switch"], 1)
