"""Generic bounded status plan from capability definitions and local bindings."""

from __future__ import annotations


def status_groups(profile, context):
    """Only scheduled or explicitly selected GETs start a capability group.

    Only scheduled routes and explicitly selected alternatives may poll.
    Missing jobs are handled by the bounded read-discovery owner.
    """
    groups = []
    for capability, definition in profile.registry.capabilities.items():
        if not definition.get("status"):
            continue
        routes = profile.registry.resolve(capability, "status", context)[
            "available_operations"
        ]
        scheduled = [
            ident
            for ident in routes
            if profile.registry.operations[ident]["delivery"] == "existing_poll"
        ]
        chosen = profile.active.get(f"{capability}.status")
        if chosen not in routes:
            chosen = None
        if not scheduled and not chosen:
            continue
        # Manual inventory belongs in Workbench; missing jobs are handled by
        # the bounded read-discovery scheduler, not an every-poll climate scan.
        candidates = list(scheduled)
        if chosen and chosen not in candidates:
            candidates.append(chosen)
        if chosen in candidates:
            candidates.remove(chosen)
            candidates.insert(0, chosen)
        # Shared job batch has no dependency on a particular capability name.
        batch = next(
            (
                ident
                for ident in scheduled
                if "{JOBS}" in profile.registry.operations[ident]["path"]
            ),
            None,
        )
        if batch in candidates and len(profile.registry.capabilities) > 1:
            candidates.remove(batch)
            candidates.insert(0, batch)
        groups.append((capability, candidates[:3], chosen, batch))
    groups.sort(key=lambda group: group[3] is None)
    return groups
