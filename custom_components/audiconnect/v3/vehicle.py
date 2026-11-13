"""Simple V3 vehicle state, without importing the historical V2 models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import re

from .registry import VehicleContext

_INVALID = frozenset({"", "invalid", "unsupported", "unknown", "error", "unavailable"})
CLIMATE_OFF_STATES = ("off", "stopped", "inactive")
CLIMATE_ON_STATES = ("heating", "cooling", "ventilation", "on", "active")
CHARGING_ON_STATES = ("charging",)
CHARGING_OFF_STATES = (
    "off",
    "stopped",
    "notcharging",
    "not_charging",
    "notreadyforcharging",
    "readyforcharging",
)


def charging_active(value):
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return (
        True
        if value in CHARGING_ON_STATES
        else False
        if value in CHARGING_OFF_STATES
        else None
    )


def charging_ready(value):
    """Only explicit OEM readiness statuses, not a command permission."""
    if not isinstance(value, str):
        return None
    return {"readyforcharging": True, "notreadyforcharging": False}.get(
        value.strip().lower()
    )


def window_heating_active(rows):
    """Actual window state only: a positive is conclusive; off requires both known."""
    if not isinstance(rows, list) or not rows:
        return None
    states = {}
    for row in rows:
        if not isinstance(row, dict):
            return None
        location, state = row.get("windowLocation"), row.get("windowHeatingState")
        if location not in ("front", "rear") or location in states:
            return None
        states[location] = state.strip().lower() if isinstance(state, str) else None
    if "on" in states.values():
        return True
    if set(states) == {"front", "rear"} and all(
        state == "off" for state in states.values()
    ):
        return False
    return None


def model_family_from_name(value):
    """Only manufacturer model labels, never nickname or VIN inference."""
    if not isinstance(value, str):
        return ""
    label = re.sub(r"^audi\s+", "", value.strip(), flags=re.I)
    match = re.match(r"^(?:(?:rs|sq|s|q|a)\s*[1-9]|r8)(?=\b|[- ])", label, re.I)
    if match:
        return re.sub(r"\s+", "", match.group(0)).lower()
    return "e-tron" if re.match(r"^e[- ]tron\b", label, re.I) else ""


def normalize_powertrain(value):
    """Normalize explicit vendor enums, never infer from a model label."""
    if not isinstance(value, str):
        return None
    token = re.sub(r"[^a-z0-9]", "", value.lower())
    groups = {
        "phev": {"phev", "pluginhybrid", "pluginhybridelectricvehicle"},
        "hybrid": {"hybrid", "hev", "hybridelectricvehicle", "mhev", "mildhybrid"},
        "electric": {"electric", "bev", "batteryelectric", "batteryelectricvehicle"},
        "combustion": {
            "combustion",
            "ice",
            "internalcombustion",
            "internalcombustionengine",
            "gasoline",
            "petrol",
            "diesel",
            "cng",
            "lpg",
        },
    }
    return next((key for key, values in groups.items() if token in values), None)


def powertrain_identity(vehicle):
    """Reconcile inventory, status and trips without granting control rights."""
    readings = getattr(vehicle, "readings", {})
    trips = getattr(vehicle, "trips", {})
    sources = {}

    def add(source, value):
        normalized = normalize_powertrain(value)
        if normalized is not None:
            sources[source] = normalized

    add("inventory", getattr(vehicle, "car_type", None))
    for ident, source in (
        ("carType", "range_status"),
        ("measuredCarType", "fuel_level_status"),
    ):
        row = readings.get(ident, {})
        if row.get("status") in ("verified", "readable_but_stale"):
            add(source, row.get("value"))
    for key in ("last_trip", "shortterm_current", "longterm_current"):
        add(key, trips.get(key, {}).get("vehicleType"))
    roles = {
        normalize_powertrain(readings.get(key, {}).get("value"))
        for key in ("primary_engine_type", "secondary_engine_type")
        if readings.get(key, {}).get("status") in ("verified", "readable_but_stale")
    }
    if {"electric", "combustion"} <= roles:
        sources["engine_roles"] = "hybrid"
    families = {"hybrid" if value == "phev" else value for value in sources.values()}
    conflict = len(families) > 1
    value = (
        None
        if conflict or not families
        else ("phev" if "phev" in sources.values() else next(iter(families)))
    )
    return {"value": value, "sources": sources, "conflict": conflict}


def select_vehicle_image(vehicle, vin):
    """Pick one trusted, public Audi render; never use arbitrary CDN URLs."""
    from urllib.parse import urlsplit, parse_qsl, unquote

    if not isinstance(vehicle, dict) or not isinstance(
        vehicle.get("renderPictures"), list
    ):
        return None
    candidates = []
    for picture in vehicle["renderPictures"][:32]:
        if not isinstance(picture, dict):
            continue
        url, kind = picture.get("url"), picture.get("mediaType")
        if not isinstance(url, str) or len(url) > 4096 or not isinstance(kind, str):
            continue
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "mediaservice.audi.com"
                or parsed.username
                or parsed.password
                or parsed.port
                or parsed.fragment
                or not parsed.path
                or vin.lower() in unquote(url).lower()
                or any(
                    re.search(
                        r"token|secret|auth|password|credential|session|vin", k, re.I
                    )
                    for k, _ in parse_qsl(parsed.query, keep_blank_values=True)
                )
            ):
                continue
        except ValueError:
            continue
        # Prefer a large side profile where available; accept other OEM views.
        priority = (
            "MYAPN8NB",
            "MYAAN8NB",
            "MS_MYP5",
            "MYAPN3NB",
            "MS_MYP4",
            "MS_MYP3",
            "MYAAN3NB",
        )
        candidates.append(
            (priority.index(kind) if kind in priority else len(priority), url)
        )
    return min(candidates)[1] if candidates else None


@dataclass
class V3Vehicle:
    vin: str
    name: str
    model: str
    model_family: str
    country: str
    car_type: str = ""
    model_year: str = ""
    model_source: str = ""
    auth_family: str = "auth0"
    legacy_cariad: bool = False
    legacy_api_level: int = 0
    last_command_result: str | None = None
    readings: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Latest normalized sample per family, in memory only; no raw payload cache.
    family_readings: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    capability_readings: dict[str, dict[str, Any]] = field(default_factory=dict)
    position: dict[str, Any] | None = None  # V3-owned, in-memory parked GPS
    charging_profiles: list[dict[str, Any]] = field(default_factory=list)
    active_charging_profile_id: int | None = None
    charging_profiles_captured: str | None = None
    trips: dict[str, dict[str, Any]] = field(default_factory=dict)
    trip_history: list[dict[str, Any]] = field(
        default_factory=list
    )  # local normalized archive
    advertised_capabilities: set[str] = field(default_factory=set)
    impaired_capabilities: set[str] = field(default_factory=set)
    v2_initial_discovery_completed: bool = False
    inventory_present: bool = True
    inventory_misses: int = 0
    image_url: str | None = None
    image_status: str = "not_assessed"
    identity_restored: bool = False
    identity_observed_at: str | None = None
    identity_operation: str | None = None
    registry_model: str | None = None
    year_operation: str | None = None

    @classmethod
    def from_graphql(cls, item: dict[str, Any], country: str) -> V3Vehicle:
        vin = item.get("vin")
        if not isinstance(vin, str) or len(vin) != 17 or not vin.isalnum():
            raise ValueError("Invalid Audi vehicle identifier")
        vehicle = item.get("vehicle") if isinstance(item.get("vehicle"), dict) else {}
        media = vehicle.get("media") if isinstance(vehicle.get("media"), dict) else {}

        def label(key):
            value = media.get(key)
            return (
                value.strip()
                if (
                    isinstance(value, str)
                    and 0 < len(value.strip()) <= 120
                    and value.strip().lower() not in _INVALID | {"audi", "audi vehicle"}
                    and vin.lower() not in value.lower()
                )
                else ""
            )

        long_name, short_name = label("longName"), label("shortName")
        model = long_name or short_name
        source = (
            "audi_long_name" if long_name else "audi_short_name" if short_name else ""
        )
        family = model_family_from_name(short_name) or model_family_from_name(long_name)
        core = vehicle.get("core") if isinstance(vehicle.get("core"), dict) else {}
        year = str(core.get("modelYear") or "")
        year = (
            year
            if len(year) == 4 and year.isdigit() and 1980 <= int(year) <= 2100
            else ""
        )
        nickname = item.get("nickname")
        title = nickname if isinstance(nickname, str) and nickname.strip() else model
        classification = vehicle.get("classification")
        drive = (
            classification.get("driveTrain", "")
            if isinstance(classification, dict)
            else ""
        )
        return cls(
            vin=vin.upper(),
            name=title or "Audi vehicle",
            model=model,
            model_family=family,
            country=country,
            car_type=drive.strip().lower()
            if isinstance(drive, str) and drive.strip().lower() not in _INVALID
            else "",
            model_year=year,
            model_source=source,
            year_operation="graphql.inventory.vehicleList" if year else None,
        )

    @classmethod
    def from_garage(cls, item: dict[str, Any], country: str) -> V3Vehicle:
        """CARIAD account garage, independent of vgql. Never use nickname as model."""
        from .transport import GARAGE_OPERATION

        vin = item.get("vin")
        if not isinstance(vin, str) or len(vin) != 17 or not vin.isalnum():
            raise ValueError("Invalid Audi vehicle identifier")
        model, source = "", ""
        for key in ("model", "carModel"):
            value = item.get(key)
            if (
                isinstance(value, str)
                and 0 < len(value.strip()) <= 120
                and value.strip().lower() not in _INVALID | {"audi", "audi vehicle"}
                and vin.lower() not in value.lower()
            ):
                model, source = value.strip(), "cariad_" + key
                break
        year = str(item.get("modelYear") or item.get("model_year") or "")
        year = (
            year
            if len(year) == 4 and year.isdigit() and 1980 <= int(year) <= 2100
            else ""
        )
        return cls(
            vin.upper(),
            model or "Audi vehicle",
            model,
            model_family_from_name(model),
            country,
            model_year=year,
            model_source=source,
            identity_operation=GARAGE_OPERATION if model else None,
            year_operation=GARAGE_OPERATION if year else None,
        )

    def merge_identity_evidence(
        self,
        candidate: V3Vehicle,
        *,
        operation: str | None = None,
    ) -> None:
        """Fill independent OEM identity fields from the same VIN and market.

        First accepted evidence wins for each field. Never use display labels,
        cached identity or another vehicle as fresh manufacturer evidence.
        """
        if (
            self.vin.lower() != candidate.vin.lower()
            or self.country != candidate.country
            or candidate.identity_restored
        ):
            return
        if not self.model and candidate.model:
            self.model = candidate.model
            self.model_family = candidate.model_family
            self.model_source = candidate.model_source
            self.identity_operation = operation or candidate.identity_operation
            if self.name == "Audi vehicle":
                self.name = candidate.model
        if not self.model_year and candidate.model_year:
            self.model_year = candidate.model_year
            self.year_operation = operation or candidate.year_operation
        if not self.car_type and candidate.car_type:
            self.car_type = candidate.car_type

    @property
    def context(self) -> VehicleContext:
        return VehicleContext(
            auth=self.auth_family,
            region=self.country,
            vehicle_type=self.car_type,
            model_family=self.model_family,
            legacy_cariad=self.legacy_cariad,
            legacy_api_level=self.legacy_api_level,
        )

    @property
    def climate_supported(self) -> bool | None:
        """No hard unsupported verdict from merely missing cloud data."""
        return True if self.climate_state is not None else None

    @property
    def climate_state(self) -> str | None:
        value = self.readings.get("climatisationState", {}).get("value")
        if isinstance(value, str) and value.strip().lower() not in _INVALID:
            return value.strip().lower()
        return None

    @property
    def climate_captured(self) -> datetime | None:
        from .attribute_runtime import _capture_in_utc

        return _capture_in_utc(
            self.readings.get("climatisationState", {}).get("captured")
        )

    @property
    def climate_source(self) -> str | None:
        return self.readings.get("climatisationState", {}).get("operation")

    @property
    def climate_field(self) -> str | None:
        return self.readings.get("climatisationState", {}).get("path")

    def set_climate(
        self,
        value: Any,
        captured: Any,
        *,
        route: str,
        observed_at: datetime,
        http_status: int,
        path: str | None = None,
    ) -> bool:
        """Compatibility for selected status routes: write the canonical reading."""
        from .attribute_runtime import _accept_observation
        from .freshness import timestamp_is_fresh

        if (
            not 200 <= http_status < 300
            or not isinstance(value, str)
            or value.strip().lower() in _INVALID
        ):
            return False
        if not _accept_observation(self.readings.get("climatisationState"), captured):
            return False
        fresh = timestamp_is_fresh(captured, observed_at)
        self.readings["climatisationState"] = {
            "value": value.strip().lower(),
            "captured": captured,
            "observed": observed_at.isoformat(),
            "fresh": fresh,
            "path": path,
            "job": "climatisation",
            "operation": route,
            "status": "verified" if fresh else "readable_but_stale",
            "family": "mbb" if route.startswith("mbb.") else "cariad",
        }
        return True

    @property
    def capture_age_minutes(self) -> int | None:
        if self.climate_captured is None:
            return None
        from .freshness import capture_age_minutes

        age = capture_age_minutes(self.climate_captured.isoformat())
        return int(age) if age is not None else None
