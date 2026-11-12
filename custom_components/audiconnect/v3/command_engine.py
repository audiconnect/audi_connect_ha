"""V3 command owner: eligibility, dispatch, manual evidence and normal execution.

No HA entities, V2 business logic or status polling. Dependencies are explicit
and shared with the composition root; a command cannot create a second runtime.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .action_discovery import approval_group
from .command_journal import (CommandRecord, check_command_sequence, ENGINEERING_COMMAND_COOLDOWN_SECONDS,
                              unresolved_normal_commands, blocking_normal_command)
from .operation_revision import operation_revision
from .command_parameters import map_parameters, runtime_ready, parameter_schema
from .command_readback import (configure_readback, configure_discovery_readback, reconcile_readback,
                               observe_command_response, latest_readback_command)
from .control_resolution import control_decision, resolve_control
from .response_preview import safe_response_preview
from .vehicle import V3Vehicle


class CommandEngine:
    def __init__(self, *, auth, transport, storage, profiles, require_vehicle,
                 operation_request, api_record, notify):
        self.auth = auth
        self._transport = transport
        self.storage = storage
        self.profiles = profiles
        self.require_vehicle = require_vehicle
        self._operation_request = operation_request
        self._api_record = api_record
        self._notify_discovery_change = notify
        self._actions = asyncio.Lock()

    @property
    def transport(self):
        return self._transport()

    async def _command_request(self, car: V3Vehicle, ident: str,
                               params: dict[str, Any] | None = None):
        profile = self.profiles[car.vin.lower()]
        route = profile.custom.get(ident, {})
        op = profile.registry.operations[ident]
        rendered = map_parameters(op if op.get("input_schema") else route, params)
        family, method, path, body = self._operation_request(car, ident, rendered)
        mode = op.get("request_mode")
        if mode in ("mbb_climate_start", "mbb_climate_stop"):
            from .legacy_commands import climate_body
            body = climate_body(mode, params or {})
        elif mode in {"charging_settings_update",
                    "charging_profile_update", "climate_settings_update",
                    "climate_start_settings", "flash", "auxiliary_start",
                    "engine_start"}:
            from .command_payloads import build
            body = await build(self, car, mode, params or {})
        return family, method, path, body

    async def _prepare_command(self, car, operation, params):
        """Validate ordinary commands before journaling; defer OEM proof until persisted."""
        profile = self.profiles[car.vin.lower()]
        proof_required = profile.registry.operations[operation].get("request_mode") == "engine_start"
        if proof_required:
            if params:
                raise ValueError("Unexpected engine start parameters")
            request = self._operation_request(car, operation, params)
        else:
            request = await self._command_request(car, operation, params)
        return proof_required, request

    async def _dispatch_command(self, car, family, method, path, body):
        if family == "mbb" and hasattr(self.transport, "executors"):
            from .legacy_commands import configure_home_region
            await configure_home_region(self.transport,self.auth,car)
        if family == "mbb" and path.endswith(("/lock", "/unlock")):
            from .legacy_commands import security_token
            token = await security_token(self.transport, car.vin, path.rsplit("/", 1)[-1],
                                         getattr(self.auth.service, "_spin", None))
            return await self.transport.request(family, method, path, body=body,
                                                explicit_action=True, security_token=token)
        return await self.transport.request(family, method, path, body=body, explicit_action=True)

    async def _execute_prepared(self, car, profile, record, prepared, params):
        """One physical dispatch and initial evidence path, after durable journaling."""
        proof_required, (family, method, path, body) = prepared

        def observe(status):
            if record.origin == "workbench":
                profile.observe_http(record.engineering_sequence, status)
            else:
                record.observe_http(status)

        try:
            if proof_required:
                family, method, path, body = await self._command_request(car, record.operation, params)
            response = await self._dispatch_command(car, family, method, path, body)
        except (TimeoutError, OSError, RuntimeError, ValueError):
            observe(None)
            self._api_record(profile, record.operation, family, method, None, car.vin)
            raise
        observe(response.status)
        if family == "cariad" and 200 <= response.status < 300:
            from .request_status import request_id_of
            record.request_id = request_id_of(response.data)
        self._api_record(profile, record.operation, family, method, response, car.vin)
        return family, path, response

    def control_routes_for(self, vin: str, capability: str, action: str) -> dict[str, Any]:
        vehicle = self.require_vehicle(vin)
        profile = self.profiles[vehicle.vin.lower()]
        applicable = profile.registry.resolve(capability, action, vehicle.context)["available_operations"]
        routes = [
            {
                "id": op, "family": profile.registry.operations[op]["family"],
                "method": profile.registry.operations[op]["method"],
                "path": profile.registry.operations[op]["path"],
                "approval_group": approval_group(capability, action, profile.registry.operations[op]),
                "parameters_required": bool(parameter_schema(profile.registry.operations[op], profile.custom.get(op, {})))
                    or profile.registry.operations[op].get("request_mode") == "climate_settings_update",
                "parameter_schema": parameter_schema(profile.registry.operations[op], profile.custom.get(op, {})),
                "status": profile.control_results.get(op, "not_tested"),
                "active": profile.active.get(f"{capability}.{action}") == op,
                "runtime_ready": runtime_ready(profile.custom.get(op, {})),
                "parameter_bindings": profile.custom.get(op, {}).get("parameter_bindings", {}),
                "request_mode": profile.registry.operations[op].get("request_mode"),
                # Definition only; no resolved credentials.
                "request_body": profile.registry.operations[op].get("request_body"),
                "request_variables": profile.registry.operations[op].get("request_variables", {}),
                "handler": profile.registry.operations[op].get("handler"),
                "scope": profile.registry.operations[op].get("scope", {}),
            }
            for op in applicable if profile.registry.operations[op]["method"] in ("POST", "PUT")
        ]
        in_progress = profile.discovery._active
        match = control_decision(vehicle, profile, self.auth, capability, action)
        return {
            "capability": capability, "action": action,
            "routes": routes, "active": match["operation"],
            "binding": match,
            "pending": in_progress.public() if in_progress else None,
            "requires": "Explicit per-action consent and physical verification",
            "spin_configured": bool(getattr(getattr(self.auth, "service", None), "_spin", None)),
        }

    async def disable_control(self, vin: str, capability: str, action: str, *, disabled=True) -> None:
        async with self._actions:
            vehicle = self.require_vehicle(vin)
            profile = self.profiles[vehicle.vin.lower()]
            if disabled:
                profile.disable(capability, action)
            else:
                if not profile.registry.operations_for(capability, action):
                    raise ValueError("Unknown control")
                profile.discovery.enable(capability, action)
            await self.storage.async_save(self.profiles)
            self._notify_discovery_change()

    def reconcile_commands(self) -> None:
        """Correlate fresh scheduled observations without another request."""
        for vin, profile in self.profiles.items():
            try:
                car = self.require_vehicle(vin)
            except ValueError:
                continue
            active = profile.discovery._active
            if (active is not None and active.result == "awaiting_user_feedback"
                    and active.sequence != profile.invalidated_attempt_sequence):
                record = profile.engineering_record(active.sequence)
                if record and record.state == "accepted_unconfirmed" and reconcile_readback(record, car):
                    self._confirm_working_readback(profile, active, record)
            # Reconcile independent commands even when a different capability
            # has subsequently been used. Never attribute a newer same-field
            # observation to a superseded accepted action.
            attributes = {record.readback_attribute for record in profile.command_journal
                          if record.readback_attribute}
            for attribute in attributes:
                record = latest_readback_command(profile, attribute)
                if record and reconcile_readback(record, car) and record is profile.last_command:
                    car.last_command_result = "verified"

    def refresh_bindings(self) -> None:
        """Pure local matching; no request per control and no physical tests."""
        for key, profile in self.profiles.items():
            try:
                car = self.require_vehicle(key)
            except ValueError:
                continue
            profile.fast_bindings = {
                f"{capability}.{action}": control_decision(car, profile, self.auth, capability, action)
                for capability, definition in profile.registry.capabilities.items()
                for action in (definition.get("control") or {})
            }

    def _command_route(self, vin: str, aspect: str, capability: str) -> str | None:
        try:
            car = self.require_vehicle(vin)
        except ValueError:
            return None
        return resolve_control(car, self.profiles[vin.lower()], self.auth, capability, aspect)

    def control_enabled(self, vin: str, aspect: str, capability: str = "climate") -> bool:
        return self._command_route(vin, aspect, capability) is not None

    def _reserve_wake(self, vin: str, operation: str) -> None:
        if operation not in ("cariad.remote.wake", "cariad.remote.refresh"):
            return
        remaining = getattr(self.transport, "remaining_calls", None)
        if remaining is not None and remaining <= 12:
            raise RuntimeError("Audi wake quota reserve reached")
        from .command_journal import check_wake_budget
        check_wake_budget(self.profiles[vin.lower()], time.time())

    async def test_action(
        self, vin: str, aspect: str, operation: str,
        *, params: dict[str, Any] | None = None, capability: str = "climate",
        guided: bool = False, expert: bool = False, approval: str | None = None,
    ) -> dict[str, Any]:
        """One action consent; at most one reviewed equivalent after definite rejection."""
        async with self._actions:
            from .control_resolution import reviewed_alternative
            car = self.require_vehicle(vin)
            context = car.context
            profile = self.profiles[vin.lower()]
            alternative = reviewed_alternative(capability, aspect, operation) if guided else None
            if alternative and (alternative in profile.custom or alternative not in profile.registry.resolve(
                    capability, aspect, context)["available_operations"] or
                    approval_group(capability, aspect, profile.registry.operations[alternative]) != approval):
                alternative = None
            revision = operation_revision(profile.registry.operations[alternative]) if alternative else None
            result = await self._test_action_once(vin, aspect, operation, params=params,
                capability=capability, guided=guided, expert=expert, approval=approval)
            if not alternative or result["physical_result"] != "rejected":
                return result
            profile = self.profiles[vin.lower()]
            # Respect the same per-vehicle cooldown; no detached background work.
            delay = profile.discovery.history[-1].started_at + profile.discovery.cooldown_seconds - time.time()
            if delay > 15:
                return {**result, "alternative": "paused_cooldown"}
            if delay > 0:
                await asyncio.sleep(delay)
            remaining = getattr(self.transport, "remaining_calls", None)
            if (car.context != context or self.profiles.get(vin.lower()) is not profile
                    or operation_revision(profile.registry.operations[alternative]) != revision
                    or (remaining is not None and remaining <= 12)):
                return {**result, "alternative": "paused_context_or_quota"}
            from .read_discovery import user_test_candidates
            candidate = user_test_candidates(self, car, profile, include_verified=expert).get(f"{capability}.{aspect}")
            if candidate is None or candidate[3:] != (alternative, approval):
                return {**result, "alternative": "no_eligible_route"}
            try:
                next_result = await self._test_action_once(vin, aspect, alternative, params=params,
                    capability=capability, guided=True, expert=expert, approval=approval)
            except (ValueError, RuntimeError, OSError, TimeoutError):
                if profile.discovery._active is not None:
                    raise  # The alternate may have been dispatched; preserve pending uncertainty.
                return {**result, "alternative": "paused_check_status"}
            return {**next_result, "previous_attempt": {"operation": operation,
                        "sequence": result["sequence"], "status": result["status"], "result": "rejected"}}

    async def _test_action_once(self, vin, aspect, operation, *, params, capability,
                                guided, expert, approval):
        """Shared single physical dispatch; caller holds the command lock."""
        vehicle = self.require_vehicle(vin)
        profile = self.profiles[vin.lower()]
        if guided:
            from .read_discovery import user_test_candidates
            candidate = user_test_candidates(self, vehicle, profile, include_verified=expert).get(f"{capability}.{aspect}")
            if candidate is None or candidate[3:] != (operation, approval) or params:
                raise ValueError("Discovery action changed; refresh status before testing")
        family = profile.registry.operations.get(operation, {}).get("family")
        if family not in ("cariad","mbb") or (family=="mbb" and self.auth.uses_auth0):
            raise ValueError("Control is not applicable to this authentication family")
        if operation not in profile.registry.resolve(
            capability, aspect, vehicle.context
        )["available_operations"]:
            raise ValueError("Control not applicable to this car")
        if capability == "remote" and aspect in ("engine_start", "engine_stop"):
            from .command_policy import eligible_operation
            if eligible_operation(vehicle, self.auth, capability, aspect) != operation:
                raise ValueError("Remote engine operation is not permitted for this vehicle")
        if profile.registry.operations[operation]["method"] not in ("POST", "PUT"):
            raise ValueError("Read-only operation cannot be a control")
        if profile.discovery._active is not None:
            raise ValueError("Review the previous action before trying another")
        if profile.last_command is not None:
            check_command_sequence(profile, time.time(), capability=capability, action=aspect,
                                   cooldown=ENGINEERING_COMMAND_COOLDOWN_SECONDS)
        if f"{capability}.{aspect}" in profile.discovery.disabled:
            raise ValueError("This action has been disabled by the user")
        if (profile.discovery.history and
                time.time() < profile.discovery.history[-1].started_at
                + profile.discovery.cooldown_seconds):
            raise ValueError("Vehicle command cooldown still active")
        # Reject invalid templates/parameters BEFORE reserving a pending
        # physical action, otherwise a mere validation error locks the car.
        prepared = await self._prepare_command(vehicle, operation, params)
        self._reserve_wake(vehicle.vin, operation)
        with profile.command_transaction():
            attempt = profile.begin_test(
                capability, aspect, operation, now=time.time()
            )
            record = profile.engineering_record(attempt.sequence)
            if record is None:
                raise RuntimeError("Missing durable engineering command record")
            if guided:
                configure_discovery_readback(record, vehicle, params)
            await self.storage.async_save(self.profiles)
        try:
            family, _, response = await self._execute_prepared(vehicle, profile, record, prepared, params)
        except (TimeoutError, OSError, RuntimeError, ValueError):
            response = None
        from .read_discovery import explicitly_unsupported
        if (guided and response is not None and response.status in (405, 410)
                and explicitly_unsupported(response.data) and record.state == "rejected"
                and attempt.sequence != profile.invalidated_attempt_sequence):
            profile.reject_test(attempt.sequence, now=time.time())
        if guided and response is not None and record.state == "accepted_unconfirmed":
            observe_command_response(record, vehicle, profile, family, response)
            if record.state == "verified" and attempt.sequence != profile.invalidated_attempt_sequence:
                self._confirm_working_readback(profile, attempt, record)
        await self.storage.async_save(self.profiles)
        if guided and attempt.result in ("worked", "rejected"):
            self._notify_discovery_change()
        return {
            "sequence": attempt.sequence, "operation": operation,
            "transport": attempt.transport,
            "status": response.status if response else None,
            "response_preview": None if (capability == "access" or aspect in (
                "engine_start", "engine_stop", "preheater_start"
            )) else safe_response_preview(
                response.data if response else None,
                vehicle_vin=vehicle.vin,
            ),
            "physical_result": ("verified" if attempt.result == "worked" else
                                "rejected" if attempt.result == "rejected" else "requires_user_confirmation"),
        }

    def _confirm_working_readback(self, profile, attempt, record):
        profile.confirm(attempt.sequence, worked=True, inspected_vehicle=False,
                        now=max(time.time(), record.completed_at or record.started_at), readback_verified=True)
        if (profile.control_results.get(attempt.operation) == "worked"
                and runtime_ready(profile.custom.get(attempt.operation, {}))):
            profile.choose_working(attempt.capability, attempt.action, attempt.operation)

    async def review_action(
        self, vin: str, sequence: int, outcome: str,
    ) -> dict[str, Any]:
        async with self._actions:
            profile = self.profiles[self.require_vehicle(vin).vin.lower()]
            if outcome not in ("worked", "failed", "uncertain"):
                raise ValueError("Unsupported outcome")
            profile.confirm(
                sequence,
                worked=None if outcome == "uncertain" else outcome == "worked",
                inspected_vehicle=outcome != "uncertain",
                now=time.time(),
            )
            if outcome == "worked":
                attempt = profile.discovery.history[-1]
                if (profile.control_results.get(attempt.operation) == "worked"
                        and runtime_ready(profile.custom.get(attempt.operation, {}))):
                    profile.choose_working(
                        attempt.capability, attempt.action, attempt.operation
                    )
            await self.storage.async_save(self.profiles)
            self._notify_discovery_change()
            return {"confirmed": outcome, "active": dict(profile.active)}

    async def send_control(
        self, vin: str, aspect: str, capability: str = "climate",
        *, params: dict[str, Any] | None = None, _follow_up_to: str | None = None,
    ) -> CommandRecord:
        """One journaled mutation, persisted before dispatch; never replay.

        Only an opt-in, linked refresh after a completed user command may
        bypass the general command cooldown. It still needs its own route,
        security policy, wake budget and durable journal entry.
        """
        async with self._actions:
            car = self.require_vehicle(vin)
            p = self.profiles[vin.lower()]
            if p.discovery._active is not None and p.discovery._active.capability == capability:
                raise RuntimeError("A control experiment for this capability is awaiting physical confirmation")
            if blocking_normal_command(p, capability) is not None:
                raise RuntimeError("Previous command for this capability is uncertain; inspect and review it")
            if _follow_up_to is not None:
                parent = p.last_command
                if (capability != "remote" or aspect != "refresh" or parent is None
                        or parent.command_id != _follow_up_to
                        or parent.state not in ("backend_completed", "verified")
                        or parent.parent_command_id is not None
                        or (parent.capability == "remote" and parent.action in ("refresh", "wake"))):
                    raise RuntimeError("No eligible completed parent command for vehicle refresh")
            elif p.last_command is not None:
                check_command_sequence(p, time.time(), capability=capability, action=aspect)
            if p.discovery.history and time.time() < (
                p.discovery.history[-1].started_at + p.discovery.cooldown_seconds
            ):
                raise RuntimeError("Vehicle command cooldown active after engineering test")
            ident = self._command_route(vin, aspect, capability)
            if ident is None:
                raise RuntimeError("No eligible Audi command route")
            prepared = await self._prepare_command(car, ident, params)
            self._reserve_wake(vin, ident)
            record = CommandRecord.begin(capability, aspect, ident, time.time(),
                                         operation_revision=operation_revision(p.registry.operations[ident]),
                                         parent_command_id=_follow_up_to)
            configure_readback(record, params)
            with p.command_transaction():
                p.track_command(record)
                # No physical action until the pending record is durable.
                await self.storage.async_save(self.profiles)
            try:
                family, path, response = await self._execute_prepared(car, p, record, prepared, params)
                if not 200 <= response.status < 300:
                    car.last_command_result = f"request_failed_{response.status}"
                else:
                    car.last_command_result = record.state
                    if family == "cariad":
                        from .request_status import confirm
                        request_id = record.request_id
                        # Persist backend acceptance/ID before a cancellable follow-up.
                        await self.storage.async_save(self.profiles)
                        if request_id is not None:
                            car.last_command_result = await confirm(self.transport, car.vin, request_id)
                    elif family == "mbb":
                        from .legacy_commands import confirm
                        car.last_command_result = await confirm(self.transport, path, response.data)
                    record.backend_result = car.last_command_result
                    if car.last_command_result in ("backend_completed", "rejected"):
                        record.state = car.last_command_result
                        record.completed_at = max(record.started_at, time.time())
                    elif car.last_command_result in ("unknown", "quota_limited", "pending"):
                        record.state = "uncertain"
            except asyncio.CancelledError:
                # The pre-dispatch journal is already durable; restart restores uncertainty.
                record.state = "uncertain"
                record.backend_result = "transport_uncertain"
                car.last_command_result = "transport_uncertain"
                raise
            except (TimeoutError, OSError, RuntimeError, ValueError) as err:
                record.state = "uncertain"
                record.backend_result = "transport_uncertain"
                car.last_command_result = "transport_uncertain"
                record.completed_at = max(record.started_at, time.time())
                await self.storage.async_save(self.profiles)
                self._notify_discovery_change()
                advice = "inspect and review in Engineering Dashboard" if record.requires_review else "check the vehicle; try again after the short cooldown"
                raise RuntimeError(f"Audi {capability}.{aspect}: connection error or timeout; outcome uncertain. {advice}.") from err
            if record.state in ("accepted_unconfirmed", "backend_completed"):
                observe_command_response(record, car, p, family, response)
                if record.state == "verified":
                    car.last_command_result = "verified"
            if record.state in ("rejected", "uncertain"):
                record.completed_at = max(record.started_at, time.time())
            await self.storage.async_save(self.profiles)
            self._notify_discovery_change()
            if record.state in ("rejected", "uncertain"):
                detail = f"HTTP {response.status}" if not 200 <= response.status < 300 else (record.backend_result or record.state)
                advice = ("inspect and review in Engineering Dashboard" if record.requires_review
                          else "check the vehicle; try again after the short cooldown" if record.state == "uncertain"
                          else "check permissions, quota or vehicle prerequisites")
                raise RuntimeError(f"Audi {capability}.{aspect}: {detail}; {record.state}. {advice}.")
            return record

    async def review_normal_command(self, vin: str, command_id: str) -> None:
        """Explicit acknowledgement after inspecting the car; never dispatch."""
        async with self._actions:
            car = self.require_vehicle(vin)
            p = self.profiles[car.vin.lower()]
            record = next((row for row in unresolved_normal_commands(p)
                           if row.command_id == command_id), None)
            if record is None:
                raise ValueError("No matching unresolved normal command")
            record.state = "reviewed"
            record.completed_at = max(record.started_at, time.time())
            await self.storage.async_save(self.profiles)
            self._notify_discovery_change()

    async def send_setting(self, vin: str, kind: str, value: Any) -> CommandRecord:
        """Typed V3-owned write through an explicitly verified route.

        This method cannot invoke V2. OEM method, path and body are owned by
        the active declarative V3 operation.
        """
        if kind == "set_target_soc":
            if (isinstance(value, bool) or not isinstance(value, int)
                    or value not in range(20, 101, 5)):
                raise ValueError("Audi target SoC must be 20..100 in steps of 5")
        elif kind == "set_charge_mode":
            if value not in ("manual", "timer"):
                raise ValueError("Audi charge mode must be manual or timer")
        else:
            raise ValueError("Unsupported V3 setting")
        return await self.send_control(vin, kind, "charging", params={"value": value})

