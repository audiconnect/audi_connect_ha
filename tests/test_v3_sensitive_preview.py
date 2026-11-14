"""Never leak security-sensitive access data through V3 preview."""

from custom_components.audiconnect.v3.response_preview import safe_response_preview


def test_redact_spin_even_in_admin_only_preview():
    assert safe_response_preview(
        {"spin": "1234", "S-PIN": "5678", "state": "locked"}
    ) == {"spin": "[redacted]", "S-PIN": "[redacted]", "state": "locked"}
