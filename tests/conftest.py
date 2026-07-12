"""Shared async test doubles for alfcloud - no real network, version-proof."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


class FakeResponse:
    """Minimal stand-in for an aiohttp response used as an async context manager."""

    def __init__(self, status: int = 200, payload=None):
        self.status = status
        self._payload = {} if payload is None else payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Returns queued FakeResponses in order and records every call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def _next(self):
        return self._responses.pop(0)

    def post(self, url, data=None, json=None, **kwargs):
        self.calls.append({"method": "POST", "url": url, "data": data, "json": json})
        return self._next()

    def get(self, url, headers=None, **kwargs):
        self.calls.append({"method": "GET", "url": url, "headers": headers})
        return self._next()


@pytest.fixture
def fake():
    """Namespace exposing the Session/Response doubles."""
    return SimpleNamespace(Session=FakeSession, Response=FakeResponse)


@pytest.fixture
def make_jwt():
    """Build a syntactically valid JWT string with a future `exp` claim."""
    import base64
    import json
    import time

    def _make(exp_offset: int = 3600) -> str:
        def b64(d):
            return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
        return f"{b64({'alg': 'RS256'})}.{b64({'exp': int(time.time()) + exp_offset})}.sig"

    return _make
