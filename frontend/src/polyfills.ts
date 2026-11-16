import { Buffer } from "buffer";

// @ton/core reads Node's Buffer during browser-module initialization. Install
// the browser-compatible polyfill before App imports any TON escrow modules.
if (!("Buffer" in globalThis)) {
  Object.assign(globalThis, { Buffer });
}
