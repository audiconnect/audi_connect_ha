"""An entity this integration created before is not dropped by a thin poll.

#854 gated entity creation on the car's capability list rather than on whether
the current poll carried a value. That list is job-level: it answers "does this
car do climatisation", never "does it report isMirrorHeatingActive". So two
gaps survived it.

An entity backed by a single field, inside a capability the car has, is still
dropped when a poll arrives without that field. And a car that reports no
capability list at all is protected by nothing, because the gate has to fall
back to the old behaviour there or it would strip every entity from those
vehicles.

The evidence is a rate-limit window on 2026-09-09, where two jobs answered with
errors across four consecutive polls. Every entity fed by those jobs stops being
provided if the integration reloads inside that window, which is what "no longer
provided by the integration" means in the UI.

So the registry gets a vote: an entity already registered for this car is one we
created on an earlier, better poll, and recreating it is free. The car's own
"no" still wins, since that is a statement about the vehicle rather than about
this poll.
"""

from __future__ import annotations

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.audiconnect.audi_entity import (
    entity_unique_id,
    is_entity_supported,
    should_create_entity,
)

VIN = "WAUZZZ00000000001"
OTHER_VIN = "WAUZZZ00000000002"


class Vehicle:
    """Stands in for AudiConnectVehicle: three-valued has_capability, plus
    whatever attributes this poll happened to carry."""

    def __init__(self, vin=VIN, caps=None, **attrs):
        self.vin = vin
        self._caps = caps
        for k, v in attrs.items():
            setattr(self, k, v)

    def has_capability(self, capability):
        if not self._caps:
            return None
        return capability in self._caps


class StubHass:
    """Only what EntityRegistry touches. The registry itself is the real one,
    so the lookup under test is real code over a real index."""

    def __init__(self):
        self.data = {}
        self.config = type("C", (), {"config_dir": "/tmp"})()
        self.bus = type(
            "B",
            (),
            {
                "async_listen": lambda *a, **k: None,
                "async_fire_internal": lambda *a, **k: None,
            },
        )()
        self.states = type("S", (), {"async_available": lambda *a, **k: True})()
        self.verify_event_loop_thread = lambda *a, **k: None


@pytest.fixture
def hass():
    hass = StubHass()
    registry = er.EntityRegistry(hass)
    registry.entities = er.EntityRegistryItems()
    registry.deleted_entities = {}
    registry._entities_data = registry.entities.data
    registry.async_schedule_save = lambda: None
    hass.data[er.DATA_REGISTRY] = registry
    return hass


def register(hass, platform, unique_id):
    """Put an entity in the registry the way an earlier, healthier poll would."""
    return er.async_get(hass).async_get_or_create(platform, "audiconnect", unique_id)


# --- the gap itself ---------------------------------------------------------------


def test_a_field_missing_from_this_poll_no_longer_loses_the_entity(hass):
    """The must-fire case. No capability names this field, the poll does not
    carry it, and the entity exists from before."""
    register(
        hass,
        "binary_sensor",
        entity_unique_id(Vehicle(), "binary_sensor", "glass_surface_heating"),
    )
    thin_poll = Vehicle()  # no glass_surface_heating attribute at all

    assert is_entity_supported(thin_poll, "glass_surface_heating") is False
    assert should_create_entity(
        hass,
        "binary_sensor",
        "glass_surface_heating",
        thin_poll,
        "glass_surface_heating",
    )


def test_a_brand_new_entity_is_not_invented_from_nothing(hass):
    """The must-stay-silent case, and the control for the test above: identical
    call, empty registry. Without this the rescue would create every described
    entity on every car."""
    thin_poll = Vehicle()

    assert not should_create_entity(
        hass,
        "binary_sensor",
        "glass_surface_heating",
        thin_poll,
        "glass_surface_heating",
    )


def test_another_car_s_entity_does_not_rescue_this_one(hass):
    """The registry is keyed on the VIN, so a two-car account cannot leak
    entities between vehicles."""
    register(
        hass,
        "binary_sensor",
        entity_unique_id(
            Vehicle(vin=OTHER_VIN), "binary_sensor", "glass_surface_heating"
        ),
    )

    assert not should_create_entity(
        hass,
        "binary_sensor",
        "glass_surface_heating",
        Vehicle(),
        "glass_surface_heating",
    )


def test_the_car_saying_no_still_wins_over_the_registry(hass):
    """A capability the car does not list is a fact about the vehicle. A stale
    registry entry must not resurrect a control for a feature it lacks."""
    register(
        hass,
        "device_tracker",
        entity_unique_id(Vehicle(), "device_tracker", "position"),
    )
    no_parking = Vehicle(caps=["charging"], position={"lat": 1, "lon": 2})

    assert (
        should_create_entity(
            hass,
            "device_tracker",
            "position",
            no_parking,
            "position",
            "parkingPosition",
        )
        is False
    )


def test_a_capability_the_car_has_still_creates_without_any_history(hass):
    """#854's behaviour, unchanged: the capability alone is enough."""
    capable = Vehicle(caps=["parkingPosition"])  # poll carried no position

    assert should_create_entity(
        hass,
        "device_tracker",
        "position",
        capable,
        "position",
        "parkingPosition",
    )


def test_a_value_in_this_poll_still_creates_without_any_history(hass):
    """The ordinary path on a healthy poll."""
    healthy = Vehicle(glass_surface_heating=True)

    assert should_create_entity(
        hass,
        "binary_sensor",
        "glass_surface_heating",
        healthy,
        "glass_surface_heating",
    )


# --- the unique_id is the whole mechanism -----------------------------------------

LEGACY_FORMATS = [
    ("sensor", "state_of_charge"),
    ("binary_sensor", "glass_surface_heating"),
    ("switch", "climatisation_window_heating"),
    ("number", "target_soc"),
    ("number", "charge_profile_2_target_soc"),
    ("lock", "door_lock"),
    ("climate", "climatisation"),
    ("select", "charge_mode"),
    ("device_tracker", "position"),
]


@pytest.mark.parametrize(("platform", "key"), LEGACY_FORMATS)
def test_the_unique_id_format_is_unchanged(platform, key):
    """The rescue only finds an entity if it asks for the exact string that
    entity was created with. Changing this format would orphan every existing
    entity on every install, silently, and the new ones would look fine."""
    assert entity_unique_id(Vehicle(), platform, key) == (
        f"{VIN.lower()}_{platform}_{key}"
    )


def test_the_gate_and_the_entity_agree_on_the_unique_id():
    """Guard the call site, not just the helper. Every platform now builds its
    unique_id through entity_unique_id, so the id the gate looks up and the id
    the entity registers under cannot drift apart."""
    import inspect

    from custom_components.audiconnect import (
        binary_sensor,
        climate,
        device_tracker,
        lock,
        number,
        select,
        sensor,
        switch,
    )

    for module in (
        binary_sensor,
        climate,
        device_tracker,
        lock,
        number,
        select,
        sensor,
        switch,
    ):
        source = inspect.getsource(module)
        assert '_attr_unique_id = f"{vehicle.vin.lower()}' not in source, (
            f"{module.__name__} still spells the unique_id out by hand"
        )
        assert "entity_unique_id(" in source, (
            f"{module.__name__} does not build its unique_id through the helper"
        )


# --- the two kinds of "no" ---------------------------------------------------------


def test_removing_the_s_pin_removes_the_lock_even_though_it_existed_before(hass):
    """The must-fire case for the configuration gate.

    lock_supported is doors_trunk_status_supported AND an S-PIN being set. The
    first half is about this poll and the second is about what the user
    configured, and only the first may be overridden by history. Unsetting the
    S-PIN has to take the lock away, exactly as it takes the engine buttons.
    """
    register(hass, "lock", entity_unique_id(Vehicle(), "lock", "lock"))
    no_spin = Vehicle(lock=True)

    assert not should_create_entity(
        hass, "lock", "lock", no_spin, "lock", configured=False
    )


def test_the_lock_is_still_rescued_when_the_s_pin_is_there(hass):
    """The control for the test above: same call, S-PIN present."""
    register(hass, "lock", entity_unique_id(Vehicle(), "lock", "lock"))
    thin_poll = Vehicle()  # no lock attribute in this poll

    assert should_create_entity(
        hass, "lock", "lock", thin_poll, "lock", configured=True
    )


def test_the_configuration_gate_does_not_invent_an_entity_either(hass):
    """configured=True is permission to consider, not an answer."""
    assert not should_create_entity(
        hass, "lock", "lock", Vehicle(), "lock", configured=True
    )


# --- a kept entity says it has no data, rather than inventing one -------------------


class _Coordinator:
    last_update_success = True

    def async_add_listener(self, *args, **kwargs):
        return lambda: None


def _entity(vehicle, backing=None, description=None):
    from custom_components.audiconnect.audi_entity import AudiEntity

    e = AudiEntity(_Coordinator(), vehicle)
    if backing is not None:
        e._backing_attr = backing
    if description is not None:
        e.entity_description = description
    return e


def test_a_kept_entity_reports_unavailable_rather_than_a_value_it_lacks():
    """Without this the rescue trades one wrong answer for another: a settings
    switch reads off for a setting that may well be on, and an automation acts
    on it."""
    assert _entity(Vehicle(), backing="glass_surface_heating").available is False


def test_the_same_entity_is_available_once_the_car_reports_it():
    """The control. A probe that never returns True is not measuring."""
    assert (
        _entity(
            Vehicle(glass_surface_heating=False), backing="glass_surface_heating"
        ).available
        is True
    )


def test_a_value_of_false_is_data_and_not_absence():
    """bool(None) is False too, which is the whole bug this PR exists around."""
    e = _entity(Vehicle(glass_surface_heating=False), backing="glass_surface_heating")
    assert e.available is True


def test_an_entity_with_no_backing_attribute_stays_available():
    """Entities not fed by a single vehicle field are untouched."""
    assert _entity(Vehicle()).available is True


def test_a_failed_refresh_still_wins():
    """The coordinator's own verdict is not overridden."""
    e = _entity(Vehicle(glass_surface_heating=True), backing="glass_surface_heating")
    e.coordinator.last_update_success = False
    assert e.available is False


# --- the class attribute must not eat the docstring --------------------------------


def test_every_entity_class_kept_its_docstring():
    """_backing_attr placed above a class docstring silently replaces it, and
    nothing else in this suite would notice."""
    from custom_components.audiconnect.climate import AudiClimate
    from custom_components.audiconnect.device_tracker import AudiDeviceTracker
    from custom_components.audiconnect.lock import AudiLock
    from custom_components.audiconnect.select import AudiChargeModeSelect

    for cls in (AudiClimate, AudiChargeModeSelect, AudiLock, AudiDeviceTracker):
        assert cls.__doc__, f"{cls.__name__} lost its docstring"
        # Availability must be wired one way or the other: a single backing
        # attribute for the base class to read, or the class's own `available`.
        # The lock reads two sources (the car-wide verdict, then the per-door
        # derivation) and so overrides rather than naming one attribute.
        wired = cls._backing_attr or "available" in cls.__dict__
        assert wired, f"{cls.__name__} has no availability wiring"
