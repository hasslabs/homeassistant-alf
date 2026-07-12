# Frida SSL unpinning

Only needed if the Alf app still fails to decrypt through mitmproxy after the system CA is
installed (i.e. the app pins certificates).

## Setup

1. **Desktop:** `pip install frida-tools` and note the version (`frida --version`).
2. **Phone (rooted):** download the matching `frida-server` for **arm64** from the Frida releases,
   push it, and run it as root:

   ```bash
   # in Termux as root, or via adb
   ./frida-server-<version>-android-arm64 &
   ```

3. **Find the Alf package id** (Checkpoint 0): `pm list packages | grep -i alf`.

## Run

```powershell
frida -U -f se.lf.alf -l frida/ssl-unpinning.js
```

`-U` = USB (or Tailscale-forwarded) device, `-f` = spawn the app fresh so hooks are in place before
the first TLS handshake.

## If the bundled script isn't enough

`ssl-unpinning.js` here is a compact fallback covering the common vectors. If the app uses a less
common pinning implementation, swap in the maintained community script:

- httptoolkit - <https://github.com/httptoolkit/frida-interception-and-unpinning>
  (`android-certificate-unpinning.js`)

Drop the maintained file in place of `ssl-unpinning.js` and re-run.
