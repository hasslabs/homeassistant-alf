"""Config/options flow: BankID progress loop, failure paths, entry creation, reauth.

Loaded on top of tests/ha_stubs.py; AlfBankIDLogin is replaced by a scripted fake
so the flow's own state machine is what is exercised.
"""
from __future__ import annotations

import asyncio

import pytest

from tests import ha_stubs

pytestmark = pytest.mark.skipif(
    ha_stubs.real_ha_available(), reason="real Home Assistant installed; stubs not used"
)

if not ha_stubs.real_ha_available():
    ha_stubs.load_integration()
    config_flow = ha_stubs.submodule("config_flow")


class FakeLogin:
    """Each poll pops the next status; start can be made to raise."""

    instances: list[FakeLogin] = []

    def __init__(self, *, polls=(), start_error=None, refresh_token="rt", unique_id="home-1"):
        self._polls = list(polls)
        self._start_error = start_error
        self._rt = refresh_token
        self._uid = unique_id
        self.status = "init"
        self.refresh_token = None
        self.unique_id = None
        self.qr_data_uri = "data:image/png;base64,QQ=="
        self.closed = 0

    async def async_start(self):
        if self._start_error:
            raise self._start_error
        self.status = "pending"

    async def async_poll(self):
        self.status = self._polls.pop(0) if self._polls else "pending"
        if self.status == "done":
            self.refresh_token, self.unique_id = self._rt, self._uid

    async def async_close(self):
        self.closed += 1


class FakeHass:
    def async_create_task(self, coro):
        return asyncio.ensure_future(coro)


def _flow(monkeypatch, **login_kwargs):
    created = []

    def factory():
        login = FakeLogin(**login_kwargs)
        created.append(login)
        return login

    monkeypatch.setattr(config_flow, "AlfBankIDLogin", factory)
    flow = config_flow.AlfConfigFlow()
    flow.hass = FakeHass()
    return flow, created


async def _step(flow):
    """Advance one bankid step after the pending login task has finished.

    Waits on the task itself (rather than a single event-loop tick) so the tests
    stay deterministic even if the fake login's coroutines start awaiting.
    """
    if flow._task is not None:
        await asyncio.wait({flow._task})
    return await flow.async_step_bankid()


async def test_first_step_starts_login_and_shows_qr(monkeypatch):
    flow, created = _flow(monkeypatch)
    result = await flow.async_step_user()

    assert result["type"] == "progress"
    assert result["step_id"] == "bankid"
    assert result["description_placeholders"] == {"qr": "data:image/png;base64,QQ=="}
    assert len(created) == 1


async def test_unfinished_task_keeps_showing_progress_without_new_poll(monkeypatch):
    flow, _ = _flow(monkeypatch)
    await flow.async_step_user()
    blocker = asyncio.get_running_loop().create_future()
    flow._task = blocker  # still running
    result = await flow.async_step_bankid()

    assert result["type"] == "progress"
    assert flow._polls == 0
    blocker.cancel()


async def test_successful_login_then_finish_form_and_entry(monkeypatch):
    flow, created = _flow(monkeypatch, polls=["pending", "done"])
    await flow.async_step_user()
    assert (await _step(flow))["type"] == "progress"   # start done -> poll 1
    assert (await _step(flow))["type"] == "progress"   # pending -> poll 2
    done = await _step(flow)                            # done

    assert done == {"type": "progress_done", "step_id": "finish"}
    assert created[0].closed == 1
    assert flow._login is None

    form = await flow.async_step_finish()
    assert form["type"] == "form"
    assert form["step_id"] == "finish"

    entry = await flow.async_step_finish({"enable_control": True})
    assert entry["type"] == "create_entry"
    assert entry["data"] == {"refresh_token": "rt"}
    assert entry["options"] == {"enable_control": True}
    assert flow.unique_id == "home-1"


async def test_missing_home_id_falls_back_to_domain_unique_id(monkeypatch):
    flow, _ = _flow(monkeypatch, polls=["done"], unique_id=None)
    await flow.async_step_user()
    await _step(flow)
    await _step(flow)

    entry = await flow.async_step_finish({})
    assert flow.unique_id == "alf"
    assert entry["options"] == {"enable_control": False}


async def test_already_configured_account_aborts(monkeypatch):
    flow, _ = _flow(monkeypatch, polls=["done"])
    flow._configured_unique_ids = {"home-1"}
    await flow.async_step_user()
    await _step(flow)
    await _step(flow)

    with pytest.raises(ha_stubs.AbortFlow) as info:
        await flow.async_step_finish({})
    assert info.value.reason == "already_configured"


async def test_failed_login_aborts_with_reason(monkeypatch):
    flow, created = _flow(monkeypatch, polls=["failed"])
    await flow.async_step_user()
    await _step(flow)
    result = await _step(flow)

    assert result == {"type": "progress_done", "step_id": "failed"}
    assert created[0].closed == 1
    assert await flow.async_step_failed() == {"type": "abort", "reason": "bankid_failed"}


async def test_start_exception_fails_flow(monkeypatch):
    flow, created = _flow(monkeypatch, start_error=RuntimeError("bankidref not found"))
    await flow.async_step_user()
    result = await _step(flow)

    assert result["step_id"] == "failed"
    assert created[0].closed == 1
    assert flow._login is None and flow._task is None


async def test_never_scanned_flow_stops_after_max_polls(monkeypatch):
    monkeypatch.setattr(config_flow, "_MAX_POLLS", 3)
    flow, _ = _flow(monkeypatch)  # polls forever "pending"
    await flow.async_step_user()
    results = [await _step(flow) for _ in range(4)]

    assert [r["type"] for r in results] == ["progress"] * 3 + ["progress_done"]
    assert results[-1]["step_id"] == "failed"


async def test_reauth_updates_existing_entry_token(monkeypatch):
    flow, _ = _flow(monkeypatch, polls=["done"], refresh_token="rt-fresh")
    existing = ha_stubs.ConfigEntry(data={"refresh_token": "rt-dead"})
    flow.source = "reauth"
    flow.reauth_entry = existing
    await flow.async_step_reauth({"refresh_token": "rt-dead"})
    await _step(flow)
    await _step(flow)

    result = await flow.async_step_finish()
    assert result["reason"] == "reauth_successful"
    assert result["entry"] is existing
    assert result["data_updates"] == {"refresh_token": "rt-fresh"}


async def test_options_flow_defaults_to_current_value_and_saves_input():
    opts = config_flow.AlfConfigFlow.async_get_options_flow(None)
    opts.config_entry = ha_stubs.ConfigEntry(options={"enable_control": True})

    form = await opts.async_step_init()
    assert form["type"] == "form"
    (marker,) = form["data_schema"].schema
    assert marker.default is True

    saved = await opts.async_step_init({"enable_control": False})
    assert saved == {"type": "create_entry", "title": "", "data": {"enable_control": False}}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG: config_flow.py has no async_remove override, so a flow the user abandons "
        "mid-QR never calls AlfBankIDLogin.async_close() and its own aiohttp session leaks"
    ),
)
async def test_abandoned_flow_closes_login_session(monkeypatch):
    # HA calls FlowHandler.async_remove() when the user closes the dialog. The login was
    # started in async_step_user and owns a private aiohttp.ClientSession (bankid.py),
    # which only _fail() and the success path ever close.
    flow, created = _flow(monkeypatch)
    await flow.async_step_user()
    await asyncio.wait({flow._task})

    flow.async_remove()
    for _ in range(3):  # allow a scheduled close task to run
        await asyncio.sleep(0)

    assert created[0].closed == 1
