"""Drive a fresh Keycloak auth-code + BankID login to mint a DEDICATED refresh
token for the Home Assistant integration (its own session, separate from the app).

No PKCE (confidential client). Reads the static client_secret from the git-ignored
recon/secrets.local.md. Writes the resulting refresh token to
recon/dedicated_token.secret.txt (git-ignored).

Usage:
    python recon/dedicated_login.py testauth   # just verify authorize + extraction
    python recon/dedicated_login.py            # full flow (needs BankID approval)
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import sys
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

BASE = "https://auth.lfhub.net/realms/lftt-kong-oidc"
CLIENT_ID = "android"
REDIRECT = "alfapp://auth"
UA = "Mozilla/5.0 (Linux; Android 14) alf-ha"

HERE = pathlib.Path(__file__).resolve().parent
CLIENT_SECRET = re.search(
    r"client_secret:\s*(\S+)", (HERE / "secrets.local.md").read_text(encoding="utf-8")
).group(1)
QR_PNG = HERE / "bankid_qr.local.png"
TOKEN_OUT = HERE / "dedicated_token.secret.txt"


async def authorize(session: aiohttp.ClientSession) -> dict:
    params = {
        "scope": "openid",
        "client_id": CLIENT_ID,
        "kc_idp_hint": "bankid",
        "response_type": "code",
        "redirect_uri": REDIRECT,
    }
    async with session.get(
        f"{BASE}/protocol/openid-connect/auth", params=params, allow_redirects=True
    ) as r:
        html = await r.text()
        final_q = parse_qs(urlparse(str(r.url)).query)
    bankidref = re.search(r"bankidref=([0-9a-fA-F-]{36})", html)
    autostart = re.search(r"autostarttoken=([0-9a-fA-F-]{36})", html)
    if not bankidref:
        raise RuntimeError(f"bankidref not found; landed on {final_q}")
    return {
        "bankidref": bankidref.group(1),
        "autostart": autostart.group(1) if autostart else None,
        "state": final_q.get("state", [""])[0],
        "clientId": final_q.get("clientId", [CLIENT_ID])[0],
        "bank_app_redirect_uri": final_q.get("bank_app_redirect_uri", [REDIRECT])[0],
    }


async def collect(session: aiohttp.ClientSession, ctx: dict) -> dict:
    async with session.get(
        f"{BASE}/broker/bankid/endpoint/collect", params={"bankidref": ctx["bankidref"]}
    ) as r:
        return await r.json()


async def finish(session: aiohttp.ClientSession, ctx: dict) -> str | None:
    url = f"{BASE}/broker/bankid/endpoint/done?" + urlencode(
        {
            "bankidref": ctx["bankidref"],
            "state": ctx["state"],
            "clientId": ctx["clientId"],
            "bank_app_redirect_uri": ctx["bank_app_redirect_uri"],
        }
    )
    for _ in range(10):
        async with session.get(url, allow_redirects=False) as r:
            loc = r.headers.get("Location")
        if not loc:
            return None
        if loc.startswith("alfapp://"):
            return parse_qs(urlparse(loc).query).get("code", [None])[0]
        url = loc if loc.startswith("http") else f"https://auth.lfhub.net{loc}"
    return None


async def exchange(session: aiohttp.ClientSession, code: str) -> dict:
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT,
    }
    async with session.post(f"{BASE}/protocol/openid-connect/token", data=data) as r:
        return await r.json()


async def main() -> None:
    test_only = len(sys.argv) > 1 and sys.argv[1] == "testauth"
    jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(cookie_jar=jar, headers={"User-Agent": UA}) as session:
        ctx = await authorize(session)
        print("bankidref:", ctx["bankidref"][:8] + "...", "| autostart:", bool(ctx["autostart"]),
              "| state len:", len(ctx["state"]))
        if test_only:
            print("TESTAUTH OK - authorize + extraction works")
            return

        html_path = HERE / "bankid_view.local.html"
        print("Opening the animated QR - scan it in the BankID app (Scan QR code)...", flush=True)
        for i in range(150):
            async with session.get(
                f"{BASE}/broker/bankid/endpoint/qrcode", params={"bankidref": ctx["bankidref"]}
            ) as qr:
                if qr.status == 200:
                    QR_PNG.write_bytes(await qr.read())
            html_path.write_text(
                '<html><head><meta http-equiv="refresh" content="1">'
                '<title>Alf - BankID</title></head>'
                '<body style="margin:0;padding:24px;text-align:center;font-family:sans-serif">'
                '<h3>Skanna i BankID-appen ("Skanna QR-kod")</h3>'
                f'<img src="bankid_qr.local.png?v={i}" width="320"></body></html>',
                encoding="utf-8",
            )
            if i == 0:
                try:
                    os.startfile(str(html_path))
                except Exception:  # noqa: BLE001
                    pass
            c = await collect(session, ctx)
            print("collect:", c.get("status"), c.get("hintCode"), flush=True)
            status = c.get("status")
            if status == "complete":
                break
            if status == "failed":
                print("BANKID_FAILED", c.get("hintCode"))
                return
            await asyncio.sleep(1)
        else:
            print("TIMEOUT waiting for BankID")
            return

        code = await finish(session, ctx)
        if not code:
            print("NO_CODE captured from redirect")
            return
        tokens = await exchange(session, code)
        rt = tokens.get("refresh_token")
        if rt:
            TOKEN_OUT.write_text(rt, encoding="utf-8")
            print("DEDICATED_TOKEN_WRITTEN:", TOKEN_OUT)
            print("access expires_in:", tokens.get("expires_in"),
                  "| refresh_expires_in:", tokens.get("refresh_expires_in"))
        else:
            print("NO_REFRESH_TOKEN; keys:", list(tokens.keys()))


if __name__ == "__main__":
    asyncio.run(main())
