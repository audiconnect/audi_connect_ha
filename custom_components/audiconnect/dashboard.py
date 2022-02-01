#  Utilities for integration with Home Assistant (directly or via MQTT)

import logging
import re
from datetime import datetime

_LOGGER = logging.getLogger(__name__)


class Instrument:
    def __init__(self, component, attr, name, icon=None):
        self._attr = attr
        self._component = component
        self._name = name
        self._connection = None
        self._vehicle = None
        self._icon = icon

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
        return self.camel2slug(self._attr.replace(".", "_"))

    def setup(self, connection, vehicle, mutable=True, **config):
        self._connection = connection
        self._vehicle = vehicle

        if not mutable and self.is_mutable:
            _LOGGER.info("Skipping %s because mutable", self)
            return False

        if not self.is_supported:
            # _LOGGER.debug(
            #     "%s (%s:%s) is not supported", self, type(self).__name__, self._attr,
            # )
            return False

        # _LOGGER.debug("%s is supported", self)

        self.configurate(**config)

        return True

    @property
    def component(self):
        return self._component

    @property
    def icon(self):
        return self._icon

    @property
    def name(self):
        return self._name

    @property
    def attr(self):
        return self._attr

    @property
    def vehicle_name(self):
        return self._vehicle.title

    @property
    def full_name(self):
        return "%s %s" % (self.vehicle_name, self._name)

    @property
    def vehicle_model(self):
        return self._vehicle.model

    @property
    def vehicle_model_year(self):
        return self._vehicle.model_year

    @property
    def vehicle_model_family(self):
        return self._vehicle.model_family

    @property
    def vehicle_vin(self):
        return self._vehicle.vin

    @property
    def vehicle_csid(self):
        return self._vehicle.csid

    @property
    def is_mutable(self):
        raise NotImplementedError("Must be set")

    @property
    def is_supported(self):
        supported = self._attr + "_supported"
        if hasattr(self._vehicle, supported):
            return getattr(self._vehicle, supported)
        if hasattr(self._vehicle, self._attr):
            return True
        return False

    @property
    def str_state(self):
        return self.state

    @property
    def state(self):
        if hasattr(self._vehicle, self._attr):
            return getattr(self._vehicle, self._attr)
        return self._vehicle.get_attr(self._attr)

    @property
    def attributes(self):
        return {}


class Sensor(Instrument):
    def __init__(self, attr, name, icon, unit):
        super().__init__(component="sensor", attr=attr, name=name, icon=icon)
        self._unit = unit
        self._convert = False

    def configurate(self, unit_system=None, **config):
        if self._unit and unit_system == "imperial" and "km" in self._unit:
            self._unit = "mi"
            self._convert = True
        elif self._unit and unit_system == "metric" and "mi" in self._unit:
            self._unit = "km"
            self._convert = True

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
        if val and self._unit and "mi" in self._unit and self._convert == True:
            return round(val / 1.609344)
        elif val and self._unit and "km" in self._unit and self._convert == True:
            return round(val * 1.609344)
        else:
            return val

    @property
    def unit(self):
        supported = self._attr + "_unit"
        if hasattr(self._vehicle, supported):
            return getattr(self._vehicle, supported)

        return self._unit


class BinarySensor(Instrument):
    def __init__(self, attr, name, device_class, icon=None):
        super().__init__(component="binary_sensor", attr=attr, name=name, icon=icon)
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
            _LOGGER.error("Can not encode state %s:%s", self._attr, self.state)
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
        return self._vehicle.doors_trunk_status == "Locked"

    @property
    def is_locked(self):
        return self.state

    async def lock(self):
        await self._connection.set_vehicle_lock(self.vehicle_vin, True)

    async def unlock(self):
        await self._connection.set_vehicle_lock(self.vehicle_vin, False)


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


class Preheater(Instrument):
    def __init__(self):
        super().__init__(component="switch", attr="preheater_active", name="Preheater", icon="mdi:radiator")

    @property
    def is_mutable(self):
        return True

    @property
    def str_state(self):
        return "On" if self.state else "Off"

    def is_on(self):
        return self.state

    async def turn_on(self):
        await self._connection.set_vehicle_pre_heater(self.vehicle_vin, True)

    async def turn_off(self):
        await self._connection.set_vehicle_pre_heater(self.vehicle_vin, False)


class Position(Instrument):
    def __init__(self):
        super().__init__(component="device_tracker", attr="position", name="Position")

    @property
    def is_mutable(self):
        return False

    @property
    def state(self):
        state = super().state or {}
        return (
            state.get("latitude", None),
            state.get("longitude", None),
            state.get("timestamp", None),
            state.get("parktime", None),
        )

    @property
    def str_state(self):
        state = super().state or {}
        ts = state.get("timestamp")
        pt = state.get("parktime")
        return (
            state.get("latitude", None),
            state.get("longitude", None),
            str(ts.astimezone(tz=None)) if ts else None,
            str(pt.astimezone(tz=None)) if pt else None,
        )


class TripData(Instrument):
    def __init__(self, attr, name):
        super().__init__(component="sensor", attr=attr, name=name)
        self.unit = None

    @property
    def is_mutable(self):
        return False

    @property
    def str_state(self):
        val = super().state
        txt = ""

        if val["averageElectricEngineConsumption"] is not None:
            txt = "{}{}_kWh__".format(txt, val["averageElectricEngineConsumption"])

        if val["averageFuelConsumption"] is not None:
            txt = "{}{}_ltr__".format(txt, val["averageFuelConsumption"])

        return "{}{}_kmh__{}:{:02d}h_({}_m)__{}_km__{}-{}_km".format(
            txt,
            val["averageSpeed"],
            int(val["traveltime"] / 60),
            val["traveltime"] % 60,
            val["traveltime"],
            val["mileage"],
            val["startMileage"],
            val["overallMileage"],
        )

    @property
    def state(self):
        val = super().state
        return val


class LastUpdate(Instrument):
    def __init__(self):
        super().__init__(
            component="sensor",
            attr="last_update_time",
            name="Last Update",
            icon="mdi:update",
        )
        self.unit = None

    @property
    def is_mutable(self):
        return False

    @property
    def str_state(self):
        ts = super().state
        if type(ts) == datetime:
           return str(ts.astimezone(tz=None)) if ts else None
        return ts

    @property
    def state(self):
        val = super().state
        return val


def create_instruments():
    return [
        Position(),
        LastUpdate(),
        TripData(attr="shortterm_current", name="ShortTerm Trip Data"),
        TripData(attr="shortterm_reset", name="ShortTerm Trip User Reset"),
        TripData(attr="longterm_current", name="LongTerm Trip Data"),
        TripData(attr="longterm_reset", name="LongTerm Trip User Reset"),
        Lock(),
        Preheater(),
        Sensor(attr="model", name="Model", icon="mdi:car-info", unit=None),
        Sensor(attr="mileage", name="Mileage", icon="mdi:speedometer", unit="km"),
        Sensor(attr="range", name="Range", icon="mdi:gas-station", unit="km"),
        Sensor(
            attr="service_inspection_time",
            name="Service inspection time",
            icon="mdi:room-service-outline",
            unit="days",
        ),
        Sensor(
            attr="service_inspection_distance",
            name="Service inspection distance",
            icon="mdi:room-service-outline",
            unit="km",
        ),
        Sensor(
            attr="oil_change_time", name="Oil change time", icon="mdi:oil", unit="days"
        ),
        Sensor(
            attr="oil_change_distance",
            name="Oil change distance",
            icon="mdi:oil",
            unit="km",
        ),
        Sensor(attr="oil_level", name="Oil level", icon="mdi:oil", unit="%"),
        Sensor(
            attr="charging_state",
            name="Charging state",
            icon="mdi:car-battery",
            unit=None,
        ),
        Sensor(
            attr="charging_mode", name="Charging mode", icon=None, unit=None
        ),
        Sensor(
            attr="energy_flow", name="Energy flow", icon=None, unit=None
        ),
        Sensor(
            attr="max_charge_current",
            name="Max charge current",
            icon="mdi:current-ac",
            unit="A",
        ),
        Sensor(
            attr="primary_engine_type",
            name="Primary engine type",
            icon="mdi:engine",
            unit=None,
        ),
        Sensor(
            attr="secondary_engine_type",
            name="Secondary engine type",
            icon="mdi:engine",
            unit=None,
        ),
        Sensor(
            attr="primary_engine_range",
            name="Primary engine range",
            icon="mdi:gas-station-outline",
            unit="km",
        ),
        Sensor(
            attr="secondary_engine_range",
            name="Secondary engine range",
            icon="mdi:gas-station-outline",
            unit="km",
        ),
        Sensor(
            attr="charging_power", name="Charging power", icon="mdi:flash", unit="kW"
        ),
        Sensor(
            attr="actual_charge_rate",
            name="Charging rate",
            icon="mdi:electron-framework",
            unit=None,
        ),
        Sensor(attr="tank_level", name="Tank level", icon="mdi:gas-station", unit="%"),
        Sensor(
            attr="state_of_charge",
            name="State of charge",
            icon="mdi:ev-station",
            unit="%",
        ),
        Sensor(
            attr="remaining_charging_time",
            name="Remaining charge time",
            icon="mdi:battery-charging",
            unit=None,
        ),
        Sensor(attr="plug_state", name="Plug state", icon="mdi:power-plug", unit=None),
        Sensor(
            attr="doors_trunk_status",
            name="Doors/trunk state",
            icon="mdi:car-door",
            unit=None,
        ),
        Sensor(
            attr="climatisation_state",
            name="Climatisation state",
            icon="mdi:air-conditioner",
            unit=None,
        ),
        Sensor(
            attr="outdoor_temperature",
            name="Outdoor Temperature",
            icon="mdi:mdiTemperatureCelsius",
            unit="°C",
        ),
        Sensor(attr="preheater_duration", name="Preheater runtime", icon="mdi:clock", unit="Min"),
        Sensor(attr="preheater_remaining", name="Preheater remaining", icon="mdi:clock", unit="Min"),
        BinarySensor(attr="sun_roof", name="Sun roof", device_class="window"),
        BinarySensor(
            attr="parking_light",
            name="Parking light",
            device_class="safety",
            icon="mdi:lightbulb",
        ),
        BinarySensor(attr="any_window_open", name="Windows", device_class="window"),
        BinarySensor(attr="any_door_unlocked", name="Doors lock", device_class="lock"),
        BinarySensor(attr="any_door_open", name="Doors", device_class="door"),
        BinarySensor(attr="trunk_unlocked", name="Trunk lock", device_class="lock"),
        BinarySensor(attr="trunk_open", name="Trunk", device_class="door"),
        BinarySensor(attr="hood_open", name="Hood", device_class="door"),
    ]


class Dashboard:
    def __init__(self, connection, vehicle, **config):
        self.instruments = [
            instrument
            for instrument in create_instruments()
            if instrument.setup(connection, vehicle, **config)
        ]
