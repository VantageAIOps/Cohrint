import { Hono } from 'hono';
import { Bindings, Variables } from '../types';

// Per-client release metadata. The CLI sends `?client=node` (default when
// absent, for backward compatibility) or `?client=python`. The worker picks
// the matching row and returns it — this lets us ship a single endpoint
// across both CLIs during the migration and independently bump each one.
//
// Bump `version` when a new release is cut; raise `minSupported` only for
// security-critical forced upgrades — never above `version`.
type ClientRelease = {
  version: string;
  minSupported: string;
  installCmd: string;
};

const RELEASES: Record<'node' | 'python', ClientRelease> = {
  node: {
    version: '2.2.5',
    minSupported: '2.0.0',
    installCmd: 'npm install -g cohrint-cli',
  },
  python: {
    version: '0.2.8',
    minSupported: '0.2.0',
    installCmd: 'pip install --upgrade cohrint-agent',
  },
};

const CHANGELOG_URL = 'https://github.com/VantageAIOps/VantageAI/releases';

const cli = new Hono<{ Bindings: Bindings; Variables: Variables }>();

// Public endpoint — no auth required. An optional Bearer token is accepted
// for future per-plan notices. The `client` query param selects the release
// row; unknown values fall back to `node` so legacy callers keep working.
cli.get('/latest', (c) => {
  const clientParam = (c.req.query('client') || '').toLowerCase();
  const key: 'node' | 'python' = clientParam === 'python' ? 'python' : 'node';
  const release = RELEASES[key];
  return c.json({
    version: release.version,
    min_supported_version: release.minSupported,
    install_cmd: release.installCmd,
    changelog_url: CHANGELOG_URL,
    notice: null as string | null,
    client: key,
  });
});

export { cli };
