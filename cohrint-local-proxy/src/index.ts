// Proxy server
export { startProxyServer } from "./proxy-server.js";
export type { LocalProxyConfig } from "./proxy-server.js";

// Session persistence
export { SessionStore, DEFAULT_SESSIONS_DIR } from "./session-store.js";
export type { ProxySessionRecord, PersistedEvent } from "./session-store.js";

// Privacy engine
export { sanitizeEvent, hashText, assertNoSensitiveData } from "./privacy.js";
export type { PrivacyLevel, PrivacyConfig, SanitizedEvent } from "./privacy.js";

// Pricing engine
export { calculateCost, findCheapest, PRICES } from "./pricing.js";

// Local file scanners (Layer 2)
export {
  scanAll,
  ALL_SCANNERS,
  getScannerByName,
  claudeCodeScanner,
  codexScanner,
  geminiScanner,
  cursorScanner,
  rooCodeScanner,
  openCodeScanner,
  ampScanner,
} from "./scanners/index.js";

export type {
  ScannerPlugin,
  ScanOptions,
  ScanResult,
  ScanTotals,
  ToolSummary,
  ScanError,
  ToolSession,
  ParsedMessage,
  ToolName,
} from "./scanners/types.js";

export type { FullScanOptions } from "./scanners/index.js";
