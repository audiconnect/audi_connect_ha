# Entity Architecture Restructuring — Audit & Migration Plan

## Part 1: Audit of Current Entity Architecture

### Overview

The integration (`audiconnect`) currently uses a custom **Instrument pattern** for entity
definition and state management. While functional, this pattern deviates significantly from
modern Home Assistant conventions. This audit identifies each non-standard pattern and its
impact.

---

### Finding 1: Custom Instrument Pattern Instead of EntityDescription

**Current state:** Entities are defined via a class hierarchy in `audi_services.py`:
`Instrument` → `Sensor`, `BinarySensor`, `Switch`, `Lock`, `Position`, `TripData`, etc.
Each subclass encapsulates both _metadata_ (name, icon, unit, device_class) and _runtime
state access_ (reading from the vehicle object, executing commands).

All entities are declared in `create_instruments()` which returns ~60 instrument instances.
`Dashboard` filters these by `is_supported` at setup time.

**HA standard:** Modern integrations use frozen `EntityDescription` dataclasses
(`SensorEntityDescription`, `BinarySensorEntityDescription`, etc.) for static metadata.
State access is handled directly by the entity class reading from the coordinator's data.
Descriptions are pure data; they carry no references to runtime objects.

**Impact:** The instrument objects hold mutable references to `_vehicle` and `_connection`,
making them stateful singletons tied to a specific vehicle lifecycle. This couples entity
metadata to runtime state, making the code harder to reason about, test, and extend.

---

### Finding 2: Entities Delegate Everything to Instruments

**Current state:** Entity classes like `AudiSensor` delegate virtually all properties to
`self._instrument`:

```python
class AudiSensor(AudiEntity, SensorEntity):
    @property
    def native_value(self):
        return self._instrument.state  # reads from vehicle via instrument
    @property
    def native_unit_of_measurement(self):
        return self._instrument.unit
    @property
    def device_class(self):
        return self._instrument.device_class
```

**HA standard:** Entity classes should either:

- Set `_attr_*` attributes (e.g., `_attr_device_class`) from `EntityDescription`, or
- Access coordinator data directly for dynamic values.

**Impact:** The entity classes are hollow shells. All logic, including command execution
(lock/unlock, switch on/off, preheater control), lives in the instrument layer. This is an
unnecessary indirection that makes the entity classes harder to understand and maintain.

---

### Finding 3: No `translation_key` Usage

**Current state:** Entity names are hardcoded English strings set via `_attr_name`:
`"State of charge"`, `"Mileage"`, `"Doors/trunk state"`, etc.

**HA standard:** Entity names should use `translation_key` to support localization. The
entity name is then defined in `strings.json` under `entity.<platform>.<key>.name`.

**Impact:** The integration cannot be localized. This is a quality-of-life issue rather
than a breaking one.

---

### Finding 4: Inconsistent API Rate Limit Sensor

**Current state:** `AudiApiRateLimitSensor` in `sensor.py`:

- Bypasses `AudiEntity` entirely, inheriting directly from `CoordinatorEntity`
- Duplicates `device_info` logic from `AudiEntity`
- Uses `entry_id` in unique_id (`{entry_id}_api_requests_remaining`) instead of VIN
- Accesses internal API state via deep attribute chain:
  `coordinator.account.connection._audi_service._api.vcf_remaining_calls`

**HA standard:** All entities for a domain should ideally share a common base class pattern.
Diagnostic sensors should follow the same structure as other entities.

**Impact:** This entity is structurally inconsistent. Its unique_id format differs from
all other entities, and it reaches deep into private attributes for its state.

---

### Finding 5: `VehicleData` Acts as Entity Collection Container

**Current state:** `VehicleData` in `audi_models.py` holds sets of instrument objects:

```python
class VehicleData:
    def __init__(self, config_entry):
        self.sensors: set[Any] = set()
        self.binary_sensors: set[Any] = set()
        self.switches: set[Any] = set()
        self.device_trackers: set[Any] = set()
        self.locks: set[Any] = set()
```

`AudiAccount._build_vehicle_data()` creates a `Dashboard`, iterates instruments, and
dispatches them into these sets by component type.

**HA standard:** Entity descriptions are static and defined at module level. The platform
`async_setup_entry` function filters descriptions based on what the vehicle supports.
There's no need for a separate entity-collection object.

**Impact:** The `Dashboard` → `VehicleData` → platform setup pipeline adds unnecessary
complexity. Entity discovery is a multi-step process that could be a simple list
comprehension.

---

### Finding 6: Instrument Action Methods Mix Concerns

**Current state:** Lock and switch instruments contain async command methods:

```python
class Lock(Instrument):
    async def lock(self):
        await self._connection.set_vehicle_lock(self.vehicle_vin, True)

class Preheater(Instrument):
    async def turn_on(self):
        await self._connection.set_vehicle_pre_heater(self.vehicle_vin, True)
```

**HA standard:** Command execution should live in the entity class or be delegated to a
coordinator/API client. Entity descriptions should be inert data objects.

**Impact:** The instrument layer becomes an unnecessary intermediary between the entity
and the API client for commands.

---

### Finding 7: Icon Definitions via Properties

**Current state:** Icons are stored in instruments and exposed via properties. The base
`AudiEntity` has an `icon` property that delegates to `self._instrument.icon`.

**HA standard:** Modern HA is moving toward `_attr_icon` set from EntityDescription, or
icon translations in `icons.json`. Setting icons via properties works but is the older
pattern.

**Impact:** Minor. The current approach works, but EntityDescription would be cleaner.

---

### What Is Already Correct

The integration does several things well:

- `_attr_has_entity_name = True` is set correctly on the base entity
- Device identifiers use `(DOMAIN, vin.lower())` — clean and stable
- `CoordinatorEntity` pattern is used correctly with a proper `DataUpdateCoordinator`
- Config entry version is already at 2 with proper v1→v2 migration
- Platform setup follows the correct `async_setup_entry` signature
- Service registration is multi-account safe
- Orphaned device cleanup is implemented

---

## Part 2: Migration Plan

### Guiding Principles

1. **Zero entity disruption**: Unique IDs, device identifiers, and entity registry entries
   must be preserved exactly. No entity should disappear, duplicate, or lose history.
2. **Incremental stages**: Each stage leaves the integration fully functional.
3. **No config entry version bump needed**: The version is already 2. Entity registry
   migration is not required because unique IDs are not changing.

### Unique ID Preservation Strategy

Current unique ID formula:

```
{vehicle_vin.lower()}_{instrument.component}_{instrument.slug_attr}
```

Where `slug_attr` = `camel2slug(attr.replace(".", "_"))` and `camel2slug` converts
camelCase to snake_case.

The new EntityDescription-based entities will use the exact same formula:

```
{vin.lower()}_{platform}_{description.key}
```

Where `description.key` is set to the same `slug_attr` value that instruments produce.
This is verified by ensuring every EntityDescription's `key` matches the instrument's
`slug_attr` output for the same attribute.

**API Rate Limit Sensor** unique ID `{entry_id}_api_requests_remaining` is preserved as-is.

### Device Info Preservation

Device identifiers `(DOMAIN, vin.lower())` are unchanged. The `device_info` property
in the base entity class continues to use the same format.

---

### Phase 1: Create EntityDescription Infrastructure

**Files changed:** New `descriptions.py` file.

**What:**

- Define `AudiSensorEntityDescription(SensorEntityDescription)` with an additional `value_fn`
  field (a callable that extracts the state from a Vehicle object) and `attr_key` (the
  original attribute name for support-checking).
- Similarly for `AudiBinarySensorEntityDescription`, `AudiSwitchEntityDescription`,
  `AudiLockEntityDescription`, `AudiDeviceTrackerEntityDescription`.
- Transcribe every instrument from `create_instruments()` into a corresponding
  `EntityDescription` tuple, ensuring `key` matches the instrument's `slug_attr`.

**Why:** This establishes the new metadata layer without touching any existing code.
The integration continues to work unchanged with the old instrument path.

**Verification:** The `key` field of each description matches the `slug_attr` that the
corresponding instrument would produce. This is the unique_id anchor.

---

### Phase 2: Refactor Sensor Platform

**Files changed:** `sensor.py`, `audi_entity.py`

**What:**

- Replace `AudiSensor`'s delegation to `_instrument` with direct reads from the vehicle
  object using `entity_description.value_fn(vehicle)`.
- `AudiSensor.__init__` takes `(coordinator, description, vehicle)` instead of
  `(coordinator, instrument)`.
- `unique_id` = `f"{vin.lower()}_sensor_{description.key}"` — identical output.
- `device_info` uses vehicle properties directly.
- `async_setup_entry` iterates `SENSOR_DESCRIPTIONS`, filters by vehicle support,
  creates `AudiSensor` instances.
- `AudiApiRateLimitSensor` is converted to use a description but retains its special
  unique_id format (`{entry_id}_api_requests_remaining`).

**Why:** Sensor is the largest platform (~30 entities) and proves the pattern works.

---

### Phase 3: Refactor Binary Sensor Platform

**Files changed:** `binary_sensor.py`

**What:**

- Same pattern as Phase 2. `AudiBinarySensor` uses `BinarySensorEntityDescription`
  with `value_fn` for `is_on`.
- Entity names and keys match existing instruments exactly.

---

### Phase 4: Refactor Switch, Lock, Device Tracker Platforms

**Files changed:** `switch.py`, `lock.py`, `device_tracker.py`

**What:**

- **Switch:** Description includes `turn_on_fn` and `turn_off_fn` callables that
  invoke the connection API. The entity class calls these instead of delegating to
  an instrument.
- **Lock:** Same pattern with `lock_fn` and `unlock_fn`.
- **Device Tracker:** Description for the Position entity. Coordinate extraction
  logic moves from the instrument to the entity class.

---

### Phase 5: Clean Up Legacy Code

**Files changed:** Remove `audi_services.py`, `dashboard.py`. Simplify `audi_account.py`,
`audi_models.py`, `audi_entity.py`.

**What:**

- `audi_services.py` (Instrument class hierarchy) is deleted — all metadata now lives
  in `descriptions.py`.
- `dashboard.py` (Dashboard class) is deleted — entity filtering is done in platform
  setup.
- `VehicleData` is simplified: it no longer holds entity sets, just the vehicle reference.
- `AudiAccount._build_vehicle_data()` is simplified: no more Dashboard/instrument creation.
- `AudiEntity` base class is updated to work with EntityDescription + vehicle directly.

**Why:** Removes all vestigial code from the instrument pattern.

---

### Phase 6: Add Translation Keys (Optional Enhancement)

**Files changed:** `strings.json`, entity classes.

**What:**

- Add `translation_key` to each entity description.
- Add corresponding entries in `strings.json` under `entity.<platform>.<key>.name`.
- Remove hardcoded `_attr_name` from entity classes (HA derives name from translation).

**Why:** Aligns with modern HA localization standards. This is optional but recommended
as part of the v2 modernization.

---

### What Does NOT Change

| Aspect                  | Status              |
| ----------------------- | ------------------- |
| Unique IDs              | Preserved exactly   |
| Device identifiers      | Preserved exactly   |
| Entity registry entries | No migration needed |
| Config entry version    | Stays at 2          |
| `async_migrate_entry`   | No changes needed   |
| Coordinator pattern     | Unchanged           |
| Service registration    | Unchanged           |
| Config flow             | Unchanged           |
| API client layer        | Unchanged           |

---

### Risk Assessment

| Risk                                    | Mitigation                                                                |
| --------------------------------------- | ------------------------------------------------------------------------- |
| Unique ID mismatch                      | Each description's `key` is verified against the instrument's `slug_attr` |
| Missing entity after migration          | Support-checking logic is preserved (same attribute checks)               |
| Behavioral regression in switches/locks | Command functions are moved to entity class, calling same API methods     |
| API Rate Limit sensor disruption        | Special unique_id format is preserved explicitly                          |
| State value differences                 | `value_fn` callables replicate exact instrument state logic               |
