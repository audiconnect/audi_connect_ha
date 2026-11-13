"""Read-only status owner: scheduled polling, family reads and observation mapping."""

from __future__ import annotations

from datetime import UTC, datetime
import time
from typing import Any

from .development_profiles import DevelopmentProfile, render_request
from .transport import V3Response
from .vehicle import V3Vehicle
from .freshness import timestamp_is_fresh, capture_field_timestamp as _captured
from .attribute_runtime import (
    planned_jobs,
    observe_read_only,
    _accept_observation,
    record_invalid_observation,
    record_observation,
    normalize_attribute_value,
)
from .custom_attributes import attributes_for
from .registry import extract_first
from .attribute_routes import get_read_variant
from .historical_catalog import ATTRIBUTES, capture_time, read_path
from .legacy_read_mappings import FIELDS as MBB_FIELDS
from .read_discovery import (
    record_jobs,
    pending_groups,
    reserve_group,
    MAX_EXTRA_INITIAL_REQUESTS,
    MAX_EXTRA_PERIODIC_REQUESTS,
    read_excluded,
)
from .status_planner import status_groups


def identity_refresh_due(
    vehicles, elapsed_seconds, remaining_calls, *, token_renewed=False
):
    """Account-wide read-only inventory recovery; no extra scheduler."""
    if remaining_calls is not None and remaining_calls <= 12:
        return False
    present = [car for car in vehicles.values() if car.inventory_present]
    incomplete = any(
        car.identity_restored
        or not car.image_url
        or not all((car.model, car.model_family, car.model_year, car.car_type))
        for car in present
    )
    return elapsed_seconds >= (1800 if incomplete else 86400) or (
        incomplete and token_renewed
    )


class StatusEngine:
    def __init__(
        self,
        *,
        hass,
        entry,
        auth,
        transport,
        storage,
        vehicles,
        profiles,
        discover,
        known_inventory,
        operation_request,
        api_record,
    ):
        self.hass = hass
        self.entry = entry
        self.auth = auth
        self._transport = transport
        self.storage = storage
        self.vehicles = vehicles
        self.profiles = profiles
        self.discover = discover
        self._inventory_ready = known_inventory
        self._operation_request = operation_request
        self._api_record = api_record
        self.last_cloud_poll_success = None
        self.last_cloud_poll_attempt = None
        self.last_cloud_poll_succeeded = None
        self._poll_cycles = 0
        self._identity_attempt_at = None
        self._identity_session = None
        self._trip_poll_at = {}
        self._legacy_route_backoff = {}

    @property
    def transport(self):
        return self._transport()

    async def _poll_legacy(self, car, profile, cache) -> bool:
        """Normal MBB polling, one GET per resource, with no mutations."""
        from .legacy_read_mappings import ROUTES
        from .legacy_values import observe_legacy
        from .legacy_commands import configure_home_region

        if hasattr(self.transport, "executors"):
            await configure_home_region(self.transport, self.auth, car)
        reachable = False
        for kind, template in ROUTES.items():
            key = (car.vin.lower(), kind)
            if read_excluded(profile, "mbb.discovery." + kind):
                continue
            if self._poll_cycles < self._legacy_route_backoff.get(key, 0):
                continue
            if (
                self.transport.remaining_calls is not None
                and self.transport.remaining_calls <= 12
            ):
                break
            path = template.format(VIN=car.vin, COUNTRY=car.country, TYPE="Audi")
            try:
                response = await self.transport.request("mbb", "GET", path)
            except (RuntimeError, ValueError, OSError, TimeoutError):
                break
            cache[(car.vin.lower(), "mbb", path)] = response
            self._api_record(
                profile, "mbb.discovery." + kind, "mbb", "GET", response, car.vin
            )
            if response.status in (404, 410):
                self._legacy_route_backoff[key] = self._poll_cycles + 96
                continue
            if response.status in (401, 403, 429) or response.status >= 500:
                break
            if not 200 <= response.status < 300:
                continue
            reachable = True
            observe_legacy(car, profile, kind, response)
        return reachable

    async def _poll_trips(self, car: V3Vehicle) -> None:
        """Normal read-only trip data refresh; not a diagnostic probe service.

        Only applicable Auth0 vehicles use the three reviewed routes. The
        shared poll cadence and quota protect the car and account; no extra
        coordinator, user action, raw response storage or invented trip data.
        """
        from .trips import CARIAD_TRIP_OPERATIONS, observe_cariad_trip
        from .attribute_runtime import _capture_in_utc

        remaining = self.transport.remaining_calls
        if remaining is not None and remaining < 20:
            return
        now = time.monotonic()
        key = car.vin.lower()
        last = self._trip_poll_at.get(key)
        profile = self.profiles[key]
        # Retry missing scopes at the ordinary poll cadence, not a 3-hour
        # penalty after a quota/transport/partial-response failure.
        expected = (
            [
                scope
                for op, scope in CARIAD_TRIP_OPERATIONS.items()
                if not read_excluded(profile, op)
            ]
            if car.context.auth != "legacy"
            else ["shortterm_current", "longterm_current"]
        )
        interval = 10800 if all(car.trips.get(scope) for scope in expected) else 900
        if last is not None and now - last < interval:
            return
        self._trip_poll_at[key] = now
        if car.context.auth == "legacy":
            from .trips import normalize_mbb_trips
            from datetime import timedelta
            from urllib.parse import urlencode

            query = urlencode(
                {
                    "type": "list",
                    "from": "1970-01-01T00:00:00Z",
                    "to": (datetime.now(UTC) + timedelta(minutes=90)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                }
            )
            for kind in ("shortTerm", "longTerm"):
                if read_excluded(profile, "mbb.trip." + kind):
                    continue
                try:
                    reply = await self.transport.request(
                        "mbb",
                        "GET",
                        f"/api/bs/tripstatistics/v1/vehicles/{car.vin}/tripdata/{kind}?{query}",
                    )
                except (RuntimeError, ValueError, OSError, TimeoutError):
                    break
                self._api_record(
                    profile, "mbb.trip." + kind, "mbb", "GET", reply, car.vin
                )
                if reply.status in (401, 403, 429) or reply.status >= 500:
                    break
                if not 200 <= reply.status < 300:
                    continue
                for suffix, trip in normalize_mbb_trips(reply.data).items():
                    state_key = kind.lower() + "_" + suffix
                    previous = _capture_in_utc(
                        car.trips.get(state_key, {}).get("timestamp")
                    )
                    incoming = _capture_in_utc(trip.get("timestamp"))
                    if incoming and (not previous or incoming >= previous):
                        car.trips[state_key] = trip
            return
        profile = self.profiles[car.vin.lower()]
        available = (
            profile.registry.resolve("mobility", "status", car.context)[
                "available_operations"
            ]
            if "mobility" in profile.registry.capabilities
            else ()
        )
        for ident in (*CARIAD_TRIP_OPERATIONS, "cariad.mobility.status.tripStatistics"):
            if ident not in available or read_excluded(profile, ident):
                continue
            remaining = self.transport.remaining_calls
            if remaining is not None and remaining <= 12:
                break
            family, method, path, _ = self._operation_request(car, ident)
            try:
                reply = await self.transport.request(family, method, path)
            except (TimeoutError, OSError, RuntimeError, ValueError):
                self._api_record(profile, ident, family, method, None, car.vin)
                break
            self._api_record(profile, ident, family, method, reply, car.vin)
            if reply.status in (401, 403, 429) or reply.status >= 500:
                break
            if 200 <= reply.status < 300:
                if ident == "cariad.mobility.status.tripStatistics":
                    observe_read_only(car, profile, reply.data, reply.observed_at)
                else:
                    observe_cariad_trip(car, ident, reply.data)

    async def poll(self) -> list[V3Vehicle]:
        self.last_cloud_poll_attempt = datetime.now(UTC)
        self.last_cloud_poll_succeeded = False
        self._poll_cycles += 1
        now = time.monotonic()
        initial = not self._inventory_ready()
        session = getattr(self.auth, "session_generation", None)
        if self._identity_attempt_at is None:
            self._identity_attempt_at = now
            self._identity_session = session
        elapsed = now - self._identity_attempt_at
        if initial or identity_refresh_due(
            self.vehicles,
            elapsed,
            self.transport.remaining_calls,
            token_renewed=session is not None and session != self._identity_session,
        ):
            self._identity_attempt_at = now
            try:
                await self.discover()
            except (RuntimeError, ValueError, OSError, TimeoutError):
                if initial:
                    raise
            finally:
                self._identity_session = getattr(self.auth, "session_generation", None)
        cloud_reachable = False
        # Reuse identical GET responses across capabilities on the same car.
        # API family + VIN + exact path is the request identity; a route change
        # must never trigger a second call for a response already in this poll.
        polled_responses: dict[tuple[str, str, str], V3Response] = {}
        for key, vehicle in self.vehicles.items():
            if not vehicle.inventory_present:
                continue
            profile = self.profiles[key]
            if (
                vehicle.context.auth == "legacy"
                and len(profile.registry.capabilities) > 1
            ):
                if vehicle.legacy_cariad and planned_jobs(vehicle, profile):
                    # V2 reads selective-status even on its legacy IDK session.
                    path = f"/vehicle/v1/vehicles/{vehicle.vin}/selectivestatus?jobs={','.join(planned_jobs(vehicle, profile))}"
                    try:
                        reply = await self.transport.request("cariad", "GET", path)
                    except (RuntimeError, ValueError, OSError, TimeoutError):
                        reply = None
                    if reply and 200 <= reply.status < 300:
                        polled_responses[(key, "cariad", path)] = reply
                        observe_read_only(
                            vehicle, profile, reply.data, reply.observed_at
                        )
                        record_jobs(
                            profile,
                            tuple(path.rsplit("jobs=", 1)[-1].split(",")),
                            status=reply.status,
                            payload=reply.data,
                        )
                        cloud_reachable = True
                if await self._poll_legacy(vehicle, profile, polled_responses):
                    cloud_reachable = True
                continue
            for capability, routes, chosen, batch in status_groups(
                profile, vehicle.context
            ):
                attempted_paths: set[str] = set()
                attempted_operations: set[str] = set()
                # Bounded GET discovery, no auto wake and no repeated duplicate URL.
                for ident in routes:
                    # A custom route with user parameters has no safe background
                    # default until its input is explicitly persisted.
                    if profile.custom.get(ident, {}).get("variables"):
                        continue
                    op = profile.registry.operations[ident]
                    if read_excluded(profile, ident):
                        continue
                    if "{JOBS}" in op["path"] and not planned_jobs(vehicle, profile):
                        continue
                    if (
                        "selectivestatus?jobs=" in op["path"]
                        and "{JOBS}" not in op["path"]
                        and profile.job_discovery.get(op["path"].split("jobs=", 1)[1])
                        == "unsupported"
                    ):
                        continue
                    if op["method"] != "GET" or op["family"] not in ("cariad", "mbb"):
                        continue
                    # MBB legacy variants have distinct semantics and may cost a
                    # request each. Never try manual-only endpoints on every poll.
                    if (
                        op["family"] == "mbb"
                        and op.get("delivery") == "manual"
                        and profile.active.get(f"{capability}.status") != ident
                    ):
                        continue
                    family, method, path, _body = self._operation_request(
                        vehicle, ident
                    )
                    # The default targeted climate probe repeats a job already
                    # included in the shared batch. Do not double-poll it merely
                    # because the URL spells the same job list differently.
                    if (
                        capability == "climate"
                        and ident == "cariad.climate.status.probe"
                        and op["path"].endswith("?jobs=climatisation")
                        and batch in attempted_operations
                        and vehicle.climate_state is not None
                    ):
                        continue
                    if path in attempted_paths:
                        continue
                    attempted_paths.add(path)
                    attempted_operations.add(ident)
                    response = polled_responses.get((key, family, path))
                    if response is None:
                        try:
                            response = await self.transport.request(
                                family, method, path
                            )
                        except (TimeoutError, OSError, RuntimeError, ValueError):
                            break  # Auth/transport failure is not proof of unsupported vehicle
                        polled_responses[(key, family, path)] = response
                    self._api_record(
                        profile, ident, family, method, response, vehicle.vin
                    )
                    if 200 <= response.status < 300:
                        cloud_reachable = True
                        if ident == batch and family == "cariad":
                            requested = tuple(path.rsplit("jobs=", 1)[-1].split(","))
                            observe_read_only(
                                vehicle, profile, response.data, response.observed_at
                            )
                            record_jobs(
                                profile,
                                requested,
                                status=response.status,
                                payload=response.data,
                            )
                        elif ident == "mbb.climate.status":
                            # Parse only proven V2 paths; per-attribute activation
                            # remains explicit because MBB timestamps may be absent.
                            for attr, (kind, _field) in MBB_FIELDS.items():
                                if kind == "climater":
                                    self._record_attribute_response(
                                        vehicle,
                                        profile,
                                        attr,
                                        "mbb.climater.readonly",
                                        [_field],
                                        response,
                                    )
                    value, field = profile.registry.extract(ident, response.data)
                    captured = _captured(response.data, field)
                    valid = 200 <= response.status < 300 and value is not None
                    if capability == "climate" and valid:
                        value, issue = normalize_attribute_value(
                            ATTRIBUTES["climatisationState"], value, None
                        )
                        valid = isinstance(value, str) and not issue
                        # Batch and legacy attribute extraction already own their
                        # observations. Only a selected older capability-level
                        # route may supply a fallback, never over an explicit attribute route.
                        if (
                            valid
                            and ident not in (batch, "mbb.climate.status")
                            and chosen == ident
                            and profile.attribute_routes.get("climatisationState")
                            in (None, "cariad.selectivestatus.batch")
                        ):
                            vehicle.set_climate(
                                value,
                                captured,
                                route=ident,
                                path=field,
                                observed_at=response.observed_at,
                                http_status=response.status,
                            )
                    elif valid:
                        if (
                            isinstance(value, str)
                            and value.strip().lower()
                            in (
                                "",
                                "unknown",
                                "invalid",
                                "unsupported",
                                "unavailable",
                                "error",
                            )
                            or isinstance(value, (dict, list))
                            and (
                                not value
                                or isinstance(value, dict)
                                and "error" in value
                            )
                        ):
                            valid = False
                        elif isinstance(value, (str, int, float, bool)):
                            previous = vehicle.capability_readings.get(capability)
                            if _accept_observation(previous, captured):
                                vehicle.capability_readings[capability] = {
                                    "value": value,
                                    "captured": captured,
                                    "observed": response.observed_at.isoformat(),
                                    "operation": ident,
                                    "path": field,
                                }
                    fresh = bool(
                        valid and timestamp_is_fresh(captured, response.observed_at)
                    )
                    profile.record_status(
                        capability,
                        ident,
                        http_status=response.status,
                        schema_valid=valid,
                        fresh=fresh,
                    )
                    if valid:
                        if fresh:
                            if (
                                chosen is None
                                or chosen == ident
                                or chosen not in routes
                            ):
                                profile.choose_working(capability, "status", ident)
                            if (
                                ident != batch
                                or chosen in (None, ident)
                                or len(profile.registry.capabilities) <= 1
                            ):
                                break
                        # A genuine stale capture is not a routing failure. Only
                        # missing timestamp/mapping or an explicitly selected route
                        # warrants further work.
                        if captured is not None and (
                            chosen is None or chosen == ident or chosen not in routes
                        ):
                            break
                        continue
                    if response.status in (401, 403, 429) or response.status >= 500:
                        break
        # Automatic initial CARIAD discovery: the existing 23-job GET handles
        # most fields. If that response missed known mappings, probe at most
        # four small job groups initially, two per later poll across the account.
        # No POST, no wake, no parking coordinates, no unbounded API probing.
        remaining_discovery = (
            MAX_EXTRA_INITIAL_REQUESTS
            if self._poll_cycles == 1
            else MAX_EXTRA_PERIODIC_REQUESTS
        )
        # Rotate the existing account-wide discovery budget across vehicles.
        discovery_keys = list(self.vehicles)
        start = (self._poll_cycles - 1) % len(discovery_keys) if discovery_keys else 0
        for key in discovery_keys[start:] + discovery_keys[:start]:
            car = self.vehicles[key]
            if not car.inventory_present:
                continue
            profile = self.profiles[key]
            if (car.context.auth != "auth0" and not car.legacy_cariad) or len(
                profile.registry.capabilities
            ) <= 1:
                continue  # Pilot-only synthetic tests and legacy cars are unaffected.
            if not profile.job_discovery:
                continue  # No successful bulk GET yet; don't spray blind requests.
            if remaining_discovery <= 0:
                break
            for jobs in pending_groups(profile, max_groups=remaining_discovery):
                remaining_discovery -= 1
                if (
                    self.transport.remaining_calls is not None
                    and self.transport.remaining_calls <= 12
                ):
                    break
                path = f"/vehicle/v1/vehicles/{car.vin}/selectivestatus?jobs={','.join(jobs)}"
                try:
                    response = await self.transport.request("cariad", "GET", path)
                except (TimeoutError, OSError, RuntimeError, ValueError):
                    break
                self._api_record(
                    profile,
                    "cariad.discovery." + "_".join(jobs),
                    "cariad",
                    "GET",
                    response,
                    car.vin,
                )
                if response.status in (401, 403, 429) or response.status >= 500:
                    record_jobs(
                        profile, jobs, status=response.status, payload=response.data
                    )
                    break
                reserve_group(profile, jobs)
                if 200 <= response.status < 300:
                    cloud_reachable = True
                    observe_read_only(car, profile, response.data, response.observed_at)
                record_jobs(
                    profile, jobs, status=response.status, payload=response.data
                )
                polled_responses[(key, "cariad", path)] = response

        # Explicitly selected targeted/custom GET routes are executed separately
        # from the default shared batch, deduplicated across attributes.
        for key, car in self.vehicles.items():
            if not car.inventory_present:
                continue
            profile = self.profiles[key]
            unique: dict[tuple[str, str], list[tuple[str, str, list[str]]]] = {}
            for ident, route in profile.attribute_routes.items():
                if route == "cariad.selectivestatus.batch":
                    continue
                family, path, mappings = self._attribute_request(
                    car, profile, ident, route
                )
                if "selectivestatus?jobs=" in path:
                    jobs = path.rsplit("jobs=", 1)[-1].split(",")
                    if all(
                        profile.job_discovery.get(job) == "unsupported" for job in jobs
                    ):
                        continue
                unique.setdefault((family, path), []).append((ident, route, mappings))
            # Refuse an unbounded per-attribute request explosion.
            routes = list(unique.items())
            start = ((self._poll_cycles - 1) * 4) % len(routes) if routes else 0
            for (family, path), selected in (routes[start:] + routes[:start])[:4]:
                if not (
                    family == ("mbb" if car.context.auth == "legacy" else "cariad")
                    or (family == "cariad" and car.legacy_cariad)
                ):
                    continue
                response = polled_responses.get((key, family, path))
                if response is None:
                    try:
                        response = await self.transport.request(family, "GET", path)
                    except (TimeoutError, OSError, RuntimeError, ValueError):
                        break
                    polled_responses[(key, family, path)] = response
                operations = {
                    get_read_variant(
                        ident, route, profile.attribute_custom, attributes_for(profile)
                    )["evidence_operation"]
                    for ident, route, _ in selected
                }
                for operation in sorted(operations):
                    self._api_record(
                        profile, operation, family, "GET", response, car.vin
                    )
                for ident, route, mappings in selected:
                    self._record_attribute_response(
                        car, profile, ident, route, mappings, response
                    )
                if 200 <= response.status < 300:
                    cloud_reachable = True
        # Retain the V2 GPS tracker contract without adding a new cloud poller.
        # First recovery attempt may be skipped by quota or a context change.
        # Retry missing positions every 4 cycles, while normal reads stay sparse.
        if (
            self._poll_cycles == 1
            or self._poll_cycles % 12 == 0
            or (
                self._poll_cycles % 4 == 0
                and any(
                    car.inventory_present and car.position is None
                    for car in self.vehicles.values()
                )
            )
        ):
            await self._poll_parked_positions()
        self.last_cloud_poll_succeeded = cloud_reachable
        if cloud_reachable:
            self.last_cloud_poll_success = datetime.now(UTC)
            # Existing historical trip entities or explicitly reported trip
            # capabilities opt into this normal data read, not route scanning.
            # Avoid extra requests for vehicles without applicable evidence.
            if hasattr(self.hass, "data"):
                from homeassistant.helpers import entity_registry as er

                registered = {
                    entity.unique_id
                    for entity in er.async_entries_for_config_entry(
                        er.async_get(self.hass), self.entry.entry_id
                    )
                    if entity.domain == "sensor" and entity.disabled_by is None
                }
                for car in self.vehicles.values():
                    if not car.inventory_present:
                        continue
                    profile = self.profiles[car.vin.lower()]
                    prefix = f"{car.vin.lower()}_sensor_"
                    known_trip = any(
                        prefix + key in registered
                        for key in (
                            "shortterm_current",
                            "longterm_current",
                            "last_trip",
                            "shortterm_reset",
                            "longterm_reset",
                        )
                    )
                    capability = bool(
                        {"tripStatistics", "tripData"}
                        & (car.advertised_capabilities - car.impaired_capabilities)
                    )
                    # Trip discovery is a reviewed read-only capability. Fresh
                    # installations need not already have a historical trip entity.
                    if len(profile.registry.capabilities) > 1 and (
                        known_trip
                        or capability
                        or car.context.auth in ("auth0", "legacy")
                    ):
                        await self._poll_trips(car)
        for car in self.vehicles.values():
            if not car.inventory_present:
                continue
            from .freshness import newest_vehicle_capture

            newest = newest_vehicle_capture(car)
            captured = newest.isoformat() if newest else None
            for ident, value, stamp in (
                ("last_update_time", captured, captured),
                ("model", car.model or None, None),
            ):
                if value is not None:
                    car.readings[ident] = {
                        "value": value,
                        "captured": stamp,
                        "observed": datetime.now(UTC).isoformat(),
                        "status": "readable_but_stale",
                        "family": "cariad",
                        "path": "vehicle_capture"
                        if ident == "last_update_time"
                        else "graphql.vehicle.media",
                        "job": None,
                    }
        # The composition root persists status and control bindings together.
        return list(self.vehicles.values())

    def parking_read_allowed(self, car):
        """Same explicit tracker policy for discovery planning and coverage."""
        if not hasattr(self.hass, "data"):
            return None  # Unknown in a synthetic/no-registry context.
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(self.hass)
        tracker = f"{car.vin.lower()}_device_tracker_position"
        return not any(
            entity.domain == "device_tracker"
            and entity.unique_id == tracker
            and entity.disabled_by is not None
            for entity in er.async_entries_for_config_entry(
                registry, self.entry.entry_id
            )
        )

    async def _poll_parked_positions(self) -> None:
        """Infrequent GET for the user's existing Audi parked GPS tracker.

        No coordinates in API evidence, diagnostics or profile storage.
        """
        if not hasattr(self.hass, "data"):
            return  # synthetic test engines without the HA registry
        from .parking import parse_parked_position, keep_newest_position

        for car in self.vehicles.values():
            if not car.inventory_present:
                continue
            if (
                car.context.auth != "auth0" and not car.legacy_cariad
            ) or not self.parking_read_allowed(car):
                continue
            if (
                self.transport.remaining_calls is not None
                and self.transport.remaining_calls <= 12
            ):
                return
            ident = "cariad.mobility.status.parkingPosition"
            profile = self.profiles[car.vin.lower()]
            if ident not in profile.registry.operations or read_excluded(
                profile, ident
            ):
                continue
            family, method, path, _ = self._operation_request(car, ident)
            try:
                reply = await self.transport.request(family, method, path)
            except (TimeoutError, OSError, RuntimeError, ValueError):
                self._api_record(profile, ident, family, method, None, car.vin)
                return
            self._api_record(profile, ident, family, method, reply, car.vin)
            if reply.status in (401, 403, 429) or reply.status >= 500:
                return
            if reply.status == 204:
                # Match historical V2 movement indication, explicitly a
                # parking endpoint signal, not a live location fix.
                car.readings["is_moving"] = {
                    "value": True,
                    "captured": None,
                    "observed": reply.observed_at.isoformat(),
                    "status": "readable_but_stale",
                    "family": "cariad",
                    "path": "parkingposition HTTP 204",
                    "job": None,
                }
                continue
            if not 200 <= reply.status < 300:
                continue
            point = parse_parked_position(reply.data)
            if point and keep_newest_position(car.position, point):
                car.position = point
                stamp = point.get("timestamp")
                car.readings["is_moving"] = {
                    "value": False,
                    "captured": None,
                    "observed": reply.observed_at.isoformat(),
                    "status": "readable_but_stale",
                    "family": "cariad",
                    "path": "parkingposition parked sample",
                    "job": None,
                }
                if stamp:
                    for ident in ("position_last_updated", "park_time"):
                        car.readings[ident] = {
                            "value": stamp,
                            "captured": stamp,
                            "observed": reply.observed_at.isoformat(),
                            "status": "readable_but_stale",
                            "family": "cariad",
                            "path": "parkingposition.data.carCapturedTimestamp",
                            "job": None,
                        }

    def _attribute_request(
        self,
        car: V3Vehicle,
        profile: DevelopmentProfile,
        attribute: str,
        operation: str,
    ) -> tuple[str, str, list[str]]:
        route = get_read_variant(
            attribute, operation, profile.attribute_custom, attributes_for(profile)
        )
        jobs = list(planned_jobs(car, profile))
        required = attributes_for(profile)[attribute]["job"]
        # Manual discovery must include its own job even when pruned from polling.
        if required and required not in jobs:
            jobs.append(required)
        request = render_request(
            route,
            vehicle_values={
                "VIN": car.vin,
                "TYPE": "Audi",
                "COUNTRY": car.country,
                "JOBS": ",".join(jobs),
            },
            experimental=route.get("kind") == "custom",
        )
        return request["family"], request["relative_path"], route["response_paths"]

    def _record_attribute_response(
        self,
        car: V3Vehicle,
        profile: DevelopmentProfile,
        attribute: str,
        operation: str,
        mappings: list[str],
        response: V3Response,
        *,
        publish: bool = True,
    ) -> dict[str, Any]:
        publish = publish and profile.attribute_routes.get(attribute) in (
            None,
            operation,
        )
        raw, matched_path = extract_first(response.data, mappings)
        field = matched_path or mappings[0]
        variant = get_read_variant(
            attribute, operation, profile.attribute_custom, attributes_for(profile)
        )
        family = variant["family"]
        definition = attributes_for(profile)[attribute]
        value, issue = normalize_attribute_value(
            definition, raw, variant.get("conversion")
        )
        captured = (
            (
                read_path(response.data, variant["capture_path"])
                if variant.get("capture_path")
                else capture_time(response.data, field)
            )
            if matched_path is not None
            else None
        )
        if not isinstance(captured, str):
            captured = None
        if publish and issue and 200 <= response.status < 300:
            active = profile.attribute_routes.get(attribute)
            if active == operation or active is None:
                record_invalid_observation(
                    car,
                    attribute,
                    captured,
                    response.observed_at,
                    field,
                    definition["job"],
                    issue,
                    family,
                )
            value = None
        fresh = timestamp_is_fresh(captured, response.observed_at)
        if not 200 <= response.status < 300:
            outcome = "api_error"
        elif value is None:
            outcome = "mapping_missing"
        else:
            outcome = "verified" if fresh else "readable_but_stale"
        profile.attribute_route_evidence.setdefault(attribute, {})[operation] = {
            "outcome": outcome,
            "path": field,
            "http_status": response.status,
        }
        if publish and 200 <= response.status < 300 and value is not None:
            record_observation(
                car,
                profile,
                attribute,
                value,
                captured,
                response.observed_at,
                field,
                definition["job"],
                family,
                fresh=fresh,
                operation=variant["evidence_operation"],
            )
        return {
            "attribute": attribute,
            "route": operation,
            "operation": variant["evidence_operation"],
            "result": outcome,
            "http_status": response.status,
            "mapping": field,
            "captured": captured,
            "value": value if isinstance(value, (str, int, float, bool)) else None,
        }
