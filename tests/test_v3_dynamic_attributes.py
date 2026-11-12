"""V3 read-only value discovery preserves historical entity identity."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "audiconnect"


def test_v3_binary_sensor_platform_is_loaded_from_v3_and_not_v2():
    main = (ROOT / "__init__.py").read_text()
    code = (ROOT / "binary_sensor.py").read_text()
    assert "loaded_platforms=list(PLATFORMS)" in main
    assert "from .v3.ha_platforms import setup as v3_setup" in code
    assert "if isinstance(runtime_data.v3, V3Engine)" in code
    assert "V3ReadOnlyBinarySensor" in (ROOT / "v3" / "ha_platforms.py").read_text()


def test_recovered_sensor_requires_vehicle_specific_evidence():
    """Exercise actual HA projection, not the spelling of its loop."""
    from types import SimpleNamespace as NS
    from custom_components.audiconnect.v3.ha_platforms import setup
    from custom_components.audiconnect.v3.vehicle import V3Vehicle

    car = V3Vehicle("WAUZZZ4M0MD123456", "Audi", "Q8", "q8", "DE")
    engine = NS(vehicles={car.vin.lower(): car}, profiles={})
    listeners, offered = [], []
    coordinator = NS(engine=engine, async_add_listener=lambda cb: listeners.append(cb))
    entry = NS(
        entry_id="entry",
        runtime_data=NS(v3=engine, coordinator=coordinator),
        async_on_unload=lambda cb: None,
    )
    setup("sensor", entry, offered.extend)
    uid = car.vin.lower() + "_sensor_state_of_charge"
    assert uid not in {entity.unique_id for entity in offered}
    # False/boolean must not manufacture numeric telemetry.
    car.readings["stateOfCharge"] = {"value": True}
    listeners[-1]()
    assert uid not in {entity.unique_id for entity in offered}
    car.readings["stateOfCharge"] = {"value": 0, "status": "verified"}
    listeners[-1]()
    listeners[-1]()
    assert sum(entity.unique_id == uid for entity in offered) == 1
    entity = next(entity for entity in offered if entity.unique_id == uid)
    assert entity.native_value == 0
    assert entity.native_unit_of_measurement == "%"
