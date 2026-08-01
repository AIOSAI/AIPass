// _srt_resolve.mjs — Resolves the @anthropic-ai/sandbox-runtime entry point and,
// in full mode, wraps a command via SandboxManager. Called by sandbox.py, and
// shellable directly by other branches (aipass doctor/setup.sh) for an
// existence-only check — see CLI contract below.
//
// srt is installed globally (npm i -g). ESM resolution walks up from this file's
// directory, never reaching the global node_modules — we must locate npm's
// global root ourselves. Node's own install prefix is NOT always the same as
// npm's global prefix: on Debian/Ubuntu apt layouts and the official node Docker
// images, node ships at /usr/bin (prefix /usr) while npm installs globals under
// /usr/local. A single derived path misses that layout entirely (DPLAN-0279).
// We try several candidates and take the first one that actually exists.
//
// CLI contract:
//   node _srt_resolve.mjs --resolve             Resolve only. Found: entry path
//                                                on stdout, exit 0. Not found:
//                                                tried candidates on stderr,
//                                                exit 1. No config/import needed.
//   node _srt_resolve.mjs <config.json> <cmd>    Resolve + wrap cmd for sandboxed
//                                                execution: bwrap command on
//                                                stdout, exit 0. Any failure
//                                                (resolution or wrap): message on
//                                                stderr, exit 1.

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
