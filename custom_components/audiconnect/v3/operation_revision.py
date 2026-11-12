"""Stable operation revision for evidence invalidation."""
from hashlib import sha256
import json


def operation_revision(operation: dict) -> str:
    return sha256(json.dumps(operation, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
