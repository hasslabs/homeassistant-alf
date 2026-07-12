"""Alf sensors: temperature, humidity, power, energy, illuminance, battery.

Numeric/text features that don't map to a known kind are still exposed as
diagnostic sensors, so device types this author doesn't own (extra frient/other
sensors on someone else's account) surface automatically instead of being dropped.
"""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AlfConfigEntry
from .alfcloud.features import classify_feature
from .coordinator import AlfDataUpdateCoordinator
from .entity import AlfEntity, humanize_feature

# kind -> (device_class, unit, state_class)
_KIND_DESC = {
    "temperature": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS,
                    SensorStateClass.MEASUREMENT),
    "humidity": (SensorDeviceClass.HUMIDITY, PERCENTAGE, SensorStateClass.MEASUREMENT),
    "power": (SensorDeviceClass.POWER, UnitOfPower.WATT, SensorStateClass.MEASUREMENT),
    "energy": (SensorDeviceClass.ENERGY, UnitOfEnergy.WATT_HOUR,
               SensorStateClass.TOTAL_INCREASING),
    "illuminance": (SensorDeviceClass.ILLUMINANCE, LIGHT_LUX, SensorStateClass.MEASUREMENT),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: AlfConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for device in coordinator.data.values():
        if device.battery_percentage is not None:
            entities.append(AlfBatterySensor(coordinator, device.id, voltage=False))
        elif device.battery_voltage is not None:
            entities.append(AlfBatterySensor(coordinator, device.id, voltage=True))
        for feature_id, feature in device.features.items():
            value = feature.value
            if isinstance(value, bool) or value is None:
                continue  # bools -> binary_sensor; None -> nothing to show
            desc = _KIND_DESC.get(classify_feature(feature_id))
            if desc is not None and isinstance(value, (int, float)):
                entities.append(AlfSensor(coordinator, device.id, feature_id, *desc))
            elif isinstance(value, (int, float, str)):
                entities.append(AlfDiagnosticSensor(coordinator, device.id, feature_id))
    async_add_entities(entities)


class AlfSensor(AlfEntity, SensorEntity):
    def __init__(
        self,
        coordinator: AlfDataUpdateCoordinator,
        device_id: str,
        feature_id: str,
        device_class: SensorDeviceClass,
        unit: str,
        state_class: SensorStateClass,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._feature_id = feature_id
        self._attr_unique_id = f"{device_id}:{feature_id}"
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_translation_key = classify_feature(feature_id)

    @property
    def native_value(self):
        device = self.device
        return device.value(self._feature_id) if device else None


class AlfDiagnosticSensor(AlfEntity, SensorEntity):
    """A numeric/text feature with no known mapping - surfaced as diagnostic."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: AlfDataUpdateCoordinator, device_id: str, feature_id: str
    ) -> None:
        super().__init__(coordinator, device_id)
        self._feature_id = feature_id
        self._attr_unique_id = f"{device_id}:{feature_id}"
        self._attr_name = humanize_feature(feature_id)

    @property
    def native_value(self):
        device = self.device
        return device.value(self._feature_id) if device else None


class AlfBatterySensor(AlfEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: AlfDataUpdateCoordinator, device_id: str, *, voltage: bool
    ) -> None:
        super().__init__(coordinator, device_id)
        self._voltage = voltage
        self._attr_unique_id = f"{device_id}:battery"
        if voltage:
            self._attr_device_class = SensorDeviceClass.VOLTAGE
            self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
            self._attr_translation_key = "battery_voltage"
        else:
            self._attr_device_class = SensorDeviceClass.BATTERY
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_translation_key = "battery"

    @property
    def native_value(self):
        device = self.device
        if device is None:
            return None
        return device.battery_voltage if self._voltage else device.battery_percentage
