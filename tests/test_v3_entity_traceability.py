from custom_components.audiconnect.v3.entity_traceability import link_entities


def test_bidirectional_links_use_real_registry_ids_and_contract_sources():
    report = {
        "rows": [
            {
                "attribute": "chargingState",
                "capability": "charging",
                "operation": "read",
                "platform": "sensor",
                "entity_key": "charging_state",
            }
        ],
        "operations": [
            {
                "operation": "read",
                "mappings": [
                    {
                        "entity_key": "sensor.charging_state",
                        "attribute": "chargingState",
                        "capability": "charging",
                    }
                ],
            }
        ],
    }
    actual = {
        "sensor.charging_state": ["sensor.renamed"],
        "binary_sensor.charging_ready": ["binary_sensor.ready"],
    }
    inventory = {
        "sensor.charging_state": {"source_attributes": ["chargingState"]},
        "binary_sensor.charging_ready": {"source_attributes": ["chargingState"]},
    }
    link_entities(report, actual, inventory)
    assert report["operations"][0]["mappings"][0]["entity_ids"] == ["sensor.renamed"]
    assert report["rows"][0]["entity_ids"] == ["binary_sensor.ready", "sensor.renamed"]
    for entry in report["entity_links"]:
        assert entry["capabilities"] == ["charging"] and entry["operations"] == ["read"]


def test_local_and_unmapped_entities_are_not_given_fake_api_routes():
    report = {"rows": [], "operations": []}
    link_entities(
        report,
        {
            "sensor.integration_status": ["sensor.health"],
            "sensor.unknown": ["sensor.other"],
        },
        {},
    )
    assert report["entity_links"][0]["capabilities"] == ["integration_health"]
    assert report["entity_links"][0]["operations"] == []
    assert report["entity_links"][1]["capabilities"] == []


def test_missing_and_local_entity_contracts_remain_traceable_without_registry_id():
    report = {
        "rows": [
            {
                "attribute": "user.attribute.pressure",
                "capability": "local",
                "operation": "read",
                "platform": "sensor",
                "entity_key": "v3_custom_pressure",
                "custom": True,
            },
            {
                "attribute": "stateOfCharge",
                "capability": "charging",
                "operation": "soc",
                "platform": "sensor",
                "entity_key": "state_of_charge",
            },
        ],
        "operations": [
            {
                "operation": "read",
                "mappings": [
                    {
                        "entity_key": "sensor.v3_custom_pressure",
                        "attribute": "user.attribute.pressure",
                        "capability": "local",
                    }
                ],
            }
        ],
    }
    link_entities(report, {}, {"sensor.state_of_charge": {}})
    by_key = {row["contract_key"]: row for row in report["entity_links"]}
    assert by_key["sensor.v3_custom_pressure"]["operations"] == ["read"]
    assert by_key["sensor.v3_custom_pressure"]["entity_ids"] == []
    assert by_key["sensor.state_of_charge"]["capabilities"] == ["charging"]
    assert report["rows"][1]["entity_keys"] == ["sensor.state_of_charge"]
