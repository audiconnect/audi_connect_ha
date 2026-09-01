"""#840: a rejected IDK refresh should only prompt a reauth when the refresh
token itself is dead (``invalid_grant``). Anything else — ``invalid_client``
(the client_id is fixed in code, so a reauth can't help), a transient blip, a
malformed body — must degrade to a retryable error instead of an un-actionable
reauth prompt.

No network: the classifier is a pure function over the parsed token response.
"""

from __future__ import annotations

import pytest

from custom_components.audiconnect.audi_services import (
    AudiAuthError,
    AudiTokenRefreshError,
    _raise_refresh_rejected,
)


def test_invalid_grant_needs_reauth() -> None:
    # The refresh token itself is rejected -> only a fresh sign-in fixes it.
    with pytest.raises(AudiAuthError):
        _raise_refresh_rejected("IDK refresh rejected", {"error": "invalid_grant"}, "")


@pytest.mark.parametrize(
    "parsed",
    [
        {"error": "invalid_client"},  # client-level: reauth reuses the same client
        {"error": "server_error"},  # transient VW-side blip
        {"error": "temporarily_unavailable"},
        {},  # malformed / no error field
    ],
)
def test_everything_else_is_retryable(parsed: dict) -> None:
    # Unknown / non-grant errors degrade to a retry, never a reauth prompt.
    with pytest.raises(AudiTokenRefreshError):
        _raise_refresh_rejected("IDK refresh rejected", parsed, "{}")


def test_retryable_is_not_an_auth_error() -> None:
    # AudiTokenRefreshError must not be an AudiAuthError subclass, or the
    # async_refresh_data handler would still escalate it to reauth.
    assert not issubclass(AudiTokenRefreshError, AudiAuthError)
