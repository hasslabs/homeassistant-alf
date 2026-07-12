"""Drive a Keycloak auth-code + BankID login from inside the config flow.

Ported from the standalone recon/dedicated_login.py (proven working). No PKCE.
Uses its own cookie-isolated aiohttp session (the BankID session cookies must not
mix with Home Assistant's shared client session). Exposes the current animated QR
as a data-URI for the config flow to render, and advances one poll per step.
"""
from __future__ import annotations

import base64
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from .const import CLIENT_SECRET

AUTH_BASE = "https://auth.lfhub.net/realms/lftt-kong-oidc"
API_BASE = "https://lfhub.net"
CLIENT_ID = "android"
REDIRECT = "alfapp://auth"
_UA = "Mozilla/5.0 (Linux; Android 14) alf-ha"
_REF_RE = re.compile(r"bankidref=([0-9a-fA-F-]{36})")


class AlfBankIDError(Exception):
    """BankID login failed."""


class AlfBankIDLogin:
    """One BankID login attempt, advanced one poll at a time by the config flow."""

    def __init__(self) -> None:
        self._session = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(unsafe=True), headers={"User-Agent": _UA}
        )
        self._ctx: dict[str, str] = {}
        self.qr_png: bytes | None = None
        self.status = "init"        # init | pending | done | failed
        self.hint: str | None = None
        self.refresh_token: str | None = None
        self.unique_id: str | None = None

    @property
    def qr_data_uri(self) -> str:
        if not self.qr_png:
            return ""
        return "data:image/png;base64," + base64.b64encode(self.qr_png).decode()

    async def async_close(self) -> None:
        if not self._session.closed:
            await self._session.close()

    async def async_start(self) -> None:
        """Create a BankID order and fetch the first QR frame."""
        params = {
            "scope": "openid",
            "client_id": CLIENT_ID,
            "kc_idp_hint": "bankid",
            "response_type": "code",
            "redirect_uri": REDIRECT,
        }
        async with self._session.get(
            f"{AUTH_BASE}/protocol/openid-connect/auth", params=params
        ) as r:
            html = await r.text()
            final_q = parse_qs(urlparse(str(r.url)).query)
        ref = _REF_RE.search(html)
        if not ref:
            raise AlfBankIDError("bankidref not found on start page")
        self._ctx = {
            "bankidref": ref.group(1),
            "state": final_q.get("state", [""])[0],
            "clientId": final_q.get("clientId", [CLIENT_ID])[0],
            "bru": final_q.get("bank_app_redirect_uri", [REDIRECT])[0],
        }
        self.status = "pending"
        self.hint = None
        await self._async_fetch_qr()

    async def async_poll(self) -> None:
        """Refresh the QR and poll the BankID order once; advance status."""
        await self._async_fetch_qr()
        async with self._session.get(
            f"{AUTH_BASE}/broker/bankid/endpoint/collect",
            params={"bankidref": self._ctx["bankidref"]},
        ) as r:
            data = await r.json()
        status, self.hint = data.get("status"), data.get("hintCode")
        if status == "complete":
            await self._async_finish()
        elif status == "failed":
            if self.hint == "startFailed":
                await self.async_start()  # order expired unscanned - renew it
            else:
                self.status = "failed"

    async def _async_fetch_qr(self) -> None:
        async with self._session.get(
            f"{AUTH_BASE}/broker/bankid/endpoint/qrcode",
            params={"bankidref": self._ctx["bankidref"]},
        ) as r:
            if r.status == 200:
                self.qr_png = await r.read()

    async def _async_finish(self) -> None:
        code = await self._async_code()
        if not code:
            self.status = "failed"
            return
        tokens = await self._async_exchange(code)
        self.refresh_token = tokens.get("refresh_token")
        if not self.refresh_token:
            self.status = "failed"
            return
        self.unique_id = await self._async_first_home_id(tokens.get("access_token"))
        self.status = "done"

    async def _async_code(self) -> str | None:
        url = f"{AUTH_BASE}/broker/bankid/endpoint/done?" + urlencode(
            {
                "bankidref": self._ctx["bankidref"],
                "state": self._ctx["state"],
                "clientId": self._ctx["clientId"],
                "bank_app_redirect_uri": self._ctx["bru"],
            }
        )
        for _ in range(10):
            async with self._session.get(url, allow_redirects=False) as r:
                loc = r.headers.get("Location")
            if not loc:
                return None
            if loc.startswith("alfapp://"):
                return parse_qs(urlparse(loc).query).get("code", [None])[0]
            url = loc if loc.startswith("http") else f"https://auth.lfhub.net{loc}"
        return None

    async def _async_exchange(self, code: str) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT,
        }
        async with self._session.post(
            f"{AUTH_BASE}/protocol/openid-connect/token", data=data
        ) as r:
            return await r.json()

    async def _async_first_home_id(self, access_token: str | None) -> str | None:
        if not access_token:
            return None
        try:
            async with self._session.get(
                f"{API_BASE}/api/v1/home",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            ) as r:
                homes = await r.json()
            if isinstance(homes, list) and homes:
                return homes[0].get("id")
        except (aiohttp.ClientError, ValueError):
            return None
        return None
