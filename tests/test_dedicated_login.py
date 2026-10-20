"""recon/dedicated_login.py - the standalone BankID login CLI that bankid.py was ported from.

The module reads its client secret from the git-ignored recon/secrets.local.md at
import time; the tests never read that file - Path.read_text is patched during the
import to return a placeholder. All HTTP goes to a scripted fake session, every
output path (QR png, viewer html, token file) is redirected into tmp_path, and
os.startfile/asyncio.sleep are replaced so nothing opens or waits.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parent.parent / "recon" / "dedicated_login.py"
REF = "0123abcd-0000-4000-8000-00000000beef"
AUTO = "fedc4321-0000-4000-8000-00000000cafe"
BASE = "https://auth.lfhub.net/realms/lftt-kong-oidc"


@pytest.fixture(scope="module")
def dl():
    real_read_text = pathlib.Path.read_text

    def fake_read_text(self, *args, **kwargs):
        if self.name == "secrets.local.md":
            return "client_secret: test-secret-placeholder\n"
        return real_read_text(self, *args, **kwargs)

    mp = pytest.MonkeyPatch()
    mp.setattr(pathlib.Path, "read_text", fake_read_text)
    try:
        spec = importlib.util.spec_from_file_location("dedicated_login_under_test", _SRC)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    yield mod
    sys.modules.pop("dedicated_login_under_test", None)


class Resp:
    def __init__(self, *, status=200, text="", url="", payload=None, headers=None, body=b""):
        self.status = status
        self._text = text
        self.url = url
        self._payload = payload or {}
        self.headers = headers or {}
        self._body = body

    async def text(self):
        return self._text

    async def json(self):
        return self._payload

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class Session:
    """Pops the next scripted response for the first matching URL-path suffix."""

    def __init__(self, routes):
        self._routes = {k: list(v) for k, v in routes.items()}
        self.calls: list[dict] = []

    def _take(self, method, url, **kw):
        self.calls.append({"method": method, "url": url, **kw})
        path = url.split("?", 1)[0]
        for suffix, queue in self._routes.items():
            if path.endswith(suffix):
                return queue.pop(0)
        raise AssertionError(f"unexpected request {method} {url}")

    def get(self, url, **kw):
        return self._take("GET", url, **kw)

    def post(self, url, **kw):
        return self._take("POST", url, **kw)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _start(ref=REF, auto=AUTO, query="state=st-9&clientId=android&bank_app_redirect_uri=x%3A%2F%2Fy"):
    html = f'<a href="bankid:///?autostarttoken={auto}&bankidref={ref}">go</a>' if ref else "<p>no</p>"
    return Resp(text=html, url=f"{BASE}/login-actions/authenticate?{query}")


def _redirect(loc):
    return Resp(status=302, headers={"Location": loc} if loc else {})


# --- authorize -----------------------------------------------------------------------

async def test_authorize_extracts_context_and_sends_bankid_hint(dl):
    session = Session({"/openid-connect/auth": [_start()]})
    ctx = await dl.authorize(session)

    assert ctx == {"bankidref": REF, "autostart": AUTO, "state": "st-9",
                   "clientId": "android", "bank_app_redirect_uri": "x://y"}
    params = session.calls[0]["params"]
    assert params["kc_idp_hint"] == "bankid"
    assert params["response_type"] == "code"
    assert params["redirect_uri"] == "alfapp://auth"


async def test_authorize_defaults_when_query_missing(dl):
    session = Session({"/openid-connect/auth": [_start(auto="nope", query="")]})
    ctx = await dl.authorize(session)

    assert ctx["autostart"] is None   # not a 36-char uuid
    assert ctx["state"] == ""
    assert ctx["clientId"] == "android"
    assert ctx["bank_app_redirect_uri"] == "alfapp://auth"


async def test_authorize_raises_without_bankidref(dl):
    session = Session({"/openid-connect/auth": [_start(ref=None)]})
    with pytest.raises(RuntimeError, match="bankidref not found"):
        await dl.authorize(session)


# --- finish (redirect chain) -----------------------------------------------------------

def _ctx():
    return {"bankidref": REF, "state": "st", "clientId": "android",
            "bank_app_redirect_uri": "alfapp://auth"}


async def test_finish_follows_relative_and_absolute_hops_to_app_code(dl):
    session = Session({
        "/endpoint/done": [_redirect("/realms/lftt-kong-oidc/broker/after")],
        "/broker/after": [_redirect(f"{BASE}/login-actions/final")],
        "/login-actions/final": [_redirect("alfapp://auth?state=st&code=the-code")],
    })
    assert await dl.finish(session, _ctx()) == "the-code"
    urls = [c["url"] for c in session.calls]
    assert urls[0].startswith(f"{BASE}/broker/bankid/endpoint/done?bankidref={REF}")
    assert urls[1] == "https://auth.lfhub.net/realms/lftt-kong-oidc/broker/after"
    assert all(c["allow_redirects"] is False for c in session.calls)


@pytest.mark.parametrize("loc", [None, "alfapp://auth?error=access_denied"])
async def test_finish_returns_none_without_location_or_code(dl, loc):
    session = Session({"/endpoint/done": [_redirect(loc)]})
    assert await dl.finish(session, _ctx()) is None


async def test_finish_gives_up_after_ten_hops(dl):
    session = Session({"/loop": [_redirect(f"{BASE}/loop") for _ in range(10)],
                       "/endpoint/done": [_redirect(f"{BASE}/loop")]})
    assert await dl.finish(session, _ctx()) is None
    assert len(session.calls) == 10


# --- exchange / collect ----------------------------------------------------------------

async def test_exchange_posts_auth_code_grant_with_secret(dl):
    session = Session({"/openid-connect/token": [Resp(payload={"refresh_token": "rt"})]})
    assert await dl.exchange(session, "c0de") == {"refresh_token": "rt"}
    data = session.calls[0]["data"]
    assert data == {"grant_type": "authorization_code", "client_id": "android",
                    "client_secret": "test-secret-placeholder", "code": "c0de",
                    "redirect_uri": "alfapp://auth"}


async def test_collect_queries_by_bankidref(dl):
    session = Session({"/endpoint/collect": [Resp(payload={"status": "pending"})]})
    assert await dl.collect(session, _ctx()) == {"status": "pending"}
    assert session.calls[0]["params"] == {"bankidref": REF}


# --- main ------------------------------------------------------------------------------

@pytest.fixture
def run_main(dl, monkeypatch, tmp_path):
    """Run main() against a scripted session with every side effect contained."""
    opened = []
    monkeypatch.setattr(dl, "HERE", tmp_path)
    monkeypatch.setattr(dl, "QR_PNG", tmp_path / "qr.png")
    monkeypatch.setattr(dl, "TOKEN_OUT", tmp_path / "token.txt")
    monkeypatch.setattr(dl.os, "startfile", opened.append, raising=False)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(dl.asyncio, "sleep", no_sleep)

    async def _run(routes, argv=("dedicated_login.py",)):
        session = Session(routes)
        monkeypatch.setattr(dl.aiohttp, "ClientSession", lambda **kw: session)
        monkeypatch.setattr(dl.sys, "argv", list(argv))
        await dl.main()
        return session, opened

    return _run


async def test_main_testauth_stops_after_authorize(run_main, tmp_path, capsys):
    session, opened = await run_main({"/openid-connect/auth": [_start()]},
                                     argv=("x", "testauth"))
    assert len(session.calls) == 1
    assert "TESTAUTH OK" in capsys.readouterr().out
    assert opened == [] and not (tmp_path / "token.txt").exists()


async def test_main_full_flow_writes_refresh_token(run_main, tmp_path, capsys):
    session, opened = await run_main({
        "/openid-connect/auth": [_start()],
        "/endpoint/qrcode": [Resp(body=b"PNG1"), Resp(status=500)],
        "/endpoint/collect": [Resp(payload={"status": "pending"}),
                              Resp(payload={"status": "complete"})],
        "/endpoint/done": [_redirect("alfapp://auth?code=abc")],
        "/openid-connect/token": [Resp(payload={"refresh_token": "rt-dedicated",
                                                "expires_in": 1})],
    })

    assert (tmp_path / "token.txt").read_text(encoding="utf-8") == "rt-dedicated"
    # The non-200 second QR frame keeps the first one on disk.
    assert (tmp_path / "qr.png").read_bytes() == b"PNG1"
    assert opened == [str(tmp_path / "bankid_view.local.html")]  # opened once only
    assert "DEDICATED_TOKEN_WRITTEN" in capsys.readouterr().out
    token_post = [c for c in session.calls if c["method"] == "POST"]
    assert token_post[0]["data"]["code"] == "abc"


async def test_main_failed_bankid_writes_nothing(run_main, tmp_path, capsys):
    session, _ = await run_main({
        "/openid-connect/auth": [_start()],
        "/endpoint/qrcode": [Resp(body=b"PNG")],
        "/endpoint/collect": [Resp(payload={"status": "failed", "hintCode": "userCancel"})],
    })
    assert "BANKID_FAILED userCancel" in capsys.readouterr().out
    assert not (tmp_path / "token.txt").exists()
    assert not any("/endpoint/done" in c["url"] for c in session.calls)


async def test_main_without_code_or_refresh_token_writes_nothing(run_main, tmp_path, capsys):
    common = {
        "/openid-connect/auth": [_start()],
        "/endpoint/qrcode": [Resp(body=b"PNG")],
        "/endpoint/collect": [Resp(payload={"status": "complete"})],
    }
    await run_main({**common, "/endpoint/done": [_redirect(None)]})
    assert "NO_CODE" in capsys.readouterr().out

    await run_main({
        "/openid-connect/auth": [_start()],
        "/endpoint/qrcode": [Resp(body=b"PNG")],
        "/endpoint/collect": [Resp(payload={"status": "complete"})],
        "/endpoint/done": [_redirect("alfapp://auth?code=abc")],
        "/openid-connect/token": [Resp(payload={"error": "invalid_grant"})],
    })
    assert "NO_REFRESH_TOKEN; keys: ['error']" in capsys.readouterr().out
    assert not (tmp_path / "token.txt").exists()
