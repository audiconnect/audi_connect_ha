from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .audi_account import AudiAccount
from .const import CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class AudiDataUpdateCoordinator(DataUpdateCoordinator[list[Any]]):
    """Coordinator for audi cloud polling."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        account: AudiAccount,
        config_entry: ConfigEntry,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(minutes=scan_interval),
        )
        self.account = account
        # A successful cloud poll is NOT a guarantee of new car telemetry.
        self.last_cloud_poll_attempt: datetime | None = None
        self.last_cloud_poll_success: datetime | None = None

    async def _async_update_data(self) -> list[Any]:
        self.last_cloud_poll_attempt = datetime.now(UTC)
        try:
            result = await self.account.async_refresh_data()
            self.last_cloud_poll_success = datetime.now(UTC)
            return result
        except (ConfigEntryAuthFailed, ConfigEntryNotReady):
            # Let Home Assistant handle reauth / retry-setup instead of masking
            # these as a generic update failure.
            raise
        except Exception as err:
            raise UpdateFailed(str(err)) from err

    @classmethod
    def from_entry(
        cls,
        hass: HomeAssistant,
        account: AudiAccount,
        config_entry: ConfigEntry,
    ) -> AudiDataUpdateCoordinator:
        scan_interval = config_entry.options.get(
            CONF_SCAN_INTERVAL,
            config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
        return cls(hass, account, config_entry, scan_interval)


__all__ = ["AudiDataUpdateCoordinator"]
