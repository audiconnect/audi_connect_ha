"""Historical V2 inventory deduplicates aliases without deleting references."""
from custom_components.audiconnect.v3.historical_catalog import (
    INVENTORY, ATTRIBUTES, ALIAS_OF, CANONICAL_ATTRIBUTES
)

def test_raw_references_and_user_facing_logical_entities_are_distinct():
    assert len(INVENTORY["attributes"]) == len(ATTRIBUTES)
    assert len(ALIAS_OF) == 9
    assert len(CANONICAL_ATTRIBUTES) == len(ATTRIBUTES) - len(ALIAS_OF)
    assert "any_door_unlocked" in CANONICAL_ATTRIBUTES
    assert ALIAS_OF["mileage"] == "UTC_TIME_AND_KILOMETER_STATUS"
    assert ALIAS_OF["range"] == "TOTAL_RANGE"
    assert ALIAS_OF["oil_level"] == "OIL_LEVEL_DIPSTICKS_PERCENTAGE"
    assert all(alias in ATTRIBUTES and canonical in ATTRIBUTES
               for alias, canonical in ALIAS_OF.items())

def test_aliases_never_turn_into_migrated_or_verified_entities_by_counting():
    assert "mileage" not in CANONICAL_ATTRIBUTES
    assert "UTC_TIME_AND_KILOMETER_STATUS" in CANONICAL_ATTRIBUTES
    assert ATTRIBUTES["mileage"]["paths"] == []
    assert ATTRIBUTES["UTC_TIME_AND_KILOMETER_STATUS"]["paths"]
