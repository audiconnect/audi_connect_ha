"""Independent V3 polling coordinator, not a subclass of V2 coordinator."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from ..const import CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .engine import V3Engine
from .vehicle import V3Vehicle

_LOGGER = logging.getLogger(__name__)


class V3CleanCoordinator(DataUpdateCoordinator[list[V3Vehicle]]):
    def __init__(self, hass: HomeAssistant, engine: V3Engine, entry: Any):
        minutes = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_v3", config_entry=entry,
            update_interval=timedelta(minutes=max(5, int(minutes))),
        )
        self.engine = engine

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
                raise UpdateFailed("Audi cloud returned no successful status response")
            self.engine.health.poll_error = None
            return vehicles
        except ConfigEntryAuthFailed:
            self.engine.health.poll_error = "authentication_required"
            raise
        except UpdateFailed:
            self.engine.health.poll_error = "cloud_unavailable"
            raise
        except Exception as err:
            self.engine.health.poll_error = "cloud_unavailable" if isinstance(err, (OSError, TimeoutError)) else "error"
            raise UpdateFailed(str(err)) from err
