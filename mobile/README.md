# Inventory Voice Assistant — mobile client

A single-screen Expo app: tap Connect, it fetches a LiveKit token from
`backend/speech`'s `api.py`, joins the room (mic + camera), and the
`inventory-assistant` voice agent is dispatched in automatically.

**This was hand-written in a sandbox with no npm, no Xcode/Android Studio,
and no simulator/device — it has not been built or run yet.** Everything
below needs to happen on your own machine.

## 1. Point it at your backend

Edit `src/config.ts` and set `API_BASE_URL` to wherever `backend/speech/api.py`
is actually reachable from your phone:
- Running `api.py` on your own machine, phone on the same Wi-Fi: use that
  machine's LAN IP, e.g. `http://192.168.1.23:8001`.
- Exposing a remote/sandbox's port 8001 via a tunnel (e.g. `ngrok http 8001`):
  use the tunnel's `https://...` URL.
- `localhost` will **not** work from a physical device.

Also make sure `backend/speech/agent.py` (the voice worker) and `api.py` are
both running and reachable the same way.

## 2. Install and align versions

```bash
cd backend/speech/mobile
npm install
npx expo install --fix   # reconciles versions against your installed Expo CLI/SDK
```

## 3. Build (required — this app can't run in plain Expo Go)

LiveKit's React Native SDK uses a native WebRTC module (`@livekit/react-native-webrtc`),
which plain Expo Go does not include. There's no way around a real native
build for this app, so pick one:

### Option A — EAS Build (recommended, no local Android/iOS SDK needed)

Builds the native app in Expo's cloud; you just download and install the
result.

```bash
npx eas-cli login              # free Expo account (sign up at expo.dev if needed)
npx eas-cli build:configure     # links this project to your Expo account
npm run build:android:preview   # or: npx eas build --platform android --profile preview
```
When it finishes, EAS gives you a download link (and a QR code) for the built
`.apk` — download it to your phone and install it directly (you'll need to
allow "install from unknown sources" the first time).

### Option B — local build (`expo prebuild` + `expo run:android`/`run:ios`)

Needs Xcode (iOS) or a local Android SDK + `adb` (Android) installed on your
machine first:

```bash
npx expo prebuild
npx expo run:ios       # needs Xcode
npx expo run:android   # needs Android SDK + a device/emulator connected via adb
```

## 4. Use it

Launch the app, grant microphone and camera permissions when prompted, tap
**Connect**, and talk to the assistant. Try:
- "How much Coca-Cola do we have?"
- Hold a product up to the camera and ask "what am I holding?"
- "I sold 2 Snickers bars"
