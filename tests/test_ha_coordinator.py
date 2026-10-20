"""Coordinator polling: error classification, token persistence, orphan pruning.

Loaded on top of tests/ha_stubs.py. The client is a fake returning parsed models
(or raising alfcloud errors); hass is a fake recording config-entry updates and
device-registry writes.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests import ha_stubs

pytestmark = pytest.mark.skipif(
    ha_stubs.real_ha_available(), reason="real Home Assistant installed; stubs not used"
)

if not ha_stubs.real_ha_available():
    ha_stubs.load_integration()
    coordinator_mod = ha_stubs.submodule("coordinator")
    errors = ha_stubs.submodule("alfcloud.errors")
    models = ha_stubs.submodule("alfcloud.models")


class FakeRegistry:
    def __init__(self, entries):
        self._entries = entries
        self.updates = []

    def entries_for(self, entry_id):
        return [e for e in self._entries if e.config_entry == entry_id]

    def async_update_device(self, device_id, *, remove_config_entry_id):
        self.updates.append((device_id, remove_config_entry_id))


class FakeConfigEntries:
    def __init__(self):
        self.updates = []

    def async_update_entry(self, entry, *, data):
        self.updates.append(data)
        entry.data = data


class FakeClient:
    def __init__(self, homes=(), devices=None, error=None, device_error=None):
        self._homes = list(homes)
        self._devices = devices or {}
        self._error = error
        self._device_error = device_error

    async def async_get_homes(self):
        if self._error:
            raise self._error
        return self._homes

    async def async_get_devices(self, home_id):
        if self._device_error:
            raise self._device_error
        return self._devices.get(home_id, [])


def _home(hid):
    return models.Home.from_json({"id": hid, "name": hid})


def _dev(did, home):
    return models.Device.from_json({"id": did, "name": did, "state": "online", "homeId": home})


def _reg_entry(reg_id, alf_id, config_entry="entry-1"):
    return SimpleNamespace(id=reg_id, identifiers={("alf", alf_id)}, config_entry=config_entry)


def _make(client, *, stored_rt="rt-old", current_rt="rt-old", registry=None):
    hass = SimpleNamespace(config_entries=FakeConfigEntries(),
                           device_registry=registry or FakeRegistry([]))
    entry = ha_stubs.ConfigEntry(entry_id="entry-1", data={"refresh_token": stored_rt, "x": 1})
    auth = SimpleNamespace(refresh_token=current_rt)
    return coordinator_mod.AlfDataUpdateCoordinator(hass, entry, client, auth), hass, entry


async def test_collects_devices_across_all_homes():
    client = FakeClient(
        homes=[_home("h1"), _home("h2")],
        devices={"h1": [_dev("a", "h1")], "h2": [_dev("b", "h2"), _dev("c", "h2")]},
    )
    coord, _, _ = _make(client)
    data = await coord._async_update_data()

    assert sorted(data) == ["a", "b", "c"]
    assert sorted(coord.homes) == ["h1", "h2"]
    assert coord.home_for(data["b"]).id == "h2"
    assert coord.home_for(_dev("z", "unknown-home")) is None


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        ("AlfConnectionError", ha_stubs.UpdateFailed),   # transient -> retry, not re-auth
        ("AlfAuthError", ha_stubs.ConfigEntryAuthFailed),  # refresh token dead -> reauth
        ("AlfApiError", ha_stubs.UpdateFailed),
    ],
)
@pytest.mark.parametrize("where", ["homes", "devices"])
async def test_error_classification(raised, expected, where):
    err = getattr(errors, raised)("boom")
    client = (FakeClient(error=err) if where == "homes"
              else FakeClient(homes=[_home("h")], device_error=err))
    coord, hass, _ = _make(client, current_rt="rt-new")

    with pytest.raises(expected) as info:
        await coord._async_update_data()
    assert info.value.__cause__ is err
    # A failed poll persists nothing and prunes nothing.
    assert hass.config_entries.updates == []
    assert hass.device_registry.updates == []


async def test_rotated_refresh_token_is_persisted_keeping_other_data():
    coord, hass, entry = _make(FakeClient(homes=[]), current_rt="rt-new")
    await coord._async_update_data()

    assert hass.config_entries.updates == [{"refresh_token": "rt-new", "x": 1}]
    assert entry.data["refresh_token"] == "rt-new"


@pytest.mark.parametrize("current", ["rt-old", "", None])
async def test_unchanged_or_empty_refresh_token_is_not_written(current):
    coord, hass, _ = _make(FakeClient(homes=[]), current_rt=current)
    await coord._async_update_data()
    assert hass.config_entries.updates == []


async def test_orphaned_registry_devices_are_detached_after_successful_poll():
    registry = FakeRegistry([
        _reg_entry("reg-live", "a"),
        _reg_entry("reg-stale", "old"),
        _reg_entry("reg-other-entry", "old2", config_entry="entry-2"),
    ])
    client = FakeClient(homes=[_home("h")], devices={"h": [_dev("a", "h")]})
    coord, _, _ = _make(client, registry=registry)
    await coord._async_update_data()

    assert registry.updates == [("reg-stale", "entry-1")]


async def test_empty_inventory_never_mass_removes():
    registry = FakeRegistry([_reg_entry("reg-a", "a")])
    coord, _, _ = _make(FakeClient(homes=[_home("h")]), registry=registry)
    await coord._async_update_data()
    assert registry.updates == []
