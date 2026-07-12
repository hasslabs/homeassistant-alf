# Alf cloud API - findings

> Reverse-engineered 2026-07-12 by capturing the Android app (`se.lf.alf`) via mitmproxy + Frida
> on a rooted OnePlus 6. This document is the input for Plan 2 (`alfcloud` + the HA integration).
> IDs below are placeholders (`{homeId}`, `{deviceId}`) - no real identifiers or secrets are stored
> here. The static `client_secret` lives in `recon/secrets.local.md` (git-ignored).

## Summary

- **API host:** `lfhub.net` (HTTP/2, behind Cloudflare). Bearer-auth JSON REST.
- **Auth host:** `auth.lfhub.net` - **Keycloak**, realm `lftt-kong-oidc` (Kong API gateway + OIDC).
- **TLS:** the app pins (Conscrypt). Irrelevant to the integration, which calls the API server-side
  (no pinning there). Pinning only had to be bypassed to *observe* the traffic during recon.

## Authentication (Keycloak OIDC + BankID broker)

Standard OAuth2 **authorization code** flow, identity provider = **BankID** (via Keycloak broker).

- `client_id`: **`android`** (confidential client - carries a static `client_secret`)
- `redirect_uri`: `alfapp://auth`
- Authorize: `GET https://auth.lfhub.net/realms/lftt-kong-oidc/protocol/openid-connect/auth`
- BankID broker: `/broker/bankid/login`, `/broker/bankid/endpoint/{start,qrcode,collect,done}`
  (`collect` is the status-polling loop; QR = "BankID on another device")
- **Token endpoint:** `POST https://auth.lfhub.net/realms/lftt-kong-oidc/protocol/openid-connect/token`
  - initial: `grant_type=authorization_code, client_id, client_secret, code, redirect_uri`
  - **refresh (what the integration uses):** `grant_type=refresh_token, client_id=android, client_secret, refresh_token`
  - response JSON: `access_token, refresh_token, id_token, expires_in, refresh_expires_in, token_type=Bearer, scope, session_state`
- Logout: `POST /protocol/openid-connect/logout` (`client_id, client_secret, refresh_token`)
- **All API calls** carry `Authorization: Bearer <access_token>`. The access token is a JWT
  (RS256, `iss=https://auth.lfhub.net/realms/lftt-kong-oidc`, `scope="openid userId first_login isInternal"`).

### Token lifecycle (the key finding - headless is viable indefinitely)

| Token | TTL | Notes |
|-------|-----|-------|
| access_token | `expires_in` = 432000 s = **5 days** | JWT bearer |
| refresh_token | `refresh_expires_in` = 2592000 s = **30 days** | **rotating** - each refresh issues a fresh 30-day token |

Because a polling integration refreshes far more often than every 30 days, and each refresh rotates
the 30-day window forward, **the integration never needs a new BankID login after first setup.**
This is the spec's "best case" auth path.

## API (host `lfhub.net`, Bearer auth)

Read endpoints seen:

| Endpoint | Purpose |
|----------|---------|
| `GET /user/me` | user profile |
| `GET /api/v1/home` | list of homes -> `{id: homeId, ...}` |
| `GET /api/v1/home/{homeId}/device` | **device list + all states** (the polling endpoint) |
| `GET /api/v1/home/{homeId}/climate` | climate (404 if none) |
| `GET /home/{homeId}/profile` `/rules` `/device/tasks` `/content` | profile, rules, tasks, content |
| `GET /notification/summary`, `/content/announcements`, `/product` | notifications, misc |

Conditional caching: the server supports `ETag` / `If-None-Match` and returns **304** when unchanged
(the app relies on this). The integration may send `If-None-Match` to minimise payload, or just GET.

### Control (write) - confirmed

`POST /home/{homeId}/device/action/{deviceId}:{featureId}` with body `{"value": <desired>}` -> `201`,
response `{id, deviceFeatureId, current, desired}`.

Example (smart plug off): `POST /home/{homeId}/device/action/{deviceId}:smartplug.onOff` `{"value": false}`.

## Device model

`GET /api/v1/home/{homeId}/device` -> `{"homeId": "...", "devices": [Device]}`. Each `Device`:

```jsonc
{
  "id": "...", "name": "...", "type": "frient.smartplug", "state": "online",
  "homeId": "...", "roomId": "...", "productId": "...", "parentId": "<gateway id | null>",
  "specifications": { "modelId": "SPLZB-141", "modelName": "...", "vendor": "Frient A/S",
                      "protocol": "zigbee", "serialNumber": "...", "firmwareVersion": "..." },
  "power":   { "source": {"value": "mains|battery", "defect": false},
               "status": {"value": "good", "percentage": {...}, "voltage": {"value": 3, "unit": "v"}} },
  "network": { "source": "zigbee|gsm", "status": "good", "wlan": null },
  "features": [ { "id": "smartplug.onOff", "deviceFeatureId": "{deviceId}:smartplug.onOff",
                  "current": {"value": true, "updatedAt": "..."}, "desired": null } ],
  "settings": [], "accesses": [], "alarmProfile": null
}
```

Device `type`s seen so far: `develco.gateway`, `frient.smartplug`, `frient.smokeDetector`
(magnet/motion/leak/siren present on the account - capture their feature ids when building).

### Feature -> HA entity mapping

| feature id | value | HA entity (device_class) |
|------------|-------|--------------------------|
| `smartplug.onOff` | bool | `switch` |
| `smartplug.demand` | number | `sensor` (power) |
| `smartplug.summationDelivered` | number (Wh) | `sensor` (energy, `total_increasing`) |
| `smokeDetector.fire` | bool | `binary_sensor` (smoke) |
| `generic.temperature` | number degC | `sensor` (temperature) |
| `power.status.voltage` / `power.status.percentage` | number | `sensor` (battery) |
| `state` (device-level) | "online"/... | `binary_sensor` (connectivity) |
| leak / contact(opening) / motion / humidity | tbd | map when their feature ids are captured |

Entities are built generically: iterate `devices[].features[]`, map by feature-id prefix; use
`power`/`network`/`state` for battery + connectivity; group by `id` with `DeviceInfo`
(name, `specifications.modelName`, vendor, `serialNumber`, `firmwareVersion`), and by `roomId` for areas.

## Polling / rate limits

- App polls `/device` periodically; no `429` observed. Proposed coordinator interval **30-60 s**.
- Optional: store the `ETag` and send `If-None-Match` to get cheap `304`s between changes.

## Inputs for Plan 2 (`alfcloud`)

1. **Auth:** OIDC refresh against the token endpoint (`grant_type=refresh_token` + `client_id=android`
   + `client_secret` + rotating `refresh_token`). Persist the newest refresh_token after each refresh.
2. **Config flow:** user supplies a `refresh_token` captured once at setup (5d access / 30d rotating
   refresh -> headless indefinitely). Consider shipping a small capture helper later.
3. **Read:** `GET /api/v1/home` -> homeId(s); `GET /api/v1/home/{homeId}/device` -> build entities.
4. **Control (optional, behind toggle):** `POST /home/{homeId}/device/action/{deviceFeatureId}` `{"value": ...}`.
5. **Fixtures:** real redacted captures are in `recon/fixtures/` (git-ignored, local). Build
   Plan 2 TDD fixtures as anonymised/synthetic copies (fake ids/serials) for the public repo.
