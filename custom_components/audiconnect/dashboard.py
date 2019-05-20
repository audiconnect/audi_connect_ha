#  Utilities for integration with Home Assistant (directly or via MQTT)

import logging
import re

_LOGGER = logging.getLogger(__name__)

class Instrument:
    def __init__(self, component, attr, name, icon=None):
        self.attr = attr
        self.component = component
        self.name = name
        self.vehicle = None
        self.icon = icon

    def __repr__(self):
        return self.full_name

    def configurate(self, **args):
        pass

    def camel2slug(self, s):
        """Convert camelCase to camel_case.
        >>> camel2slug('fooBar')
        'foo_bar'
        """
        return re.sub("([A-Z])", "_\\1", s).lower().lstrip("_")

    @property
    def slug_attr(self):
        return self.camel2slug(self.attr.replace(".", "_"))

    def setup(self, vehicle, mutable=True, **config):
        self.vehicle = vehicle

        if not mutable and self.is_mutable:
            _LOGGER.info("Skipping %s because mutable", self)
            return False

        if not self.is_supported:
            _LOGGER.debug(
                "%s (%s:%s) is not supported",
                self,
                type(self).__name__,
                self.attr,
            )
            return False

        _LOGGER.debug("%s is supported", self)

        self.configurate(**config)

        return True

    @property
    def vehicle_name(self):
        return self.vehicle.vin

    @property
    def full_name(self):
        return "%s %s" % (self.vehicle_name, self.name)

    @property
    def is_mutable(self):
        raise NotImplementedError("Must be set")

    @property
    def is_supported(self):
        supported = self.attr + "_supported"
        if hasattr(self.vehicle, supported):
            return getattr(self.vehicle, supported)
        if hasattr(self.vehicle, self.attr):
            return True
        return False

    @property
    def str_state(self):
        return self.state

    @property
    def state(self):
        if hasattr(self.vehicle, self.attr):
            return getattr(self.vehicle, self.attr)
        return self.vehicle.get_attr(self.attr)

    @property
    def attributes(self):
        return {}

class Sensor(Instrument):
    def __init__(self, attr, name, icon, unit):
        super().__init__(component="sensor", attr=attr, name=name, icon=icon)
        self.unit = unit

    def configurate(self, scandinavian_miles=False, **config):
        if self.unit and scandinavian_miles and "km" in self.unit:
            self.unit = "mil"

    @property
    def is_mutable(self):
        return False

    @property
    def str_state(self):
        if self.unit:
            return "%s %s" % (self.state, self.unit)
        else:
            return "%s" % self.state

    @property
    def state(self):
        val = super().state
        if val and self.unit and "mil" in self.unit:
            return val / 10
        else:
            return val

class BinarySensor(Instrument):
    def __init__(self, attr, name, device_class):
        super().__init__(component="binary_sensor", attr=attr, name=name)
        self.device_class = device_class

    @property
    def is_mutable(self):
        return False

    @property
    def str_state(self):
        if self.device_class in ["door", "window"]:
            return "Open" if self.state else "Closed"
        if self.device_class == "safety":
            return "Warning!" if self.state else "OK"
        if self.device_class == "plug":
            return "Charging" if self.state else "Plug removed"
        if self.device_class == "lock":
            return "Unlocked" if self.state else "Locked"
        if self.state is None:
            _LOGGER.error("Can not encode state %s:%s", self.attr, self.state)
            return "?"
        return "On" if self.state else "Off"

    @property
    def state(self):
        val = super().state
        if isinstance(val, (bool, list)):
            #  for list (e.g. bulb_failures):
            #  empty list (False) means no problem
            return bool(val)
        elif isinstance(val, str):
            return val != "Normal"
        return val

    @property
    def is_on(self):
        return self.state

class Lock(Instrument):
    def __init__(self):
        super().__init__(component="lock", attr="lock", name="Door lock")

    @property
    def is_mutable(self):
        return True

    @property
    def str_state(self):
        return "Locked" if self.state else "Unlocked"

    @property
    def state(self):
        return self.vehicle.is_locked

    @property
    def is_locked(self):
        return self.state

    async def lock(self):
        await self.vehicle.lock()

    async def unlock(self):
        await self.vehicle.unlock()


class Switch(Instrument):
    def __init__(self, attr, name, icon):
        super().__init__(component="switch", attr=attr, name=name, icon=icon)

    @property
    def is_mutable(self):
        return True

    @property
    def str_state(self):
        return "On" if self.state else "Off"

    def is_on(self):
        return self.state

    def turn_on(self):
        pass

    def turn_off(self):
        pass

class Position(Instrument):
    def __init__(self):
        super().__init__(
            component="device_tracker", attr="position", name="Position"
        )

    @property
    def is_mutable(self):
        return False

    @property
    def state(self):
        state = super().state or {}
        return (
            state.get("latitude", "?"),
            state.get("longitude", "?"),
            state.get("timestamp", None),
            state.get("parktime", None)
        )

    @property
    def str_state(self):
        state = super().state or {}
        ts = state.get("timestamp")
        pt = state.get("parktime")
        return (
            state.get("latitude", "?"),
            state.get("longitude", "?"),
            str(ts.astimezone(tz=None)) if ts else None,
            str(pt.astimezone(tz=None)) if pt else None            
        )

def create_instruments():
    return [
        Position(),
        Sensor(attr="last_update_time", name="Last Update", icon="mdi:time", unit=None),
        Sensor(attr="mileage", name="Mileage", icon="mdi:speedometer", unit="km"),
        Sensor(attr="range", name="Range", icon="mdi:gas-station", unit="km"),
        Sensor(attr="service_inspection_time", name="Service inspection time", icon="mdi:room-service-outline", unit="days"),
        Sensor(attr="service_inspection_distance", name="Service inspection distance", icon="mdi:room-service-outline", unit="km"),
        Sensor(attr="oil_change_time", name="Oil change time", icon="mdi:oil", unit="days"),
        Sensor(attr="oil_change_distance", name="Oil change distance", icon="mdi:oil", unit="km"),
        Sensor(attr="oil_level", name="Oil level", icon="mdi:oil", unit="%"),
        Sensor(attr="charging_state", name="Charging state", icon="mdi:car-battery", unit=None),
        Sensor(attr="max_charge_current", name="Max charge current", icon="mdi:current-ac", unit=None),
        Sensor(attr="engine_type1", name="Engine 1", icon="mdi:engine", unit=None),
        Sensor(attr="engine_type2", name="Engine 2", icon="mdi:engine", unit=None),
        BinarySensor(attr="parking_light", name="Parking light", device_class="safety"),
        BinarySensor(attr="any_window_open", name="Windows", device_class="window"),
        BinarySensor(attr="any_door_unlocked", name="Doors", device_class="lock"),
        BinarySensor(attr="trunk_unlocked", name="Trunk", device_class="lock")
    ]

class Dashboard:
    def __init__(self, vehicle, **config):
        _LOGGER.debug("Setting up dashboard with config :%s", config)
        self.instruments = [
            instrument
            for instrument in create_instruments()
            if instrument.setup(vehicle, **config)
        ]