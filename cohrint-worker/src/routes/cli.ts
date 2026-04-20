import { Hono } from 'hono';
import { Bindings, Variables } from '../types';

// Latest cohrint-cli version that ships to end users. Bump this when a new
// release is cut so installed CLIs see the update banner on next launch.
const LATEST_CLI_VERSION = '2.2.5';

// CLIs below this version are refused service at startup — used for forced
// upgrades when a release contains a security-critical fix. Leave equal to
// LATEST_CLI_VERSION or older; never ahead of it.
const MIN_SUPPORTED_CLI_VERSION = '2.0.0';

const INSTALL_CMD = 'npm install -g cohrint-cli';
const CHANGELOG_URL = 'https://github.com/VantageAIOps/VantageAI/releases';

const cli = new Hono<{ Bindings: Bindings; Variables: Variables }>();

// Public endpoint — no auth required. Accepts an optional Bearer token so
// we can layer per-plan or per-user notices later without breaking clients
// that haven't finished setup yet.
cli.get('/latest', (c) => {
  return c.json({
    version: LATEST_CLI_VERSION,
    min_supported_version: MIN_SUPPORTED_CLI_VERSION,
    install_cmd: INSTALL_CMD,
    changelog_url: CHANGELOG_URL,
    notice: null as string | null,
  });
});

export { cli };
