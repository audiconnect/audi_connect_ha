"""#786: a failing login retried at a fixed interval fills the log and keeps
hammering a service that is already unhappy. Back off between attempts, and keep
the attempts in between at debug so only the final failure is reported.

No network: try_login and the sleep are both replaced.
"""

from __future__ import annotations

import asyncio

from custom_components.audiconnect import audi_connect_account
from custom_components.audiconnect.audi_connect_account import (
    MAX_LOGIN_RETRY_DELAY,
    AudiConnectAccount,
)


def _account(monkeypatch) -> tuple[AudiConnectAccount, list[float]]:
    account = AudiConnectAccount(
        session=None, country="DE", spin=None, api_level=1, refresh_token="token"
    )

    slept: list[float] = []

    async def _sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(audi_connect_account.asyncio, "sleep", _sleep)
    return account, slept


def test_delay_grows_between_attempts(monkeypatch) -> None:
    account, slept = _account(monkeypatch)

    async def _always_fails(_log_error):
        return False

    account.try_login = _always_fails
    asyncio.run(account.login())

    # Three attempts, so two waits, and the second is longer than the first.
    assert slept == [10, 20]


def test_delay_is_capped(monkeypatch) -> None:
    account, slept = _account(monkeypatch)
    account._connect_retries = 8

    async def _always_fails(_log_error):
        return False

    account.try_login = _always_fails
    asyncio.run(account.login())

    assert max(slept) == MAX_LOGIN_RETRY_DELAY
    assert slept[-1] == MAX_LOGIN_RETRY_DELAY


def test_no_waiting_once_login_succeeds(monkeypatch) -> None:
    account, slept = _account(monkeypatch)

    async def _succeeds(_log_error):
        return True

    account.try_login = _succeeds
    asyncio.run(account.login())

    assert slept == []
    assert account._loggedin is True


def test_retries_stop_at_the_configured_count(monkeypatch) -> None:
    account, slept = _account(monkeypatch)
    attempts: list[bool] = []

    async def _records(log_error):
        attempts.append(log_error)
        return False

    account.try_login = _records
    asyncio.run(account.login())

    # The final attempt is the one allowed to report the error.
    assert len(attempts) == account._connect_retries
    assert attempts == [False, False, True]
