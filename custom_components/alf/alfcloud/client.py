"""REST client for the Alf cloud API (read + optional control)."""
from __future__ import annotations

from typing import Any

import aiohttp

from .auth import AlfAuth
from .const import ACTION_PATH, API_BASE, DEVICES_PATH, HOMES_PATH
from .errors import AlfApiError
from .models import Device, Home, parse_devices, parse_homes


class AlfClient:
    """Talks to lfhub.net, injecting a bearer token from AlfAuth."""

    def __init__(self, auth: AlfAuth, session: aiohttp.ClientSession) -> None:
        self._auth = auth
        self._session = session

    async def async_get_homes(self) -> list[Home]:
        return parse_homes(await self._request("GET", HOMES_PATH))

    async def async_get_devices(self, home_id: str) -> list[Device]:
        return parse_devices(await self._request("GET", DEVICES_PATH.format(home_id=home_id)))

    async def async_set_feature(self, home_id: str, device_feature_id: str, value: Any) -> dict:
        path = ACTION_PATH.format(home_id=home_id, device_feature_id=device_feature_id)
        return await self._request("POST", path, json={"value": value})

    async def _request(self, method: str, path: str, *, json: Any = None, _retry: bool = True) -> Any:
        token = await self._auth.async_get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        url = API_BASE + path
        try:
            opener = (
                self._session.post(url, json=json, headers=headers)
                if method == "POST"
                else self._session.get(url, headers=headers)
            )
            async with opener as resp:
                if resp.status == 401 and _retry:
                    await self._auth.async_refresh()
                    return await self._request(method, path, json=json, _retry=False)
                if resp.status >= 400:
                    raise AlfApiError(f"{method} {path} failed: HTTP {resp.status}", resp.status)
                return await resp.json()
        except aiohttp.ClientError as err:
            raise AlfApiError(f"{method} {path} transport error: {err}") from err
