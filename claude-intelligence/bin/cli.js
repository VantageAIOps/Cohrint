#!/usr/bin/env node
'use strict';
/**
 * @cohrint/claude-code CLI
 *
 * Usage:
 *   npx @cohrint/claude-code setup   — install Stop hook into ~/.claude/
 *   npx @cohrint/claude-code status  — check if hook is installed
 */

const { existsSync, mkdirSync, readFileSync, writeFileSync, copyFileSync } = require('node:fs');
const { join, dirname } = require('node:path');
const { homedir } = require('node:os');

const HOOK_SRC = join(__dirname, '..', 'hooks', 'cohrint-track.js');

function setup() {
  const home = homedir();
  const claudeDir = join(home, '.claude');
  const hooksDir = join(claudeDir, 'hooks');
  const settingsPath = join(claudeDir, 'settings.json');
  const destHook = join(hooksDir, 'cohrint-track.js');

  if (!existsSync(claudeDir)) {
    console.error('✗ ~/.claude/ not found. Install Claude Code first: https://claude.ai/code');
    process.exit(1);
  }
  console.log('✓ Found ~/.claude/');

  if (!existsSync(hooksDir)) {
    mkdirSync(hooksDir, { recursive: true });
    console.log('✓ Created ~/.claude/hooks/');
  } else {
    console.log('✓ ~/.claude/hooks/ exists');
  }

  copyFileSync(HOOK_SRC, destHook);
  console.log(`✓ Installed cohrint-track.js → ${destHook}`);

  let settings = {};
  if (existsSync(settingsPath)) {
    try { settings = JSON.parse(readFileSync(settingsPath, 'utf-8')); } catch { /* start fresh */ }
  }

  const hookEntry = {
    matcher: '*',
    hooks: [{ type: 'command', command: `node ${destHook}` }],
  };

  if (!Array.isArray(settings.hooks)) settings.hooks = [];
  const alreadyInstalled = settings.hooks.some(
    (h) => typeof h === 'object' && h !== null &&
      JSON.stringify(h.hooks || '').includes('cohrint-track.js')
  );

  if (!alreadyInstalled) {
    settings.hooks.push(hookEntry);
    writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
    console.log('✓ Patched ~/.claude/settings.json with Stop hook');
  } else {
    console.log('✓ Stop hook already present — skipped');
  }

  console.log('\nSetup complete! Costs tracked automatically after each Claude Code session.\n');
  console.log('Add your API key to your shell profile:');
  console.log('  export COHRINT_API_KEY=crt_...\n');
  console.log('Get your free key: https://cohrint.com/signup.html\n');
  console.log('Optional env vars:');
  console.log('  COHRINT_TEAM=<team>       — tag events with a team name');
  console.log('  COHRINT_PROJECT=<project> — tag events with a project name');
}

function status() {
  const destHook = join(homedir(), '.claude', 'hooks', 'cohrint-track.js');
  const settingsPath = join(homedir(), '.claude', 'settings.json');

  const hookInstalled = existsSync(destHook);
  let hookInSettings = false;
  if (existsSync(settingsPath)) {
    try {
      const settings = JSON.parse(readFileSync(settingsPath, 'utf-8'));
      hookInSettings = Array.isArray(settings.hooks) &&
        settings.hooks.some((h) => JSON.stringify(h).includes('cohrint-track.js'));
    } catch { /* ignore */ }
  }

  console.log(`Hook file:     ${hookInstalled ? '✓ installed' : '✗ not found'} (${destHook})`);
  console.log(`settings.json: ${hookInSettings ? '✓ registered' : '✗ not registered'}`);
  console.log(`API key:       ${process.env.COHRINT_API_KEY ? '✓ set' : '✗ COHRINT_API_KEY not set'}`);

  if (hookInstalled && hookInSettings && process.env.COHRINT_API_KEY) {
    console.log('\nStatus: ACTIVE — all systems go.');
  } else {
    console.log('\nStatus: INCOMPLETE — run: npx @cohrint/claude-code setup');
  }
}

const cmd = process.argv[2];
const isPostinstall = process.argv.includes('--postinstall');

if (isPostinstall) {
  // Silent post-install: just print a helpful hint, don't auto-setup
  if (!existsSync(join(homedir(), '.claude', 'hooks', 'cohrint-track.js'))) {
    console.log('\n[cohrint] Run `npx @cohrint/claude-code setup` to enable Claude Code cost tracking.\n');
  }
} else if (cmd === 'setup') {
  setup();
} else if (cmd === 'status') {
  status();
} else {
  console.log('Usage:');
  console.log('  npx @cohrint/claude-code setup   — install Stop hook');
  console.log('  npx @cohrint/claude-code status  — check installation status');
  console.log('\nDocs: https://cohrint.com/docs.html');
}
