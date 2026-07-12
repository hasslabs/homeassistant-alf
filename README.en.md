# Alf (Länsförsäkringar) - Home Assistant integration

[🇸🇪 Svenska](README.md) | **🇬🇧 English**

> Alf is a Swedish-only product, so the primary README is in Swedish. This is an English translation
> for the wider Home Assistant community and for HACS review.

Reads all your **Alf** device stats (and optionally controls smart plugs) into Home Assistant over
the same `lfhub.net` cloud API the Alf app uses - **without touching the Alf hub**, so the insurance
discount and the 24/7 alarm central stay intact.

Alf is Länsförsäkringar's white-label of Onics/Develco (the *frient* brand). The hub is deliberately
locked (no local API), so this integration talks to the cloud instead. The API was mapped by
reverse-engineering the Android app - see [`docs/api/alf-cloud-api.md`](docs/api/alf-cloud-api.md).

## What you get

- **Binary sensors:** smoke, leak, motion, opening, tamper, and per-device connectivity.
- **Sensors:** temperature, humidity, power, energy, illuminance, battery (% or voltage).
- **Switches** (optional, off by default): smart plug on/off.

Entities are built generically from each device's `features[]`, so new device types appear
automatically. Devices group under their gateway; rooms map to areas.

## Devices & what each entity means

Unknown/less-common signals are exposed as **diagnostic** entities (hidden under "Diagnostic" on the
device page), so nothing is dropped and nothing is mislabelled.

### Smart plug (frient)
- **Plug** - on/off switch (only when device control is enabled).
- **Power** (W) - instantaneous power draw.
- **Energy** (Wh) - cumulative energy used (`total_increasing`).

### Smoke detector (frient)
- **Smoke** - fire/smoke detected.
- **Temperature** (°C).

### Water leak detector (frient)
- **Leak** - moisture/flood detected at the sensor.
- **Temperature** (°C).

### LeakBot (clamped on the incoming water pipe)
LeakBot doesn't sit *in* water like a normal leak puck. It clamps onto the **cold** incoming pipe
just after the main stop tap and senses **temperature** (its "Thermi-Q" method): whenever water flows
it cools the pipe, and a hidden leak makes water trickle continuously, so the pipe stays cold in a
tell-tale pattern. From that it derives these signals:

| Entity | Can show | Normally | What it means / if it flips |
|---|---|---|---|
| **Leak** | `Detected` / `Clear` | **Clear** | LeakBot's overall leak verdict. `Detected` = it believes water is leaking on the supply. **This is the one to build automations/alerts on.** |
| **High water flow** | `Off` / `On` | **Off** | Raw diagnostic bit. `On` = water has flowed steadily longer than normal use explains (possible leak). Inferred, unverified - don't build alerts on it. |
| **Hot pipe** | `Off` / `On` | **Off** | Raw diagnostic bit. `On` = the clamped pipe is too warm to sense leaks reliably (likely the wrong pipe). Inferred, unverified. |
| **Detached from pipe** | `Off` / `On` | **Off** | Raw diagnostic bit, **unreliable** - some correctly-attached units still report `On`. Therefore **disabled by default**. Don't rely on it to tell whether the clamp came off. |
| **Problem** | `OK` / `Problem` | **OK** | The device's own hardware health. `Problem` = a device fault (needs attention). |
| **Connectivity** | `Connected` / `Disconnected` | **Connected** | `Disconnected` = the device is offline (battery, range, or hub down). |

**A healthy LeakBot reads:** Leak = `Clear`, Problem = `OK`, Connectivity = `Connected`.

High water flow / Hot pipe / Detached are **raw, inferred diagnostic bits** (not verified fault signals),
shown as plain `Off`/`On` sensors under Diagnostic rather than red "Problem". In particular **Detached
from pipe is unreliable** (can read `On` while the clamp is fine) and is disabled by default. **Leak**,
**Problem** and **Connectivity** are the ones to build automations on.

> The meanings of High water flow / Hot pipe / Detached are inferred from LeakBot's Thermi-Q mechanism
> and the API field names, not confirmed. If **Leak** shows `Detected` while everything is dry, check the
> Alf app - it may be a genuine slow-leak warning to investigate.

### Gateway (Develco) and batteries
- **Connectivity** - the hub is online. (Its internal `mode`/`scan` settings are not exposed.)
- Battery devices expose a **Battery** (%) or **Battery voltage** (V) diagnostic sensor.

## Authentication (BankID QR, then headless)

Login is BankID. When you add the integration, Home Assistant shows a **BankID QR code** - scan it in
the BankID app ("Scan QR code") and approve. No token pasting. The backend is Keycloak OIDC: the
access token lasts 5 days and the refresh token lasts 30 days and **rotates on every refresh**, so
after that single login the integration runs headless indefinitely. The rotated refresh token is
persisted automatically; if the session ever expires, Home Assistant prompts you to log in with
BankID again (reauth).

## The client secret

The Android client is confidential, so refreshing tokens needs a static `client_secret`. It is a
**non-personal app secret** - identical for every Alf install and also extractable from the APK - so
it is **embedded in the integration** (`custom_components/alf/const.py`). It is useless on its own:
every session still requires your own BankID login. Nothing to configure.

## Install via HACS (recommended)

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hasslabs&repository=homeassistant-alf&category=integration)

1. HACS -> the three-dot menu -> **Custom repositories** -> add
   `https://github.com/hasslabs/homeassistant-alf`, category **Integration** (or click the badge).
2. Install **Alf**, then restart Home Assistant.
3. Settings -> Devices & Services -> Add Integration -> **Alf**, and **scan the BankID QR**.

## Install (manual)

1. Copy `custom_components/alf/` into your HA `config/custom_components/`.
2. Restart Home Assistant.
3. Settings -> Devices & Services -> Add Integration -> **Alf**. A BankID QR code appears - scan it in
   the BankID app ("Scan QR code") and approve. Tick "Enable device control" on the last step if you
   want plug switches.
4. Control can also be toggled later via Integration -> Configure.

## Not for life-safety timing

Home Assistant polls the cloud (~45 s), so leak/smoke changes here lag slightly. The Alf alarm central
remains the real-time safety path; this integration is for visibility, history, and automation.

## Development

- `alfcloud/` is a standalone, unit-tested async client (auth refresh + rotation, homes/devices,
  control). Run `python -m pytest`. It is **vendored** into `custom_components/alf/alfcloud/` for
  shipping - re-copy after changes: `Copy-Item alfcloud/*.py custom_components/alf/alfcloud/`.
- Recon toolkit, spec, and plans live under `recon/` and `docs/`.

## Legal

Unofficial, personal-use interoperability with your own Alf account. The API is not public and can
change without notice. No personal credentials are committed - only the app's non-personal
`client_secret` (see above).
