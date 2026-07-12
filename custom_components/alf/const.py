"""Constants for the Alf integration."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "alf"
PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

CONF_REFRESH_TOKEN = "refresh_token"
OPT_ENABLE_CONTROL = "enable_control"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=45)

# Static, non-personal app secret, identical for every Android install and also extractable
# from the Alf APK. Embedded because the integration needs it to refresh tokens, and it is
# useless on its own - every token still requires the user's own BankID login. See README.
CLIENT_SECRET = "9ZyMeq1rsVatRQfXgjXwKjfYtl8ix3ke"
