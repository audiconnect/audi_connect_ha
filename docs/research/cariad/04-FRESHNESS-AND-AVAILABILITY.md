# 04 — Parked-Car Latency, Observation Freshness and Availability

## Real-world requirement: an Audi can be stale for days

**Owner-observed behavior:** when this Audi is parked, new vehicle data may appear **hours or even days later**. This is a primary requirement, not an edge case. Treat the old OEM value as an old observation, never as a current measurement.

A 15-minute schedule describes **the frequency of requests/deliveries**, not vehicle reporting. Likewise, a successful HA polling cycle does **not** prove any underlying vehicle measurement changed.

## Canonical observation record (proposed)

```python
@dataclass(frozen=True)
class VehicleObservation:
    field: str
    value: object | None
    unit: str | None
    source: str                      # audi_bff | legacy_mbb | data_act
    observed_at: datetime | None     # on-vehicle/provider captured time
    delivered_at: datetime | None    # API response or ZIP timestamp, if known
    fetched_at: datetime             # integration poll time
    status: str                      # valid | missing | stale | invalid | error
    supported: bool | None           # True | False | Unknown
    source_detail: str | None = None # endpoint + job, sanitized
```

These exact class/field names are a design suggestion; preserve existing public HA entity IDs.

### Never collapse distinct timestamps

- `observed_at` means **the time of the actual car reading**, if the API exposes it.
- `delivered_at` means **when the cloud made this payload available**, not when the vehicle woke.
- `fetched_at` means **when HA received it**.
- `freshness_age = now - observed_at`, **only when observed_at is known**.
- `ingestion_lag = delivered_at - observed_at` where both are known.
- `poll_lag = fetched_at - delivered_at` where both are known.

If the car timestamp is absent, show **unknown observation age** rather than `fresh`.

## Proposed state model

| State | Meaning | HA representation |
| --- | --- | --- |
| **Current observation** | Captured recently by the vehicle under a documented field-specific criterion | Normal numeric/state value + last captured timestamp |
| **Last known / stale** | Value is valid historical information but old | Preserve value when semantically safe, expose captured timestamp, freshness and source; never call it live |
| **No observation yet** | No valid value ever received | `unknown` / entity unavailable as appropriate, not 0 |
| **Not supported** | Firm evidence that the car lacks this feature | Capability-based entity visibility; avoid oscillation |
| **Cloud temporarily unavailable** | Requests failing but cached last reading exists | Keep last-known history and record upstream failure; distinguish stale from unsupported |
| **Command pending / unconfirmed** | API accepted a remote action but no vehicle readback yet | Expose unconfirmed status, not "success" |
| **Portal empty delivery** | A new 15-minute ZIP arrived with no data | Track delivery event without updating any vehicle observation |

**Caution:** Home Assistant state availability is entity- and feature-dependent. A safety-sensitive lock or charging-status control may need `unavailable`/uncertain even if a last-known value exists, while mileage or a trip aggregate can retain its historical value. Do not use one indiscriminate stale policy.

## Different semantic freshness expectations

| Type | If car is parked for 2 days | Recommended behavior |
| --- | --- | --- |
| Odometer | Last value is still informative but not a guaranteed current reading | Show last-known, time and age |
| Trip record | Historical event is inherently timestamped | Keep history; do not fabricate new trip |
| Fuel/battery SoC | Last-known SoC may be useful, but could have changed off-platform | Label stale and prevent unsafe automations |
| Lock/door/window | Old status **must not be claimed as current security status** | Unknown/uncertain for safety decisions; show last-known separately |
| Charging power/state | Old power reading must not be represented as charging now | Current state unknown; optionally preserve last measured power in diagnostics |
| Parking position | Last reported coordinates are not a live vehicle location | Last known parking position + timestamp, never assume "vehicle moving" from HTTP 204 |
| Data Act ZIP arrival time | Fresh ZIP may contain stale values | Never update observed_at using ZIP time |

### Suggested configurable policies, **not OEM guarantees**

Avoid one universal cutoff. Proposed defaults can be adjusted by domain and actual user needs:

- `security_currentness`: conservative threshold; if exceeded, control decisions must use unknown/refresh rather than last-known locked status.
- `charging_currentness`: conservative threshold for live power / active charging control.
- `informational_last_known`: retain historical vehicle values for days, with explicit freshness indicator.
- `trip_event_retention`: history remains valid indefinitely unless source data is corrected/deleted.
- `data_act`: never infer fresh from schedule; require a source timestamp, or present unknown freshness.

Do **not** equate sleep state with permanent unsupported feature. Never wake the car automatically because a reading crossed a chosen threshold.

## Merge algorithm for multiple authorized sources

1. Match by **semantic field** and normalized unit, e.g., `fuel_percent` vs `battery_12v_percent` are *not* equivalent.
2. Use the timestamp on the individual source reading, not dataset/response receipt time.
3. Disallow overwriting a newer observation with an older one.
4. Distinguish better quality/semantics: `shortterm_aggregate` is not a `last_trip` event.
5. Preserve original source, old/new timestamp, field status and conversion provenance.
6. Log a sanitized **drift event** if sources disagree materially at overlapping observed times; never silently pick whichever poll was last.
7. A command response is not an observation of completed vehicle state.

## Regression tests specifically required

- Parked vehicle, same `carCapturedTimestamp` for **72 hours** despite successful BFF polls -> data remains last-known/stale, no false fresh timestamp.
- Fifteen-minute portal ZIPs generated for 72 hours, all empty -> no value reset, no fake readings and visible diagnostics.
- New Data Act ZIP carrying observation from two days earlier -> not preferred over a BFF observation from an hour ago.
- BFF returns HTTP 207 with some jobs at newer timestamps, others old -> update only valid newer jobs.
- `parkingposition` returns 204 after a real parked-car report -> do not derive moving state.
- A charger reads 2 kW historically but car is now asleep -> don't present 2 kW as current charging power.
- Vehicle status `0` is real only when the OEM reported zero, not when parsing failed.
- Timestamps from different time zones, naive and aware -> normalize to UTC safely.
- Cached stale lock/door data must not enable dangerous automation based on assumed "currently locked".
- Stop/unlock/wake commands are not triggered by freshness maintenance.

## User experience

The vehicle diagnostics should expose **last vehicle update**, **last successful cloud retrieval**, **last EU Data Act delivery**, **last non-empty EU Data Act dataset**, **oldest/newest field capture times**, and **source of selected measurements**.

A concise message could be:

> **Vehicle data last reported 2 days ago.** Audi Connect checked the cloud 4 minutes ago. The vehicle appears parked/asleep; the last reported values remain available as historical information.

Only mention parked/asleep if actually supported by a recent OEM status; otherwise say `no newer vehicle observation has been received`.

See [03 — EU Data Act](03-EU-DATA-ACT.md) and [06 — Engineering Playbook](06-ENGINEERING-PLAYBOOK.md).