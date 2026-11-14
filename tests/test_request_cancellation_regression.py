"""Caller cancellation must propagate, distinct from the request deadline.

Regression for upstream #880 / closed PR #885; no real Audi network calls.
"""

from __future__ import annotations

import asyncio

import pytest

from custom_components.audiconnect import audi_api
from custom_components.audiconnect.audi_api import AudiAPI


class _BlockingContext:
    def __init__(self, entered: asyncio.Event) -> None:
        self.entered = entered

    async def __aenter__(self):
        self.entered.set()
        await asyncio.Event().wait()

    async def __aexit__(self, *_args):
        return None


class _BlockingSession:
    def __init__(self, entered: asyncio.Event) -> None:
        self.entered = entered
        self.calls = 0

    def request(self, *_args, **_kwargs):
        self.calls += 1
        return _BlockingContext(self.entered)


@pytest.mark.asyncio
async def test_external_cancellation_is_not_converted_to_a_timeout():
    entered = asyncio.Event()
    session = _BlockingSession(entered)
    api = AudiAPI(session)
    pending = asyncio.create_task(
        api.request("GET", "https://example.invalid/poll", data=None)
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert session.calls == 1


@pytest.mark.asyncio
async def test_request_deadline_is_still_a_real_timeout(monkeypatch):
    monkeypatch.setattr(audi_api, "TIMEOUT", 0.01)
    entered = asyncio.Event()
    api = AudiAPI(_BlockingSession(entered))
    with pytest.raises(TimeoutError):
        await api.request("GET", "https://example.invalid/poll", data=None)
    assert entered.is_set()
