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
| `GET /home/{homeId}/device/tasks` | **outstanding alarms** (see "Tasks" below); `[]` when none |
| `GET /home/{homeId}/profile` `/rules` `/content` | profile, rules, content |
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
| `waterLeakDetector.flood` | bool | `binary_sensor` (moisture) - clears correctly |
| `leakbot.leak` | bool | **do not trust** - latches, see "Tasks" below |
| `leakbot.highFlow` / `.hotPipe` / `.onPipe` | bool | diagnostic (`onPipe` reads true when correctly fitted) |
| `leakbot.hardwareProblem` | bool | `binary_sensor` (problem) |
| contact(opening) / motion / humidity | tbd | map when their feature ids are captured |

Entities are built generically: iterate `devices[].features[]`, map by feature-id prefix; use
`power`/`network`/`state` for battery + connectivity; group by `id` with `DeviceInfo`
(name, `specifications.modelName`, vendor, `serialNumber`, `firmwareVersion`), and by `roomId` for areas.

## Tasks - the alarm layer (captured 2026-11-03)

`GET /home/{homeId}/device/tasks` -> a JSON **array**, `[]` when nothing is outstanding. The
`/api/v1/`-prefixed spelling answers `500`, so only the unprefixed path works.

This is the layer the app renders, and it is **not** the same thing as a feature value. Captured
by wetting a `frient.waterLeakDetector` probe:

```jsonc
[{
  "deviceId": "{deviceId}", "taskId": "{uuid}", "homeId": "{homeId}",
  "eventId": "alarm.flood.true",            // alarm.<feature>.<value>
  "title": "Vatten upptäckt",
  "description": "Så gör du vid misstänkt läcka.",
  "severity": "warning", "isUrgent": true,
  "createdAt": "2026-11-03T11:14:28.524Z",
  "homeScreenTitle": "Vatten upptäckt",
  "homeScreenDescription": "{device name} har detekterat en läcka.",
  "entryContext": "guide",
  "content": { "id": "...", "title": "Misstänkt dropp", "description": "...",
               "body": "### Tysta larmet ###\n..." }   // ready-made Swedish guide, markdown-ish
}]
```

Task types named in the APK (v3.35.0), each keyed by a `deviceFeatureId`: `LeakDetectorFlood`,
`LeakBotHighFlow`, `LeakBotLowSignal`, `LeakBotLowBattery`, `LeakBotHardwareProblem`. The app's
LeakBot status strings are flow-based (`device_status_leakbot_normal_flow_label`,
`..._HighFlowLeakage_label`, `..._lowFlowLeakage_label`), so a LeakBot verdict is **not** read off
`leakbot.leak`.

**Why this matters:** `leakbot.leak` on this account has read `true` since `2026-07-21T22:43:56Z`
and has never been rewritten, while `tasks` is empty and the app shows normal flow. The feature
latched and nothing clears it. By contrast `waterLeakDetector.flood` went `true` at
`11:14:28.164Z` and back to `false` at `11:14:40.337Z` entirely on its own. So feature booleans
can be stale forever; a task is the signal that tracks reality.

Timing: the task was created `11:14:28.524Z`, a third of a second after the feature changed, and
the whole episode lasted **12 seconds** - shorter than the integration's 45 s poll, which missed
it completely (Home Assistant recorded no state change at all).

**Tasks are ephemeral.** The task above was gone by `12:44Z` with nothing acknowledged in
between - only `GET`s were issued - so a task clears itself once the condition clears. The exact
lifetime was not pinned down (present at `11:14:30Z`, absent at `12:44Z`). Consequence: tasks are
a view of what is wrong *now*, not a durable alarm log, so **polling tasks does not rescue a
short event either** - a 12-second flood leaves a task that is also short-lived.

### How the app gets alarms instantly (and why the integration can't, yet)

Not over WebSockets. `wss://lfhub.net/ws/events/all` (both strings are in the APK, driven by a
Ktor WebSockets client, with an `ApiWebSocketMessage.DeviceMessage` / `.UnknownMessage` model)
answers `404 {"message":"no Route matched with those values"}` at the gateway, while
`GET /api/v1/home` returns `200` with the same bearer token. The app also gates it behind
`FeatureFlag.BooleanFlag.WebSockets`. So it is built but not deployed - do not design against it.

The live path is **Firebase Cloud Messaging**: the app registers a token with
`PUT /profile/pushToken` (body `PushTokenRequestBody(deviceId=...)`, captured returning `200`) and
removes it with `DELETE /profile/pushToken/{tokenId}`, handled by
`se.lftt.alf.pushnotifications.AlfFirebaseMessagingService`. Receiving those pushes outside the
app would mean impersonating an FCM registration - possible, but a different class of work from
the REST client.

Known event ids (from the APK): `alarm.flood.true`, `alarm.fire.true`, `alarm.burglary.true`,
`alarm.armed-away`, `alarm.armed-night`, `alarm.armed-partly`, `alarm.disarmed`,
`alarm.sensitivity`, `alarm.system`. Notably there is **no** `alarm.highFlow.*`, even though the
APK names a `LeakBotHighFlow` task type.

**So a polling integration will miss short events, and no documented endpoint closes that gap.**
Shortening the interval narrows the window without removing it.

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
