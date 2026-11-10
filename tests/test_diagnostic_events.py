"""Privacy and status tests for Audi Connect diagnostics."""
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "custom_components/audiconnect/diagnostic_events.py"
spec = importlib.util.spec_from_file_location("audi_diagnostic_events", MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestDiagnostics(unittest.TestCase):
    def test_legacy_401_contains_no_vin_or_token(self):
        url = "https://msg.volkswagen.de/fs-car/bs/climatisation/v1/Audi/DE/vehicles/EXAMPLEVIN0000001/climater/actions?token=SECRET"
        event = module.build_http_event("POST", url, 401)
        self.assertEqual(event["route"], "legacy_climatisation")
        self.assertEqual(event["outcome"], "http_rejected")
        self.assertNotIn("EXAMPLEVIN0000001", str(event))
        self.assertNotIn("SECRET", str(event))

    def test_accepted_command_not_marked_success(self):
        event = module.build_http_event("POST", "https://emea.bff.cariad.digital/vehicle/v1/vehicles/SECRET/climatisation/start", 200)
        self.assertEqual(event["outcome"], "http_accepted_not_vehicle_confirmed")

    def test_auth0_token_exchange_is_not_vehicle_command(self):
        event = module.build_http_event(
            "POST",
            "https://group.identity.vwgroup.io/oauth/token?secret=PRIVATE",
            200,
        )
        self.assertEqual(event["route"], "authentication")
        self.assertEqual(event["outcome"], "authentication_http_success")
        self.assertNotIn("PRIVATE", str(event))

    def test_other_post_is_not_assumed_authentication(self):
        event = module.build_http_event(
            "POST", "https://example.org/oauth/token", 200
        )
        self.assertEqual(event["route"], "other")
        self.assertEqual(event["outcome"], "http_accepted_not_vehicle_confirmed")

    def test_auth0_failed_token_exchange(self):
        event = module.build_http_event(
            "POST", "https://group.identity.vwgroup.io/oauth/token", 401
        )
        self.assertEqual(event["route"], "authentication")
        self.assertEqual(event["outcome"], "http_rejected")

    def test_successful_read_ignored(self):
        self.assertIsNone(module.build_http_event("GET", "https://example.test/vehicle/v1/status", 200))

    def test_legacy_unlock(self):
        url = "https://example.test/api/rolesrights/authorization/v2/vehicles/EXAMPLEVIN0000001/services/rlu_v1/operations/UNLOCK/security-pin-auth-requested"
        self.assertEqual(module.build_http_event("POST", url, 401)["route"], "remote_lock_authorization")

    def test_http_error_is_recorded_even_for_read(self):
        self.assertEqual(module.build_http_event("GET", "https://example.test/selectivestatus", 502)["outcome"], "http_rejected")


if __name__ == "__main__":
    unittest.main()
