from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .audi_account import AudiAccount
from .const import CONF_SCAN_ACTIVE, CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class AudiDataUpdateCoordinator(DataUpdateCoordinator[list[Any]]):
    """Coordinator for audi cloud polling."""

    def __init__(self, hass: HomeAssistant, account: AudiAccount, scan_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval),
        )
        self.account = account

    async def _async_update_data(self) -> list[Any]:
        try:
            return await self.account.async_refresh_data()
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err

    @classmethod
    def from_entry(cls, hass: HomeAssistant, account: AudiAccount, config_entry: Any) -> "AudiDataUpdateCoordinator":
        scan_active = config_entry.options.get(CONF_SCAN_ACTIVE, True)
        scan_interval = config_entry.options.get(
            CONF_SCAN_INTERVAL,
            config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
        coordinator = cls(hass, account, scan_interval)
        if not scan_active:
            coordinator.update_interval = None
        return coordinator


__all__ = ["AudiDataUpdateCoordinator"]
