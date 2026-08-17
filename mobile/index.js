// Hermes (Android's JS engine) has no built-in TextEncoder/TextDecoder.
// Something in LiveKit's dependency chain touches it at module-load time,
// crashing the app before it even renders - this polyfill must load before
// anything else, including the @livekit/react-native import below (multiple
// static imports run top-to-bottom in file order, so this being first
// guarantees it executes first).
import 'fast-text-encoding';

import { registerGlobals } from '@livekit/react-native';

// Must run before any other LiveKit/WebRTC code loads. Using require() here
// instead of a static import is deliberate: static imports (including
// `import App from './App'`) get hoisted above other statements by Babel's
// CommonJS transform, so a static import of App - which pulls in
// AudioSession/LiveKitRoom from @livekit/react-native - would actually
// evaluate before this call, not after, and crash on launch before WebRTC
// globals exist. require() executes in place, so this ordering is real.
registerGlobals();

const { registerRootComponent } = require('expo');
const App = require('./App').default;

registerRootComponent(App);
