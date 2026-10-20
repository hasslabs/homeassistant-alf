import base64
import json
import time

import pytest

from alfcloud.auth import AlfAuth
from alfcloud.errors import AlfAuthError, AlfConnectionError


def _make_jwt(exp: int) -> str:
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b64({'alg': 'RS256'})}.{b64({'exp': exp})}.signature"


async def test_refresh_returns_token_and_rotates_refresh_token(fake):
    session = fake.Session([fake.Response(payload={
        "access_token": _make_jwt(int(time.time()) + 3600),
        "refresh_token": "rt-new",
        "expires_in": 3600,
    })])
    auth = AlfAuth("rt-old", "app-secret", session)
    token = await auth.async_get_access_token()

    assert token.count(".") == 2
    assert auth.refresh_token == "rt-new"  # rotated, caller must persist
    sent = session.calls[0]["data"]
    assert sent["grant_type"] == "refresh_token"
    assert sent["client_id"] == "android"
    assert sent["refresh_token"] == "rt-old"


async def test_cached_token_is_reused_without_second_call(fake):
    session = fake.Session([fake.Response(payload={
        "access_token": _make_jwt(int(time.time()) + 3600),
        "expires_in": 3600,
    })])
    auth = AlfAuth("rt", "app-secret", session)
    first = await auth.async_get_access_token()
    second = await auth.async_get_access_token()  # cached: no second response queued

    assert first == second
    assert len(session.calls) == 1


async def test_bad_refresh_raises_auth_error(fake):
    session = fake.Session([fake.Response(status=400, payload={"error": "invalid_grant"})])
    auth = AlfAuth("rt-bad", "app-secret", session)

    with pytest.raises(AlfAuthError):
        await auth.async_get_access_token()


async def test_transport_error_raises_connection_error(fake):
    # DNS/connect failure at refresh time is transient, not an auth failure:
    # it must be a distinct AlfConnectionError so HA retries instead of forcing re-auth.
    session = fake.Session([fake.Boom("Timeout while contacting DNS servers")])
    auth = AlfAuth("rt", "app-secret", session)

    with pytest.raises(AlfConnectionError):
        await auth.async_get_access_token()


async def test_connection_error_is_not_auth_error(fake):
    # Guard the classification boundary: a transport error must NOT be caught as AlfAuthError.
    session = fake.Session([fake.Boom()])
    auth = AlfAuth("rt", "app-secret", session)

    with pytest.raises(AlfConnectionError):
        await auth.async_get_access_token()
    assert not issubclass(AlfConnectionError, AlfAuthError)


async def test_missing_access_token_raises_auth_error(fake):
    session = fake.Session([fake.Response(payload={"refresh_token": "rt-new"})])
    auth = AlfAuth("rt-old", "app-secret", session)

    with pytest.raises(AlfAuthError):
        await auth.async_get_access_token()
    assert auth.refresh_token == "rt-old"  # nothing rotated on a rejected response


async def test_refresh_without_new_refresh_token_keeps_old_one(fake):
    session = fake.Session([fake.Response(payload={
        "access_token": _make_jwt(int(time.time()) + 3600),
    })])
    auth = AlfAuth("rt-keep", "app-secret", session)
    await auth.async_get_access_token()

    assert auth.refresh_token == "rt-keep"


async def test_token_inside_expiry_margin_is_refreshed(fake):
    # exp 30 s ahead is inside the 60 s safety margin -> next call must refresh again.
    session = fake.Session([
        fake.Response(payload={"access_token": _make_jwt(int(time.time()) + 30)}),
        fake.Response(payload={"access_token": _make_jwt(int(time.time()) + 3600)}),
    ])
    auth = AlfAuth("rt", "app-secret", session)
    first = await auth.async_get_access_token()
    second = await auth.async_get_access_token()

    assert len(session.calls) == 2
    assert first != second


@pytest.mark.parametrize("opaque", ["not-a-jwt", "a.%%%.c", "a.bm90LWpzb24.c"])
async def test_opaque_access_token_falls_back_to_expires_in(fake, opaque):
    # Unreadable exp claim -> lifetime comes from expires_in, so the token is cached.
    session = fake.Session([fake.Response(payload={"access_token": opaque, "expires_in": 3600})])
    auth = AlfAuth("rt", "app-secret", session)

    assert await auth.async_get_access_token() == opaque
    assert await auth.async_get_access_token() == opaque
    assert len(session.calls) == 1


async def test_opaque_token_without_expires_in_uses_short_default(fake, monkeypatch):
    session = fake.Session([fake.Response(payload={"access_token": "opaque"})])
    auth = AlfAuth("rt", "app-secret", session)
    monkeypatch.setattr("alfcloud.auth.time.time", lambda: 1_000_000.0)
    await auth.async_refresh()

    assert auth._access_exp == 1_000_300.0  # 300 s default lifetime


async def test_custom_client_id_and_token_url_are_used(fake):
    session = fake.Session([fake.Response(payload={"access_token": "opaque"})])
    auth = AlfAuth("rt", "sec", session, client_id="other", token_url="https://example.invalid/t")
    await auth.async_refresh()

    call = session.calls[0]
    assert call["url"] == "https://example.invalid/t"
    assert call["data"]["client_id"] == "other"
    assert call["data"]["client_secret"] == "sec"
