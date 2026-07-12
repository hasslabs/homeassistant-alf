"""DataUpdateCoordinator that polls the Alf cloud for device states."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .alfcloud import AlfAuth, AlfClient, Device, Home
from .alfcloud.errors import AlfApiError, AlfAuthError
from .const import CONF_REFRESH_TOKEN, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class AlfDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Device]]):
    """Fetches all homes + devices; keeps the rotating refresh token persisted."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: AlfClient,
        auth: AlfAuth,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=DEFAULT_SCAN_INTERVAL)
        self.config_entry = entry
        self.client = client
        self._auth = auth
        self.homes: dict[str, Home] = {}

    async def _async_update_data(self) -> dict[str, Device]:
        try:
            homes = await self.client.async_get_homes()
            self.homes = {home.id: home for home in homes}
            devices: dict[str, Device] = {}
            for home in homes:
                for device in await self.client.async_get_devices(home.id):
                    devices[device.id] = device
        except AlfAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AlfApiError as err:
            raise UpdateFailed(str(err)) from err
        self._persist_rotated_refresh_token()
        return devices

    def _persist_rotated_refresh_token(self) -> None:
        current = self._auth.refresh_token
        if current and current != self.config_entry.data.get(CONF_REFRESH_TOKEN):
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_REFRESH_TOKEN: current},
            )

    def home_for(self, device: Device) -> Home | None:
        return self.homes.get(device.home_id)
