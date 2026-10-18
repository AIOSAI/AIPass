// _srt_resolve.mjs — Resolves the @anthropic-ai/sandbox-runtime entry point and,
// in full mode, wraps a command via SandboxManager (sandbox.py; doctor/setup.sh shell --resolve).
// srt is global and ESM never walks to npm's global root, which on apt/Docker layouts is not
// node's own prefix: so several candidates are tried, first existing wins.
// --resolve: entry path on stdout, exit 0; not found: tried paths on stderr, exit 1.
// <config.json> <cmd>: bwrap command on stdout, exit 0; any failure on stderr, exit 1.

import { existsSync, readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';

const PKG_RELATIVE_ENTRY = '@anthropic-ai/sandbox-runtime/dist/index.js';

function npmGlobalRoot() {
  try {
    const root = execFileSync('npm', ['root', '-g'], { encoding: 'utf-8', timeout: 5000 }).trim();
    return root || null;
  } catch {
    return null;
  }
}

function candidateNodeModulesDirs() {
  const dirs = [];

  const envPrefix = process.env.npm_config_prefix || process.env.NPM_CONFIG_PREFIX;
  if (envPrefix) dirs.push(join(envPrefix, 'lib', 'node_modules'));

  const npmRoot = npmGlobalRoot();
  if (npmRoot) dirs.push(npmRoot);

  dirs.push('/usr/local/lib/node_modules', '/usr/lib/node_modules');
  dirs.push(join(dirname(dirname(process.execPath)), 'lib', 'node_modules'));

  return dirs;
}

function resolveSrtEntry() {
  const tried = [];
  for (const dir of candidateNodeModulesDirs()) {
    const entry = join(dir, PKG_RELATIVE_ENTRY);
    tried.push(entry);
    if (existsSync(entry)) {
      return entry;
    }
  }
  const err = new Error(`srt not resolvable — tried:\n${tried.join('\n')}`);
  err.tried = tried;
  throw err;
}

async function main() {
  if (process.argv[2] === '--resolve') {
    process.stdout.write(resolveSrtEntry() + '\n');
    return;
  }

  const configPath = process.argv[2];
  const command = process.argv[3];

  if (!configPath || !command) {
    process.stderr.write('usage: _srt_resolve.mjs --resolve | _srt_resolve.mjs <config.json> <command>\n');
    process.exit(1);
  }

  const entry = resolveSrtEntry();
  const { SandboxManager } = await import(pathToFileURL(entry).href);

  const config = JSON.parse(readFileSync(configPath, 'utf-8'));
  await SandboxManager.initialize(config);
  const wrapped = await SandboxManager.wrapWithSandbox(command, '/bin/bash', config);
  process.stdout.write(wrapped);
  await SandboxManager.reset();
}

main().catch((err) => {
  process.stderr.write(`srt-resolve error: ${err.message}\n`);
  process.exit(1);
});
