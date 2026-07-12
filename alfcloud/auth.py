"""OIDC token handling for the Alf cloud API (Keycloak refresh grant)."""
from __future__ import annotations

import base64
import json
import time

import aiohttp

from .const import CLIENT_ID, TOKEN_URL
from .errors import AlfAuthError

# Refresh this many seconds before the access token actually expires.
_EXPIRY_MARGIN_S = 60


def _jwt_exp(token: str) -> int | None:
    """Return the `exp` claim of a JWT, or None if it can't be read."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode())).get("exp")
    except Exception:  # noqa: BLE001 - any malformed token just means "unknown expiry"
        return None


class AlfAuth:
    """Holds a rotating refresh token and hands out fresh access tokens.

    The refresh token rotates on every refresh; read `refresh_token` after each
    call so the caller (HA config entry) can persist the newest one.
    """

    def __init__(
        self,
        refresh_token: str,
        client_secret: str,
        session: aiohttp.ClientSession,
        *,
        client_id: str = CLIENT_ID,
        token_url: str = TOKEN_URL,
    ) -> None:
        self._refresh_token = refresh_token
        self._client_secret = client_secret
        self._session = session
        self._client_id = client_id
        self._token_url = token_url
        self._access_token: str | None = None
        self._access_exp: float = 0.0

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        if self._access_token and time.time() < self._access_exp - _EXPIRY_MARGIN_S:
            return self._access_token
        await self.async_refresh()
        return self._access_token  # type: ignore[return-value]

    async def async_refresh(self) -> None:
        """Exchange the refresh token for a new access token (and rotate it)."""
        data = {
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": self._refresh_token,
        }
        try:
            async with self._session.post(self._token_url, data=data) as resp:
                if resp.status != 200:
                    raise AlfAuthError(f"token refresh failed: HTTP {resp.status}")
                payload = await resp.json()
        except aiohttp.ClientError as err:
            raise AlfAuthError(f"token refresh transport error: {err}") from err

        token = payload.get("access_token")
        if not token:
            raise AlfAuthError("token refresh response missing access_token")
        self._access_token = token
        if payload.get("refresh_token"):
            self._refresh_token = payload["refresh_token"]
        exp = _jwt_exp(token)
        self._access_exp = float(exp) if exp else time.time() + payload.get("expires_in", 300)
