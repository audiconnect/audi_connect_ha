"""Privacy and status tests for Audi Connect diagnostics."""

import importlib.util
from pathlib import Path
import unittest

MODULE = (
    Path(__file__).resolve().parents[1]
    / "custom_components/audiconnect/diagnostic_events.py"
)
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
        event = module.build_http_event(
            "POST",
            "https://emea.bff.cariad.digital/vehicle/v1/vehicles/SECRET/climatisation/start",
            200,
        )
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
        event = module.build_http_event("POST", "https://example.org/oauth/token", 200)
        self.assertEqual(event["route"], "other")
        self.assertEqual(event["outcome"], "http_accepted_not_vehicle_confirmed")

    def test_auth0_failed_token_exchange(self):
        event = module.build_http_event(
            "POST", "https://group.identity.vwgroup.io/oauth/token", 401
        )
        self.assertEqual(event["route"], "authentication")
        self.assertEqual(event["outcome"], "http_rejected")

    def test_successful_read_ignored(self):
        self.assertIsNone(
            module.build_http_event(
                "GET", "https://example.test/vehicle/v1/status", 200
            )
        )

    def test_legacy_unlock(self):
        url = "https://example.test/api/rolesrights/authorization/v2/vehicles/EXAMPLEVIN0000001/services/rlu_v1/operations/UNLOCK/security-pin-auth-requested"
        self.assertEqual(
            module.build_http_event("POST", url, 401)["route"],
            "remote_lock_authorization",
        )

    def test_http_error_is_recorded_even_for_read(self):
        self.assertEqual(
            module.build_http_event("GET", "https://example.test/selectivestatus", 502)[
                "outcome"
            ],
            "http_rejected",
        )

    def test_redirect_is_not_command_acceptance(self):
        event = module.build_http_event(
            "PUT", "https://example.test/vehicle/v1/vehicles/VIN/charging/profiles", 307
        )
        self.assertEqual(event["outcome"], "http_redirect")


class TestVehicleTransport(unittest.IsolatedAsyncioTestCase):
    async def test_vehicle_write_does_not_follow_redirect(self):
        from unittest.mock import MagicMock

        from aiohttp import ClientResponseError
        from custom_components.audiconnect.audi_api import AudiAPI

        session = MagicMock()
        response = session.request.return_value.__aenter__.return_value
        response.status = 307
        response.headers = {"Location": "https://example.test/other"}
        response.reason = "Temporary Redirect"
        response.history = ()
        for path in (
            "/vehicle/v1/vehicles/VIN/charging/profiles",
            "/vehicle/v1/engine/VIN/stop",
            "/fs-car/bs/rlu/v1/Audi/DE/vehicles/VIN/actions",
        ):
            session.request.reset_mock()
            with self.assertRaises(ClientResponseError):
                await AudiAPI(session).request(
                    "PUT",
                    "https://example.test" + path,
                    data="{}",
                    allow_redirects=True,
                )
            session.request.assert_called_once()
            self.assertIs(session.request.call_args.kwargs["allow_redirects"], False)

        session.request.reset_mock()
        await AudiAPI(session).request(
            "POST",
            "https://group.identity.vwgroup.io/oauth/token",
            data=None,
            raw_reply=True,
            allow_redirects=True,
        )
        self.assertIs(session.request.call_args.kwargs["allow_redirects"], True)
        self.assertNotIn("middlewares", session.request.call_args.kwargs)

    async def test_actual_aiohttp_disconnect_never_replays_vehicle_write(self):
        from aiohttp import ClientSession, web
        from custom_components.audiconnect.audi_api import AudiAPI

        calls = []

        async def disconnect(request):
            calls.append(request.method)
            await request.read()
            request.transport.abort()
            return web.Response()

        app = web.Application()
        app.router.add_route(
            "*", "/vehicle/v1/vehicles/VIN/charging/profiles", disconnect
        )
        runner = web.AppRunner(app)
        await runner.setup()
        try:
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = runner.addresses[0][1]
            url = f"http://127.0.0.1:{port}/vehicle/v1/vehicles/VIN/charging/profiles"
            async with ClientSession() as session:
                for method in ("PUT", "POST"):
                    with self.assertRaisesRegex(RuntimeError, "outcome uncertain"):
                        await AudiAPI(session).request(method, url, data="{}")
            self.assertEqual(calls, ["PUT", "POST"])
        finally:
            await runner.cleanup()


if __name__ == "__main__":
    unittest.main()
