"""BankID login state machine (custom_components/alf/bankid.py) - HA-free, no network.

bankid.py only needs aiohttp plus CLIENT_SECRET from the integration's const.py, and
const.py imports Home Assistant. So the module is loaded by file path inside a
synthetic package whose `const` is a stub - the same "load by path" approach as
test_cleanup.py. Every HTTP call goes to a scripted fake session.
"""
from __future__ import annotations

import base64
import importlib.util
import sys
import types
from pathlib import Path

import aiohttp
import pytest

_PKG = "alf_bankid_under_test"
_BANKID = Path(__file__).resolve().parent.parent / "custom_components" / "alf" / "bankid.py"

_pkg = types.ModuleType(_PKG)
_pkg.__path__ = []  # mark as a package so `from .const import ...` resolves
_const = types.ModuleType(f"{_PKG}.const")
_const.CLIENT_SECRET = "test-client-secret"
sys.modules.setdefault(_PKG, _pkg)
sys.modules.setdefault(f"{_PKG}.const", _const)
_spec = importlib.util.spec_from_file_location(f"{_PKG}.bankid", _BANKID)
bankid = importlib.util.module_from_spec(_spec)
sys.modules[f"{_PKG}.bankid"] = bankid
_spec.loader.exec_module(bankid)

REF = "0123abcd-4567-89ef-0123-456789abcdef"  # 36 chars, matches _REF_RE
AUTH = bankid.AUTH_BASE


class Resp:
    """aiohttp-response stand-in usable as an async context manager."""

    def __init__(self, *, status=200, json=None, text="", body=b"", url="", headers=None,
                 raise_on_json=None):
        self.status = status
        self._json = json
        self._text = text
        self._body = body
        self.url = url
        self.headers = headers or {}
        self._raise_on_json = raise_on_json

    async def json(self):
        if self._raise_on_json is not None:
            raise self._raise_on_json
        return self._json

    async def text(self):
        return self._text

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class Session:
    """Routes each request to the next scripted response for its URL path."""

    def __init__(self, routes: dict[str, list]):
        self._routes = {k: list(v) for k, v in routes.items()}
        self.calls: list[dict] = []
        self.closed = False

    def _take(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        for suffix, queue in self._routes.items():
            if url.split("?", 1)[0].endswith(suffix):
                item = queue.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
        raise AssertionError(f"unexpected request {method} {url}")

    def get(self, url, **kwargs):
        return self._take("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._take("POST", url, **kwargs)

    async def close(self):
        self.closed = True


def _start_page(ref=REF):
    return Resp(
        text=f'<html><a href="bankid://?bankidref={ref}">open</a></html>',
        url=f"{AUTH}/login?state=st-1&clientId=android&bank_app_redirect_uri=alfapp%3A%2F%2Fauth",
    )


def _qr(png=b"PNG1"):
    return Resp(body=png)


async def _login(routes):
    login = bankid.AlfBankIDLogin()
    await login._session.close()  # drop the real (never used) session
    login._session = Session(routes)
    return login


async def test_start_extracts_order_context_and_first_qr():
    login = await _login({"/openid-connect/auth": [_start_page()], "/qrcode": [_qr(b"QR")]})
    await login.async_start()

    assert login.status == "pending"
    assert login._ctx == {
        "bankidref": REF, "state": "st-1", "clientId": "android", "bru": "alfapp://auth",
    }
    assert login.qr_png == b"QR"
    assert login.qr_data_uri == "data:image/png;base64," + base64.b64encode(b"QR").decode()
    auth_call = login._session.calls[0]
    assert auth_call["params"]["kc_idp_hint"] == "bankid"
    assert auth_call["params"]["redirect_uri"] == "alfapp://auth"


async def test_start_defaults_context_when_final_url_has_no_query():
    page = Resp(text=f"bankidref={REF}", url=f"{AUTH}/login")
    login = await _login({"/openid-connect/auth": [page], "/qrcode": [_qr()]})
    await login.async_start()

    assert login._ctx["state"] == ""
    assert login._ctx["clientId"] == "android"
    assert login._ctx["bru"] == "alfapp://auth"


async def test_start_without_bankidref_raises():
    page = Resp(text="<html>Something went wrong</html>", url=f"{AUTH}/login")
    login = await _login({"/openid-connect/auth": [page]})

    with pytest.raises(bankid.AlfBankIDError):
        await login.async_start()
    assert login.status == "init"


async def test_qr_data_uri_empty_before_any_frame():
    login = await _login({})
    assert login.qr_data_uri == ""


async def test_non_200_qr_keeps_previous_frame():
    login = await _login({
        "/openid-connect/auth": [_start_page()],
        "/qrcode": [_qr(b"OLD"), Resp(status=404, body=b"NOPE")],
        "/collect": [Resp(json={"status": "pending", "hintCode": "outstandingTransaction"})],
    })
    await login.async_start()
    await login.async_poll()

    assert login.qr_png == b"OLD"
    assert login.status == "pending"
    assert login.hint == "outstandingTransaction"


async def test_failed_with_other_hint_marks_failed():
    login = await _login({
        "/openid-connect/auth": [_start_page()],
        "/qrcode": [_qr(), _qr()],
        "/collect": [Resp(json={"status": "failed", "hintCode": "userCancel"})],
    })
    await login.async_start()
    await login.async_poll()

    assert login.status == "failed"
    assert login.hint == "userCancel"


async def test_expired_unscanned_order_is_renewed():
    new_ref = "ffffffff-0000-1111-2222-333333333333"
    login = await _login({
        "/openid-connect/auth": [_start_page(), _start_page(new_ref)],
        "/qrcode": [_qr(b"A"), _qr(b"B"), _qr(b"C")],
        "/collect": [Resp(json={"status": "failed", "hintCode": "startFailed"})],
    })
    await login.async_start()
    await login.async_poll()

    assert login.status == "pending"
    assert login.hint is None  # reset by the restart
    assert login._ctx["bankidref"] == new_ref
    assert login.qr_png == b"C"


def _complete_routes(*, done, token, homes):
    return {
        "/openid-connect/auth": [_start_page()],
        "/qrcode": [_qr(), _qr()],
        "/collect": [Resp(json={"status": "complete"})],
        "/endpoint/done": done,
        "/openid-connect/token": [token],
        "/api/v1/home": [homes],
    }


async def test_complete_follows_redirects_exchanges_code_and_reads_home_id():
    routes = _complete_routes(
        done=[Resp(status=302, headers={"Location": "/realms/x/step2?a=1"})],
        token=Resp(json={"access_token": "at", "refresh_token": "rt"}),
        homes=Resp(json=[{"id": "home-1"}, {"id": "home-2"}]),
    )
    # The relative hop lands on .../step2, which then redirects into the app scheme.
    routes["/realms/x/step2"] = [Resp(status=302, headers={"Location": "alfapp://auth?code=C0DE"})]
    login = await _login(routes)
    await login.async_start()
    await login.async_poll()

    assert login.status == "done"
    assert login.refresh_token == "rt"
    assert login.unique_id == "home-1"
    calls = login._session.calls
    hop = next(c for c in calls if "/step2" in c["url"])
    assert hop["url"] == "https://auth.lfhub.net/realms/x/step2?a=1"
    assert all(c.get("allow_redirects") is False for c in calls if "done" in c["url"]
               or "step2" in c["url"])
    token_call = next(c for c in calls if c["url"].endswith("/openid-connect/token"))
    assert token_call["data"]["grant_type"] == "authorization_code"
    assert token_call["data"]["code"] == "C0DE"
    assert token_call["data"]["client_secret"] == "test-client-secret"
    home_call = next(c for c in calls if c["url"].endswith("/api/v1/home"))
    assert home_call["headers"]["Authorization"] == "Bearer at"


async def test_done_url_carries_order_context():
    routes = _complete_routes(
        done=[Resp(status=302, headers={"Location": "alfapp://auth?code=X"})],
        token=Resp(json={"access_token": "at", "refresh_token": "rt"}),
        homes=Resp(json=[]),
    )
    login = await _login(routes)
    await login.async_start()
    await login.async_poll()

    done_call = next(c for c in login._session.calls if "/endpoint/done" in c["url"])
    assert f"bankidref={REF}" in done_call["url"]
    assert "state=st-1" in done_call["url"]
    assert "bank_app_redirect_uri=alfapp%3A%2F%2Fauth" in done_call["url"]
    # Empty home list: login still succeeds, just without a unique id.
    assert login.status == "done"
    assert login.unique_id is None


async def test_missing_redirect_location_fails_login():
    routes = _complete_routes(done=[Resp(status=200)], token=None, homes=None)
    login = await _login(routes)
    await login.async_start()
    await login.async_poll()

    assert login.status == "failed"
    assert not any(c["url"].endswith("/token") for c in login._session.calls)


async def test_redirect_loop_gives_up_after_ten_hops():
    loop = [Resp(status=302, headers={"Location": "https://auth.lfhub.net/loop"})
            for _ in range(9)]
    routes = _complete_routes(
        done=[Resp(status=302, headers={"Location": "https://auth.lfhub.net/loop"})],
        token=None, homes=None,
    )
    routes["/loop"] = loop
    login = await _login(routes)
    await login.async_start()
    await login.async_poll()

    assert login.status == "failed"
    hops = [c for c in login._session.calls if "/endpoint/done" in c["url"] or "/loop" in c["url"]]
    assert len(hops) == 10


async def test_app_redirect_without_code_fails_login():
    routes = _complete_routes(
        done=[Resp(status=302, headers={"Location": "alfapp://auth?error=access_denied"})],
        token=None, homes=None,
    )
    login = await _login(routes)
    await login.async_start()
    await login.async_poll()

    assert login.status == "failed"


async def test_token_response_without_refresh_token_fails_login():
    routes = _complete_routes(
        done=[Resp(status=302, headers={"Location": "alfapp://auth?code=X"})],
        token=Resp(json={"error": "invalid_grant"}),
        homes=None,
    )
    login = await _login(routes)
    await login.async_start()
    await login.async_poll()

    assert login.status == "failed"
    assert login.refresh_token is None


@pytest.mark.parametrize(
    "homes",
    [
        Resp(raise_on_json=ValueError("not json")),
        aiohttp.ClientError("boom"),
        Resp(json={"homes": [{"id": "h"}]}),  # not a list -> no id
    ],
    ids=["bad-json", "transport-error", "non-list"],
)
async def test_home_lookup_problems_do_not_block_login(homes):
    routes = _complete_routes(
        done=[Resp(status=302, headers={"Location": "alfapp://auth?code=X"})],
        token=Resp(json={"access_token": "at", "refresh_token": "rt"}),
        homes=homes,
    )
    login = await _login(routes)
    await login.async_start()
    await login.async_poll()

    assert login.status == "done"
    assert login.refresh_token == "rt"
    assert login.unique_id is None


async def test_no_access_token_skips_home_lookup():
    routes = _complete_routes(
        done=[Resp(status=302, headers={"Location": "alfapp://auth?code=X"})],
        token=Resp(json={"refresh_token": "rt"}),
        homes=None,
    )
    login = await _login(routes)
    await login.async_start()
    await login.async_poll()

    assert login.status == "done"
    assert login.unique_id is None
    assert not any(c["url"].endswith("/api/v1/home") for c in login._session.calls)


async def test_close_is_idempotent():
    login = await _login({})
    await login.async_close()
    assert login._session.closed
    await login.async_close()  # already closed: no error
