"""Pure V3 capability registry: no HA services, token handling or HTTP calls.

The registry owns definitions/selection; the runtime owns dispatch and evidence.
Model/region refinements are optional: generic operations always remain defined.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Formatter
from typing import Any
from collections.abc import Mapping

_ALLOWED_FIELDS = frozenset({"VIN", "COUNTRY", "TYPE", "JOBS"})
_ALLOWED_SCOPE = frozenset({"auth", "region", "vehicle_type", "model_family"})
_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT"})


@lru_cache(maxsize=1)
def _builtin_read_paths() -> dict[str, str]:
    """Cache immutable path strings, never a mutable per-vehicle registry."""
    raw = json.loads(
        Path(__file__).with_name("full_catalog.json").read_text(encoding="utf-8")
    )
    catalog = CapabilityRegistry(raw)
    return {
        ident: operation["path"]
        for ident, operation in catalog.operations.items()
        if operation["method"] == "GET"
    }


def builtin_read_path(operation: str) -> str:
    """Return the reviewed built-in GET template, never a local override."""
    return _builtin_read_paths()[operation]


def selective_status_path(vin: str = "{VIN}", jobs: str = "{JOBS}") -> str:
    """One CARIAD selective-status template for polling, discovery and evidence."""
    return builtin_read_path("cariad.climate.status.batch").format(VIN=vin, JOBS=jobs)


def read_json_path(payload: Any, path: str) -> Any:
    """Extract legacy dotted paths or RFC 6901 JSON Pointers, without eval."""
    if not isinstance(path, str) or not path:
        return None
    if path.startswith("/"):
        # RFC 6901: ~1 represents a slash, ~0 represents a tilde.
        parts = [
            part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")
        ]
    else:
        parts = path.split(".")
    node = payload
    for part in parts:
        if isinstance(node, dict):
            if part not in node:
                return None
            node = node[part]
        elif isinstance(node, list):
            if (
                not part.isascii()
                or not part.isdigit()
                or (len(part) > 1 and part[0] == "0")
            ):
                return None
            index = int(part)
            if index >= len(node):
                return None
            node = node[index]
        else:
            return None
    return node


def extract_first(payload: Any, paths) -> tuple[Any, str | None]:
    """One ordered response selector; false and zero are valid observations."""
    for path in paths:
        value = read_json_path(payload, path)
        if value is not None:
            return value, path
    return None, None


class RegistryError(ValueError):
    """Invalid V3 catalog or unsupported operation."""


@dataclass(frozen=True)
class VehicleContext:
    auth: str
    region: str = ""
    vehicle_type: str = ""
    model_family: str = ""
    legacy_cariad: bool = False
    legacy_api_level: int = 0


@dataclass
class RouteEvidence:
    """Evidence for a route, scoped per vehicle by the caller."""

    readable: int = 0
    cached_present: int = 0
    consecutive_not_found: int = 0
    suspended_until: float = 0
    last_result: str = "not_tested"

    def record(self, http_status: int, usable: bool, now: float) -> None:
        if http_status in (404, 410):
            self.consecutive_not_found += 1
            self.last_result = "not_found"
            if self.consecutive_not_found >= 3:
                self.suspended_until = now + 86400
        elif 200 <= http_status < 300 and usable:
            self.readable += 1
            self.consecutive_not_found = 0
            self.suspended_until = 0
            self.last_result = "readable"
        else:
            # Neither sleeping vehicles nor Audi cloud failures remove features.
            self.consecutive_not_found = 0
            self.last_result = (
                "not_authorized"
                if http_status in (401, 403)
                else "rate_limited"
                if http_status == 429
                else "upstream_error"
                if http_status >= 500
                else "inconclusive"
            )

    def suspended(self, now: float) -> bool:
        return now < self.suspended_until


def _check_path(path: Any, extra_fields: frozenset[str] = frozenset()) -> None:
    if not isinstance(path, str) or not path.startswith("/"):
        raise RegistryError("API paths must be relative to approved family hosts")
    if "://" in path or "//" in path or ".." in path or "\\" in path or "#" in path:
        raise RegistryError("Unsafe API path")
    allowed = _ALLOWED_FIELDS | extra_fields
    for _, field_name, format_spec, conversion in Formatter().parse(path):
        if field_name is not None and (
            field_name not in allowed or conversion or format_spec
        ):
            raise RegistryError("Unknown or unsafe path template variable")


class CapabilityRegistry:
    """One brand catalog, with optional operation-level context refinement."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        if raw.get("schema_version") != 1 or raw.get("brand") != "audi":
            raise RegistryError("Unsupported V3 schema or brand")
        self.families = raw.get("api_families")
        self.operations = raw.get("operations")
        self.capabilities = raw.get("capabilities")
        if not all(
            isinstance(x, dict)
            for x in (self.families, self.operations, self.capabilities)
        ):
            raise RegistryError("V3 catalog sections must be objects")
        if not self.capabilities or len(self.capabilities) > 30:
            raise RegistryError("Empty or excessive V3 capability catalog")
        if self.families.get("cariad", {}).get("executor") not in (None, "cariad_v1"):
            raise RegistryError("Unrecognized CARIAD family executor")
        if self.families.get("mbb", {}).get("executor") not in (None, "mbb_legacy_v1"):
            raise RegistryError("Unrecognized legacy MBB executor")
        if self.families.get("graphql", {}).get("executor") not in (
            None,
            "graphql_v1",
        ):
            raise RegistryError("Unrecognized GraphQL family executor")
        for family in self.families.values():
            if not isinstance(family, dict) or (
                type(family.get("priority", 100)) is not int
                or not 0 <= family.get("priority", 100) <= 1000
            ):
                raise RegistryError("Invalid API family priority")
        for op in self.operations.values():
            if not isinstance(op, dict):
                raise RegistryError("Malformed operation")
            family = self.families.get(op.get("family"))
            if not isinstance(family, dict) or family.get("auth") not in (
                "auth0",
                "legacy",
            ):
                raise RegistryError("Unknown API family or auth")
            if op.get("method") not in _ALLOWED_METHODS:
                raise RegistryError("Method not supported by V3 pilot")
            variables = op.get("request_variables", {})
            if (
                not isinstance(variables, dict)
                or len(variables) > 12
                or any(
                    not isinstance(name, str)
                    or not name.isidentifier()
                    or not name.isupper()
                    or name in _ALLOWED_FIELDS
                    or kind not in ("string", "integer", "number", "boolean")
                    for name, kind in variables.items()
                )
            ):
                raise RegistryError("Unrecognized or unsafe declared API variables")
            _check_path(op.get("path"), frozenset(variables))
            scope = op.get("scope", {})
            if not isinstance(scope, dict) or set(scope) - _ALLOWED_SCOPE:
                raise RegistryError("Invalid context refinement")
            if any(not isinstance(v, str) for v in scope.values()):
                raise RegistryError("Context scope values must be strings")
            if op.get("delivery") not in ("existing_poll", "manual"):
                raise RegistryError("Unknown operation owner")
            if op["method"] != "GET" and op["delivery"] != "manual":
                raise RegistryError("A control may never execute automatically")
            if op["method"] == "GET":
                if not isinstance(op.get("response_paths"), list):
                    raise RegistryError("GET requires response mapping paths")
                if any(not isinstance(p, str) for p in op["response_paths"]):
                    raise RegistryError("Invalid response path")
        for definition in self.capabilities.values():
            if not isinstance(definition, dict) or set(definition) - {
                "status",
                "control",
            }:
                raise RegistryError("Capability must own optional status/control")
            if not definition:
                raise RegistryError("Capability must have a supported aspect")
            control = definition.get("control") or {}
            if not isinstance(control, dict) or any(
                not isinstance(action, str) or not action or len(action) > 48
                for action in control
            ):
                raise RegistryError("Invalid control definition")
            for aspect in ("status", *control):
                node = (
                    definition.get("status")
                    if aspect == "status"
                    else control.get(aspect)
                )
                if node is None:
                    continue
                refs = node.get("operations") if isinstance(node, dict) else None
                if (
                    not isinstance(refs, list)
                    or not refs
                    or len(refs) != len(set(refs))
                ):
                    raise RegistryError("Missing or duplicate operation reference")
                for ref in refs:
                    op = self.operations.get(ref)
                    if op is None or (op["method"] == "GET") != (aspect == "status"):
                        raise RegistryError("Invalid operation reference")

    @classmethod
    def from_json_file(cls, path: Path) -> CapabilityRegistry:
        """File read must run in HA's executor, never on the event loop."""
        registry = cls(json.loads(path.read_text(encoding="utf-8")))
        if path == Path(__file__).with_name("full_catalog.json"):
            # Warm the shared route strings in the same HA executor as the catalog.
            _builtin_read_paths()
        return registry

    def family_priority(self, family: str) -> int:
        """One read-source preference per family, not per capability."""
        return self.families[family].get("priority", 100)

    def operations_for(self, capability: str, aspect: str) -> list[str]:
        definition = self.capabilities.get(capability)
        if definition is None or (
            aspect not in ("status", "start", "stop")
            and aspect not in (definition.get("control") or {})
        ):
            raise RegistryError("Unknown capability or aspect")
        node = (
            definition.get("status")
            if aspect == "status"
            else ((definition.get("control") or {}).get(aspect))
        )
        return list(node.get("operations", [])) if node else []

    def resolve(
        self,
        capability: str,
        aspect: str,
        context: VehicleContext,
        evidence: Mapping[str, RouteEvidence] | None = None,
        *,
        preferred: str | None = None,
        now: float = 0,
    ) -> dict[str, Any]:
        """Resolve exactly one known route, without making a network request."""
        evidence = evidence or {}
        candidates: list[str] = []
        excluded: list[dict[str, str]] = []
        for ident in self.operations_for(capability, aspect):
            op = self.operations[ident]
            family = self.families[op["family"]]
            scope = {**op.get("scope", {}), "auth": family["auth"]}
            # Legacy IDK sessions also carry a CARIAD bearer. Only exact
            # built-in historical routes opt in; custom routes never do.
            if (
                context.auth == "legacy"
                and family["auth"] == "auth0"
                and context.legacy_cariad
                and op.get("legacy_compatible") is True
                and (
                    not op.get("legacy_climate_level1") or context.legacy_api_level == 1
                )
            ):
                scope["auth"] = "legacy"
            if (
                context.auth == "legacy"
                and context.legacy_cariad
                and context.legacy_api_level == 1
                and op.get("legacy_climate_level0") is True
            ):
                excluded.append(
                    {"operation": ident, "reason": "legacy_climate_api_level"}
                )
                continue
            if op.get("implementation") == "not_implemented":
                excluded.append(
                    {"operation": ident, "reason": "adapter_not_implemented"}
                )
            elif any(getattr(context, k, None) != v for k, v in scope.items()):
                excluded.append({"operation": ident, "reason": "context_mismatch"})
            elif aspect == "status" and evidence.get(ident, RouteEvidence()).suspended(
                now
            ):
                excluded.append(
                    {"operation": ident, "reason": "temporarily_quarantined"}
                )
            else:
                candidates.append(ident)

        if aspect == "status":
            # Preserve declared route order within a family. Commands retain their
            # independent verification and operation selection contract.
            candidates.sort(
                key=lambda ident: self.family_priority(self.operations[ident]["family"])
            )

        if preferred and preferred not in candidates:
            raise RegistryError("Selected operation does not match vehicle context")
        chosen = preferred
        if chosen is None:
            if aspect == "status":
                # Existing batch first: never schedule a second GET to learn.
                passive = [
                    ident
                    for ident in candidates
                    if self.operations[ident]["delivery"] == "existing_poll"
                ]
                if passive:
                    chosen = min(
                        passive,
                        key=lambda ident: (
                            self.family_priority(self.operations[ident]["family"]),
                            -evidence.get(ident, RouteEvidence()).readable,
                            self.operations[ident].get("priority", 100),
                        ),
                    )
            else:
                # Choosing a command here never invokes it: the HA user still
                # has to press ON/OFF. No automatic fallback or retries.
                if candidates:
                    chosen = min(
                        candidates,
                        key=lambda ident: self.operations[ident].get("priority", 100),
                    )

        return {
            "operation": chosen,
            "reason": "preferred"
            if preferred
            else (
                "existing_poll"
                if aspect == "status" and chosen
                else "manual_control_only"
                if chosen
                else "no_applicable_route"
            ),
            "available_operations": candidates,
            "excluded": excluded,
        }

    def extract(self, operation: str, payload: Any) -> tuple[Any, str | None]:
        """Read a declarative RFC 6901 pointer or legacy dotted path."""
        op = self.operations[operation]
        if op["method"] != "GET":
            raise RegistryError("Only a GET response may be extracted")
        return extract_first(payload, op["response_paths"])
