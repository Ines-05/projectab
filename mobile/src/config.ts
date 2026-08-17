// Point this at wherever speech/api.py (the token endpoint) is actually
// reachable from your phone. Currently set to localhost + `adb reverse
// tcp:8001 tcp:8001`, which tunnels the phone's localhost:8001 to this
// machine over the USB cable - phone must stay connected via USB, and
// `adb reverse` must be re-run each time the device reconnects (it doesn't
// persist across USB disconnects).
//
// Alternatives if you want it working over Wi-Fi instead (no USB tether):
// - Same Wi-Fi network: use this machine's LAN IP, e.g. "http://192.168.1.23:8001"
// - Remote/tunnel: expose port 8001 (e.g. `ngrok http 8001`), use the
//     tunnel's https URL, e.g. "https://xxxx.ngrok.app"
export const API_BASE_URL = 'http://localhost:8001';
