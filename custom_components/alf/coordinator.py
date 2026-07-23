"""DataUpdateCoordinator that polls the Alf cloud for device states."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .alfcloud import AlfAuth, AlfClient, Device, Home
from .alfcloud.errors import AlfApiError, AlfAuthError, AlfConnectionError
from .cleanup import orphaned_device_ids
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
        except AlfConnectionError as err:
            # Transient network/DNS failure (e.g. HA started before DNS was up).
            # UpdateFailed makes HA retry with backoff - and become ConfigEntryNotReady
            # on first setup - instead of forcing a manual reload or re-auth.
            raise UpdateFailed(str(err)) from err
        except AlfAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AlfApiError as err:
            raise UpdateFailed(str(err)) from err
        self._persist_rotated_refresh_token()
        self._purge_orphaned_devices(set(devices))
        return devices

    def _purge_orphaned_devices(self, live_ids: set[str]) -> None:
        """Drop registry devices the Alf account no longer contains.

        Removing and re-adding a device in the Alf app mints a new device id, which
        would otherwise leave the old one stranded as a permanent "unavailable"
        entry. We reconcile the whole registry (not just this session's diff) so an
        already-stranded device is cleaned up on the next poll too. Dropping the
        config entry from the device makes HA delete it and its entities.
        """
        device_reg = dr.async_get(self.hass)
        entries = dr.async_entries_for_config_entry(
            device_reg, self.config_entry.entry_id
        )
        for device_id in orphaned_device_ids(entries, live_ids, DOMAIN):
            device_reg.async_update_device(
                device_id, remove_config_entry_id=self.config_entry.entry_id
            )

    def _persist_rotated_refresh_token(self) -> None:
        current = self._auth.refresh_token
        if current and current != self.config_entry.data.get(CONF_REFRESH_TOKEN):
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_REFRESH_TOKEN: current},
            )

    def home_for(self, device: Device) -> Home | None:
        return self.homes.get(device.home_id)
