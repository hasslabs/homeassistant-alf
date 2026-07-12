"""Base entity for Alf devices."""
from __future__ import annotations

import re

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .alfcloud import Device
from .const import DOMAIN
from .coordinator import AlfDataUpdateCoordinator


def humanize_feature(feature_id: str) -> str:
    """'leakbot.highFlow' -> 'High flow' (fallback name for unmapped features)."""
    suffix = feature_id.rsplit(".", 1)[-1]
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", suffix)
    return spaced[:1].upper() + spaced[1:].lower()


class AlfEntity(CoordinatorEntity[AlfDataUpdateCoordinator]):
    """An entity backed by one Alf device in the coordinator data."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AlfDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id

    @property
    def device(self) -> Device | None:
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        device = self.device
        return super().available and device is not None and device.online

    @property
    def device_info(self) -> DeviceInfo:
        device = self.device
        info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=device.name if device else self._device_id,
            manufacturer=device.vendor if device else None,
            model=device.model_name if device else None,
            serial_number=device.serial_number if device else None,
            sw_version=device.firmware_version if device else None,
        )
        if device and device.parent_id:
            info["via_device"] = (DOMAIN, device.parent_id)
        home = self.coordinator.home_for(device) if device else None
        if home is not None and device is not None:
            room = home.room_name(device.room_id)
            if room:
                info["suggested_area"] = room
        return info
