"""Read-only access data display. Stale or partial is never a safe closed state."""
from .freshness import capture_age_minutes

COMPONENTS = {
    "door": ("frontLeft", "frontRight", "rearLeft", "rearRight", "trunk", "bonnet"),
    "window": ("frontLeft", "frontRight", "rearLeft", "rearRight"),
}

def _component_state(tokens, positive, negative):
    if (not isinstance(tokens, list) or any(token in tokens for token in ("unsupported", "invalid", "unknown"))
            or (positive in tokens) == (negative in tokens)):
        return "unknown"
    return positive if positive in tokens else negative


def access_summary(car, kind):
    row = car.readings.get(kind + "_detail", {})
    value = row.get("value")
    rows = value.get("items", []) if isinstance(value, dict) else []
    names = COMPONENTS[kind]
    # Only explicitly known components. Contradictions and duplicates are unknown.
    states, locks, roof = {}, {}, {}
    for component in rows:
        name, tokens = component.get("name"), component.get("status")
        if kind == "window" and name in ("sunRoof", "roofCover"):
            roof[name] = "unknown" if name in roof else _component_state(tokens, "open", "closed")
            continue
        if name not in names:
            continue
        state = _component_state(tokens, "open", "closed")
        states[name] = "unknown" if name in states else state
        if kind == "door":
            locks[name] = "unknown" if name in locks else _component_state(tokens, "unlocked", "locked")
    states = {name: states.get(name, "unknown") for name in names}
    age = capture_age_minutes(row.get("captured"))
    aggregate = ("open" if "open" in states.values() else
                 "closed" if all(s == "closed" for s in states.values()) else "unknown")
    state = ("unknown" if age is None else "stale" if age > 60 else aggregate)
    return state, {"components": states, "lock_states": locks, "roof_components": roof,
                   "last_reported_aggregate": aggregate,
                   "vehicle_captured": row.get("captured"), "age_minutes": age,
                   "cloud_observed": row.get("observed"),
                   "freshness": "unknown" if age is None else "stale" if age > 60 else "fresh",
                   "complete": all(s != "unknown" for s in states.values())}
