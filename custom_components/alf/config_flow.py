"""Config flow for the Alf integration - BankID login via an in-HA QR code."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .bankid import AlfBankIDLogin
from .const import CONF_REFRESH_TOKEN, DOMAIN, OPT_ENABLE_CONTROL

# Safety stop so a never-scanned flow can't poll forever.
_MAX_POLLS = 150


class AlfConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in with BankID (QR shown in HA) and store the resulting refresh token."""

    VERSION = 1

    def __init__(self) -> None:
        self._login: AlfBankIDLogin | None = None
        self._task: Any = None
        self._polls = 0
        self._refresh_token: str | None = None
        self._unique_id: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_bankid()

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_bankid()

    async def async_step_bankid(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._login is None:
            self._login = AlfBankIDLogin()
            self._task = self.hass.async_create_task(self._login.async_start())
            return self._show_progress()

        if not self._task.done():
            return self._show_progress()

        try:
            self._task.result()
        except Exception:  # noqa: BLE001 - any failure just restarts the add
            return await self._fail()

        if self._login.status == "done":
            self._refresh_token = self._login.refresh_token
            self._unique_id = self._login.unique_id
            await self._login.async_close()
            self._login = self._task = None
            return self.async_show_progress_done(next_step_id="finish")

        if self._login.status == "failed" or self._polls >= _MAX_POLLS:
            return await self._fail()

        self._polls += 1
        self._task = self.hass.async_create_task(self._login.async_poll())
        return self._show_progress()

    def _show_progress(self) -> ConfigFlowResult:
        return self.async_show_progress(
            step_id="bankid",
            progress_action="bankid",
            progress_task=self._task,
            description_placeholders={"qr": (self._login.qr_data_uri if self._login else "")},
        )

    async def _fail(self) -> ConfigFlowResult:
        if self._login is not None:
            await self._login.async_close()
        self._login = self._task = None
        return self.async_show_progress_done(next_step_id="failed")

    async def async_step_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_abort(reason="bankid_failed")

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data_updates={CONF_REFRESH_TOKEN: self._refresh_token},
            )
        if user_input is None:
            return self.async_show_form(
                step_id="finish",
                data_schema=vol.Schema(
                    {vol.Optional(OPT_ENABLE_CONTROL, default=False): bool}
                ),
            )
        await self.async_set_unique_id(self._unique_id or DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Alf",
            data={CONF_REFRESH_TOKEN: self._refresh_token},
            options={OPT_ENABLE_CONTROL: user_input.get(OPT_ENABLE_CONTROL, False)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return AlfOptionsFlow()


class AlfOptionsFlow(OptionsFlow):
    """Toggle experimental device control (default off)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        OPT_ENABLE_CONTROL,
                        default=self.config_entry.options.get(OPT_ENABLE_CONTROL, False),
                    ): bool
                }
            ),
        )
