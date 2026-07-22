"""The Alf (Länsförsäkringar) integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .alfcloud import AlfAuth, AlfClient
from .const import CLIENT_SECRET, CONF_REFRESH_TOKEN, DOMAIN, PLATFORMS
from .coordinator import AlfDataUpdateCoordinator

type AlfConfigEntry = ConfigEntry[AlfDataUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AlfConfigEntry) -> bool:
    """Set up Alf from a config entry."""
    session = async_get_clientsession(hass)
    auth = AlfAuth(entry.data[CONF_REFRESH_TOKEN], CLIENT_SECRET, session)
    coordinator = AlfDataUpdateCoordinator(hass, entry, AlfClient(auth, session), auth)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AlfConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: AlfConfigEntry) -> None:
    """Reload when options (e.g. the control toggle) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: AlfConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow deleting a device from the UI once the Alf cloud stops reporting it.

    Stale devices are pruned automatically after each poll, but this also enables the
    delete button so the user can remove one immediately (e.g. an already-stranded
    duplicate) without waiting for the next refresh. A still-live device is refused -
    it would only reappear on the next update.
    """
    return not any(
        identifier[0] == DOMAIN and identifier[1] in entry.runtime_data.data
        for identifier in device_entry.identifiers
    )
