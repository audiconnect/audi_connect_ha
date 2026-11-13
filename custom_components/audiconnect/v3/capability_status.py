"""V3 Capability Status Dashboard — evidence, not inferred support.

A read-only inventory of known paths from the V3 catalog and carefully
copied V2 references.  The V2 references do NOT import or execute V2 code,
and MUST NEVER be reported as tested by V3 without actual V3 evidence.

Rows use placeholders instead of real VINs and never expose raw responses.
"""

from __future__ import annotations

from dataclasses import asdict
from .operation_revision import operation_revision

from typing import Any
from datetime import UTC, datetime
from collections import Counter

from .attribute_contracts import semantic_value_issue, contract_for, binary_contract_for
from .freshness import timestamp_is_fresh

from .development_profiles import DevelopmentProfile
from .action_discovery import approval_group
from .vehicle import V3Vehicle
from .historical_catalog import INVENTORY, ALIAS_OF, CANONICAL_ATTRIBUTES
from .custom_attributes import attributes_for
from .attribute_routes import get_read_variant, read_variants
from .legacy_read_mappings import variant_for as legacy_variant_for
from .registry import builtin_read_path, selective_status_path
from .read_discovery import summary as discovery_summary
from .transport import (
    INVENTORY_OPERATION,
    IDENTITY_QUERIES,
    IDENTITY_OPERATIONS,
    GARAGE_OPERATION,
    GARAGE_PATH,
    POST_GARAGE_OPERATION,
)

GARAGE_FIELDS = {
    "garage_model": ("data[].model", "sensor.model", "Manufacturer model"),
    "garage_car_model": (
        "data[].carModel",
        "sensor.model",
        "Manufacturer model (alternate)",
    ),
    "garage_model_year": ("data[].modelYear", "sensor.model", "Model year"),
    "garage_model_year_alt": (
        "data[].model_year",
        "sensor.model",
        "Model year (alternate)",
    ),
}

IDENTITY_FIELDS = {
    "manufacturer_model": (
        "data.userVehicles[].vehicle.media.longName",
        "sensor.model",
        "Manufacturer model",
    ),
    "model_family": (
        "data.userVehicles[].vehicle.media.shortName",
        "sensor.model",
        "Model family",
    ),
    "model_year": (
        "data.userVehicles[].vehicle.core.modelYear",
        "sensor.model",
        "Model year",
    ),
    "drive_train": (
        "data.userVehicles[].vehicle.classification.driveTrain",
        "sensor.car_type",
        "OEM drivetrain",
    ),
    "vehicle_image": (
        "data.userVehicles[].vehicle.renderPictures[].mediaType",
        "sensor.model",
        "Vehicle image",
    ),
}

# Source: V2 capability_jobs.BASE_SELECTIVE_JOBS and api_probe.py.
# This is a migration backlog, not 24 proven V3 capabilities.
_V2_SELECTIVE_JOBS = {row["id"]: row["capability"] for row in INVENTORY["jobs"]}


def _v2_additional_get():
    return {
        "parkingPosition": builtin_read_path("cariad.mobility.status.parkingPosition"),
        # Reference-only: pendingRequests is not a generic executable GET.
        "pendingRequests": "/vehicle/v1/vehicles/{VIN}/pendingrequests",
        "tripStatistics": builtin_read_path("cariad.mobility.status.tripStatistics"),
    }


_NATIVE_TRIP_ATTRIBUTES = frozenset(
    (
        "shortterm_current",
        "shortterm_reset",
        "longterm_current",
        "longterm_reset",
    )
)


def attribute_reading(vehicle, ident):
    """Use the native trip snapshot owner rather than duplicating trip state."""
    if ident in _NATIVE_TRIP_ATTRIBUTES:
        trip = vehicle.trips.get(ident, {})
        stamp = trip.get("timestamp")
        from .attribute_runtime import _capture_in_utc

        if _capture_in_utc(stamp) is not None:
            return {
                "value": stamp,
                "captured": stamp,
                "path": "trip." + ident,
                "family": "mbb" if trip.get("source") == "mbb_legacy" else "cariad",
            }
    return vehicle.readings.get(ident, {})


def attribute_status(vehicle, profile, definition, now):
    """Canonical attribute status shared by coverage and detailed projections."""
    ident = definition["id"]
    evidence = profile.attribute_evidence.get(ident, {})
    reading = attribute_reading(vehicle, ident)
    legacy = legacy_variant_for(ident) if vehicle.context.auth == "legacy" else None
    native_trip = ident in _NATIVE_TRIP_ATTRIBUTES
    derived = definition.get("derived_job") is not None
    known = bool(
        definition["paths"] or legacy or native_trip or derived or ident == "model"
    )
    fallback = (
        "not_tested"
        if definition.get("local")
        else "not_observed"
        if native_trip
        or derived
        or ident == "model"
        or (
            known
            and definition["paths"]
            and profile.job_discovery.get(definition["job"]) == "not_observed"
        )
        else "not_tested"
        if known
        else "mapping_pending"
    )
    status = evidence.get("status", fallback)
    if not reading and status in ("verified", "readable_but_stale"):
        status = "not_observed"
    key = definition["entity_key"]
    contract = definition.get("contract") or (
        binary_contract_for(key)
        if definition.get("platform") == "binary_sensor"
        else contract_for(key)
    )
    issue = reading.get("reason")
    value = reading.get("value")
    if reading:
        issue = issue or semantic_value_issue(key, value, contract)
        if reading.get("status") == "invalid_value" or issue:
            status = "invalid_value"
        elif value is not None:
            status = (
                "verified"
                if timestamp_is_fresh(reading.get("captured"), now)
                else "readable_but_stale"
            )
    if ident in getattr(profile, "attribute_disabled", ()):
        status = "disabled_by_user"
    return status, issue, contract


def build_status_report(
    vehicle: V3Vehicle,
    profile: DevelopmentProfile,
) -> dict[str, Any]:
    """Produce independently understandable API/attribute/control coverage.

    Workbench candidates are listed even if context-incompatible; 'absent'
    evidence is always 'not_tested', never 'unsupported'.
    """
    rows: list[dict[str, Any]] = []
    seen_paths: set[tuple[str, str]] = set()
    for capability, definition in profile.registry.capabilities.items():
        for aspect in ("status", *(definition.get("control") or {})):
            ids = profile.registry.operations_for(capability, aspect)
            applicable = set(
                profile.registry.resolve(capability, aspect, vehicle.context)[
                    "available_operations"
                ]
            )
            for ident in ids:
                op = profile.registry.operations[ident]
                key = f"{capability}.{aspect}"
                read_evidence = profile.read_results.get(ident, {})
                control_evidence = profile.control_results.get(ident)
                result = (
                    read_evidence.get("outcome", "not_tested")
                    if aspect == "status"
                    else control_evidence or "not_tested"
                )
                if ident not in applicable:
                    result = "not_applicable_to_vehicle"
                elif key in profile.discovery.disabled and aspect != "status":
                    result = "disabled_by_user"
                paths = op.get("response_paths") or [None]
                for path in paths:
                    # A 2xx GET mapping is proof for one actual extracted
                    # response field only, not every fallback path in catalog.
                    attr_result = result
                    if (
                        aspect == "status"
                        and result == "worked"
                        and path
                        != (
                            vehicle.climate_field
                            if capability == "climate"
                            else vehicle.capability_readings.get(capability, {}).get(
                                "path"
                            )
                        )
                    ):
                        attr_result = "mapped_not_confirmed"
                    rows.append(
                        {
                            "capability": capability,
                            "aspect": aspect,
                            "attribute": path
                            if path is not None
                            else ("control." + aspect),
                            "api_family": op["family"],
                            "operation": ident,
                            "method": op["method"],
                            "path": op["path"],
                            "status": attr_result,
                            "route_result": result,
                            "source": "v3_live_evidence"
                            if (read_evidence or control_evidence is not None)
                            else "v3_catalog",
                            "selected": profile.active.get(key) == ident,
                            "saved_candidate": profile.draft_selected.get(key) == ident,
                            "custom": ident in profile.custom,
                            "context_applicable": ident in applicable,
                        }
                    )
                if op["method"] == "GET":
                    seen_paths.add((op["family"], op["path"]))

    for job, family_group in _V2_SELECTIVE_JOBS.items():
        path = selective_status_path(jobs=job)
        if ("cariad", path) in seen_paths:
            continue
        rows.append(
            {
                "capability": family_group,
                "aspect": "status",
                "attribute": job,
                "api_family": "cariad",
                "operation": f"v2.reference.selectivestatus.{job}",
                "method": "GET",
                "path": path,
                "status": "known_v2_not_migrated",
                "route_result": "known_v2_not_migrated",
                "source": "v2_reference_only",
                "selected": False,
                "saved_candidate": False,
                "custom": False,
                "context_applicable": None,
            }
        )
    for label, path in _v2_additional_get().items():
        if ("cariad", path) in seen_paths:
            continue
        rows.append(
            {
                "capability": "mobility" if label != "pendingRequests" else "remote",
                "aspect": "status",
                "attribute": label,
                "api_family": "cariad",
                "operation": f"v2.reference.{label}",
                "method": "GET",
                "path": path,
                "status": "known_v2_not_migrated",
                "route_result": "known_v2_not_migrated",
                "source": "v2_reference_only",
                "selected": False,
                "saved_candidate": False,
                "custom": False,
                "context_applicable": None,
            }
        )

    for attr in CANONICAL_ATTRIBUTES.values():
        evidence = profile.attribute_evidence.get(attr["id"], {})
        selected = profile.attribute_routes.get(attr["id"])
        legacy = legacy_variant_for(attr["id"])
        candidate = legacy if vehicle.context.auth == "legacy" else None
        known = bool(attr["paths"] or candidate)
        family = (
            "mbb"
            if evidence.get("source") == "mbb.legacy"
            else "cariad"
            if evidence.get("source") == "cariad.selectivestatus"
            else "mbb"
            if candidate
            else "cariad"
            if vehicle.context.auth == "auth0" and attr["paths"]
            else "unknown"
        )
        mapped_path = (
            evidence.get("path")
            or (candidate["response_paths"][0] if candidate else None)
            or (attr["paths"][0] if attr["paths"] else "-")
        )
        rows.append(
            {
                "capability": attr["capability"],
                "aspect": "status",
                "attribute": attr["id"],
                "entity_key": attr["entity_key"],
                "api_family": family,
                "operation": (
                    get_read_variant(
                        attr["id"],
                        selected,
                        profile.attribute_custom,
                        attributes_for(profile),
                    )["evidence_operation"]
                    if selected
                    else "v2.attribute." + attr["id"]
                ),
                "method": "GET" if known else "-",
                "path": mapped_path,
                "route_result": evidence.get("status", "not_tested"),
                "source": "v3_historical_evidence"
                if evidence
                else "v3_derived_reference"
                if attr.get("derived_job")
                else "v2_attribute_reference",
                "selected": selected is not None,
                "saved_candidate": False,
                "custom": False,
                "context_applicable": bool(candidate)
                if vehicle.context.auth == "legacy"
                else bool(attr["paths"]),
                "job": attr.get("derived_job") or attr["job"],
            }
        )
    for attr in attributes_for(profile).values():
        if not attr.get("local"):
            continue
        ident = attr["id"]
        evidence = profile.attribute_evidence.get(ident, {})
        selected = profile.attribute_routes.get(ident)
        choices = [
            r for r in profile.attribute_custom.values() if r["attribute"] == ident
        ]
        rows.append(
            {
                "capability": attr["capability"],
                "aspect": "status",
                "attribute": ident,
                "entity_key": attr["entity_key"],
                "api_family": "cariad",
                "operation": selected or (choices[0]["id"] if choices else ident),
                "method": "GET",
                "path": evidence.get("path")
                or (choices[0]["response_path"] if choices else "-"),
                "route_result": evidence.get("status", "not_tested"),
                "source": "v3_live_evidence"
                if evidence
                else "local_attribute_definition",
                "selected": selected is not None,
                "saved_candidate": False,
                "custom": True,
                "context_applicable": vehicle.context.auth != "legacy"
                or vehicle.legacy_cariad,
                "job": None,
            }
        )
    for control in INVENTORY["controls"]:
        rows.append(
            {
                "capability": control["capability"],
                "aspect": "control",
                "attribute": control["id"],
                "api_family": control["api_family"] or "unknown",
                "operation": "v2.control." + control["id"],
                "method": "POST" if control["path"] else "-",
                "path": control["path"] or "-",
                "status": "migration_pending",
                "route_result": "migration_pending",
                "source": "v2_control_reference",
                "selected": False,
                "saved_candidate": False,
                "custom": False,
                "context_applicable": None,
            }
        )
    # The catalog is global; these are real scan results for the selected car.
    scan = discovery_summary(profile)
    controls_for_vehicle = []
    for capability, definition in profile.registry.capabilities.items():
        for action in definition.get("control") or {}:
            available = profile.registry.resolve(capability, action, vehicle.context)[
                "available_operations"
            ]
            current = profile.active.get(f"{capability}.{action}")
            controls_for_vehicle.append(
                {
                    "capability": capability,
                    "action": action,
                    "api_family": "mbb"
                    if vehicle.context.auth == "legacy"
                    else "cariad",
                    "candidate_count": len(available),
                    "approval_groups": sorted(
                        {
                            approval_group(
                                capability, action, profile.registry.operations[ident]
                            )
                            for ident in available
                        }
                    ),
                    "verified": current is not None
                    and profile.control_results.get(current) == "worked",
                    "status": "verified"
                    if current and profile.control_results.get(current) == "worked"
                    else "not_tested"
                    if available
                    else "not_applicable_to_vehicle",
                    "requires_manual_test": True,
                }
            )
    cockpit = _cockpit(vehicle, profile, rows, controls_for_vehicle)
    counts = {
        **scan,
        "observed_attributes": sum(
            r["source"] == "v3_live_evidence"
            and r["status"] in ("verified", "readable_but_stale")
            for r in rows
            if r.get("entity_key")
        ),
        "pending_mappings": sum(
            bool(r.get("entity_key")) and r["status"] == "mapping_pending" for r in rows
        ),
        "total": len(rows),
        "v2_attribute_inventory": len(INVENTORY["attributes"]),
        "v2_unique_attributes": len(CANONICAL_ATTRIBUTES),
        "v2_alias_references": len(ALIAS_OF),
        "v2_control_inventory": len(INVENTORY["controls"]),
        "v3_verified_attributes": sum(
            r["source"] == "v3_live_evidence" and r["status"] == "verified"
            for r in rows
        ),
        "v2_unmapped_attributes": sum(r["status"] == "mapping_pending" for r in rows),
        "verified_working": sum(x["status"] == "worked" for x in rows),
        "reported_failed": sum(
            x["status"] in ("failed", "previously_failed") for x in rows
        ),
        "stale": sum(x["status"] == "readable_but_stale" for x in rows),
        "not_tested": sum(x["status"] == "not_tested" for x in rows),
        "v2_reference_only": sum(x["source"] == "v2_reference_only" for x in rows),
        "not_applicable": sum(x["status"] == "not_applicable_to_vehicle" for x in rows),
    }
    return {
        "schema_version": 1,
        **cockpit,
        "vehicle": {
            "label": vehicle.name,
            "model": vehicle.model,
            "model_family": vehicle.model_family or "unknown",
            "region": vehicle.country,
            "authentication": vehicle.context.auth,
        },
        "counts": counts,
        "control_actions": controls_for_vehicle,
        "pending_control": profile.discovery.active_attempt.public()
        if profile.discovery.active_attempt
        else None,
        "rows": rows,
        "notes": (
            "V2 reference paths are only migration candidates: not discovered "
            "or validated by V3. A cloud response is not a physical command "
            "confirmation. No VIN, tokens or response data are included."
        ),
    }


def _cockpit(vehicle, profile, rows, controls):
    """Read-only projection of existing evidence; no network or state writes."""
    now = datetime.now(UTC)
    findings = []
    attributes = []
    catalog = profile.registry.operations
    records = profile.api_observations
    fast = profile.fast_bindings
    definitions = attributes_for(profile)
    mapped_paths = {}
    for descriptor in definitions.values():
        for path in descriptor["paths"]:
            mapped_paths.setdefault(path, set()).add(descriptor["id"])
    for route in profile.attribute_custom.values():
        path = route.get("response_path")
        if path:
            mapped_paths.setdefault(path, set()).add(route["attribute"])
    for row in rows:
        if not row.get("entity_key"):
            continue
        ident = row["attribute"]
        reading = attribute_reading(vehicle, ident)
        definition = definitions.get(ident, {})
        status, issue, contract = attribute_status(vehicle, profile, definition, now)
        row["status"] = status
        value = reading.get("value")
        if reading:
            row["path"] = reading.get("path") or row["path"]
            row["source"] = "v3_live_evidence"
            row["api_family"] = reading.get("family") or row["api_family"]
        row.update(
            platform=definition.get("platform"),
            metadata=contract,
            observed=bool(reading),
            captured=reading.get("captured"),
            observed_at=reading.get("observed"),
            value_type=type(value).__name__ if value is not None else None,
            semantic_issue=issue,
        )
        if issue:
            findings.append(
                {
                    "id": "attribute:" + ident,
                    "severity": "review",
                    "capability": row["capability"],
                    "attribute": ident,
                    "reason": issue,
                    "operation": row["operation"],
                }
            )
        attributes.append(row)
    for item in controls:
        key = item["capability"] + "." + item["action"]
        binding = fast.get(key, {})
        item.update(
            binding_status=binding.get("status", "unknown"),
            active_operation=binding.get("operation"),
            enabled=bool(binding.get("operation")),
            physical_evidence="local_verified"
            if binding.get("status") == "local_verified"
            else "historical_worked"
            if item["verified"]
            else "not_verified",
        )
        if binding.get("operation"):
            item["requires_manual_test"] = False

    # Historical references are not real V3 tests. Keep them visible but separate.
    references = {
        row["operation"]: row for row in rows if row["source"] == "v2_reference_only"
    }
    journal = {row.operation: row for row in profile.command_journal}
    # Derive declared relationships from the same variants used by the editor
    # and runtime, including untested custom definitions. Evidence is separate.
    variants = {}
    for row in attributes:
        for variant in read_variants(
            row["attribute"], profile.attribute_custom, definitions
        ):
            variants.setdefault(variant["evidence_operation"], []).append(
                (row, variant)
            )
    operations = []
    for ident in sorted(
        set(catalog)
        | set(records)
        | set(references)
        | set(journal)
        | set(variants)
        | set(IDENTITY_QUERIES)
        | {GARAGE_OPERATION}
        | (
            {POST_GARAGE_OPERATION}
            if POST_GARAGE_OPERATION
            in (vehicle.identity_operation, vehicle.year_operation)
            else set()
        )
    ):
        declared = variants.get(ident, [])
        op = catalog.get(ident) or (declared[0][1] if declared else {})
        record = records.get(ident, {})
        ref = references.get(ident, {})
        matching = [
            row
            for row in rows
            if row["operation"] == ident and not row.get("entity_key")
        ]
        read = profile.read_results.get(ident, {})
        physical = profile.control_results.get(ident, "not_tested")
        command = journal.get(ident)
        method = op.get("method") or record.get("method") or ref.get("method")
        active = (
            any(row["selected"] for row in matching)
            or any(item.get("operation") == ident for item in fast.values())
            or any(row["selected"] and row["operation"] == ident for row in attributes)
        )
        applicable = [
            row["context_applicable"]
            for row in matching
            if row["context_applicable"] is not None
        ]
        http = record.get("http_status")
        schema = (
            "valid"
            if read.get("schema_valid") is True
            else "invalid"
            if read.get("schema_valid") is False
            else "unknown"
        )
        tested = bool(read or record or command or physical != "not_tested")
        reasons = []
        if schema == "invalid":
            reasons.append("response_schema_mismatch")
        if physical in ("failed", "uncertain") or (
            command and command.state in ("uncertain", "physical_failed")
        ):
            reasons.append(
                "physical_control_" + (command.state if command else physical)
            )
        if http is not None and not 200 <= http < 300:
            reasons.append("http_error")
        if (
            ident not in IDENTITY_OPERATIONS
            and method in ("POST", "PUT")
            and http is not None
            and 200 <= http < 300
            and physical != "worked"
            and not (command and command.state == "verified")
        ):
            reasons.append("accepted_not_physically_verified")
        caps = sorted(
            {row["capability"] for row in matching}
            | {row["capability"] for row, _ in declared}
            | ({command.capability} if command else set())
        )
        if ident in IDENTITY_OPERATIONS:
            caps = ["vehicle_identity"]
            active = (
                ident == INVENTORY_OPERATION
                or ident == vehicle.identity_operation
                or ident == vehicle.year_operation
            )
            applicable = [True]
            method = "GET" if ident == GARAGE_OPERATION else "POST"
            physical = "not_applicable"
            identity_fields = (
                GARAGE_FIELDS if ident == GARAGE_OPERATION else IDENTITY_FIELDS
            )
            schema_key = "inventory" if ident == INVENTORY_OPERATION else ident
            evidence = profile.job_schema.get(schema_key, {})
            # Only this operation's observed non-null fields count as evidence.
            observed = {
                f["path"]
                for f in evidence.get("latest_identity_fields", [])
                if f["quality"] == "observed"
                and f["type"] not in ("null", "object", "array")
            }
            required = [
                spec[0]
                for key, spec in identity_fields.items()
                if (key == "vehicle_image") == ident.endswith(".images")
            ]
            if http is not None and 200 <= http < 300:
                complete = (
                    (
                        any(
                            path in observed
                            for path in ("data[].model", "data[].carModel")
                        )
                        and any(
                            path in observed
                            for path in ("data[].modelYear", "data[].model_year")
                        )
                    )
                    if ident == GARAGE_OPERATION
                    else all(path in observed for path in required)
                )
                schema = "valid" if complete else "partial"
                if schema == "partial":
                    reasons.append("identity_metadata_incomplete")
        operation = {
            "operation": ident,
            "family": op.get("family") or record.get("family") or ref.get("api_family"),
            "method": method,
            "path": op.get("path") or ref.get("path"),
            "capabilities": caps,
            "applicability": (
                "applicable"
                if any(applicable)
                else "not_applicable"
                if applicable
                else "unknown"
            ),
            "tested": tested,
            "http_status": http,
            "transport": record.get("result"),
            "http_class": read.get("http_class"),
            "schema": schema,
            "partial_http": http == 207,
            "physical": physical,
            "last_command_state": command.state if command else None,
            "backend_result": command.backend_result if command else None,
            "active": active,
            "last_test": record.get("at"),
            "attention": reasons,
            "catalog": ident in catalog,
            "reference_only": ident in references
            or ident
            in ("cariad.selectivestatus.targeted", "cariad.selectivestatus.batch"),
        }
        fields = []
        raw_fields = {(f["path"], f["type"]): f for f in record.get("fields", [])}
        for schema_evidence in profile.job_schema.values():
            if schema_evidence.get("source") == ident:
                raw_fields.update(
                    {
                        (f["path"], f["type"]): f
                        for f in schema_evidence.get("fields", [])
                    }
                )
        for field in raw_fields.values():
            path = field["path"]
            matches = sorted(mapped_paths.get(path, set()))
            status = (
                "metadata"
                if path.rsplit(".", 1)[-1] in ("carCapturedTimestamp", "timestamp")
                else "declared_mapping"
                if matches
                else "container"
                if field["type"] in ("array", "object")
                else "review_unmapped"
            )
            if (
                path == "oilLevel.oilLevelStatus.value.value"
                and field["type"] == "boolean"
            ):
                status = "derived_binary"
                matches = ["oil_level_binary"]
            fields.append({**field, "mapping": status, "attributes": matches})
        job = (
            op.get("path", "").split("jobs=", 1)[-1]
            if "jobs=" in op.get("path", "")
            else None
        )
        operation["job_evidence"] = profile.job_discovery.get(job) if job else None
        if ident in IDENTITY_OPERATIONS:
            operation["family"] = "cariad" if ident == GARAGE_OPERATION else "graphql"
            operation["path"] = (
                GARAGE_PATH if ident == GARAGE_OPERATION else "/vgql/v1/graphql"
            )
            operation["read_only"] = True
            if ident not in (INVENTORY_OPERATION, "graphql.inventory.images"):
                operation["reference_only"] = True
                operation["retired_experiment"] = True
                operation["active"] = False
                active = False
            operation["graphql_errors"] = evidence.get("graphql_errors", [])
            operation["auth_context"] = evidence.get("auth_context")
            fields = [
                {
                    **field,
                    "mapping": "declared_mapping"
                    if any(
                        field["path"] == spec[0] for spec in identity_fields.values()
                    )
                    else "container"
                    if field["type"] in ("array", "object")
                    else "review_unmapped",
                    "attributes": [
                        key
                        for key, spec in identity_fields.items()
                        if field["path"] == spec[0]
                    ],
                }
                for field in evidence.get("fields", [])
            ]
            operation["mappings"] = [
                {
                    "attribute": key,
                    "capability": "vehicle_identity",
                    "field": spec[0],
                    "entity_key": spec[1],
                    "name": spec[2],
                    "status": "observed" if spec[0] in observed else "not_observed",
                    "active": active,
                }
                for key, spec in identity_fields.items()
                if (key == "vehicle_image") == ident.endswith(".images")
            ]
        else:
            from .product_contract import projection_descriptor

            links = []
            declared_by_attribute = {
                row["attribute"]: variant for row, variant in declared
            }
            for row in attributes:
                variant = declared_by_attribute.get(row["attribute"])
                if (
                    not variant
                    and row["operation"] != ident
                    and not any(
                        row["attribute"] in field["attributes"] for field in fields
                    )
                ):
                    continue
                descriptor = definitions.get(row["attribute"], {})
                target = projection_descriptor(descriptor) if descriptor else None
                selected = row["selected"] and row["operation"] == ident
                evidence = (
                    profile.attribute_route_evidence.get(row["attribute"], {}).get(
                        variant["id"], {}
                    )
                    if variant
                    else {}
                )
                field = (
                    row["path"]
                    if selected or not variant
                    else variant["response_paths"][0]
                )
                links.append(
                    {
                        "attribute": row["attribute"],
                        "capability": row["capability"],
                        "field": field,
                        "entity_key": (target["platform"] + "." + target["entity_key"])
                        if target
                        else None,
                        "status": row["status"]
                        if selected or not variant
                        else evidence.get("outcome", "not_tested"),
                        "active": selected,
                    }
                )
            from .product_contract import control_buttons, stateful_controls

            for row in matching:
                if row["aspect"] == "status":
                    continue
                cap, action = row["capability"], row["aspect"]
                targets = {
                    f"button.{key}"
                    for key, _, _, capability, command_action in control_buttons()
                    if (capability, command_action) == (cap, action)
                }
                for key, definition in stateful_controls().items():
                    if definition["capability"] == cap and action in (
                        definition["on"],
                        definition["off"],
                    ):
                        targets.add("switch." + key)
                if cap == "climate" and action in (
                    "start",
                    "stop",
                    "start_with_settings",
                    "set_temperature",
                ):
                    targets.add("climate.climatisation")
                if cap == "access" and action in ("lock", "unlock"):
                    targets.add("lock.lock")
                if cap == "charging" and action == "set_target_soc":
                    targets.add("number.target_state_of_charge")
                if cap == "charging" and action == "set_charge_mode":
                    targets.add("select.charge_mode")
                for target in sorted(targets):
                    links.append(
                        {
                            "attribute": "control." + action,
                            "capability": cap,
                            "field": None,
                            "entity_key": target,
                            "status": row["status"],
                            "active": row["selected"],
                        }
                    )
            for link in list(links):
                if link["attribute"] == "chargingState":
                    links.append(
                        {
                            **link,
                            "entity_key": "binary_sensor.charging_ready",
                            "attribute": "charging_ready",
                        }
                    )
            operation["mappings"] = links
            operation["capabilities"] = sorted(
                set(operation["capabilities"]) | {m["capability"] for m in links}
            )
        operation["fields"] = fields
        operation["fields_truncated"] = (
            evidence.get("truncated")
            if ident in IDENTITY_OPERATIONS
            else record.get("fields_truncated")
        )
        if any(field["mapping"] == "review_unmapped" for field in fields):
            reasons.append("unmapped_response_fields_review")
        operations.append(operation)
        for reason in [] if operation.get("retired_experiment") else reasons:
            findings.append(
                {
                    "id": "operation:" + ident + ":" + reason,
                    "severity": "review",
                    "capability": caps[0] if caps else None,
                    "operation": ident,
                    "reason": reason,
                }
            )
    # Keep all engineering observations, but only current, actionable issues
    # belong on Overview. Never turn a historical route test into a task.
    from .vehicle import (
        CLIMATE_ON_STATES,
        CHARGING_ON_STATES,
        normalize_powertrain,
        powertrain_identity,
    )

    powertrain = powertrain_identity(vehicle)
    identity = {
        "manufacturer_model": bool(vehicle.model),
        "model_year": bool(vehicle.model_year),
        "oem_drivetrain": normalize_powertrain(vehicle.car_type) is not None,
        "powertrain": powertrain["value"],
        "powertrain_conflict": powertrain["conflict"],
        "last_known": vehicle.identity_restored,
    }
    if not vehicle.model:
        findings.append(
            {
                "id": "vehicle:manufacturer_model",
                "severity": "review",
                "reason": "manufacturer_identity_missing",
                "capability": "vehicle_identity",
                "operation": INVENTORY_OPERATION,
            }
        )
    elif not vehicle.model_year or not identity["oem_drivetrain"]:
        findings.append(
            {
                "id": "vehicle:identity_partial",
                "severity": "review",
                "reason": "manufacturer_identity_partial",
                "capability": "vehicle_identity",
                "operation": INVENTORY_OPERATION,
            }
        )
    if not vehicle.model_family:
        findings.append(
            {
                "id": "vehicle:model_family",
                "severity": "review",
                "reason": "model_family_unknown",
                "capability": "vehicle_identity",
                "operation": INVENTORY_OPERATION,
            }
        )

    # Current binding decisions own actionability; old route tests remain evidence.
    for control in controls:
        status = control["binding_status"]
        if status in ("candidate_unverified", "no_working_route"):
            findings.append(
                {
                    "id": "control:" + control["capability"] + "." + control["action"],
                    "severity": "review",
                    "capability": control["capability"],
                    "action": control["action"],
                    "reason": status,
                }
            )
    by_attribute = {row["attribute"]: row for row in attributes}
    next_actions = []
    for finding in findings:
        reason = finding["reason"]
        if finding["id"] in (
            "vehicle:manufacturer_model",
            "vehicle:identity_partial",
        ) or finding["id"].startswith("control:"):
            next_actions.append(finding)
            continue
        attr = finding.get("attribute")
        if attr:
            row = by_attribute[attr]
            reading = vehicle.readings.get(attr, {})
            if (
                reason == "boolean_oil_level_use_binary"
                or row["status"] != "invalid_value"
                or not timestamp_is_fresh(reading.get("captured"), now)
            ):
                continue
            if reason == "negative_duration":
                entity = row["entity_key"]
                if (
                    entity == "remaining_climatisation_time"
                    and vehicle.climate_state not in CLIMATE_ON_STATES
                ):
                    continue
                if (
                    entity == "remaining_charging_time"
                    and vehicle.readings.get("chargingState", {}).get("value")
                    not in CHARGING_ON_STATES
                ):
                    continue
                if entity not in (
                    "remaining_climatisation_time",
                    "remaining_charging_time",
                ):
                    continue
            next_actions.append(finding)
            continue
        command = journal.get(finding.get("operation"))
        if not command or not reason.startswith("physical_control_"):
            continue
        if command.requires_review:
            next_actions.append(finding)
    next_actions.sort(
        key=lambda f: (
            0
            if f["id"].startswith("vehicle:")
            else 1
            if f["reason"].startswith("physical_control_")
            else 2,
            f["id"],
        )
    )

    summaries = []
    for name in sorted(
        {r["capability"] for r in rows}
        | {c["capability"] for c in controls}
        | {"vehicle_identity"}
    ):
        a = [r for r in attributes if r["capability"] == name]
        c = [r for r in controls if r["capability"] == name]
        o = [
            r
            for r in operations
            if name in r["capabilities"] and not r["reference_only"]
        ]
        jobs = {
            job: profile.job_discovery.get(job, "not_scanned")
            for job, group in _V2_SELECTIVE_JOBS.items()
            if group == name
        }
        summaries.append(
            {
                "capability": name,
                "attributes": len(a),
                "read_status": dict(Counter(r["status"] for r in a)),
                "controls": len(c),
                "enabled_controls": sum(r["enabled"] for r in c),
                "locally_verified_controls": sum(
                    r["physical_evidence"] == "local_verified" for r in c
                ),
                "operations": len(o),
                "tested_operations": sum(r["tested"] for r in o),
                "job_status": jobs,
                "advertised_jobs": sorted(set(jobs) & vehicle.advertised_capabilities),
                "impaired_jobs": sorted(set(jobs) & vehicle.impaired_capabilities),
                "attention": sum(r.get("capability") == name for r in next_actions),
            }
        )
    from .freshness import capture_coverage

    return {
        "operations": operations,
        "capability_summary": summaries,
        "job_capture_coverage": capture_coverage(vehicle),
        "findings": findings,
        "next_actions": next_actions,
        "identity_summary": identity,
        "api_job_status": {
            job: profile.job_discovery.get(job, "not_scanned")
            for job in _V2_SELECTIVE_JOBS
        },
        "operation_counts": {
            "total": len(operations),
            "tested": sum(r["tested"] for r in operations),
            "active": sum(r["active"] for r in operations),
            "attention": sum(bool(r["attention"]) for r in operations),
            "historical_references": len(references),
        },
    }


def diagnostic_route_label(ident, registry):
    """Keep known discovery identifiers, never export custom route names."""
    if (
        ident in registry.operations
        or ident in IDENTITY_OPERATIONS
        or ident in ("cariad.discovery.full", "cariad.selectivestatus.batch")
    ):
        return ident
    if ident.startswith("cariad.discovery."):
        jobs = ident.removeprefix("cariad.discovery.").split("_")
        if jobs and all(job in _V2_SELECTIVE_JOBS for job in jobs):
            return ident
    if ident.startswith("mbb.discovery."):
        from .legacy_read_mappings import read_routes

        if ident.removeprefix("mbb.discovery.") in read_routes():
            return ident
    return "custom_or_discovery_route"


def diagnostic_capability_summary(vehicle, profile, base_registry, auth):
    """Safe diagnostic projection of the same capability model as the dashboard.

    No nickname, user route, VIN, payload, setting values or custom identifiers.
    Catalog compatibility, current command eligibility and physical evidence
    remain independent. This is a read-only computation from current state.
    """
    from .control_resolution import control_decision
    from .command_journal import unresolved_normal_commands
    from .read_discovery import physical_control_evidence

    report = build_status_report(vehicle, profile)
    known = base_registry.capabilities
    summaries = [
        row
        for row in report["capability_summary"]
        if row["capability"] in known or row["capability"] == "vehicle_identity"
    ]
    controls = []
    for capability, definition in known.items():
        for action in definition.get("control", {}):
            decision = control_decision(vehicle, profile, auth, capability, action)
            operation = decision["operation"]
            candidates = base_registry.resolve(capability, action, vehicle.context)[
                "available_operations"
            ]
            controls.append(
                {
                    "capability": capability,
                    "action": action,
                    "binding_status": decision["status"],
                    "reason": decision.get("reason"),
                    "eligible": operation is not None,
                    "route_available": decision["route_available"],
                    "route_status": decision["route_status"],
                    "dispatch_ready": decision["dispatch_ready"],
                    "dispatch_reason": decision["dispatch_reason"],
                    "operation": diagnostic_route_label(operation, base_registry)
                    if operation
                    else None,
                    "physical_evidence": physical_control_evidence(profile, candidates),
                }
            )
    for row in summaries:
        actions = [item for item in controls if item["capability"] == row["capability"]]
        row["enabled_controls"] = sum(item["eligible"] for item in actions)
        row["locally_verified_controls"] = sum(
            item["binding_status"] == "local_verified" for item in actions
        )
    operations = [
        {
            key: item.get(key)
            for key in (
                "operation",
                "family",
                "method",
                "applicability",
                "tested",
                "http_status",
                "schema",
                "physical",
                "last_command_state",
                "active",
                "job_evidence",
                "fields_truncated",
            )
        }
        for item in report["operations"]
        if item["operation"] in base_registry.operations
        or item["operation"] in IDENTITY_OPERATIONS
    ]

    def safe_command(row):
        if row.capability not in known or row.action not in known[row.capability].get(
            "control", {}
        ):
            return None
        return {
            "capability": row.capability,
            "action": row.action,
            "operation": diagnostic_route_label(row.operation, base_registry),
            "http_status": row.http_status,
            "started_at": row.started_at,
        }

    pending = profile.discovery.active_attempt
    pending_summary = safe_command(pending) if pending else None
    if pending_summary is not None:
        pending_summary["result"] = pending.result
    unresolved = []
    for record in unresolved_normal_commands(profile):
        item = safe_command(record)
        if item is not None:
            unresolved.append(
                {
                    **item,
                    "state": record.state,
                    "backend_result": record.backend_result,
                    "review_required": record.requires_review,
                }
            )
    return {
        "pending_engineering_test": pending_summary,
        "unresolved_normal_commands": unresolved,
        "capabilities": summaries,
        "attributes": {
            ident: attribute_status(vehicle, profile, definition, datetime.now(UTC))[0]
            for ident, definition in CANONICAL_ATTRIBUTES.items()
        },
        "historically_normalized_without_current_reading": sorted(
            ident
            for ident in CANONICAL_ATTRIBUTES
            if not attribute_reading(vehicle, ident)
            and profile.attribute_evidence.get(ident, {}).get("status")
            in ("verified", "readable_but_stale")
        ),
        "controls": controls,
        "operations": operations,
        "job_capture_coverage": {
            job: data
            for job, data in report["job_capture_coverage"].items()
            if job in _V2_SELECTIVE_JOBS or job == "unclassified"
        },
        "operation_counts": {
            "total": len(operations),
            "tested": sum(bool(row["tested"]) for row in operations),
            "active": sum(bool(row["active"]) for row in operations),
            "scope": "built_in_operations_and_inventory",
        },
        "engineering_operation_counts": report["operation_counts"],
        # No previous context fields or custom identifiers in shared diagnostics.
        "historical_physical_evidence": [
            {
                "operation": row["operation"],
                "outcome": row["outcome"],
                "current_context": row["context"] == asdict(profile.discovery.context),
                "revision_matches": (
                    row["operation_revision"]
                    == operation_revision(base_registry.operations[row["operation"]])
                    if row["operation_revision"] is not None
                    else None
                ),
                "authorizes_control": False,
            }
            for row in getattr(profile, "historical_control_evidence", [])
            if row["operation"] in base_registry.operations
        ],
    }
