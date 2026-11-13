"""Architecture guard: V2 behavior never becomes a V3 compatibility shim.

V2 keeps its original business entities/requests. V3 has its own entities,
normalization, API execution and command implementation. The shared touch
points are account bootstrap, runtime selection and HA platform forwarding.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components/audiconnect"
PLATFORMS = (
    "sensor",
    "binary_sensor",
    "button",
    "switch",
    "lock",
    "climate",
    "number",
    "select",
    "device_tracker",
)


def test_v2_platform_modules_have_only_one_v3_delegation_point():
    for platform in PLATFORMS:
        source = (ROOT / f"{platform}.py").read_text()
        assert source.count("v3_setup(") == 1, platform
        assert source.count("if isinstance(runtime_data.v3, V3Engine):") == 1, platform
        assert "from .v3.ha_platforms import setup as v3_setup" in source
        assert f'v3_setup("{platform}", config_entry, async_add_entities)' in source
        # V3 entity classes and business paths must remain out of V2.
        assert "V3ReadOnlySensor(" not in source
        assert "V3ReadOnlyBinarySensor(" not in source
        assert "V3ControlButton(" not in source
        assert "V3ClimateEntity(" not in source
        assert "V3LockEntity(" not in source


def test_v3_runtime_owns_business_behavior_and_all_nine_platforms():
    bootstrap = (ROOT / "__init__.py").read_text()
    platforms = (ROOT / "v3/ha_platforms.py").read_text()
    engine = (ROOT / "v3/engine.py").read_text()
    auth = (ROOT / "v3/auth.py").read_text()
    actions = (ROOT / "v3/service_commands.py").read_text()

    assert "loaded_platforms=list(PLATFORMS)" in ast.unparse(ast.parse(bootstrap))
    assert "auth=V3Auth(hass, config_entry, shared_account=account)" in bootstrap
    assert "_async_register_services(hass)" in bootstrap
    for platform in PLATFORMS:
        assert f'"{platform}"' in platforms

    assert "AudiAccount" not in engine
    assert "AudiDataUpdateCoordinator" not in engine
    assert "AudiConnectVehicle" not in engine
    assert "async_refresh_data" not in engine
    assert "AudiAccount" not in platforms
    assert "AudiConnectVehicle" not in platforms
    assert "audi_services" not in actions
    assert "AudiAccount" not in actions
    # The explicit shared-session seam is limited to authentication.
    assert "shared_account" in auth
    assert ".async_refresh_data(" not in auth


def test_shared_account_owns_session_lifecycle():
    auth = (ROOT / "v3/auth.py").read_text()
    account = (ROOT / "audi_connect_account.py").read_text()
    assert "await self._connection.ensure_session()" in auth
    assert "await self.ensure_session()" in account
    for private in ("._loggedin", "._logintime", "._sync_refresh_token", "._audi_service"):
        assert private not in auth
    assert ".refresh_token_if_necessary(" not in auth
