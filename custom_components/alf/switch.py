"""Alf switches: smart plug on/off. Only created when control is enabled."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AlfConfigEntry
from .const import OPT_ENABLE_CONTROL
from .coordinator import AlfDataUpdateCoordinator
from .entity import AlfEntity

_ONOFF_FEATURE = "smartplug.onOff"


async def async_setup_entry(
    hass: HomeAssistant, entry: AlfConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if not entry.options.get(OPT_ENABLE_CONTROL, False):
        return
    coordinator = entry.runtime_data
    async_add_entities(
        AlfSwitch(coordinator, device.id)
        for device in coordinator.data.values()
        if _ONOFF_FEATURE in device.features
    )


class AlfSwitch(AlfEntity, SwitchEntity):
    _attr_device_class = SwitchDeviceClass.OUTLET
    _attr_translation_key = "outlet"

    def __init__(self, coordinator: AlfDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}:{_ONOFF_FEATURE}"

    @property
    def is_on(self) -> bool | None:
        device = self.device
        return bool(device.value(_ONOFF_FEATURE)) if device else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        device = self.device
        feature = device.features.get(_ONOFF_FEATURE) if device else None
        if device is None or feature is None:
            return
        await self.coordinator.client.async_set_feature(
            device.home_id, feature.device_feature_id, value
        )
        await self.coordinator.async_request_refresh()
