"""Alf binary sensors: smoke, leak, motion, opening, tamper, problem, connectivity.

Boolean features that don't map to a known device_class are still surfaced as
diagnostic binary sensors (nothing is silently dropped). Well-known ones (e.g.
LeakBot's highFlow/hotPipe/onPipe) get clear translated names.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AlfConfigEntry
from .alfcloud.features import classify_feature
from .coordinator import AlfDataUpdateCoordinator
from .entity import AlfEntity, humanize_feature

_KIND_TO_CLASS = {
    "smoke": BinarySensorDeviceClass.SMOKE,
    "moisture": BinarySensorDeviceClass.MOISTURE,
    "motion": BinarySensorDeviceClass.MOTION,
    "opening": BinarySensorDeviceClass.OPENING,
    "tamper": BinarySensorDeviceClass.TAMPER,
    "problem": BinarySensorDeviceClass.PROBLEM,
}

# Clear, translatable names for well-known diagnostic booleans (keyed by lowercased id).
_DIAGNOSTIC_KEYS = {
    "leakbot.highflow": "high_flow",
    "leakbot.hotpipe": "hot_pipe",
    "leakbot.onpipe": "on_pipe",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: AlfConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for device in coordinator.data.values():
        entities.append(AlfConnectivitySensor(coordinator, device.id))
        for feature_id, feature in device.features.items():
            if not isinstance(feature.value, bool):
                continue
            device_class = _KIND_TO_CLASS.get(classify_feature(feature_id))
            entities.append(AlfBinarySensor(coordinator, device.id, feature_id, device_class))
    async_add_entities(entities)


class AlfBinarySensor(AlfEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator: AlfDataUpdateCoordinator,
        device_id: str,
        feature_id: str,
        device_class: BinarySensorDeviceClass | None,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._feature_id = feature_id
        self._attr_unique_id = f"{device_id}:{feature_id}"
        if device_class is not None:
            self._attr_device_class = device_class
            self._attr_translation_key = classify_feature(feature_id)
        else:
            # Unknown boolean -> diagnostic. Known ones get a translated name.
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            key = _DIAGNOSTIC_KEYS.get(feature_id.lower())
            if key:
                self._attr_translation_key = key
                # These are fault-style flags: "on" = something to look at, "off" = OK.
                # PROBLEM makes HA render them as OK / Problem instead of Off / On, so a
                # healthy LeakBot reads "OK" rather than a confusing bare "off".
                self._attr_device_class = BinarySensorDeviceClass.PROBLEM
            else:
                self._attr_name = humanize_feature(feature_id)

    @property
    def is_on(self) -> bool | None:
        device = self.device
        return bool(device.value(self._feature_id)) if device else None


class AlfConnectivitySensor(AlfEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "connectivity"

    def __init__(self, coordinator: AlfDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}:connectivity"

    @property
    def available(self) -> bool:
        # Must stay available even when the device is offline, to report it.
        return self.coordinator.last_update_success and self.device is not None

    @property
    def is_on(self) -> bool | None:
        device = self.device
        return device.online if device else None
