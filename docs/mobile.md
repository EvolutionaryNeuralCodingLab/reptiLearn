# Mobile app (Android)

ReptiLearn’s control UI can run as an Android app via [Capacitor](https://capacitorjs.com/). The app is a thin shell around the same React UI; it still talks to a lab machine running the Python server. There is **no authentication** — use a VPN and/or SSH tunnel, as with the browser UI.

## Requirements

- Node.js **18+** (20 LTS recommended). If you use nvm: `nvm install 20 && nvm use 20`
- Android Studio (to build/install an APK), or a device with USB debugging
- A reachable ReptiLearn server (VPN, LAN IP, or SSH local forward to port 3500)

## Build and install

From the repository root:

```bash
cd ui
npm install
npm run build:mobile
npm run open:android
```

In Android Studio, run the app on a device or emulator, or use **Build → Build Bundle(s) / APK(s)**.

Scripts:

| Script | Purpose |
|--------|---------|
| `npm run build:mobile` | Production web build + `cap sync android` |
| `npm run sync:android` | Sync web assets into the Android project only |
| `npm run open:android` | Open the project in Android Studio |

## First launch — set the server URL

On first open the app shows **Waiting for connection** with connection settings.

Enter the URL of your ReptiLearn host, for example:

- SSH tunnel on the phone (Termux): `http://127.0.0.1:3500`
- VPN / LAN: `http://192.168.x.x:3500`

Tap **Connect**. You can change this later from the ReptiLearn menu → **Connection…**, or via the status indicator on the phone top bar.

Cleartext HTTP is enabled so local tunnels and typical lab setups work without TLS.

## Phone layout

On narrow screens the UI switches to bottom tabs:

- **Main** — session / arena / video / schedule / analysis / mic controls, live streams, and status (`StateView`)
- **Control** — experiment run/stop and the log

Wider screens keep the existing desktop split-pane layout. The same phone layout also appears if you open the web UI in a mobile browser.

## Microphone (voice)

The Android app needs `RECORD_AUDIO` and `MODIFY_AUDIO_SETTINGS` (already declared in `android/app/src/main/AndroidManifest.xml`). After installing a build that includes those permissions, tap the mic control once and **Allow** when Android prompts. If you denied it earlier: phone **Settings → Apps → ReptiLearn → Permissions → Microphone → Allow**.

## Remote access reminder

From [Getting started](getting_started.md): ReptiLearn has no user authentication. Prefer SSH tunnels and/or a VPN. Do not expose port 3500 to the public internet.
