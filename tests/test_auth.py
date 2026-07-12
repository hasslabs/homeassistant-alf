import base64
import json
import time

import pytest

from alfcloud.auth import AlfAuth
from alfcloud.errors import AlfAuthError


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
