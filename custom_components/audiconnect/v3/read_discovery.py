"""Bounded automatic read-only CARIAD discovery.

The first request is the existing 23-job shared selectivestatus GET. These
small, prioritized follow-up groups are used only when its response has no
recognizable field for a historical job. Never send a vehicle action, wake-up,
location request, or every possible route on startup.

Discovery evidence is *vehicle-scoped*: a requested but missing field is not
evidence that the capability is unsupported on other Audi models.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .historical_catalog import V2_JOBS

MAX_EXTRA_INITIAL_REQUESTS = 4
MAX_EXTRA_PERIODIC_REQUESTS = 2
MAX_TARGETED_PROBE_ATTEMPTS = 3

# Prioritize mapped jobs first, then exhaust all known fixed read-only jobs.
PROBE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("climatisation",),
    ("charging",),
    ("fuelStatus", "measurements"),
    ("access", "vehicleLights"),
    ("vehicleHealthInspection", "oilLevel"),
    ("readiness",),
    ("chargingProfiles", "chargingTimers"),
    ("climatisationTimers",),
    ("userCapabilities",),
    ("activeVentilation", "auxiliaryHeating", "hybridCarAuxiliaryHeating"),
    ("batteryChargingCare", "batterySupport"),
    ("departureProfiles", "departureTimers"),
    ("honkAndFlash", "lvBattery", "vehicleHealthWarnings"),
)

_JOBS = frozenset(V2_JOBS)


def _retry_requested(payload):
    if not isinstance(payload, Mapping):
        return False
    error = payload.get("error")
    return payload.get("retry") is True or (
        isinstance(error, Mapping) and error.get("retry") is True
    )


def explicitly_unsupported(payload):
    """Only a job/route-level explicit negative; never a missing field or stale value.

    Numeric vendor codes and vague "unavailable" are deliberately not guessed.
    A child status error does not establish that the entire job is unsupported.
    """
    if not isinstance(payload, Mapping) or _retry_requested(payload):
        return False
    error = payload.get("error")
    candidates = (
        [error]
        if isinstance(error, str)
        else [error.get(key) for key in ("code", "errorCode", "type")]
        if isinstance(error, Mapping)
        else []
    )
    candidates += [payload.get("errorCode")]
    return any(
        isinstance(value, str)
        and "".join(c for c in value.lower() if c.isalnum())
        in (
            "notsupported",
            "unsupported",
            "jobnotsupported",
            "capabilitynotsupported",
            "vehiclenotsupported",
            "servicenotsupported",
        )
        for value in candidates
    )


def record_jobs(
    profile: Any, requested: tuple[str, ...], *, status: int, payload: Any
) -> None:
    """Store only response-presence evidence, never raw Audi response content."""
    for job in requested:
        if job not in _JOBS:
            continue
        if not 200 <= status < 300 or not isinstance(payload, dict):
            # Temporary cloud/auth errors do not mean unsupported.
            if profile.job_discovery.get(job) not in ("observed", "unsupported"):
                profile.job_discovery[job] = "inconclusive"
            continue
        top = payload.get(job)
        if 200 <= status < 300 and explicitly_unsupported(top):
            profile.job_discovery[job] = "unsupported"
            continue
        found = False
        retry_requested = False
        stack = [top]
        # Some reviewed jobs return data inside a shared namespace. A timer
        # schema is read evidence only, never permission to activate ventilation.
        if job == "activeVentilation":
            timers = payload.get("climatisationTimers")
            if isinstance(timers, Mapping):
                stack.append(timers.get("activeVentilationTimersStatus"))
        budget = 64
        while stack and budget:
            budget -= 1
            item = stack.pop()
            if isinstance(item, Mapping):
                retry_requested |= _retry_requested(item)
                if item.get("error") is not None:
                    continue
                if "value" in item and item["value"] not in (None, {}, []):
                    found = True
                    break
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item[:16])
        if found:
            profile.job_discovery[job] = "observed"
        elif retry_requested:
            # Audi explicitly requests another read (e.g. error 4112).
            # Historical mapping evidence cannot turn this response into success.
            if profile.job_discovery.get(job) not in ("observed", "unsupported"):
                profile.job_discovery[job] = "inconclusive"
        elif profile.job_discovery.get(job) != "unsupported" and any(
            item.get("job") == job for item in profile.attribute_evidence.values()
        ):
            profile.job_discovery[job] = "observed"
        elif profile.job_discovery.get(job) not in (
            "observed",
            "unsupported",
            "inconclusive",
        ):
            profile.job_discovery[job] = "not_observed"


def pending_groups(profile: Any, *, max_groups: int) -> list[tuple[str, ...]]:
    """Cover unprobed jobs first; retry inconclusive jobs within a fixed budget."""
    if max_groups <= 0:
        return []
    groups = []
    # Complete the initial catalog scan before spending calls on recovery.
    for retry in (False, True):
        for group in PROBE_GROUPS:
            pending = tuple(
                job
                for job in group
                if job in _JOBS
                and profile.job_discovery.get(job) not in ("observed", "unsupported")
                and (
                    0
                    < profile.job_probe_attempts.get(job, 0)
                    < MAX_TARGETED_PROBE_ATTEMPTS
                    and profile.job_discovery.get(job) == "inconclusive"
                    if retry
                    else profile.job_probe_attempts.get(job, 0) == 0
                )
            )
            if pending:
                groups.append(pending)
            if len(groups) == max_groups:
                return groups
    return groups


def reserve_group(profile: Any, jobs: tuple[str, ...]) -> None:
    for job in jobs:
        if job not in _JOBS:
            raise ValueError("Unknown job cannot be auto-probed")
        profile.job_probe_attempts[job] = min(
            MAX_TARGETED_PROBE_ATTEMPTS, profile.job_probe_attempts.get(job, 0) + 1
        )


def summary(profile: Any) -> dict[str, int]:
    observed = sum(profile.job_discovery.get(job) == "observed" for job in V2_JOBS)
    missing = sum(profile.job_discovery.get(job) == "not_observed" for job in V2_JOBS)
    inconclusive = sum(
        profile.job_discovery.get(job) == "inconclusive" for job in V2_JOBS
    )
    unsupported = sum(
        profile.job_discovery.get(job) == "unsupported" for job in V2_JOBS
    )
    assessed = sum(
        profile.job_discovery.get(job) in ("observed", "unsupported")
        or (
            profile.job_discovery.get(job) == "not_observed"
            and profile.job_probe_attempts.get(job, 0) > 0
        )
        for job in V2_JOBS
    )
    return {
        "catalog_jobs": len(V2_JOBS),
        "assessed_jobs": assessed,
        "assessment_percent": round(100 * assessed / len(V2_JOBS), 1),
        "observed_percent": round(100 * observed / len(V2_JOBS), 1),
        "observed_jobs": observed,
        "not_observed_jobs": missing,
        "inconclusive_jobs": inconclusive,
        "unsupported_jobs": unsupported,
        "not_scanned_jobs": len(V2_JOBS)
        - observed
        - missing
        - inconclusive
        - unsupported,
        "targeted_probe_jobs": len(profile.job_probe_attempts),
    }


def full_read_plan(profile, context, family):
    """One reviewed fixed GET per distinct path, with explicit exclusions."""
    import string

    candidates, excluded = [], []
    seen = set()
    registry = profile.registry
    for capability, definition in registry.capabilities.items():
        if not definition.get("status"):
            continue
        resolved = registry.resolve(capability, "status", context)
        allowed = set(resolved["available_operations"])
        for ident in registry.operations_for(capability, "status"):
            op = registry.operations[ident]
            if op.get("method") != "GET" or op.get("family") != family:
                continue
            reason = None
            if ident not in allowed:
                reason = "context_or_adapter_not_applicable"
            elif ident in profile.custom:
                reason = "custom_route_requires_explicit_test"
            elif "{JOBS}" in op["path"]:
                reason = "shared_batch_covered_separately"
            elif any(
                name not in ("VIN", "TYPE", "COUNTRY")
                for _, name, _, _ in string.Formatter().parse(op["path"])
                if name
            ):
                reason = "parameters_required"
            elif op.get("request_body") is not None:
                reason = "unexpected_get_body"
            elif op["path"] in seen:
                reason = "duplicate_path"
            if reason:
                excluded.append({"operation": ident, "reason": reason})
                continue
            seen.add(op["path"])
            candidates.append((ident, op["path"]))

    # Prioritize not-observed jobs without omitting already batch-observed routes.
    def priority(item):
        job = item[1].split("jobs=", 1)[-1] if "jobs=" in item[1] else None
        return (profile.job_discovery.get(job) == "observed", item[0])

    return sorted(candidates, key=priority), excluded


STANDALONE_READS = frozenset(
    (
        "cariad.mobility.status.shortTerm",
        "cariad.mobility.status.longTerm",
        "cariad.mobility.status.lastTrip",
        "cariad.mobility.status.parkingPosition",
        "cariad.mobility.status.tripStatistics",
        "mbb.trip.shortTerm",
        "mbb.trip.longTerm",
    )
    + tuple(
        "mbb.discovery." + kind
        for kind in ("charger", "climater", "vehicle_data", "preheater", "timer")
    )
)


def record_standalone_read(profile, operation, status, payload=None):
    """Persist assessment and explicit route exclusions; a temporary error cannot erase coverage."""
    if operation not in STANDALONE_READS or not hasattr(
        profile, "standalone_discovery"
    ):
        return
    unsupported = getattr(profile, "unsupported_reads", None)
    if unsupported is not None:
        if status in (405, 410) or (
            status in (200, 207, 400, 404, 422) and explicitly_unsupported(payload)
        ):
            unsupported.add(operation)
        elif type(status) is int and 200 <= status < 300:
            unsupported.discard(operation)
    if type(status) is int and (
        200 <= status < 300 or status in (400, 404, 405, 410, 422)
    ):
        previous = profile.standalone_discovery.get(operation)
        if previous is None or 200 <= status < 300 or not 200 <= previous < 300:
            profile.standalone_discovery[operation] = status


def read_excluded(profile, operation):
    return operation in getattr(profile, "unsupported_reads", ())


def physical_control_evidence(profile, candidates):
    """Stored context-scoped outcomes, independent of current eligibility."""
    outcomes = {profile.control_results.get(operation) for operation in candidates}
    return (
        "worked"
        if "worked" in outcomes
        else "failed"
        if "failed" in outcomes
        else "not_tested"
    )


def user_progress(car, profile, auth, *, base_registry=None, parking_allowed=None):
    """Read coverage and control evidence are independent, never proof of support."""
    from .historical_catalog import INVENTORY, CANONICAL_ATTRIBUTES
    from .control_resolution import control_decision

    modern = car.context.auth == "auth0" or car.legacy_cariad
    jobs = {}
    if modern:
        for job in V2_JOBS:
            status = profile.job_discovery.get(job, "not_scanned")
            schema = getattr(profile, "job_schema", {}).get(job, {})
            fields = schema.get("fields", [])
            # Structural error and command-request envelopes are not telemetry
            # schemas. Keep their evidence visible without counting them as data.
            parts = [field["path"].split(".") for field in fields]
            schema_status = (
                "truncated"
                if schema.get("truncated")
                else "captured"
                if any("value" in path and "error" not in path for path in parts)
                else "error_only"
                if any("error" in path for path in parts)
                else "request_only"
                if any("requests" in path for path in parts)
                else "no_value"
                if fields
                else "not_captured"
            )
            attempts = profile.job_probe_attempts.get(job, 0)
            jobs[job] = {
                "status": status,
                "attempts": attempts,
                "retry_exhausted": status == "inconclusive"
                and attempts >= MAX_TARGETED_PROBE_ATTEMPTS,
                "schema_inventory": schema_status,
                "schema_field_count": len(fields),
                "assessed": status in ("observed", "unsupported")
                or (
                    status == "not_observed"
                    and profile.job_probe_attempts.get(job, 0) > 0
                ),
            }
    reads = {}
    excluded_reads = {}
    if "mobility" in profile.registry.capabilities and modern:
        from .trips import CARIAD_TRIP_OPERATIONS

        available = profile.registry.resolve("mobility", "status", car.context)[
            "available_operations"
        ]
        for operation in (
            *CARIAD_TRIP_OPERATIONS,
            "cariad.mobility.status.parkingPosition",
            "cariad.mobility.status.tripStatistics",
        ):
            if operation in available:
                if (
                    operation == "cariad.mobility.status.parkingPosition"
                    and parking_allowed is False
                ):
                    excluded_reads[operation] = "tracker_disabled_by_user"
                    continue
                reads[operation] = getattr(profile, "standalone_discovery", {}).get(
                    operation,
                    profile.api_observations.get(operation, {}).get("http_status"),
                )
    if car.context.auth == "legacy":
        from .legacy_read_mappings import read_routes

        for operation in [
            *("mbb.discovery." + kind for kind in read_routes()),
            "mbb.trip.shortTerm",
            "mbb.trip.longTerm",
        ]:
            reads[operation] = getattr(profile, "standalone_discovery", {}).get(
                operation,
                profile.api_observations.get(operation, {}).get("http_status"),
            )

    def assessed_http(status):
        return type(status) is int and (
            200 <= status < 300 or status in (400, 404, 405, 410, 422)
        )

    controls = []
    registry = base_registry or profile.registry
    for capability, definition in registry.capabilities.items():
        for action in definition.get("control", {}):
            available = registry.resolve(capability, action, car.context)[
                "available_operations"
            ]
            decision = control_decision(car, profile, auth, capability, action)
            physical = physical_control_evidence(profile, available)
            controls.append(
                {
                    "capability": capability,
                    "action": action,
                    "catalog_applicable": bool(available),
                    "eligible": bool(decision["operation"]),
                    "status": decision["status"],
                    "reason": decision.get("reason"),
                    "physical": physical,
                }
            )
    from collections import Counter
    from datetime import UTC, datetime
    from .capability_status import attribute_status

    now = datetime.now(UTC)
    owners = {row["id"]: row["capability"] for row in INVENTORY["jobs"]}
    capabilities = {}
    for name in registry.capabilities:
        subset = [row for job, row in jobs.items() if owners.get(job) == name]
        actions = [row for row in controls if row["capability"] == name]
        attrs = [
            attr for attr in CANONICAL_ATTRIBUTES.values() if attr["capability"] == name
        ]
        evidence = Counter(
            attribute_status(car, profile, attr, now)[0] for attr in attrs
        )
        normalized = evidence["verified"] + evidence["readable_but_stale"]
        capabilities[name] = {
            "jobs_total": len(subset),
            "attributes_total": len(attrs),
            "attributes_normalized": normalized,
            "attribute_normalization_percent": round(100 * normalized / len(attrs), 1)
            if attrs
            else None,
            "attribute_evidence": dict(evidence),
            "jobs_assessed": sum(row["assessed"] for row in subset),
            "jobs_observed": sum(row["status"] == "observed" for row in subset),
            "controls_catalog_applicable": sum(
                row["catalog_applicable"] for row in actions
            ),
            "controls_physically_verified": sum(
                row["physical"] == "worked" for row in actions
            ),
        }
    total = len(jobs) + len(reads)
    assessed = sum(row["assessed"] for row in jobs.values()) + sum(
        assessed_http(s) for s in reads.values()
    )
    applicable = [row for row in controls if row["catalog_applicable"]]
    verified = sum(row["physical"] == "worked" for row in applicable)
    schema_captured = sum(
        row["schema_inventory"] == "captured" for row in jobs.values()
    )
    attr_total = sum(row["attributes_total"] for row in capabilities.values())
    attr_normalized = sum(row["attributes_normalized"] for row in capabilities.values())
    pending = (
        {
            job
            for group in pending_groups(profile, max_groups=2 * len(PROBE_GROUPS))
            for job in group
        }
        if modern
        else set()
    )
    exhausted = [job for job, row in jobs.items() if row["retry_exhausted"]]
    missing_reads = [op for op, value in reads.items() if not assessed_http(value)]
    unresolved = [
        job
        for job, row in jobs.items()
        if row["status"] not in ("observed", "unsupported") and job not in pending
    ]
    read_state = (
        "discovering"
        if pending
        else "awaiting_data"
        if missing_reads
        else "complete_with_unresolved"
        if unresolved
        else "complete"
    )
    return {
        "read_state": read_state,
        "read_pending_jobs": sorted(pending),
        "read_retry_exhausted_jobs": exhausted,
        "read_unresolved_jobs": unresolved,
        "read_pending_standalone": missing_reads,
        "read_assessment_percent": round(100 * assessed / total, 1) if total else None,
        "schema_inventory_captured_jobs": schema_captured,
        "schema_inventory_total_jobs": len(jobs),
        "schema_inventory_percent": round(100 * schema_captured / len(jobs), 1)
        if jobs
        else None,
        "schema_inventory_scope": "current_session_untruncated_value_schema_not_semantic_completeness",
        "read_assessed": assessed,
        "read_total": total,
        "jobs": jobs,
        "attributes_normalized": attr_normalized,
        "attributes_catalog_total": attr_total,
        "attribute_normalization_percent": round(100 * attr_normalized / attr_total, 1)
        if attr_total
        else None,
        "attribute_normalization_scope": "canonical_scalar_catalog; not all OEM schema leaves",
        "standalone_http": reads,
        "unsupported_reads": sorted(op for op in reads if read_excluded(profile, op)),
        "model_present": bool(car.model),
        "controls_catalog_applicable": len(applicable),
        "controls_physically_verified": verified,
        "control_verification_percent": round(100 * verified / len(applicable), 1)
        if applicable
        else None,
        "controls": controls,
        "capabilities": capabilities,
        "control_evidence_scope": "stored_vehicle_context_not_current_release_physical_acceptance",
        "standalone_schema": {
            operation: {
                "field_count": len(schema.get("fields", [])),
                "truncated": bool(schema.get("truncated")),
                "http_status": schema.get("http_status"),
            }
            for operation in reads
            if (schema := getattr(profile, "job_schema", {}).get(operation))
        },
        "excluded_read_routes": excluded_reads,
        "excluded_reads": ["custom and reference-only routes"],
        "parking_policy": "disabled"
        if parking_allowed is False
        else "enabled"
        if parking_allowed is True
        else "unknown",
        "scope": "selective-status jobs and reviewed standard trip/legacy resources; not vehicle support",
    }


def user_test_candidates(engine, car, profile, *, include_verified=False):
    """Only simple, reviewed, currently eligible native operations."""
    from .control_resolution import control_decision
    from .action_discovery import approval_group

    labels = {
        ("climate", "start"): "Start cabin climate",
        ("climate", "stop"): "Stop cabin climate",
        ("climate", "window_heating_start"): "Start window heating",
        ("climate", "window_heating_stop"): "Stop window heating",
        ("charging", "start"): "Start charging",
        ("charging", "stop"): "Stop charging",
        ("access", "lock"): "Lock vehicle",
        ("access", "unlock"): "Unlock vehicle",
        ("remote", "flash"): "Flash vehicle lights",
        ("remote", "wake"): "Wake vehicle",
    }
    result = {}
    for (capability, action), label in labels.items():
        if capability not in profile.registry.capabilities:
            continue
        definition = profile.registry.capabilities[capability].get("control", {})
        if action not in definition:
            continue
        decision = control_decision(
            car, profile, engine.auth, capability, action, for_discovery=True
        )
        operation = decision["operation"]
        if (
            not operation
            or operation in profile.custom
            or (decision["status"] == "local_verified" and not include_verified)
        ):
            continue
        op = profile.registry.operations[operation]
        group = approval_group(capability, action, op)
        if group not in ("non_spin", "spin") or op.get("request_variables"):
            continue
        result[capability + "." + action] = (
            label,
            capability,
            action,
            operation,
            group,
        )
    return result
