"""strings.json and translations/*.json must cover every key the integration uses.

A translation_key without a matching entry gives an unnamed entity in HA, and a
missing flow step or abort reason shows the raw key in the UI. The keys are read
from the platform modules themselves (via tests/ha_stubs.py), so adding a new
kind or diagnostic key without translating it fails here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests import ha_stubs

pytestmark = pytest.mark.skipif(
    ha_stubs.real_ha_available(), reason="real Home Assistant installed; stubs not used"
)

_ALF = Path(__file__).resolve().parent.parent / "custom_components" / "alf"
_FILES = [_ALF / "strings.json", *sorted((_ALF / "translations").glob("*.json"))]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _key_paths(node, prefix=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _key_paths(value, (*prefix, key))
    else:
        yield prefix


def _used_entity_keys() -> dict[str, set[str]]:
    binary = ha_stubs.submodule("binary_sensor")
    sensor = ha_stubs.submodule("sensor")
    switch = ha_stubs.submodule("switch")
    return {
        "binary_sensor": (
            set(binary._KIND_TO_CLASS)
            | set(binary._DIAGNOSTIC_KEYS.values())
            | {binary.AlfConnectivitySensor._attr_translation_key}
        ),
        "sensor": set(sensor._KIND_DESC) | {"battery", "battery_voltage"},
        "switch": {switch.AlfSwitch._attr_translation_key},
    }


def test_translation_files_exist():
    names = [p.name for p in _FILES]
    assert "strings.json" in names and "en.json" in names


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_every_entity_translation_key_is_named(path):
    entity = _load(path)["entity"]
    for platform, keys in _used_entity_keys().items():
        missing = {k for k in keys if not entity.get(platform, {}).get(k, {}).get("name")}
        assert not missing, f"{path.name}: {platform} lacks names for {sorted(missing)}"


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_config_and_options_flow_strings_present(path):
    data = _load(path)
    config = data["config"]
    # {qr} must survive translation or the QR code never renders.
    assert "{qr}" in config["progress"]["bankid"]
    assert config["step"]["finish"]["data"]["enable_control"]
    for reason in ("already_configured", "reauth_successful", "bankid_failed"):
        assert config["abort"][reason], reason
    assert data["options"]["step"]["init"]["data"]["enable_control"]


@pytest.mark.parametrize("path", _FILES[1:], ids=lambda p: p.name)
def test_translations_have_same_keys_as_strings_json(path):
    expected = set(_key_paths(_load(_FILES[0])))
    actual = set(_key_paths(_load(path)))
    assert expected - actual == set(), f"{path.name} is missing keys"
    assert actual - expected == set(), f"{path.name} has keys not in strings.json"
