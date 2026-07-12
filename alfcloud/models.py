"""Typed models parsed from the Alf cloud API JSON."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Feature:
    """One device feature, e.g. smartplug.onOff or generic.temperature."""

    id: str
    device_feature_id: str
    value: Any
    updated_at: str | None = None
    desired: Any = None

    @classmethod
    def from_json(cls, data: dict) -> "Feature":
        current = data.get("current") or {}
        return cls(
            id=data.get("id"),
            device_feature_id=data.get("deviceFeatureId"),
            value=current.get("value"),
            updated_at=current.get("updatedAt"),
            desired=data.get("desired"),
        )


@dataclass
class Device:
    """A single Alf device with its features and metadata."""

    id: str
    name: str
    type: str
    state: str
    home_id: str
    room_id: str | None = None
    parent_id: str | None = None
    model_id: str | None = None
    model_name: str | None = None
    vendor: str | None = None
    protocol: str | None = None
    serial_number: str | None = None
    firmware_version: str | None = None
    power_source: str | None = None
    battery_percentage: float | None = None
    battery_voltage: float | None = None
    features: dict[str, Feature] = field(default_factory=dict)

    @property
    def online(self) -> bool:
        return self.state == "online"

    def value(self, feature_id: str) -> Any:
        feature = self.features.get(feature_id)
        return feature.value if feature is not None else None

    @classmethod
    def from_json(cls, data: dict) -> "Device":
        spec = data.get("specifications") or {}
        power = data.get("power") or {}
        status = power.get("status") or {}
        percentage = status.get("percentage") or {}
        voltage = status.get("voltage") or {}
        features: dict[str, Feature] = {}
        for raw in data.get("features") or []:
            feature = Feature.from_json(raw)
            if feature.id:
                features[feature.id] = feature
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            type=data.get("type"),
            state=data.get("state"),
            home_id=data.get("homeId"),
            room_id=data.get("roomId"),
            parent_id=data.get("parentId"),
            model_id=spec.get("modelId"),
            model_name=spec.get("modelName"),
            vendor=spec.get("vendor"),
            protocol=spec.get("protocol"),
            serial_number=spec.get("serialNumber"),
            firmware_version=spec.get("firmwareVersion"),
            power_source=(power.get("source") or {}).get("value"),
            battery_percentage=percentage.get("value") if isinstance(percentage, dict) else None,
            battery_voltage=voltage.get("value") if isinstance(voltage, dict) else None,
            features=features,
        )


@dataclass
class Room:
    id: str
    name: str


@dataclass
class Home:
    id: str
    name: str
    rooms: dict[str, Room] = field(default_factory=dict)

    def room_name(self, room_id: str | None) -> str | None:
        room = self.rooms.get(room_id) if room_id else None
        return room.name if room is not None else None

    @classmethod
    def from_json(cls, data: dict) -> "Home":
        rooms: dict[str, Room] = {}
        for raw in data.get("rooms") or []:
            rid = raw.get("id")
            if rid:
                rooms[rid] = Room(id=rid, name=raw.get("name"))
        return cls(id=data.get("id"), name=data.get("name"), rooms=rooms)


def parse_homes(payload: Any) -> list[Home]:
    """GET /api/v1/home returns a JSON list of homes."""
    items = payload if isinstance(payload, list) else (payload or {}).get("homes", [])
    return [Home.from_json(item) for item in items]


def parse_devices(payload: dict) -> list[Device]:
    """GET /api/v1/home/{id}/device returns {"homeId": ..., "devices": [...]}."""
    return [Device.from_json(item) for item in (payload or {}).get("devices") or []]
