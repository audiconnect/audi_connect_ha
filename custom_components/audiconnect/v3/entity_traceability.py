"""Admin-only reverse index from product and mapping contracts."""

from .product_contract import product_inventory


def link_entities(report, actual, inventory=None):
    inventory = product_inventory()["entities"] if inventory is None else inventory
    rows = report.get("rows", [])
    keys = set(actual)
    keys.update(
        mapping["entity_key"]
        for op in report.get("operations", [])
        for mapping in op.get("mappings", [])
        if mapping.get("entity_key")
    )
    keys.update(
        f"{row['platform']}.{row['entity_key']}"
        for row in rows
        if row.get("platform")
        and row.get("entity_key")
        and (row.get("custom") or f"{row['platform']}.{row['entity_key']}" in inventory)
    )
    by_key = {
        key: {
            "contract_key": key,
            "entity_ids": sorted(set(actual.get(key, []))),
            "capabilities": set(),
            "attributes": set(),
            "operations": set(),
        }
        for key in keys
    }
    for operation in report.get("operations", []):
        for mapping in operation.get("mappings", []):
            key = mapping.get("entity_key")
            mapping["entity_ids"] = sorted(set(actual.get(key, [])))
            if key not in by_key:
                continue
            entry = by_key[key]
            if mapping.get("capability"):
                entry["capabilities"].add(mapping["capability"])
            if mapping.get("attribute"):
                entry["attributes"].add(mapping["attribute"])
            entry["operations"].add(operation["operation"])
    known_operations = {
        operation["operation"] for operation in report.get("operations", [])
    }
    for key, entry in by_key.items():
        sources = set(inventory.get(key, {}).get("source_attributes", []))
        for row in rows:
            direct = key == f"{row.get('platform')}.{row.get('entity_key')}"
            if not row.get("entity_key") or not (
                direct or row.get("attribute") in sources
            ):
                continue
            entry["attributes"].add(row["attribute"])
            entry["capabilities"].add(row["capability"])
            if row.get("operation") in known_operations:
                entry["operations"].add(row["operation"])
        if not entry["capabilities"] and key in {
            "sensor.vehicle_data_freshness",
            "sensor.vehicle_data_age",
            "sensor.cloud_last_successful_poll",
            "sensor.api_requests_remaining",
            "sensor.discovery_coverage",
            "sensor.integration_status",
            "sensor.last_error",
            "binary_sensor.integration_problem",
            "button.v3_refresh_cloud",
        }:
            entry["capabilities"].add("integration_health")
        if key in ("sensor.door_status", "sensor.window_status"):
            entry["capabilities"].add("access")
        if key in (
            "device_tracker.position",
            "sensor.last_trip",
            "sensor.trip_history",
        ) or inventory.get(key, {}).get("trip_metric"):
            entry["capabilities"].add("mobility")
        for field in ("capabilities", "attributes", "operations"):
            entry[field] = sorted(entry[field])
    for row in rows:
        key = f"{row.get('platform')}.{row.get('entity_key')}"
        linked = [
            entry
            for entry in by_key.values()
            if entry["contract_key"] == key
            or (
                row.get("entity_key")
                and row.get("attribute") in entry["attributes"]
                and row.get("capability") in entry["capabilities"]
            )
        ]
        row["entity_keys"] = sorted(entry["contract_key"] for entry in linked)
        row["entity_ids"] = sorted(
            {eid for entry in linked for eid in entry["entity_ids"]}
        )
    for action in report.get("control_actions", []):
        linked = [
            entry
            for entry in by_key.values()
            if action.get("capability") in entry["capabilities"]
            and "control." + str(action.get("action")) in entry["attributes"]
        ]
        action["entity_keys"] = sorted(entry["contract_key"] for entry in linked)
        action["entity_ids"] = sorted(
            {eid for entry in linked for eid in entry["entity_ids"]}
        )
    report["entity_links"] = sorted(
        by_key.values(), key=lambda item: item["contract_key"]
    )
    return report
