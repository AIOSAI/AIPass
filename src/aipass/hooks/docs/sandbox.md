[<- Back to the README](../README.md)

# The kernel sandbox (srt/bwrap)

**Branch** hooks · **Code** `apps/modules/sandbox.py`

---

## Kernel Sandbox (srt/bwrap)

The sandbox module (`apps/modules/sandbox.py`) provides the kernel-level filesystem boundary for agent sessions. It wraps Anthropic's `@anthropic-ai/sandbox-runtime` (srt) library, which uses bubblewrap (bwrap) + Landlock + seccomp on Linux to enforce write/read restrictions at the OS level.

## Key Functions

| Function | What it does |
|---|---|
| `build_policy(branch_path)` | Generates per-role writable/RO map from branch passport |
| `sandbox_launch(command, *, cwd=None, policy, env=None)` | Resolves bwrap command via srt, spawns sandboxed process |
| `resolve_bwrap_command(...)` | Resolves the bwrap argv without spawning — what external callers actually consume |
| `build_srt_config(policy)` | Converts policy dict to srt config format |

## Policy Rules

- **Every agent**: own branch tree + the system temp dir (`tempfile.gettempdir()`, plus `$TMPDIR` when it differs) + shared channels (system_logs, .ai_central, memory_pool, AIPASS_REGISTRY.json, flow_json) + sibling `.ai_mail.local/` and `DASHBOARD.local.json` carve-ins + its **own** `~/.claude/projects/<encoded-cwd>/` (added only if that directory already exists — not the whole `projects/` tree)
- **devpulse only**: .git writable (the only committer)
- **All other agents**: .git read-only, sibling source trees read-only
- **Deny**: broker_secret (deny_read + deny_write for all roles)

Bind-mount, not isolation: the sandbox preserves the shared live filesystem. Reads stay open everywhere. Only writes to protected paths are blocked at the kernel level (EROFS).

## Architecture

The Node helper (`_srt_resolve.mjs`) resolves the globally-installed srt library via `process.execPath` (ESM resolution doesn't walk to global node_modules). The resolver runs with CWD set to `/var/tmp` to prevent srt's mandatory-deny mask files from polluting the branch directory.

@ai_mail's `dispatch_monitor` wires the launch seam with `build_policy` + `build_srt_config` +
`resolve_bwrap_command` — **not** `sandbox_launch`, which this section previously claimed. Corrected
2026-08-13 against `ai_mail/apps/handlers/dispatch/dispatch_monitor.py:69`, whose call order is pinned
by `ai_mail/tests/test_dispatch_monitor.py:1759`. An earlier claim here that the @drone broker
validates sandbox policy before agent launch could not be substantiated — the broker is a privileged
delete daemon and no policy validation was found in its tree — so it has been removed rather than
restated.

---

## Related

- [edit_gate.md](edit_gate.md) — the in-process fence the kernel boundary sits under
