"""Independent V3 polling coordinator, not a subclass of V2 coordinator."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from ..const import CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .command_readback import optimistic_expiry, projection_attributes
from .engine import V3Engine
from .vehicle import V3Vehicle

_LOGGER = logging.getLogger(__name__)


class NativeStatusUnavailable(UpdateFailed):
    """Inventory was loaded, but the native status poll did not succeed."""


class V3CleanCoordinator(DataUpdateCoordinator[list[V3Vehicle]]):
    def __init__(self, hass: HomeAssistant, engine: V3Engine, entry: Any):
        minutes = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_v3",
            config_entry=entry,
            update_interval=timedelta(minutes=max(5, int(minutes))),
        )
        self.engine = engine
        self._cancel_projection_timer = None
        if hasattr(entry, "async_on_unload"):
            entry.async_on_unload(self._cancel_projection_expiry)

    @callback
    def _cancel_projection_expiry(self):
        if self._cancel_projection_timer is not None:
            self._cancel_projection_timer()
            self._cancel_projection_timer = None

    @callback
    def _projection_expired(self, _now):
        self._cancel_projection_timer = None
        self.async_update_listeners()

    @callback
    def async_update_listeners(self):
        """One account-level local expiry; never poll or replay a mutation."""
        super().async_update_listeners()
        self._cancel_projection_expiry()
        now = datetime.now(UTC).timestamp()
        deadlines = []
        for profile in self.engine.profiles.values():
            latest = {}
            for record in profile.command_journal:
                for attribute in projection_attributes(record):
                    latest[attribute] = record
            for record in latest.values():
                expiry = optimistic_expiry(record)
                if expiry is not None and expiry > now:
                    deadlines.append(expiry)
        if deadlines:
            self._cancel_projection_timer = async_call_later(
                self.hass, min(deadlines) - now, self._projection_expired
            )

    @property
    def last_cloud_poll_attempt(self):
        return self.engine.last_cloud_poll_attempt

    @property
    def last_cloud_poll_success(self):
        return self.engine.last_cloud_poll_success

    async def _async_update_data(self) -> list[V3Vehicle]:
        try:
            vehicles = await self.engine.poll()
            if self.engine.last_cloud_poll_succeeded is False:
                raise NativeStatusUnavailable(
                    "Audi cloud returned no successful status response"
                )
            self.engine.health.poll_error = None
            return vehicles
        except ConfigEntryAuthFailed:
            self.engine.health.poll_error = "authentication_required"
            raise
        except UpdateFailed:
            self.engine.health.poll_error = "cloud_unavailable"
            raise
        except Exception as err:
            self.engine.health.poll_error = (
                "cloud_unavailable"
                if isinstance(err, (OSError, TimeoutError))
                else "error"
            )
            raise UpdateFailed(str(err)) from err
