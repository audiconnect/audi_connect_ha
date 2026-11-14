"""V3 composition root, public runtime facade and profile orchestration.

No V2 account, vehicle model, legacy service calls, or V2 coordinator imports.
The auth facade is the only bridge to existing Audi credential code.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from .auth import V3Auth, configured_spin, redaction_context
from .action_discovery import validate_approval
from .command_engine import CommandEngine
from .command_parameters import runtime_ready
from .status_engine import StatusEngine
from .development_profiles import DevelopmentProfile, DevelopmentProfileError
from .profile_store import V3ProfileStorage
from .trip_archive import V3TripArchive
from .response_preview import (
    engineering_response,
    MAX_ENGINEERING_ROUTES,
    MAX_ENGINEERING_HISTORY,
)
from .api_observations import record_for, save_record, save_execution_review
from .registry import CapabilityRegistry, selective_status_path
from .product_contract import entity_projection_report
from .transport import GARAGE_OPERATION, V3Response, V3Transport, INVENTORY_OPERATION
from .vehicle import V3Vehicle
from .attribute_runtime import planned_jobs
from .custom_attributes import (
    MAX_CUSTOM_ATTRIBUTES,
    attributes_for,
    descriptor,
    validate_definition,
)
from .attribute_routes import (
    get_read_variant,
    read_variants,
    validate_custom_read_route,
)
from .legacy_read_mappings import read_routes
from .historical_catalog import V2_JOBS
from .read_discovery import (
    record_jobs,
    pending_groups,
    reserve_group,
    full_read_plan,
    summary as discovery_summary,
)
from ..const import (
    CONF_FILTER_VINS,
    CONF_REFRESH_AFTER_ACTION,
    CONF_UPDATE_SLEEP,
    DOMAIN,
    REFRESH_VEHICLE_DATA_COMPLETED_EVENT,
    REFRESH_VEHICLE_DATA_FAILED_EVENT,
    UPDATE_SLEEP,
)

_LOGGER = logging.getLogger(__name__)


class V3Engine:
    """One entry, one V3 session, one poller and independently editable profiles."""

    def __init__(
        self,
        hass: Any,
        entry: Any,
        registry: CapabilityRegistry,
        *,
        auth: V3Auth | None = None,
        transport: V3Transport | None = None,
        storage: V3ProfileStorage | None = None,
    ):
        self.hass, self.entry, self.registry = hass, entry, registry
        self.auth = auth or V3Auth(hass, entry)
        self.transport = transport or V3Transport(hass, self.auth)
        self.storage = storage or V3ProfileStorage(hass, entry.entry_id)
        self.trip_archive = (
            V3TripArchive(hass, entry.entry_id) if storage is None else None
        )
        self.vehicles: dict[str, V3Vehicle] = {}
        self.profiles: dict[str, DevelopmentProfile] = {}
        self._known_vehicle_inventory = False
        from .integration_health import IntegrationHealth

        self.health = IntegrationHealth()
        self.cloud_refresh_vin: str | None = None
        self.projected_entities: dict[str, set[str]] = {}
        self.commands = CommandEngine(
            auth=self.auth,
            transport=lambda: self.transport,
            storage=self.storage,
            profiles=self.profiles,
            require_vehicle=self.require_vehicle,
            operation_request=self._operation_request,
            api_record=self._api_record,
            notify=self._notify_discovery_change,
        )
        self.status = StatusEngine(
            hass=hass,
            entry=entry,
            auth=self.auth,
            transport=lambda: self.transport,
            storage=self.storage,
            vehicles=self.vehicles,
            profiles=self.profiles,
            discover=self.discover,
            known_inventory=lambda: self._known_vehicle_inventory,
            operation_request=self._operation_request,
            api_record=self._api_record,
            notify=self._notify_discovery_change,
            apply_identity=self._apply_identity_candidate,
        )

    @property
    def last_cloud_poll_success(self):
        return self.status.last_cloud_poll_success

    @property
    def last_cloud_poll_attempt(self):
        return self.status.last_cloud_poll_attempt

    @property
    def last_cloud_poll_succeeded(self):
        return self.status.last_cloud_poll_succeeded

    def _rebind_identity_context(self, vehicle, profile, old_context):
        if profile is not None and vehicle.context != old_context:
            profile.rebind_context(vehicle.context)
            vehicle.advertised_capabilities.clear()
            vehicle.impaired_capabilities.clear()
            # A newly resolved manufacturer label/type does not change the
            # identity of this VIN or its measured telemetry. Invalidate
            # control applicability, not the last-known vehicle measurements.
            context = vehicle.context
            metadata_refined = (
                context.auth == old_context.auth
                and context.region == old_context.region
                and context.legacy_cariad == old_context.legacy_cariad
                and context.legacy_api_level == old_context.legacy_api_level
                and old_context.vehicle_type in ("", context.vehicle_type)
                and old_context.model_family in ("", context.model_family)
            )
            if not metadata_refined:
                vehicle.readings.clear()
                vehicle.family_readings.clear()
                vehicle.position = None
            vehicle.capability_readings.clear()
            vehicle.charging_profiles.clear()
            vehicle.active_charging_profile_id = None
            vehicle.charging_profiles_captured = None
            # Completed trip snapshots are VIN-scoped historical facts.
            # A refined model/auth context invalidates control evidence, not trips.
            self.status.invalidate_trip_poll(vehicle.vin)

    def _apply_identity_candidate(
        self, car, profile, candidate, operation, observed_at, *, fill_missing=False
    ):
        """Apply only fresh, same-vehicle reviewed manufacturer metadata."""
        from .identity_cache import capture_identity

        if (
            candidate is None
            or candidate.vin.lower() != car.vin.lower()
            or candidate.country != car.country
            or not (candidate.model or (fill_missing and candidate.model_year))
        ):
            return False
        if fill_missing:
            if (
                car.model_family
                and candidate.model_family
                and car.model_family != candidate.model_family
            ):
                return False
            old_context = car.context
            previous = (car.model, car.model_year)
            car.merge_identity_evidence(candidate, operation=operation)
            if previous == (car.model, car.model_year):
                return False
            if not previous[0] and car.model:
                car.identity_restored = False
                car.identity_observed_at = observed_at.isoformat()
            self._rebind_identity_context(car, profile, old_context)
            identity = capture_identity(car)
            if identity:
                profile.manufacturer_identity = identity
            self.health.observe_inventory(self, car)
            return True
        if car.model and not car.identity_restored and car.model != candidate.model:
            return False  # Do not replace a current canonical label with conflicting metadata.
        old_context = car.context
        if car.model and car.model != candidate.model:
            car.image_url = None
            car.image_status = "not_assessed"
        car.model = candidate.model
        car.model_family = candidate.model_family
        car.model_source = candidate.model_source
        car.identity_restored = False
        car.identity_observed_at = observed_at.isoformat()
        car.identity_operation = operation
        if candidate.model_year:
            car.model_year = candidate.model_year
            car.year_operation = operation
        if candidate.car_type:
            car.car_type = candidate.car_type
        if car.name == "Audi vehicle":
            car.name = car.model
        self._rebind_identity_context(car, profile, old_context)
        identity = capture_identity(car)
        if identity:
            profile.manufacturer_identity = identity
        return bool(identity)

    async def discover(self) -> None:
        """Own vehicle discovery. No V2 vehicle updates or extra poll task."""
        found = await self.transport.discover_vehicles()
        inventory_operation = getattr(
            self.transport, "last_inventory_operation", INVENTORY_OPERATION
        )
        garage = inventory_operation == GARAGE_OPERATION
        options = getattr(self.entry, "options", {})
        data = getattr(self.entry, "data", {})
        excluded = {
            x.strip().lower()
            for x in str(
                options.get(CONF_FILTER_VINS, data.get(CONF_FILTER_VINS, ""))
            ).split(",")
            if x.strip()
        }
        known: dict[str, V3Vehicle] = {}
        inventory_items = {}
        complete = bool(found) and getattr(
            self.transport, "last_inventory_complete", True
        )
        for item in found:
            try:
                parser = V3Vehicle.from_garage if garage else V3Vehicle.from_graphql
                parsed = parser(item, self.auth.country)
            except (ValueError, TypeError, AttributeError):
                complete = False
                continue
            if parsed.vin.lower() in excluded:
                continue
            from .identity_cache import apply_cached_identity

            if parsed.vin.lower() not in self.vehicles:
                loader = getattr(self.storage, "async_identity", None)
                if loader is not None:
                    apply_cached_identity(
                        parsed, await loader(parsed.vin.lower(), parsed.country)
                    )
            vehicle = self.vehicles.get(parsed.vin.lower(), parsed)
            old_context = vehicle.context
            if parsed.model and not parsed.identity_restored:
                if vehicle.model and vehicle.model != parsed.model:
                    vehicle.image_url = None
                    vehicle.image_status = "not_assessed"
                vehicle.identity_restored = False
                vehicle.identity_observed_at = datetime.now(UTC).isoformat()
                vehicle.identity_operation = (
                    parsed.identity_operation or inventory_operation
                )
                vehicle.model = parsed.model
                vehicle.model_source = parsed.model_source
                vehicle.model_family = parsed.model_family
            elif vehicle.model and vehicle.model_source != "eu_data_act_modelName":
                vehicle.identity_restored = True
            if parsed.car_type:
                vehicle.car_type = parsed.car_type
            if parsed.model_year:
                vehicle.model_year = parsed.model_year
                vehicle.year_operation = (
                    parsed.year_operation
                    or parsed.identity_operation
                    or inventory_operation
                )
            vehicle.country = parsed.country
            if not vehicle.model and self.trip_archive is not None:
                from .identity_cache import previous_registry_model

                vehicle.registry_model = previous_registry_model(
                    self.hass, self.entry, vehicle.vin
                )
            vehicle.inventory_present = True
            vehicle.inventory_misses = 0
            vehicle.name = (
                parsed.name
                if parsed.name != "Audi vehicle"
                else vehicle.model or parsed.name
            )
            vehicle.auth_family = "auth0" if self.auth.uses_auth0 else "legacy"
            vehicle.legacy_cariad = not self.auth.uses_auth0 and bool(
                getattr(self.auth, "has_cariad_bearer", False)
            )
            vehicle.legacy_api_level = getattr(self.auth, "legacy_api_level", 0)
            profile = self.profiles.get(parsed.vin.lower())
            self._rebind_identity_context(vehicle, profile, old_context)
            known[parsed.vin.lower()] = vehicle
            inventory_items[parsed.vin.lower()] = item
        # An empty or malformed inventory cannot revoke a vehicle. Require two
        # complete nonempty snapshots, or an explicit local VIN exclusion.
        for key, car in self.vehicles.items():
            if key in excluded:
                car.inventory_present = False
            elif key not in known and complete:
                car.inventory_misses += 1
                if car.inventory_misses >= 2:
                    car.inventory_present = False
        if not known:
            if found and excluded:
                self._known_vehicle_inventory = True
                return
            # Empty response might be a cloud bug or loss of scopes. Never
            # delete HA devices or learned API profiles based on an empty poll.
            if not self._known_vehicle_inventory:
                raise RuntimeError("V3 did not receive a usable vehicle inventory")
            return
        # Returning/new cars must restore saved evidence, not start blank.
        missing = {
            vin: car.context for vin, car in known.items() if vin not in self.profiles
        }
        if missing:
            self.profiles.update(await self.storage.async_load(self.registry, missing))
        if self.trip_archive is not None and missing:
            try:
                await self.trip_archive.restore({key: known[key] for key in missing})
            except (OSError, ValueError):
                _LOGGER.warning("Unable to restore private Audi trip archive")
        from .identity_cache import capture_identity

        for key, car in known.items():
            identity = capture_identity(car)
            if identity:
                self.profiles[key].manufacturer_identity = identity
        self.vehicles.update(known)
        self._known_vehicle_inventory = True
        for car in known.values():
            self.health.observe_inventory(self, car)
        metadata = getattr(self.transport, "last_inventory_metadata", None)
        if metadata is not None:
            for vin, item in inventory_items.items():
                # The exact decoded row for this vehicle only. Do not expose
                # another vehicle's inventory even in an admin inspector.
                errors = getattr(self.transport, "last_inventory_errors", {}).get(
                    vin, []
                )
                response = V3Response(
                    metadata.status,
                    {"data": [item]}
                    if garage
                    else {"data": {"userVehicles": [item]}, "errors": errors},
                    metadata.observed_at,
                    metadata.remaining_calls,
                    metadata.request,
                )
                if garage:
                    from .transport import selected_garage_response

                    response = selected_garage_response(response, known[vin].vin)
                self._api_record(
                    self.profiles[vin],
                    inventory_operation,
                    "cariad" if garage else "graphql",
                    "GET" if garage else "POST",
                    response,
                    known[vin].vin,
                )
        # Save fresh identity before optional image discovery. A garage fallback
        # is not proof that the GraphQL media endpoint is authorized.
        fresh = {
            key: car
            for key, car in known.items()
            if car.model and not car.identity_restored
        }
        if fresh:
            await self.storage.async_save(self.profiles)
        image_reader = getattr(self.transport, "discover_vehicle_images", None)
        remaining = getattr(self.transport, "remaining_calls", None)
        targets = {key: car for key, car in fresh.items() if not car.image_url}
        if (
            targets
            and not garage
            and image_reader is not None
            and (remaining is None or remaining > 12)
        ):
            try:
                async with asyncio.timeout(8):
                    images = await image_reader()
            except Exception:  # Optional media must not interrupt valid identity.
                for car in targets.values():
                    car.image_status = "inconclusive"
            else:
                from .identity_cache import validated_image

                changed = False
                for key, car in targets.items():
                    url = validated_image(images.get(key), car.vin)
                    if url:
                        car.image_url = url
                        car.image_status = "observed"
                        self.profiles[key].manufacturer_identity = capture_identity(car)
                        changed = True
                    else:
                        car.image_status = "not_observed"
                if changed:
                    await self.storage.async_save(self.profiles)

    @staticmethod
    def _identity_candidate(response, car, operation):
        from .transport import (
            GARAGE_OPERATION,
            selected_garage_response,
            garage_rows,
            selected_identity_response,
            identity_rows,
        )

        garage = operation == GARAGE_OPERATION
        selected = (
            selected_garage_response(response, car.vin)
            if garage
            else selected_identity_response(response, car.vin)
        )
        rows = garage_rows(selected.data) if garage else identity_rows(selected.data)
        candidate = (
            (V3Vehicle.from_garage if garage else V3Vehicle.from_graphql)(
                rows[0], car.country
            )
            if len(rows) == 1
            else None
        )
        return selected, candidate

    def _operation_request(
        self,
        vehicle: V3Vehicle,
        ident: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[str, str, str, Any]:
        profile = self.profiles[vehicle.vin.lower()]
        op = profile.registry.operations[ident]
        if op.get("request_mode") == "verified_vehicle_target":
            raise ValueError(
                "Pilot stored-settings adapter not implemented; use the full V3 catalog"
            )
        preview = profile.preview_request(
            ident,
            vehicle_values={
                "VIN": vehicle.vin,
                "COUNTRY": vehicle.country,
                "TYPE": "Audi",
                "JOBS": (
                    "climatisation"
                    if ident in profile.custom
                    else ",".join(planned_jobs(vehicle, profile))
                ),
            },
            user_values=params or {},
        )
        family, method, path = (
            preview["family"],
            preview["method"],
            preview["relative_path"],
        )
        # Retain the existing built-in MBB US endpoint exception.
        if (
            ident not in profile.custom
            and family == "mbb"
            and vehicle.country == "US"
            and "/climater/actions" in path
        ):
            path = f"/api/bs/climatisation/v1/vehicles/{vehicle.vin}/climater/actions"
        from .command_payloads import resolve_secure_body

        return (
            family,
            method,
            path,
            resolve_secure_body(
                self.auth,
                profile,
                vehicle,
                ident,
                family,
                method,
                path,
                preview["json_body"],
            ),
        )

    async def _command_request(self, car, ident, params=None):
        return await self.commands.command_request(car, ident, params)

    async def _dispatch_command(self, car, family, method, path, body):
        return await self.commands.dispatch_command(car, family, method, path, body)

    def redact_evidence(self, payload, vin):
        """Return masked evidence, never the credentials used to mask it."""
        spin, secrets = redaction_context(self.entry, self.auth)
        return engineering_response(
            payload, vehicle_vin=vin, spin=spin, secrets=secrets
        )

    def _api_record(
        self,
        profile: DevelopmentProfile,
        operation: str,
        family: str,
        method: str,
        response: V3Response | None,
        vin: str,
    ) -> None:
        self.health.observe(
            vin.lower(), operation, method, response, self.registry.operations
        )
        detail = None
        request = None
        if response is not None:
            spin, known = redaction_context(self.entry, self.auth)
            try:
                detail = engineering_response(
                    response.data, vehicle_vin=vin, spin=spin, secrets=known
                )
                if response.request is not None:
                    request = engineering_response(
                        response.request, vehicle_vin=vin, spin=spin, secrets=known
                    )
            except (TypeError, ValueError, OverflowError, RecursionError):
                detail = {
                    "payload": "[RESPONSE INSPECTION UNAVAILABLE]",
                    "truncated": True,
                }
        from .transport import GARAGE_OPERATION

        record = record_for(
            family=family,
            method=method,
            http_status=response.status if response else None,
            payload=detail["payload"] if detail else None,
            vin=vin,
            at=response.observed_at if response else None,
        )
        if (
            (
                operation.startswith("cariad.mobility.status.")
                and operation != "cariad.mobility.status.parkingPosition"
            )
            or operation.startswith("mbb.trip.")
        ) and method == "GET":
            record["preview"] = "[trip values withheld: private history]"
        if operation == GARAGE_OPERATION:
            record["preview"] = (
                "[garage metadata withheld: selected vehicle structure only]"
            )
        save_record(profile, operation, record)
        if method == "GET":
            from .read_discovery import record_standalone_read

            record_standalone_read(
                profile,
                operation,
                record["http_status"],
                response.data if response else None,
            )
        # Share structural evidence per reviewed job, not private response values.
        if (
            response is not None
            and 200 <= response.status < 300
            and isinstance(response.data, (dict, list))
        ):
            from .response_preview import safe_schema_inventory, merge_schema_evidence
            from .read_discovery import STANDALONE_READS

            # Structural walker redacts key names and never exports values.
            # Use original decoded types; an admin-preview cap is not a schema cap.
            payload = response.data
            groups = (
                {job: {job: payload[job]} for job in V2_JOBS if job in payload}
                if method == "GET" and isinstance(payload, dict)
                else {}
            )
            from .transport import IDENTITY_OPERATIONS

            if operation in IDENTITY_OPERATIONS:
                groups = {
                    "inventory"
                    if operation == INVENTORY_OPERATION
                    else operation: payload
                }
            elif method == "GET" and operation in STANDALONE_READS:
                groups[operation] = (
                    payload if isinstance(payload, dict) else {"response": payload}
                )
            for job, data in groups.items():
                fields, truncated = safe_schema_inventory(
                    data,
                    vehicle_vin=vin,
                    all_items=True,
                    field_limit=512,
                    char_limit=64000,
                    secrets=known + (str(spin or ""),),
                )
                if not fields:
                    continue
                archived = merge_schema_evidence(
                    {"fields": profile.historical_job_schema.get(job, [])},
                    fields,
                    truncated,
                    status=record["http_status"],
                    at=record["at"],
                    source="historical",
                )
                profile.historical_job_schema[job] = archived["fields"]
                profile.job_schema[job] = merge_schema_evidence(
                    profile.job_schema.get(job),
                    fields,
                    truncated,
                    status=record["http_status"],
                    at=record["at"],
                    source=operation
                    if operation in self.registry.operations
                    or operation in STANDALONE_READS
                    or operation in IDENTITY_OPERATIONS
                    else "reviewed_read",
                )
                if operation in IDENTITY_OPERATIONS:
                    profile.job_schema[job]["latest_identity_fields"] = fields
                    profile.job_schema[job]["graphql_errors"] = payload.get(
                        "errors", []
                    )
                    if response.request and response.request.get("auth_context"):
                        profile.job_schema[job]["auth_context"] = response.request[
                            "auth_context"
                        ]
        profile.engineering_responses.pop(operation, None)
        if detail is not None:
            profile.engineering_responses[operation] = {
                "operation": operation,
                "family": family,
                "method": method,
                "http_status": record["http_status"],
                "at": record["at"],
                "request": request,
                **detail,
            }
            current = profile.engineering_responses[operation]
            if not any(
                item["operation"] == operation and item["at"] == current["at"]
                for item in profile.engineering_history
            ):
                profile.engineering_history.append(current)
                del profile.engineering_history[:-MAX_ENGINEERING_HISTORY]
            while len(profile.engineering_responses) > MAX_ENGINEERING_ROUTES:
                profile.engineering_responses.pop(
                    next(iter(profile.engineering_responses))
                )

    async def save_identity_draft(
        self, vin: str, operation: str, query: str, variables: dict
    ) -> None:
        car = self.require_vehicle(vin)
        self.profiles[car.vin.lower()].save_identity_draft(operation, query, variables)
        await self.storage.async_save(self.profiles)

    async def experiment_identity_query(
        self, vin: str, operation: str, query: str, variables: dict | None = None
    ) -> dict[str, Any]:
        """Session-only evidence; never overwrite canonical route or activate a mapping."""
        from .transport import (
            IDENTITY_QUERIES,
            selected_identity_response,
            identity_rows,
            validate_identity_query,
        )
        from .response_preview import engineering_response, safe_schema_inventory

        if operation not in IDENTITY_QUERIES:
            raise ValueError("Choose a GraphQL identity template")
        validate_identity_query(query, variables)
        car = self.require_vehicle(vin)
        if (
            self.transport.remaining_calls is not None
            and self.transport.remaining_calls <= 12
        ):
            raise RuntimeError("Audi quota is low")
        response = (
            await self.transport.experiment_identity_query(query, variables)
            if variables is not None
            else await self.transport.experiment_identity_query(query)
        )
        selected = selected_identity_response(response, car.vin)
        rows = [
            row
            for row in identity_rows(response.data)
            if isinstance(row, dict)
            and isinstance(row.get("vin"), str)
            and row["vin"].lower() == car.vin.lower()
        ]
        spin, known = redaction_context(self.entry, self.auth)
        # Unknown field names/types only. Never return raw unknown account values.
        fields, truncated = safe_schema_inventory(
            {"data": {"userVehicles": rows}},
            vehicle_vin=car.vin,
            all_items=True,
            secrets=known + (str(spin or ""),),
        )
        detail = engineering_response(
            selected.data, vehicle_vin=car.vin, spin=spin, secrets=known
        )
        request = engineering_response(
            response.request, vehicle_vin=car.vin, spin=spin, secrets=known
        )
        execution = {
            "operation": "graphql.inventory.experiment",
            "template": operation,
            "family": "graphql",
            "method": "POST",
            "http_status": response.status,
            "at": response.observed_at.isoformat(),
            "request": request,
            "fields": fields,
            "fields_truncated": truncated,
            **detail,
        }
        profile = self.profiles[car.vin.lower()]
        profile.engineering_history.append(execution)
        del profile.engineering_history[:-MAX_ENGINEERING_HISTORY]
        return execution

    async def test_identity_operation(
        self, vin: str, operation: str, *, activate=False
    ) -> dict[str, Any]:
        """One reviewed read; explicit adoption requires fresh matching OEM metadata."""
        from .transport import IDENTITY_QUERIES, GARAGE_OPERATION, identity_rows

        if operation != GARAGE_OPERATION and operation not in IDENTITY_QUERIES:
            raise ValueError("Unknown reviewed GraphQL operation")
        car = self.require_vehicle(vin)
        if (
            self.transport.remaining_calls is not None
            and self.transport.remaining_calls <= 12
        ):
            raise RuntimeError("Audi quota is low")
        response = await self.transport.test_identity_query(operation)
        is_garage = operation == GARAGE_OPERATION
        selected, candidate = self._identity_candidate(response, car, operation)
        profile = self.profiles[car.vin.lower()]
        can_activate = bool(
            200 <= response.status < 300
            and candidate
            and candidate.model
            and (not car.model or car.identity_restored or car.model == candidate.model)
        )
        activated = False
        if activate:
            async with self.commands.exclusive():
                if (
                    not can_activate
                    or self.require_vehicle(vin) is not car
                    or self.profiles.get(car.vin.lower()) is not profile
                    or profile.discovery.active_attempt is not None
                ):
                    raise ValueError(
                        "No current matching manufacturer identity or pending control review"
                    )
                activated = self._apply_identity_candidate(
                    car, profile, candidate, operation, response.observed_at
                )
                if not activated:
                    raise ValueError(
                        "Identity evidence conflicts with current vehicle context"
                    )
        # Record after context reconciliation; the adoption must not erase its own evidence.
        self._api_record(
            profile,
            operation,
            "cariad" if is_garage else "graphql",
            "GET" if is_garage else "POST",
            selected,
            car.vin,
        )
        await self.storage.async_save(self.profiles)
        self._notify_discovery_change()
        from .vehicle import select_vehicle_image

        image_present = any(
            select_vehicle_image(row.get("vehicle"), car.vin) is not None
            for row in identity_rows(response.data)
            if isinstance(row, dict)
            and str(row.get("vin", "")).lower() == car.vin.lower()
        )
        return {
            "operation": operation,
            "http_status": response.status,
            "image_present": image_present,
            "errors": selected.data.get("errors", []),
            "vehicle_present": candidate is not None,
            "model_present": bool(candidate and candidate.model),
            "year_present": bool(candidate and candidate.model_year),
            "drive_type_present": bool(candidate and candidate.car_type),
            "can_activate": can_activate,
            "activated": activated,
            "note": "Reviewed OEM identity applied."
            if activated
            else "Read-only candidate evidence; no automatic activation.",
        }

    async def test_family_reads(
        self, vin: str, family: str, *, full: bool = False
    ) -> dict[str, Any]:
        """Explicit, bounded read-only API-family sweep, never remote commands.

        CARIAD: one 23-job GET plus at most two targeted mapped GET groups.
        Legacy MBB: at most five reviewed GETs, only for legacy auth.
        The API cloud budget remains enforced by V3Transport.
        """
        vehicle = self.require_vehicle(vin)
        if family == "graphql":
            from .transport import IDENTITY_QUERIES

            routes = list(IDENTITY_QUERIES) if full else [INVENTORY_OPERATION]
            results = []
            for operation in routes:
                if (
                    self.transport.remaining_calls is not None
                    and self.transport.remaining_calls <= 12
                ):
                    break
                results.append(await self.test_identity_operation(vin, operation))
                if results[-1]["http_status"] in (401, 403, 429):
                    break
            return {
                "family": family,
                "results": results,
                "request_count": len(results),
                "note": "Reviewed read-only GraphQL queries; no automatic activation.",
            }
        expected = "mbb" if vehicle.context.auth == "legacy" else "cariad"
        if family != expected and not (family == "cariad" and vehicle.legacy_cariad):
            raise ValueError("API family is not applicable to this vehicle")
        profile = self.profiles[vehicle.vin.lower()]
        if full:
            return await self._scan_catalog_reads(vehicle, profile, family)
        outcomes: list[dict[str, Any]] = []
        if (
            self.transport.remaining_calls is not None
            and self.transport.remaining_calls <= 12
        ):
            raise RuntimeError("Audi quota is low; read-only scan has been suspended")
        if family == "cariad":
            plans = [
                (
                    "cariad.discovery.full",
                    selective_status_path(vehicle.vin, ",".join(V2_JOBS)),
                    tuple(V2_JOBS),
                )
            ]
        else:
            plans = [
                (
                    f"mbb.discovery.{kind}",
                    template.format(
                        VIN=vehicle.vin, TYPE="Audi", COUNTRY=vehicle.country
                    ),
                    (),
                )
                for kind, template in read_routes().items()
            ]

        async def run_one(route_id: str, path: str, jobs: tuple[str, ...]) -> bool:
            if (
                self.transport.remaining_calls is not None
                and self.transport.remaining_calls <= 12
            ):
                return False
            try:
                response = await self.transport.request(family, "GET", path)
            except (TimeoutError, OSError, RuntimeError, ValueError):
                self._api_record(profile, route_id, family, "GET", None, vehicle.vin)
                outcomes.append(
                    {
                        "operation": route_id,
                        "http_status": None,
                        "result": "transport_uncertain",
                    }
                )
                return False
            self._api_record(profile, route_id, family, "GET", response, vehicle.vin)
            outcome = "http_ok" if 200 <= response.status < 300 else "http_error"
            if family == "cariad":
                record_jobs(
                    profile, jobs, status=response.status, payload=response.data
                )
            # Research records evidence; only scheduled polling publishes readings.
            outcomes.append(
                {
                    "operation": route_id,
                    "http_status": response.status,
                    "result": outcome,
                }
            )
            return outcome == "http_ok"

        for ident, path, jobs in plans:
            if not await run_one(ident, path, jobs):
                break
        if family == "cariad" and outcomes and outcomes[0]["result"] == "http_ok":
            for group in pending_groups(profile, max_groups=2):
                path = selective_status_path(vehicle.vin, ",".join(group))
                if not await run_one(
                    "cariad.discovery." + "_".join(group), path, group
                ):
                    break
                reserve_group(profile, group)
        await self.storage.async_save(self.profiles)
        self._notify_discovery_change()
        return {
            "family": family,
            "request_count": len(outcomes),
            "results": outcomes,
            "readable_attributes": len(vehicle.readings),
            "note": "Only safe GET requests were sent. Stale cloud data is not current vehicle data.",
        }

    async def _scan_catalog_reads(self, car, profile, family):
        """Explicit exhaustive reviewed-route scan, in bounded resumable batches."""
        plan, excluded = full_read_plan(profile, car.context, family)
        results = []
        pending = []
        stopped = None
        for ident, template in plan:
            prior = profile.api_observations.get(ident, {})
            status = prior.get("http_status")
            if status is not None and status not in (401, 403, 429) and status < 500:
                results.append(
                    {
                        "operation": ident,
                        "http_status": status,
                        "result": "previously_attempted",
                    }
                )
                continue
            pending.append((ident, template))
        attempted = 0
        for ident, template in pending:
            if attempted >= 12:
                stopped = "batch_limit"
                break
            if (
                self.transport.remaining_calls is not None
                and self.transport.remaining_calls <= 12
            ):
                stopped = "quota_reserve"
                break
            path = template.format(VIN=car.vin, TYPE="Audi", COUNTRY=car.country)
            attempted += 1
            try:
                reply = await self.transport.request(family, "GET", path)
            except (TimeoutError, OSError, RuntimeError, ValueError):
                self._api_record(profile, ident, family, "GET", None, car.vin)
                results.append(
                    {
                        "operation": ident,
                        "http_status": None,
                        "result": "transport_uncertain",
                    }
                )
                stopped = "transport_uncertain"
                break
            self._api_record(profile, ident, family, "GET", reply, car.vin)
            outcome = "http_ok" if 200 <= reply.status < 300 else "http_error"
            results.append(
                {"operation": ident, "http_status": reply.status, "result": outcome}
            )
            if family == "cariad" and "selectivestatus?jobs=" in path:
                jobs = tuple(path.rsplit("jobs=", 1)[-1].split(","))
                record_jobs(profile, jobs, status=reply.status, payload=reply.data)
            # A full engineering scan must not publish readings or trip history.
            # Individual 400/404/405/422 results are evidence; continue.
            # Account/auth/quota/server failures suspend the scan.
            if reply.status in (401, 403, 429) or reply.status >= 500:
                stopped = "account_or_service_error"
                break
        await self.storage.async_save(self.profiles)
        self._notify_discovery_change()
        remaining = [
            ident
            for ident, _ in plan
            if not (
                (http := profile.api_observations.get(ident, {}).get("http_status"))
                is not None
                and http not in (401, 403, 429)
                and http < 500
            )
        ]
        return {
            "family": family,
            "mode": "full",
            "request_count": attempted,
            "eligible_routes": len(plan),
            "remaining_routes": remaining,
            "excluded_routes": excluded,
            "stopped": stopped,
            "results": results,
            "note": "Read-only; no automatic vehicle actions or activation.",
        }

    def engineering_history_for(
        self, vin: str, family: str = "all"
    ) -> list[dict[str, Any]]:
        car = self.require_vehicle(vin)
        profile = self.profiles[car.vin.lower()]
        history = list(profile.engineering_history)
        recorded = {(item["operation"], item["at"]) for item in history}
        history.extend(
            item
            for item in profile.engineering_responses.values()
            if (item["operation"], item["at"]) not in recorded
        )
        return sorted(
            (item for item in history if family == "all" or item["family"] == family),
            key=lambda item: item["at"],
            reverse=True,
        )

    def api_results_for(self, vin: str, family: str = "all") -> list[dict[str, Any]]:
        car = self.require_vehicle(vin)
        if family not in ("all", "cariad", "mbb", "graphql"):
            raise ValueError("Unknown API family")
        profile = self.profiles[car.vin.lower()]
        return [
            {"operation": ident, **record}
            for ident, record in reversed(list(profile.api_observations.items()))
            if family == "all" or record["family"] == family
        ]

    async def review_execution(
        self, vin: str, operation: str, at: str, outcome: str, comment: str
    ) -> None:
        """Annotate existing evidence without running or activating anything."""
        car = self.require_vehicle(vin)
        profile = self.profiles[car.vin.lower()]
        records = self.api_results_for(vin) + self.engineering_history_for(vin)
        if not any(
            row["operation"] == operation and row["at"] == at for row in records
        ):
            raise ValueError("Execution evidence is no longer retained")
        if not isinstance(comment, str) or len(comment) > 500:
            raise ValueError("Comment must be at most 500 characters")
        spin, secrets = redaction_context(self.entry, self.auth)
        masked = engineering_response(
            comment, vehicle_vin=car.vin, spin=spin, secrets=secrets
        )["payload"]
        save_execution_review(
            profile,
            {"operation": operation, "at": at, "outcome": outcome, "comment": masked},
        )
        await self.storage.async_save(self.profiles)

    def engineering_response_for(self, vin: str, operation: str) -> dict[str, Any]:
        """Read latest local detail; never issue a request or restore raw payloads."""
        car = self.require_vehicle(vin)
        profile = self.profiles[car.vin.lower()]
        detail = profile.engineering_responses.get(operation)
        if detail is None:
            return {"available": False, "operation": operation}
        return {"available": True, **detail}

    async def _save_trip_archive(self) -> None:
        if self.trip_archive is not None:
            try:
                await self.trip_archive.save(self.vehicles)
            except (OSError, ValueError):
                _LOGGER.warning("Unable to save private Audi trip archive")

    async def poll(self) -> list[V3Vehicle]:
        cars = await self.status.poll()
        self.commands.reconcile_commands()
        self.commands.refresh_bindings()
        await self.storage.async_save(self.profiles)
        await self._save_trip_archive()
        return cars

    def require_vehicle(self, vin: str) -> V3Vehicle:
        vehicle = self.vehicles.get(vin.lower())
        if vehicle is None or not vehicle.inventory_present:
            raise ValueError("Vehicle is not present in the current account inventory")
        return vehicle

    def control_routes_for(
        self, vin: str, capability: str, action: str
    ) -> dict[str, Any]:
        return self.commands.control_routes_for(vin, capability, action)

    async def disable_control(
        self, vin: str, capability: str, action: str, *, disabled=True
    ) -> None:
        await self.commands.disable_control(vin, capability, action, disabled=disabled)

    def _command_route(self, vin: str, aspect: str, capability: str) -> str | None:
        return self.commands.command_route(vin, aspect, capability)

    def control_enabled(
        self, vin: str, aspect: str, capability: str = "climate"
    ) -> bool:
        return self.commands.control_enabled(vin, aspect, capability)

    async def approved_control_discovery(
        self,
        vin: str,
        aspect: str,
        operation: str,
        *,
        approval: str,
        params: dict[str, Any] | None = None,
        capability: str = "climate",
        guided: bool = False,
        expert: bool = False,
    ) -> dict[str, Any]:
        """Public discovery boundary: one explicitly approved semantic action."""
        vehicle = self.require_vehicle(vin)
        profile = self.profiles[vehicle.vin.lower()]
        op = profile.registry.operations.get(operation)
        if op is None:
            raise ValueError("Unknown discovery operation")
        if (
            operation
            not in profile.registry.resolve(capability, aspect, vehicle.context)[
                "available_operations"
            ]
        ):
            raise ValueError("Control not applicable to this car")
        validate_approval(
            capability,
            aspect,
            op,
            approval,
            has_spin=bool(configured_spin(self.auth)),
        )
        if guided:
            return await self.commands.test_action(
                vin,
                aspect,
                operation,
                params=params,
                capability=capability,
                guided=True,
                expert=expert,
                approval=approval,
            )
        return await self.test_action(
            vin, aspect, operation, params=params, capability=capability
        )

    async def test_action(
        self,
        vin: str,
        aspect: str,
        operation: str,
        *,
        params: dict[str, Any] | None = None,
        capability: str = "climate",
    ):
        return await self.commands.test_action(
            vin, aspect, operation, params=params, capability=capability
        )

    async def review_action(self, vin: str, sequence: int, outcome: str):
        return await self.commands.review_action(vin, sequence, outcome)

    async def add_route(self, vin: str, route: dict[str, Any]) -> str:
        async with self.commands.exclusive():
            if route.get("aspect") == "status":
                raise ValueError("Use an attribute read template")
            profile = self.profiles[self.require_vehicle(vin).vin.lower()]
            op = profile.add(route)
            await self.storage.async_save(self.profiles)
            return op

    def share_definition(self, vin: str, operation: str) -> dict[str, Any]:
        car = self.require_vehicle(vin)
        spin, secrets = redaction_context(self.entry, self.auth)
        return self.profiles[car.vin.lower()].share_definition(
            operation, vin=car.vin, spin=spin, secrets=secrets
        )

    async def discard_unused_route(self, vin: str, operation: str) -> None:
        async with self.commands.exclusive():
            profile = self.profiles[self.require_vehicle(vin).vin.lower()]
            profile.discard_unused_route(operation)
            await self.storage.async_save(self.profiles)
        self._notify_discovery_change()

    async def select_working(
        self, vin: str, aspect: str, operation: str, capability: str = "climate"
    ) -> None:
        """Admin activates a verified control; reads use attribute activation."""
        async with self.commands.exclusive():
            if aspect == "status":
                raise ValueError("Use attribute mapping activation for read routes")
            car = self.require_vehicle(vin)
            p = self.profiles[car.vin.lower()]
            if not runtime_ready(p.custom.get(operation, {})):
                raise DevelopmentProfileError(
                    "Dynamic parameters without semantic bindings remain test-only"
                )
            p.choose_working(capability, aspect, operation)
            await self.storage.async_save(self.profiles)

    def _refresh_event(self, vin: str, record) -> None:
        """Retain historical event IDs, never report an unconfirmed refresh as complete."""
        bus = getattr(self.hass, "bus", None)
        if bus is None:
            return
        completed = record.state in ("backend_completed", "verified")
        event = (
            REFRESH_VEHICLE_DATA_COMPLETED_EVENT
            if completed
            else REFRESH_VEHICLE_DATA_FAILED_EVENT
        )
        bus.async_fire(
            f"{DOMAIN}_{event}",
            {
                "vin": "*" * max(0, len(vin) - 4) + vin[-4:],
                "outcome": record.state,
            },
        )

    async def _follow_up_cloud(self) -> None:
        """One read-only coordinator refresh, never a second polling owner."""
        coordinator = getattr(
            getattr(self.entry, "runtime_data", None), "coordinator", None
        )
        if coordinator is None or not hasattr(coordinator, "async_request_refresh"):
            return
        try:
            delay = float(
                getattr(self.entry, "options", {}).get(CONF_UPDATE_SLEEP, UPDATE_SLEEP)
            )
        except (TypeError, ValueError):
            delay = UPDATE_SLEEP
        try:
            await asyncio.sleep(max(0, min(delay, 300)))
            await coordinator.async_request_refresh()
        except Exception:
            # A follow-up read must not turn an already accepted command into a
            # failed service call (which could prompt an unsafe user retry).
            _LOGGER.warning("Audi command follow-up cloud read failed")

    async def _after_command(self, vin: str, record) -> None:
        if (
            getattr(getattr(self.entry, "runtime_data", None), "coordinator", None)
            is None
        ):
            return
        remote_refresh = record.capability == "remote" and record.action == "refresh"
        if remote_refresh:
            self._refresh_event(vin, record)
        elif (
            getattr(self.entry, "options", {}).get(CONF_REFRESH_AFTER_ACTION, False)
            and record.state in ("backend_completed", "verified")
            and not (record.capability == "remote" and record.action == "wake")
        ):
            # The existing opt-in V2 option permits one explicit refresh after
            # an accepted action. Never send it after uncertainty, recurse, or
            # bypass the wake quota/security/evidence checks.
            try:
                refresh = await self.commands.send_control(
                    vin, "refresh", "remote", _follow_up_to=record.command_id
                )
            except (RuntimeError, ValueError):
                profile = self.profiles.get(vin.lower())
                refresh = getattr(profile, "last_command", None)
                if (
                    refresh is not None
                    and refresh.parent_command_id == record.command_id
                ):
                    self._refresh_event(vin, refresh)
                _LOGGER.debug("Audi optional vehicle refresh skipped or unconfirmed")
            else:
                self._refresh_event(vin, refresh)
        await self._follow_up_cloud()

    async def send_control(
        self,
        vin: str,
        aspect: str,
        capability: str = "climate",
        *,
        params: dict[str, Any] | None = None,
    ) -> None:
        profile = self.profiles.get(vin.lower())
        previous = getattr(profile, "last_command", None)
        try:
            record = await self.commands.send_control(
                vin, aspect, capability, params=params
            )
        except (RuntimeError, ValueError):
            current = getattr(profile, "last_command", None)
            if (
                capability == "remote"
                and aspect == "refresh"
                and current is not None
                and current is not previous
            ):
                self._refresh_event(vin, current)
                await self._follow_up_cloud()
            raise
        await self._after_command(vin, record)

    async def review_normal_command(self, vin: str, command_id: str) -> None:
        await self.commands.review_normal_command(vin, command_id)

    async def send_setting(self, vin: str, kind: str, value: Any) -> None:
        record = await self.commands.send_setting(vin, kind, value)
        await self._after_command(vin, record)

    def attribute_routes_for(self, vin: str, attribute: str) -> dict[str, Any]:
        car = self.require_vehicle(vin)
        profile = self.profiles[car.vin.lower()]
        alternatives = [
            r
            for r in read_variants(
                attribute, profile.attribute_custom, attributes_for(profile)
            )
            if r["family"] == ("mbb" if car.context.auth == "legacy" else "cariad")
            or (r["family"] == "cariad" and car.legacy_cariad)
        ]
        for variant in alternatives:
            evidence = profile.attribute_route_evidence.get(attribute, {}).get(
                variant["id"], {}
            )
            variant["result"] = evidence.get("outcome", "not_tested")
            variant["active"] = profile.attribute_routes.get(attribute) == variant["id"]
        return {
            "attribute": attribute,
            "capability": attributes_for(profile)[attribute]["capability"],
            "routes": alternatives,
            "active": profile.attribute_routes.get(attribute),
            "draft": profile.attribute_drafts.get(attribute),
            "disabled": attribute in profile.attribute_disabled,
        }

    async def add_attribute_route(self, vin: str, definition: dict[str, Any]) -> str:
        car = self.require_vehicle(vin)
        profile = self.profiles[car.vin.lower()]
        raw = dict(definition)
        local = raw.pop("attribute_definition", None)
        attributes = attributes_for(profile)
        if local is not None:
            local = validate_definition(local)
            ident = local["id"]
            if ident != raw.get("attribute") or ident in attributes:
                raise ValueError("New local attribute must have a unique matching ID")
            if len(profile.attribute_definitions) >= MAX_CUSTOM_ATTRIBUTES:
                raise ValueError("Too many local attributes")
            attributes[ident] = descriptor(local)
        route = validate_custom_read_route(raw, attributes)
        if route["id"] in profile.attribute_custom:
            raise ValueError("Choose a new custom route identifier")
        if len(profile.attribute_custom) >= 50:
            raise ValueError("Too many custom routes")
        if local is not None:
            profile.attribute_definitions[local["id"]] = local
        profile.attribute_custom[route["id"]] = route
        await self.storage.async_save(self.profiles)
        return route["id"]

    async def test_attribute_route(
        self, vin: str, attribute: str, route: str
    ) -> dict[str, Any]:
        async with self.commands.exclusive():
            car = self.require_vehicle(vin)
            return await self.status.test_attribute_route(car, attribute, route)

    async def save_attribute_candidate(
        self, vin: str, attribute: str, route: str
    ) -> None:
        car = self.require_vehicle(vin)
        profile = self.profiles[car.vin.lower()]
        get_read_variant(
            attribute, route, profile.attribute_custom, attributes_for(profile)
        )
        profile.attribute_drafts[attribute] = route
        await self.storage.async_save(self.profiles)

    def _notify_discovery_change(self, *, reconcile_registry=True) -> None:
        coordinator = getattr(
            getattr(self.entry, "runtime_data", None), "coordinator", None
        )
        if coordinator is not None and hasattr(coordinator, "async_update_listeners"):
            # Local evidence changes are not a successful cloud update.
            coordinator.async_update_listeners()
        if (
            reconcile_registry
            and coordinator is not None
            and hasattr(self.hass, "async_create_task")
        ):
            from .registry_lifecycle import async_apply_v3_entity_visibility

            self.hass.async_create_task(
                async_apply_v3_entity_visibility(
                    self.hass, self.entry, True, expected_engine=self
                ),
                eager_start=False,
            )

    async def activate_attribute_route(
        self, vin: str, attribute: str, route: str
    ) -> None:
        car = self.require_vehicle(vin)
        profile = self.profiles[car.vin.lower()]
        choice = get_read_variant(
            attribute, route, profile.attribute_custom, attributes_for(profile)
        )
        if choice["family"] != (
            "mbb" if car.context.auth == "legacy" else "cariad"
        ) and not (choice["family"] == "cariad" and car.legacy_cariad):
            raise ValueError("Route does not match the vehicle API family")
        result = profile.attribute_route_evidence.get(attribute, {}).get(route, {})
        if result.get("outcome") != "verified" and not (
            (choice["family"] == "mbb" or choice.get("allow_last_known"))
            and result.get("outcome") == "readable_but_stale"
        ):
            if choice["family"] == "mbb":
                raise ValueError(
                    "Test an MBB GET response before enabling legacy polling"
                )
            raise ValueError(
                "Test the route and verify fresh vehicle data before activation"
            )
        car.family_readings.pop(attribute, None)
        profile.attribute_disabled.discard(attribute)
        profile.attribute_routes[attribute] = route
        profile.attribute_drafts[attribute] = route
        await self.storage.async_save(self.profiles)
        self._notify_discovery_change()

    async def disable_attribute_route(
        self, vin: str, attribute: str, *, disabled=True
    ) -> None:
        car = self.require_vehicle(vin)
        profile = self.profiles[car.vin.lower()]
        if attribute not in attributes_for(profile):
            raise ValueError("Unknown attribute")
        car.family_readings.pop(attribute, None)
        if disabled:
            profile.attribute_disabled.add(attribute)
            previous = profile.attribute_routes.pop(attribute, None)
            if previous:
                profile.attribute_drafts[attribute] = previous
        else:
            # Resume standard discovery, not an untested custom mapping.
            profile.attribute_disabled.discard(attribute)
        await self.storage.async_save(self.profiles)
        self._notify_discovery_change()

    async def resume_read_discovery(self, vin: str):
        """Explicit recovery: retry only unresolved targeted reads; no mutations."""
        car = self.require_vehicle(vin)
        profile = self.profiles[car.vin.lower()]
        for job in tuple(profile.job_probe_attempts):
            if profile.job_discovery.get(job) not in ("observed", "unsupported"):
                profile.job_probe_attempts.pop(job, None)
        await self.storage.async_save(self.profiles)
        coordinator = getattr(
            getattr(self.entry, "runtime_data", None), "coordinator", None
        )
        if (
            coordinator is not None
            and self.health.snapshot(self, car)["status"] != "rate_limited"
        ):
            await coordinator.async_request_refresh()
        return self.discovery_progress(car, profile)

    def discovery_progress(self, car, profile):
        """One read-only coverage contract for diagnostics and user entities."""
        from .read_discovery import user_progress

        progress = user_progress(
            car,
            profile,
            self.auth,
            base_registry=self.registry,
            parking_allowed=self.status.parking_read_allowed(car),
        )
        health = self.health.snapshot(self, car)
        if progress["read_state"] not in (
            "complete",
            "complete_with_unresolved",
        ) and health["status"] in (
            "authentication_required",
            "rate_limited",
            "cloud_unavailable",
            "error",
        ):
            progress["read_state"] = "paused"
            progress["read_pause_reason"] = health["status"]
        retry_at = getattr(getattr(self.transport, "quota", None), "retry_at", None)
        progress["read_retry_at"] = retry_at.isoformat() if retry_at else None
        return progress

    def diagnostics(self) -> dict[str, Any]:
        """No VIN, tokens, literal user routes, response bodies or coordinates."""
        from .capability_status import (
            diagnostic_capability_summary,
            diagnostic_route_label,
        )
        from .vehicle import powertrain_identity
        from .access_summary import access_summary
        from .freshness import vehicle_capture_summary
        from .historical_catalog import ATTRIBUTES, V2_JOBS

        vehicles = []
        for index, car in enumerate(self.vehicles.values(), 1):
            p = self.profiles.get(car.vin.lower())
            schemas = getattr(p, "job_schema", {})
            capture = vehicle_capture_summary(car)
            if capture["source_attribute"] not in ATTRIBUTES and capture[
                "source_attribute"
            ] not in (
                "measuredCarType",
                "measuredElectricRange",
                "measuredFuelRange",
                "measuredTotalRange",
                "measuredElectricSOC",
                "batteryElectricRange",
                "maintenanceMileage",
                "primaryEngineFuelLevel",
                "secondaryEngineFuelLevel",
                "windowHeatingActive",
                "preheater_active",
            ):
                capture["source_attribute"] = (
                    "other_reading" if capture["source_attribute"] else None
                )
            if capture["source_job"] not in V2_JOBS:
                capture["source_job"] = None
            # Keep historical-only evidence, without repeating current fields.
            historical = {}
            for job, rows in getattr(p, "historical_job_schema", {}).items():
                current = {
                    (r["path"], r["type"], r.get("quality"))
                    for r in schemas.get(job, {}).get("fields", [])
                }
                extra = [
                    r
                    for r in rows
                    if (r["path"], r["type"], r.get("quality")) not in current
                ]
                if extra:
                    historical[job] = extra
            vehicles.append(
                {
                    "vehicle_slot": index,
                    "trip_data_sources": len(car.trips),
                    "normalized_trip_history_count": len(car.trip_history),
                    "context": {
                        "auth": car.context.auth,
                        "region": car.country,
                        "model_family": car.model_family,
                    },
                    "identity_evidence": {
                        "manufacturer_model_present": bool(car.model),
                        "model_source": car.model_source or None,
                        "identity_restored": car.identity_restored,
                        "identity_observed_at": car.identity_observed_at,
                        "identity_operation": car.identity_operation,
                        "year_operation": car.year_operation,
                        "registry_model_present": bool(car.registry_model),
                        "vehicle_image_present": bool(car.image_url),
                        "vehicle_image_status": car.image_status,
                        "model_year_present": bool(car.model_year),
                        "drive_type_present": bool(car.car_type),
                        "powertrain": powertrain_identity(car),
                    },
                    "integration_health": self.health.snapshot(self, car),
                    "vehicle_capture": capture,
                    "access_evidence": {
                        kind: {
                            key: value
                            for key, value in access_summary(car, kind)[1].items()
                            if key in ("freshness", "complete", "age_minutes")
                        }
                        for kind in ("door", "window")
                    },
                    "capability_evidence": diagnostic_capability_summary(
                        car, p, self.registry, self.auth
                    )
                    if p
                    else {},
                    "job_schema_evidence": schemas,
                    "historical_schema_evidence": {
                        "scope": "vin_scoped_historical_only_delta_not_current_support",
                        "fields_by_job": historical,
                    },
                    "discovery_progress": self.discovery_progress(car, p) if p else {},
                    "trip_archive_evidence": {
                        "record_count": len(car.trip_history),
                        "snapshot_scopes": sorted(car.trips),
                        "snapshot_sources": {
                            key: row.get("source") for key, row in car.trips.items()
                        },
                        "parking_position_present": car.position is not None,
                        "scope": "observed_normalized_records_not_lifetime_history",
                        "complete_odometer_interval_count": sum(
                            row.get("startMileage") is not None
                            and row.get("overallMileage") is not None
                            for row in car.trip_history
                        ),
                    },
                    "climate": {
                        "readable": car.climate_state is not None,
                        "capture_age_minutes": car.capture_age_minutes,
                        "selected_status": diagnostic_route_label(
                            p.active["climate.status"], self.registry
                        )
                        if p and p.active.get("climate.status")
                        else None,
                        "start_enabled": self.control_enabled(car.vin, "start")
                        if p
                        else False,
                        "stop_enabled": self.control_enabled(car.vin, "stop")
                        if p
                        else False,
                        "candidate_count": len(
                            p.registry.operations_for("climate", "status")
                        )
                        if p
                        else 0,
                        # Operation IDs are stable for built-ins; user-authored
                        # names and literal custom URL templates are private and
                        # replaced with generic identifiers for diagnostics.
                        "read_route_evidence": [
                            {
                                "operation": ident
                                if ident in self.registry.operations
                                else "custom_status_variant",
                                "outcome": evidence.get("outcome", "untested"),
                                "http_class": (
                                    f"{evidence['http_status'] // 100}xx"
                                    if type(evidence.get("http_status")) is int
                                    else "unknown"
                                ),
                                "schema_valid": evidence.get("schema_valid", False),
                                "fresh": evidence.get("fresh", False),
                                "timestamp_present": evidence.get("timestamp_present"),
                            }
                            for ident, evidence in (p.read_results.items() if p else ())
                        ][:15],
                        "control_route_evidence": [
                            {
                                "operation": ident
                                if ident in self.registry.operations
                                else "custom_control_variant",
                                "outcome": outcome,
                            }
                            for ident, outcome in (
                                p.control_results.items() if p else ()
                            )
                        ][:15],
                        "disabled_controls": sorted(p.discovery.disabled) if p else [],
                        "automatic_read_discovery": discovery_summary(p) if p else {},
                        "last_api_results": [
                            {
                                "operation": diagnostic_route_label(
                                    ident, self.registry
                                ),
                                **{
                                    key: entry[key]
                                    for key in (
                                        "at",
                                        "family",
                                        "method",
                                        "http_status",
                                        "result",
                                        "fields_truncated",
                                    )
                                    if key in entry
                                },
                            }
                            for ident, entry in reversed(
                                list(p.api_observations.items())
                            )
                        ][:24]
                        if p
                        else [],
                    },
                }
            )
        return {
            "mode": "v3",
            "diagnostics_schema_version": 2,
            "privacy_scope": "structural_evidence_only_no_response_previews",
            "polling_owner": "independent_v3_discovery_engine",
            "data_act_polling": self.status.data_act_poll_status(),
            "requests": self.transport.request_count,
            "requests_scope": "current_transport_runtime",
            "poll_attempt_count": self.status.poll_attempt_count,
            "last_poll_scope": "native_cloud_reachability",
            "api_evidence_scope": "latest_per_operation_including_restored_evidence",
            "inventory_source": getattr(
                self.transport, "last_inventory_operation", INVENTORY_OPERATION
            ),
            "inventory_fallback_reason": getattr(
                self.transport, "last_inventory_fallback_reason", None
            ),
            "identity_auth_context": {
                family: self.auth.identity_auth_evidence(family)
                for family in ("cariad", "graphql")
            }
            if hasattr(self.auth, "identity_auth_evidence")
            else {},
            "last_poll_success": self.last_cloud_poll_success.isoformat()
            if self.last_cloud_poll_success
            else None,
            "last_poll_succeeded": self.last_cloud_poll_succeeded,
            "last_poll_attempt": self.last_cloud_poll_attempt.isoformat()
            if self.last_cloud_poll_attempt
            else None,
            "quota_remaining": self.transport.remaining_calls,
            "quota_scope": (
                "unknown_no_header"
                if self.transport.remaining_calls is None
                else "conservative_estimate_since_last_header"
            ),
            "quota_observed_at": (
                stamp.isoformat()
                if (
                    stamp := getattr(
                        self.transport, "remaining_calls_observed_at", None
                    )
                )
                else None
            ),
            "vehicles": vehicles,
            "entity_projection": entity_projection_report(self),
        }
