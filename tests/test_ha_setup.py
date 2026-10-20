"""Config-entry lifecycle (__init__.py) and the coordinator driven through the real client.

Loaded on top of tests/ha_stubs.py. The integration's own AlfAuth/AlfClient run
unmodified against the queued FakeSession from conftest (no network), so these
tests check the wiring between entry data, token refresh, the HTTP client and
the coordinator's error classification - the path every poll takes in HA.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests import ha_stubs

pytestmark = pytest.mark.skipif(
    ha_stubs.real_ha_available(), reason="real Home Assistant installed; stubs not used"
)

if not ha_stubs.real_ha_available():
    integration = ha_stubs.load_integration()
    const = ha_stubs.submodule("const")
    coordinator_mod = ha_stubs.submodule("coordinator")
    alfcloud = ha_stubs.submodule("alfcloud")

HOMES_URL = "https://lfhub.net/api/v1/home"
DEVICES_URL = "https://lfhub.net/api/v1/home/h1/device"


class FakeConfigEntries:
    """Records the hass.config_entries calls made by the integration."""

    def __init__(self, *, unload_result=True):
        self.calls: list[tuple] = []
        self._unload_result = unload_result

    async def async_forward_entry_setups(self, entry, platforms):
        # Snapshot what the platforms would see when they are set up.
        self.calls.append(("forward", list(platforms), entry.runtime_data))

    async def async_unload_platforms(self, entry, platforms):
        self.calls.append(("unload", list(platforms)))
        return self._unload_result

    async def async_reload(self, entry_id):
        self.calls.append(("reload", entry_id))

    def async_update_entry(self, entry, *, data):
        self.calls.append(("update_entry", dict(data)))
        entry.data = data


class EmptyRegistry:
    def entries_for(self, entry_id):
        return []


def _hass(session, **kw):
    return SimpleNamespace(
        client_session=session,
        config_entries=FakeConfigEntries(**kw),
        device_registry=EmptyRegistry(),
    )


def _entry(rt="rt-stored"):
    return ha_stubs.ConfigEntry(entry_id="entry-1", data={"refresh_token": rt})


def _token(fake, jwt, *, status=200, rt="rt-rotated"):
    return fake.Response(status=status, payload={"access_token": jwt, "refresh_token": rt})


def _homes(fake):
    return fake.Response(payload=[{"id": "h1", "name": "Hemma"}])


def _devices(fake):
    return fake.Response(payload={"homeId": "h1", "devices": [
        {"id": "d1", "name": "Plug", "state": "online", "homeId": "h1"},
    ]})


# --- async_setup_entry / unload / reload ------------------------------------------------

async def test_setup_entry_refreshes_with_stored_token_then_forwards_platforms(fake, make_jwt):
    session = fake.Session([_token(fake, make_jwt()), _homes(fake), _devices(fake)])
    hass, entry = _hass(session), _entry()

    assert await integration.async_setup_entry(hass, entry) is True

    token_call = session.calls[0]
    assert token_call["method"] == "POST"
    assert token_call["data"]["grant_type"] == "refresh_token"
    assert token_call["data"]["refresh_token"] == "rt-stored"
    assert token_call["data"]["client_secret"] == const.CLIENT_SECRET
    # The API calls carry the freshly minted access token.
    assert [c["url"] for c in session.calls[1:]] == [HOMES_URL, DEVICES_URL]
    assert session.calls[1]["headers"]["Authorization"].startswith("Bearer ")

    coordinator = entry.runtime_data
    assert isinstance(coordinator, coordinator_mod.AlfDataUpdateCoordinator)
    assert list(coordinator.data) == ["d1"]
    # Platforms are forwarded only after the first refresh produced data.
    forward = [c for c in hass.config_entries.calls if c[0] == "forward"]
    assert forward == [("forward", list(const.PLATFORMS), coordinator)]
    # The rotated refresh token from the first refresh is persisted right away.
    assert ("update_entry", {"refresh_token": "rt-rotated"}) in hass.config_entries.calls
    # An options-update listener is registered and removed again on unload.
    assert entry.update_listeners == [integration._async_reload]
    assert entry.on_unload == [("remove-listener", integration._async_reload)]


async def test_setup_entry_not_ready_when_cloud_unreachable(fake):
    hass, entry = _hass(fake.Session([fake.Boom()])), _entry()

    with pytest.raises(ha_stubs.ConfigEntryNotReady):
        await integration.async_setup_entry(hass, entry)
    assert entry.runtime_data is None
    assert hass.config_entries.calls == []
    assert entry.update_listeners == []


async def test_setup_entry_requests_reauth_when_refresh_token_rejected(fake):
    hass, entry = _hass(fake.Session([fake.Response(status=400)])), _entry()

    with pytest.raises(ha_stubs.ConfigEntryAuthFailed):
        await integration.async_setup_entry(hass, entry)
    assert hass.config_entries.calls == []


@pytest.mark.parametrize("result", [True, False])
async def test_unload_entry_unloads_all_platforms_and_returns_result(result):
    hass, entry = _hass(None, unload_result=result), _entry()

    assert await integration.async_unload_entry(hass, entry) is result
    assert hass.config_entries.calls == [("unload", list(const.PLATFORMS))]


async def test_options_change_reloads_the_entry():
    hass, entry = _hass(None), _entry()
    await integration._async_reload(hass, entry)
    assert hass.config_entries.calls == [("reload", "entry-1")]


# --- coordinator through the real AlfClient --------------------------------------------

def _coordinator(session):
    hass, entry = _hass(session), _entry()
    auth = alfcloud.AlfAuth("rt-stored", "secret", session)
    client = alfcloud.AlfClient(auth, session)
    return coordinator_mod.AlfDataUpdateCoordinator(hass, entry, client, auth), hass


async def test_single_401_refreshes_token_and_retries(fake, make_jwt):
    session = fake.Session([
        _token(fake, make_jwt(), rt="rt-1"),
        fake.Response(status=401),                 # access token revoked server-side
        _token(fake, make_jwt(), rt="rt-2"),       # forced refresh
        _homes(fake),
        _devices(fake),
    ])
    coord, hass = _coordinator(session)

    data = await coord._async_update_data()
    assert list(data) == ["d1"]
    # Only the newest rotated token is persisted.
    assert hass.config_entries.calls == [("update_entry", {"refresh_token": "rt-2"})]


async def test_second_401_after_forced_refresh_is_update_failed_not_reauth(fake, make_jwt):
    # A 401 that survives a successful token refresh is an API problem, not a dead
    # refresh token, so HA must retry (UpdateFailed) instead of asking for BankID again.
    session = fake.Session([
        _token(fake, make_jwt()),
        fake.Response(status=401),
        _token(fake, make_jwt()),
        fake.Response(status=401),
    ])
    coord, hass = _coordinator(session)

    with pytest.raises(ha_stubs.UpdateFailed) as info:
        await coord._async_update_data()
    assert "HTTP 401" in str(info.value)
    assert hass.config_entries.calls == []


async def test_server_error_on_devices_is_update_failed(fake, make_jwt):
    session = fake.Session([_token(fake, make_jwt()), _homes(fake), fake.Response(status=503)])
    coord, _ = _coordinator(session)

    with pytest.raises(ha_stubs.UpdateFailed, match="HTTP 503"):
        await coord._async_update_data()


async def test_refresh_rejected_during_retry_is_reauth(fake, make_jwt):
    session = fake.Session([
        _token(fake, make_jwt()),
        fake.Response(status=401),
        fake.Response(status=401),   # the refresh token itself is now rejected
    ])
    coord, _ = _coordinator(session)

    with pytest.raises(ha_stubs.ConfigEntryAuthFailed):
        await coord._async_update_data()
