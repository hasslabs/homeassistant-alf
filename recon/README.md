# Alf recon - capture runbook

Goal: capture the Alf app's cloud traffic on the **rooted OnePlus 6**, redact every secret, and
produce a documented API contract in [`../docs/api/alf-cloud-api.md`](../docs/api/alf-cloud-api.md).

> **Safety rule:** only redacted files in `recon/fixtures/` are ever committed. `recon/raw/` is
> git-ignored and stays on this machine. Never `git add` a raw capture.

## Checkpoint 0 - app runs on the capture device (CONFIRMED)

Verified 2026-07-11 over SSH: the OnePlus 6 (A6003) runs Android 14 (SDK 34), arm64-v8a, and the
Alf app is already installed as package `se.lf.alf`. Checkpoint 0 passes - no emulator fallback
needed. Use `se.lf.alf` as the package id and an arm64 frida-server in the steps below.

## 1. Start mitmproxy on the desktop

```powershell
# from the repo root, with the [capture] extra installed:
.\.venv\Scripts\python.exe -m pip install -e ".[capture]"
.\.venv\Scripts\python.exe -m mitmproxy -s recon/capture_addon.py --listen-port 8080
```

Note the desktop's LAN IP (`ipconfig`).

## 2. Point the OnePlus at the proxy

Wi-Fi settings → your network → advanced → Proxy = **Manual**, host = `<desktop-ip>`, port `8080`.

## 3. Install the mitmproxy CA as a *system* cert

On Android 7+ apps ignore user-added CAs, so the cert must go in the system store:

1. On the phone browse to `http://mitm.it` and download the **Android** certificate.
2. Promote it to the system store - easiest with the Magisk module **"Always Trust User Certs"**
   (or "MagiskTrustUserCerts"). Install the module, reboot.
   - Manual alternative (Termux as root): copy the cert into `/system/etc/security/cacerts/`
     named `<subject_hash_old>.0`, `chmod 644`, reboot.

After this, plain TLS should decrypt in mitmproxy for apps that don't pin.

## 4. Start Frida unpinning (only if TLS still fails)

If the Alf app pins beyond the system store, decryption fails until you unpin:

1. Push a `frida-server` (arm64) whose version matches the desktop `frida-tools`
   (`pip install frida-tools`), run it as root on the phone.
2. From the desktop:

```powershell
frida -U -f se.lf.alf -l frida/ssl-unpinning.js
```

See [`../frida/README.md`](../frida/README.md) for details.

## 5. Log in with "BankID on another device"

Start login in the Alf app on the OnePlus, choose **"BankID på annan enhet"**, and approve in the
BankID app on your ordinary phone. This avoids BankID refusing to run on the rooted device.

**While logging in, watch the login/token exchange in mitmproxy** and record in the API doc:
what token(s) come back, their apparent TTL, whether a refresh token is issued, and whether a
device-registration/attestation call happens. This token lifecycle is the single most important
finding (spec §5).

## 6. Walk every screen and trigger devices

Open each app view. Trigger one of each device type so its state endpoint fires: open a
Magnetsensor, lift a water detector, toggle a Smart Plug. Each captured exchange is written to
`recon/raw/NNNN_METHOD_path.json`.

## 7. Redact - before anything is committed

This rewrites every raw record into a redacted fixture using `recon/redact.py`:

```powershell
.\.venv\Scripts\python.exe -m recon.redact recon/raw recon/fixtures
```

Then **eyeball a few fixtures** and confirm no token / personnummer / cookie remains before you
`git add recon/fixtures`.

## 8. Summarize the endpoints

```powershell
.\.venv\Scripts\python.exe -m recon.summarize recon/fixtures
```

Paste the table into `docs/api/alf-cloud-api.md`, fill in the auth/token and per-device JSON
sections, and that document becomes the input for Plan 2 (`alfcloud` + the HA integration).
