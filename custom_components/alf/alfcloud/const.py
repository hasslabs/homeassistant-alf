"""Endpoints and constants for the Alf (lfhub.net) cloud API.

Discovered via recon 2026-07-12 (see docs/api/alf-cloud-api.md).
"""
from __future__ import annotations

AUTH_HOST = "auth.lfhub.net"
API_HOST = "lfhub.net"
API_BASE = f"https://{API_HOST}"
REALM = "lftt-kong-oidc"

TOKEN_URL = f"https://{AUTH_HOST}/realms/{REALM}/protocol/openid-connect/token"
CLIENT_ID = "android"
# CLIENT_SECRET is a static, non-personal app secret (same for every Android install,
# extractable from the APK). It is supplied to AlfAuth by the integration - see auth.py.

# Read endpoints.
HOMES_PATH = "/api/v1/home"
DEVICES_PATH = "/api/v1/home/{home_id}/device"
# Control (write): POST with body {"value": <desired>}.
ACTION_PATH = "/home/{home_id}/device/action/{device_feature_id}"

# Access token is a 5-day JWT; refresh token is 30 days and rotates on each refresh.
ACCESS_TOKEN_TTL_S = 432000
REFRESH_TOKEN_TTL_S = 2592000
