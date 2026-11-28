"""Vehicle dashboard reuses HA entity permissions and exact registry ownership."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from homeassistant.auth.models import Group, User
from homeassistant.auth.permissions import PermissionLookup
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import Unauthorized
from custom_components.audiconnect.v3 import vehicle_dashboard as panel
from custom_components.audiconnect.v3.engine import V3Engine


@pytest.fixture
def native(monkeypatch):
    vin = "wauc1234567890123"
    car = NS(vin=vin, inventory_present=True, trip_history=[])
    engine = Mock(spec=V3Engine)
    engine.vehicles = {vin: car}
    entry = NS(
        domain="audiconnect",
        entry_id="account",
        state=ConfigEntryState.LOADED,
        options={"runtime_version": "v3_climate", "v3_development_workbench": False},
        runtime_data=NS(v3=engine),
    )
    device = NS(
        id="device",
        name_by_user=None,
        name="Audi " + vin,
        identifiers={("audiconnect", vin)},
        config_entries={"account"},
    )

    def registered(key, entity_id):
        return NS(
            entity_id=entity_id,
            unique_id=vin + "_" + key.replace(".", "_", 1),
            device_id=device.id,
            config_entry_id=entry.entry_id,
            platform="audiconnect",
            disabled_by=None,
            hidden_by=None,
            name=None,
            original_name=None,
        )

    model = registered("sensor.model", "sensor.audi_model")
    trips = registered("sensor.trip_history", "sensor.audi_trips")
    lock = registered("lock.lock", "lock.audi")
    entities = [model, trips, lock]
    registry = NS(
        async_get=lambda ident: next(
            (row for row in entities if row.entity_id == ident), None
        )
    )
    hass = NS(
        config_entries=NS(
            async_get_entry=lambda ident: entry if ident == entry.entry_id else None,
            async_entries=lambda domain: [entry],
        )
    )
    monkeypatch.setattr(panel.er, "async_get", lambda hass: registry)
    monkeypatch.setattr(
        panel.er, "async_entries_for_config_entry", lambda registry, ident: entities
    )
    monkeypatch.setattr(
        panel.dr,
        "async_get",
        lambda hass: NS(async_get=lambda ident: device if ident == device.id else None),
    )
    return NS(
        hass=hass,
        entry=entry,
        car=car,
        device=device,
        entities=entities,
        model=model,
        trips=trips,
        lock=lock,
        vin=vin,
    )


def user(read, control=()):
    return NS(
        permissions=NS(
            check_entity=lambda ident, policy: (
                ident in (read if policy == "read" else control)
            )
        )
    )


def test_user_panel_independent_of_workbench_and_permission_scoped(native):
    rows = panel.vehicle_list(native.hass, user({"sensor.audi_model", "lock.audi"}))
    assert len(rows) == 1
    assert rows[0]["name"] == "Audi"
    assert native.vin not in str(rows)
    assert "entry_id" not in rows[0]
    assert {row["key"] for row in rows[0]["entities"]} == {"sensor.model", "lock.lock"}
    assert not any(row["control"] for row in rows[0]["entities"])
    rows = panel.vehicle_list(native.hass, user({"lock.audi"}, {"lock.audi"}))
    assert rows[0]["entities"][0]["control"] is True
    assert panel.vehicle_list(native.hass, user(set())) == []


def test_wrong_device_disabled_inventory_and_v2_fail_closed(native):
    allowed = user({"sensor.audi_model"})
    native.model.disabled_by = "user"
    assert panel.vehicle_list(native.hass, allowed) == []
    native.model.disabled_by = None
    native.model.hidden_by = "user"
    assert panel.vehicle_list(native.hass, allowed) == []
    native.model.hidden_by = None
    native.device.identifiers = {("audiconnect", "unrelated")}
    assert panel.vehicle_list(native.hass, allowed) == []
    native.device.identifiers = {("audiconnect", native.vin)}
    native.car.inventory_present = False
    assert panel.vehicle_list(native.hass, allowed) == []
    native.car.inventory_present = True
    native.entry.options["runtime_version"] = "v2"
    assert panel.vehicle_list(native.hass, allowed) == []


def test_trip_archive_uses_same_native_read_permission_and_owner(native):
    allowed = user({"sensor.audi_trips", "sensor.audi_model"})
    result = panel.vehicle_trips(native.hass, allowed, "sensor.audi_trips")
    assert result["trips"] == []
    assert result["coverage"] == "observed_records"
    with pytest.raises(PermissionError):
        panel.vehicle_trips(native.hass, user(set()), "sensor.audi_trips")
    with pytest.raises(ValueError):
        panel.vehicle_trips(native.hass, allowed, "sensor.audi_model")
    native.trips.config_entry_id = "unrelated"
    with pytest.raises(ValueError):
        panel.vehicle_trips(native.hass, allowed, "sensor.audi_trips")


def test_local_service_settings_reuse_entry_options_and_scope(native):
    dealer = NS(**vars(native.model))
    dealer.entity_id = "sensor.audi_dealer"
    dealer.unique_id = native.vin + "_sensor_local_dealer"
    native.entities.append(dealer)
    denied = user({"sensor.audi_dealer"})
    denied.is_admin = False
    with pytest.raises(PermissionError):
        panel.local_service_details(native.hass, denied, dealer.entity_id)
    admin = user({"sensor.audi_dealer"})
    admin.is_admin = True
    native.hass.config_entries.async_update_entry = Mock()
    result = panel.local_service_details(
        native.hass, admin, dealer.entity_id, {"dealer_name": "Audi Service"}
    )
    assert result == {"dealer_name": "Audi Service"}
    options = native.hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert options["local_dealers"][native.vin]["dealer_name"] == "Audi Service"
    assert options["runtime_version"] == "v3_climate"
    with pytest.raises(ValueError):
        panel.local_service_details(
            native.hass, admin, dealer.entity_id, {"warranty_expiry": "invalid"}
        )
    assert native.hass.config_entries.async_update_entry.call_count == 1


def test_admin_configuration_entry_is_exact_and_not_exposed_to_read_only_user(native):
    normal = user({"sensor.audi_model"})
    normal.is_admin = False
    assert "configuration_entry" not in panel.vehicle_list(native.hass, normal)[0]
    admin = user({"sensor.audi_model"})
    admin.is_admin = True
    result = panel.vehicle_list(native.hass, admin)[0]
    assert result["configuration_entry"] == native.entry.entry_id
    assert result["entities"][0]["translation_key"] == "v3_model"


def test_real_ha_user_policy_and_admin_websocket_guard(native):
    lookup = PermissionLookup(
        entity_registry=panel.er.async_get(native.hass),
        device_registry=panel.dr.async_get(native.hass),
    )
    resident = User(
        name="Resident",
        perm_lookup=lookup,
        is_active=True,
        groups=[
            Group(
                name="Restricted",
                policy={
                    "entities": {
                        "entity_ids": {
                            "sensor.audi_model": {"read": True},
                            "sensor.audi_trips": {"read": True},
                            "lock.audi": {"read": True},
                        }
                    }
                },
            )
        ],
    )
    assert not resident.is_admin
    rows = panel.vehicle_list(native.hass, resident)
    assert len(rows) == 1
    assert all(not entity["control"] for entity in rows[0]["entities"])
    assert (
        panel.vehicle_trips(native.hass, resident, native.trips.entity_id)["trips"]
        == []
    )
    with pytest.raises(Unauthorized):
        panel.ws_service_details(native.hass, NS(user=resident), {"id": 1})
    resident.groups = [Group(name="No vehicle access", policy={})]
    assert panel.vehicle_list(native.hass, resident) == []
    with pytest.raises(PermissionError):
        panel.vehicle_trips(native.hass, resident, native.trips.entity_id)


def test_duplicate_loaded_account_is_rejected_even_with_one_readable_entity(native):
    other_engine = Mock(spec=V3Engine)
    other_engine.vehicles = {native.vin: native.car}
    other = NS(
        domain="audiconnect",
        entry_id="other",
        state=ConfigEntryState.LOADED,
        options={"runtime_version": "v3_climate"},
        runtime_data=NS(v3=other_engine),
    )
    native.device.config_entries.add(other.entry_id)
    native.hass.config_entries.async_get_entry = lambda ident: {
        native.entry.entry_id: native.entry,
        other.entry_id: other,
    }.get(ident)
    assert panel.vehicle_list(native.hass, user({native.model.entity_id})) == []
    with pytest.raises(ValueError):
        panel.vehicle_trips(
            native.hass, user({native.trips.entity_id}), native.trips.entity_id
        )
    other.options["runtime_version"] = "v2"
    assert len(panel.vehicle_list(native.hass, user({native.model.entity_id}))) == 1


def test_profile_names_keep_native_instance_identity(native):
    profile = NS(**vars(native.model))
    profile.entity_id = "number.home_target"
    profile.unique_id = native.vin + "_number_charge_profile_2_target_soc"
    profile.original_name = "Charging profile 2 target SOC"
    native.entities.append(profile)
    rows = panel.vehicle_list(native.hass, user({profile.entity_id}))
    assert rows[0]["entities"][0]["translation_key"] is None
    assert rows[0]["entities"][0]["name"] == profile.original_name


async def test_consumer_websocket_dispatch_with_native_ha_registry_and_permissions(
    tmp_path,
):
    """Real HA dispatcher, schema, registry and user; no OEM or HTTP socket."""
    import json
    from types import MappingProxyType

    from homeassistant.components import websocket_api
    from homeassistant.components.websocket_api.connection import ActiveConnection
    from custom_components.audiconnect import AudiRuntimeData, _async_update_listener
    from homeassistant.config_entries import ConfigEntries, ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})
    await hass.config_entries.async_initialize()
    dr.async_setup(hass)
    await dr.async_load(hass, load_empty=True)
    await er.async_load(hass, load_empty=True)
    entry = ConfigEntry(
        domain="audiconnect",
        title="Audi",
        data={},
        options={"runtime_version": "v3_climate"},
        source="user",
        version=1,
        minor_version=1,
        unique_id="test-account",
        discovery_keys=MappingProxyType({}),
        pref_disable_new_entities=False,
        pref_disable_polling=False,
        subentries_data=None,
        state=ConfigEntryState.LOADED,
    )
    # Seed an already loaded fixture account without calling the Audi network.
    hass.config_entries._entries[entry.entry_id] = entry
    vin = "testvin0000000001"
    engine = Mock(spec=V3Engine)
    engine.vehicles = {vin: NS(vin=vin, inventory_present=True, trip_history=[])}
    coordinator = NS(async_update_listeners=Mock())
    entry.runtime_data = AudiRuntimeData(
        account=None,
        coordinator=coordinator,
        v3=engine,
        options_snapshot=dict(entry.options),
        data_snapshot=dict(entry.data),
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("audiconnect", vin)},
        name="Audi fixture",
    )
    registry = er.async_get(hass)
    model = registry.async_get_or_create(
        "sensor",
        "audiconnect",
        vin + "_sensor_model",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="audi_model",
    )
    trips = registry.async_get_or_create(
        "sensor",
        "audiconnect",
        vin + "_sensor_trip_history",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="audi_trips",
    )
    dealer = registry.async_get_or_create(
        "sensor",
        "audiconnect",
        vin + "_sensor_local_dealer",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="audi_dealer",
    )
    other = ConfigEntry(
        domain="audiconnect",
        title="Other Audi",
        data={},
        options={"runtime_version": "v3_climate"},
        source="user",
        version=1,
        minor_version=1,
        unique_id="other-account",
        discovery_keys=MappingProxyType({}),
        pref_disable_new_entities=False,
        pref_disable_polling=False,
        subentries_data=None,
        state=ConfigEntryState.LOADED,
    )
    hass.config_entries._entries[other.entry_id] = other
    other_vin = "testvin0000000002"
    other_engine = Mock(spec=V3Engine)
    other_engine.vehicles = {
        other_vin: NS(vin=other_vin, inventory_present=True, trip_history=[])
    }
    other.runtime_data = NS(v3=other_engine)
    other_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("audiconnect", other_vin)},
        name="Other fixture",
    )
    other_dealer = registry.async_get_or_create(
        "sensor",
        "audiconnect",
        other_vin + "_sensor_local_dealer",
        config_entry=other,
        device_id=other_device.id,
        suggested_object_id="other_dealer",
    )
    lookup = PermissionLookup(
        entity_registry=registry, device_registry=dr.async_get(hass)
    )
    user = User(
        name="Resident",
        perm_lookup=lookup,
        is_active=True,
        groups=[
            Group(
                name="Read model only",
                policy={"entities": {"entity_ids": {model.entity_id: {"read": True}}}},
            )
        ],
    )
    assert len(vin) == 17
    assert user.permissions.check_entity(model.entity_id, "read")
    assert panel._scoped_vehicle(hass, model) is not None
    for handler in (
        panel.ws_vehicle_list,
        panel.ws_vehicle_trips,
        panel.ws_service_details,
    ):
        websocket_api.async_register_command(hass, handler)
    messages = []
    connection = ActiveConnection(Mock(), hass, messages.append, user, None, None)

    async def request(msg):
        connection.async_handle(msg)
        await hass.async_block_till_done(wait_background_tasks=True)
        result = messages.pop(0)
        return json.loads(result) if isinstance(result, (bytes, str)) else result

    try:
        response = await request({"id": 1, "type": "audiconnect/vehicle/list"})
        assert response["success"]
        assert [
            item["entity_id"] for item in response["result"]["vehicles"][0]["entities"]
        ] == [model.entity_id]
        assert "configuration_entry" not in response["result"]["vehicles"][0]
        assert vin not in str(response)
        denied = await request(
            {"id": 2, "type": "audiconnect/vehicle/trips", "entity_id": trips.entity_id}
        )
        assert not denied["success"] and denied["error"]["code"] == "unauthorized"
        denied = await request(
            {
                "id": 3,
                "type": "audiconnect/vehicle/service_details",
                "entity_id": dealer.entity_id,
                "updates": {"dealer_name": "Not allowed"},
            }
        )
        assert not denied["success"] and denied["error"]["code"] == "unauthorized"
        assert "local_dealers" not in entry.options
        malformed = await request(
            {
                "id": 4,
                "type": "audiconnect/vehicle/trips",
                "entity_id": trips.entity_id,
                "limit": 10001,
            }
        )
        assert (
            not malformed["success"] and malformed["error"]["code"] == "invalid_format"
        )
        # The real dispatcher now receives the administrator's authenticated user
        # context. Both accounts exist, but the write is scoped by native entity ID.
        connection.user = User(
            name="Owner", perm_lookup=lookup, is_active=True, is_owner=True
        )
        saved = await request(
            {
                "id": 5,
                "type": "audiconnect/vehicle/service_details",
                "entity_id": dealer.entity_id,
                "updates": {"dealer_name": "New dealer"},
            }
        )
        assert saved["success"]
        assert entry.options["local_dealers"][vin]["dealer_name"] == "New dealer"
        assert "local_dealers" not in other.options
        coordinator.async_update_listeners.assert_called_once_with()
        readback = await request(
            {
                "id": 6,
                "type": "audiconnect/vehicle/service_details",
                "entity_id": dealer.entity_id,
            }
        )
        assert readback["result"]["settings"] == {"dealer_name": "New dealer"}
        second = await request(
            {
                "id": 7,
                "type": "audiconnect/vehicle/service_details",
                "entity_id": other_dealer.entity_id,
            }
        )
        assert second["result"]["settings"] == {}
        archive = await request(
            {
                "id": 8,
                "type": "audiconnect/vehicle/trips",
                "entity_id": trips.entity_id,
                "start_date": "2026-11-01",
                "end_date": "2026-12-01",
            }
        )
        assert archive["success"] and archive["result"]["total"] == 0
    finally:
        connection.async_handle_close()
        await hass.async_block_till_done(wait_background_tasks=True)
        hass.import_executor.shutdown(wait=True)


def test_trip_period_uses_existing_native_permissions(native):
    allowed = user({native.trips.entity_id})
    result = panel.vehicle_trips(
        native.hass,
        allowed,
        native.trips.entity_id,
        start_date="2026-11-01",
        end_date="2026-12-01",
    )
    assert result["start_date"] == "2026-11-01"
    assert result["total"] == 0
    with pytest.raises(PermissionError):
        panel.vehicle_trips(
            native.hass, user(set()), native.trips.entity_id, start_date="2026-11-01"
        )
