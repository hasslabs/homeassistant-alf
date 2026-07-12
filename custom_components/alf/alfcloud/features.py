"""Classify an Alf feature id into a semantic kind.

Pure and HA-independent so it can be unit-tested. Classification uses the
feature *suffix* (the part after the last dot) so a device namespace like
``leakbot`` does not accidentally match the ``leak`` needle for every feature.
The Home Assistant layer maps each kind to a concrete device_class / entity.
"""
from __future__ import annotations

# (kind, substrings that identify it) - checked in order, most specific first.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("smoke", ("fire", "smoke")),
    ("moisture", ("leak", "flood", "moist", "water", "wet")),
    ("motion", ("motion", "pir", "occup")),
    ("opening", ("contact", "magnet", "door", "window", "opening")),
    ("tamper", ("tamper",)),
    ("problem", ("problem", "fault", "malfunction", "error", "defect")),
    ("temperature", ("temperature", "temp")),
    ("humidity", ("humidity",)),
    ("illuminance", ("illum", "lux")),
    ("energy", ("summationdelivered", "energy", "consumption")),
    ("power", ("demand", "power", "watt")),
    ("battery", ("battery",)),
    ("onoff", ("onoff", "on_off")),
)

BINARY_KINDS = frozenset({"smoke", "moisture", "motion", "opening", "tamper", "problem"})
SENSOR_KINDS = frozenset({"temperature", "humidity", "illuminance", "energy", "power", "battery"})
SWITCH_KINDS = frozenset({"onoff"})


def classify_feature(feature_id: str) -> str:
    """Return the semantic kind of a feature id, or 'unknown'.

    Only the suffix after the last dot is inspected, e.g. ``leakbot.highFlow``
    is classified on ``highFlow`` (not on the ``leakbot`` prefix).
    """
    suffix = feature_id.rsplit(".", 1)[-1].lower()
    for kind, needles in _RULES:
        if any(needle in suffix for needle in needles):
            return kind
    return "unknown"
