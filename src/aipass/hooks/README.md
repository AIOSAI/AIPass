[← Back to AIPass](../../../README.md)

# Hooks

> Hook infrastructure for AIPass. A single dispatch engine routes hook events across platforms (Claude Code, Codex) with per-project configuration, full logging, and crash isolation.

Every hook event flows through one engine. Platform bridges normalize the event format, the engine reads per-project config (`.aipass/hooks.json`), dispatches matching handlers, and logs everything to JSONL diagnostics.

## Quick Start

```bash
drone @hooks status              # Show hook config for current project
drone @hooks log                 # Tail recent hook activity
drone @hooks engine              # Show connected handlers
drone @hooks verify              # Cross-check provider ↔ project wiring
drone @hooks --help              # Full help reference
```

## Start here

| You want to | Read |
|---|---|
| Identity, session history | [`.trinity/`](.trinity/) |
| Hook engine design | `DPLAN-0184` |
| Per-project config | `.aipass/hooks.json` |

## Commands

| Command | What it does |
|---|---|
| `drone @hooks` | Show branch structure (auto-discovered modules) |
| `drone @hooks status` | Show hook config for current project |
| `drone @hooks engine` | Show connected handlers |
| `drone @hooks log` | Tail recent hook activity (last 20 JSONL entries) |
| `drone @hooks hooksound` | Show current sound mute status |
| `drone @hooks hooksound off` | Mute all hook sounds |
| `drone @hooks hooksound on` | Unmute all hook sounds |
| `drone @hooks feedback` | Show feedback pulse status (enabled/disabled) |
| `drone @hooks feedback off` | Disable feedback pulse for this project |
| `drone @hooks feedback on` | Enable feedback pulse for this project |
| `drone @hooks dismiss <alert-id>` | Remove an alert from `.aipass/alerts.json` |
| `drone @hooks cadence` | Show prompt injection cadence config and state |
| `drone @hooks diagnostics_state` | Show recorded post-edit diagnostics and re-check them live |
| `drone @hooks sessions` | List live Claude Code sessions (PIDs) |
| `drone @hooks sessions reclaim [@branch]` | Stop sessions cleanly — clean slate |
| `drone @hooks presence` | Show branch presence claims |
| `drone @hooks context_window` | Show transcript fill vs the compact window |
| `drone @hooks sandbox` | Show kernel sandbox (srt/bwrap) status |
| `drone @hooks test [--verbose]` | Run the portable hook test runner |
| `drone @hooks verify` | Cross-check provider settings vs project hook config (exits non-zero on ERROR findings) |
| `drone @hooks --help` | Full help reference |
| `drone @hooks --version` | Version info |

## Two-Tier Hook Model

Hooks operate on two tiers:

**Tier 1 — Provider Settings (wiring).** Claude Code's `~/.claude/settings.json` (or project `.claude/settings.json`) defines hook entries that point to the bridge (`claude.py`). These are installed by `setup.sh` / `doctor` — they're pure wiring. Wiring comes in two shapes. Five events use **one fan-out entry** that dispatches every enabled handler for that event: PreToolUse, PostToolUse, SubagentStop, Stop, Notification. Three events are wired **per handler** (`claude.py EventType:hook_name`, one entry each): UserPromptSubmit (13 entries), PreCompact (8 — four handlers × `manual`/`auto`), SessionStart (1). The per-handler form exists for two reasons: a single fan-out entry concatenates every handler's stdout into one blob, which buries prompt injection past Claude Code's inline preview; and per-entry wiring gives each handler its own timeout budget (in the current manifest, UserPromptSubmit runs at 90s except `auto_process` at 120s; PreCompact runs 60s/120s/120s/30s; SessionStart 30s). Provider settings cannot be changed by branches — only setup tooling manages them.

**Tier 2 — Project Config (control).** Each project's `.aipass/hooks.json` controls which hooks fire for that project. Created by `aipass init`. Edit `enabled` flags to turn hooks on/off per project. Use `drone @hooks status` to view current config.

**Why provider-only wiring?** Claude Code does not fire `PreToolUse`/`PostToolUse` hooks from project-level settings — only from user-level settings (DPLAN-0160 platform limitation). So all hook entries live in provider settings, and per-project control happens through `.aipass/hooks.json`.

**Deploying new handlers:** whether `.aipass/hooks.json` alone is enough depends on which shape the event uses.

| New handler on | Provider change needed |
|---|---|
| PreToolUse, PostToolUse, SubagentStop, Stop, Notification | **None** — the fan-out entry already dispatches it |
| UserPromptSubmit, SessionStart | **One** new entry: `claude.py <Event>:<hook_name>` |
| PreCompact | **Two** new entries — one `matcher: manual`, one `matcher: auto` |

Provider settings are human-gated (`git_gate.py` `TRUSTED_HOOK_EDITORS`), so when an entry is needed, email @devpulse to wire it. Without it the engine never receives the event and the handler never fires — and the suite cannot see the gap, so verify with firing evidence in `engine.jsonl`.

**Keeping the manifest and live settings in sync:** `.claude/provider_manifest.json` (repo root, self-editable by @hooks) is the source of truth; `~/.claude/settings.json` is the live copy Claude Code actually reads, and only `aipass doctor --fix` (or a trusted editor like @devpulse) can write it. Editing the manifest does NOT apply live — this sync step has silently lapsed before (DPLAN-0278: live drifted a full matcher behind for weeks). Run `aipass doctor` after any manifest edit to see the drift, then ask @devpulse to apply it (or run `aipass doctor --fix` if you're a trusted editor).

## Architecture

```
src/aipass/hooks/
├── .trinity/                    # Identity & memory
├── apps/
│   ├── hooks.py                 # Entry point (drone @hooks)
│   ├── sound.py                 # Shared sound utilities (speak, play, mute)
│   ├── modules/
│   │   ├── cadence.py           # Prompt injection cadence (every-Nth-turn gating)
│   │   ├── context_window.py    # Transcript usage reader + per-branch compact-window resolver
│   │   ├── diagnostics_state.py # What .diagnostics_state.json means — shared by auto_fix + edit_gate
│   │   ├── hook_test.py         # Portable test runner (drone @hooks test)
│   │   ├── cc_sessions.py       # CC-native session file reader (~/.claude/sessions/<pid>.json)
│   │   ├── cc_transcripts.py    # CC-native transcript reader (~/.claude/projects/<cwd>/<sessionId>.jsonl)
│   │   ├── engine.py            # Core dispatch — routes events to handlers
│   │   ├── feedback.py          # Feedback pulse toggle (drone @hooks feedback on/off)
│   │   ├── grounding_content.py # Shared kernel/navmap/branch/identity content loaders (DPLAN-0276)
│   │   ├── hooksound.py         # Sound control (drone @hooks hooksound on/off)
│   │   ├── hookstatus.py        # Config viewer (drone @hooks status)
│   │   ├── alert_dismiss.py      # Dismiss alerts (drone @hooks dismiss <id>)
│   │   ├── presence.py          # Branch presence — claim/release/refresh for .ai_central/PRESENCE.central.json
│   │   ├── sandbox.py           # Kernel sandbox — srt/bwrap wrapper + per-role policy generator
│   │   └── wire_verify.py       # Wire verification — provider ↔ project hook wiring checker
│   ├── handlers/
│   │   ├── bridges/             # One per provider (thin normalization)
│   │   │   ├── claude.py        # Claude Code bridge
│   │   │   └── codex.py         # Codex bridge (normalizes stdin/stdout envelope)
│   │   ├── prompt/              # Prompt injection hooks
│   │   │   ├── branch_loader.py #   Injects aipass_local_prompt.md
│   │   │   ├── tier0_kernel.py  #   Injects tier0 kernel prompt (every turn)
│   │   │   ├── navmap.py        #   Injects tier1 navmap prompt (periodic)
│   │   │   ├── identity.py      #   Injects passport identity block
│   │   │   ├── compass_recall.py #  Governance recall injection (capped per session)
│   │   │   ├── feedback_pulse.py #  Periodic feedback ask (~10 turns, toggleable — disabled here)
│   │   │   ├── context_gauge.py #   Nudges /prep before auto-compact fires (80%/95% of window)
│   │   │   ├── temporal.py      #   Injects weekday/date/time/tz/part-of-day, every turn
│   │   │   └── persistent_alert.py # Injects advisory banners from .aipass/alerts.json
│   │   ├── security/            # Enforcement hooks
│   │   │   ├── edit_gate.py     #   Blocks unsafe edits (cross-project, cross-branch, inbox, diagnostics)
│   │   │   ├── git_gate.py      #   Enforces git access tiers
│   │   │   ├── presence_gate.py  #   Single-session gate — blocks duplicate runtimes per branch
│   │   │   ├── registry_gate.py  #   Seals *_REGISTRY.json — blocks raw writes/edits/deletes, redirects to drone @spawn
│   │   │   ├── rm_gate.py       #   Guardrail — catches accidental rm -rf, teaches drone rm
│   │   │   └── subagent_gate.py #   Blocks sub-agent stop until clean
│   │   ├── lifecycle/           # Session management hooks
│   │   │   ├── auto_fix.py      #   Post-edit diagnostics (ruff, pyright, py_compile)
│   │   │   ├── auto_process.py  #   Scheduled inbox/task processing (UserPromptSubmit + PreCompact)
│   │   │   ├── auto_watchdog.py #   Watchdog arming after dispatch (live; retirement pending — see below)
│   │   │   ├── compact.py       #   Pre-compact memory archival
│   │   │   ├── session_boot.py  #   Boot wrapper (main() CLI, not a hook — no handle())
│   │   │   ├── post_compact_regrounding.py # Mid-turn re-ground backstop after compaction (PostToolUse, DPLAN-0276)
│   │   │   ├── pre_compact_prep.py # Mechanical AUTO-COMPACT SNAPSHOT stamp (fill %, git, locks, plans)
│   │   │   ├── rollover.py      #   Pre-compact memory rollover
│   │   │   └── session_start.py #   Cadence reset on new chat / clear (SessionStart)
│   │   └── notification/        # Sound/alert hooks
│   │       ├── announce.py      #   Announcement tone on notification
│   │       ├── email.py         #   Inbox check on prompt
│   │       ├── stop_sound.py    #   Bell on session stop
│   │       ├── telegram_response.py # Telegram reply delivery on Stop
│   │       └── tool_sound.py    #   Announces tool name via TTS
│   ├── handlers/config/         # Config utilities (not hooks — no handle())
│   │   ├── loader.py            #   hooks.json discovery + validation
│   │   ├── trust_registry.py    #   Trusted-project registry (enroll/revoke/hash checks)
│   │   └── diagnostics.py       #   JSONL logging for hook execution
│   ├── handlers/cli/            # CLI utilities (not hooks — no handle())
│   │   └── help_flags.py        #   Help-flag detection — did the caller ask, or instruct?
│   └── handlers/json/           # JSON utilities (not hooks — no handle())
│       └── json_handler.py      #   Auto-creating JSON handler for hooks data files
├── logs/
│   └── engine.jsonl             # JSONL diagnostics (every hook execution)
└── tests/                       # 1711 tests across 50 test files (1709 pass, 2 env-skipped)
```

## How It Works

1. Provider settings invoke the bridge one of two ways: `claude.py <Event>` (one fan-out entry, all enabled handlers — tool events) or `claude.py <Event>:<hook_name>` (one entry per handler — UserPromptSubmit, PreCompact, SessionStart). There is no bare `claude.py UserPromptSubmit` entry; it is 13 named ones.
2. Bridge normalizes stdin, loads project config via `loader.find_project_config()`
3. Bridge calls `engine.dispatch(event_type, stdin_data, config)`
4. Engine runs matching hooks sequentially, logs each to JSONL
5. First hook returning `{"decision": "block"}` with exit code 2 = bail (block the action)
6. Exit code 2 without JSON = crash (log error, continue to next hook)
7. All hook stdout concatenated and returned to platform

## Two Log Streams

Hook execution is recorded twice, at different levels of detail:

| Stream | Contents | Default |
|--------|----------|---------|
| `logs/engine.jsonl` | Every hook — agent, exit code, timing, stderr, cwd. Source of truth for diagnostics. | Always on |
| `system_logs/hooks_engine.log` (prax) | Warnings, errors, blocks, engine lifecycle. Per-hook narration suppressed. | Quiet |

Per-hook narration ran ~3 lines per tool call, which dominated the prax stream and tripped the runaway detector during ordinary multi-agent operation. It is off by default; nothing is lost, since `engine.jsonl` carries strictly more detail.

```bash
AIPASS_HOOKS_VERBOSE_LOG=1    # restore per-hook lines in the prax stream
```

prax's `SystemLogger` exposes only `info`/`warning`/`error`, so there is no DEBUG level to demote to — the switch lives in `engine._log_detail()`. Blocks, crashes, timeouts, and trust-break banners are never suppressed.

## Dynamic Dispatch

Handlers are called **dynamically at runtime** — the engine uses `importlib.import_module()` + `getattr()` on the dotted handler path from `hooks.json` (e.g., `aipass.hooks.apps.handlers.prompt.identity.handle`). Handlers are never statically imported. This means static analysis tools (including seedgo's dead_code checker) cannot see that they are used — the last unshielded run scored `dead_code` at 40% and reported 29 of 49 files unreferenced, which is this indirection and not rot. That measurement is historic and not re-verified here: `apps/` now carries 53 non-`__init__` files, and re-running unshielded needs a bypass-rule change this branch does not make for a doc pass. Shielded, `dead_code` audits 100%.

Every handler is verified wired in `hooks.json` (31 entries, 30 distinct names). Firing evidence is a *narrow* window — `logs/engine.jsonl` keeps 2 generations at ~500 KB, which is minutes to tens of minutes of live traffic, so absence from it is not evidence of a dead wire. In a sampled ~24-minute window, 26 of the 30 names appear. The four absentees are the three PreCompact-only handlers (`pre_compact`, `pre_compact_rollover`, `pre_compact_prep`) and `notification_sound` — none of those events fired in the window. `feedback_pulse` does appear, but as `{"action": "skipped_disabled"}`: it is wired `enabled: false` in this repo, so it is dispatched and declines.

## Event Types

| Event | Hooks | Description |
|---|---|---|
| UserPromptSubmit | presence_gate, persistent_alert, identity, email, branch_loader, tier0_kernel, navmap, compass_recall, feedback_pulse, context_gauge, temporal, auto_process, user_message_relay | Presence gate + alerts + prompt injection + inbox + governance recall + feedback + context gauge + temporal + auto-process + TG mirror |
| PreToolUse | tool_sound, edit_gate, git_gate, rm_gate, registry_gate | Security gates + guardrails + sound |
| PostToolUse | auto_fix, auto_watchdog, post_compact_regrounding | Diagnostics + watchdog + post-compaction re-ground backstop |
| SubagentStop | subagent_gate | Seedgo validation |
| Stop | stop_sound, telegram_response, presence_release | Bell + Telegram delivery + presence release |
| Notification | announce | Announcement tone |
| SessionStart | cadence_reset | Cadence reset on new chat / clear |
| PreCompact | compact, rollover, pre_compact_prep, auto_process | Memory archival + rollover + mechanical snapshot stamp + inbox/task processing |

That table mixes handler filenames with `hooks.json` entry names, because three of the names are not
handler files in this branch. `user_message_relay` belongs to @skills
(`skills/lib/telegram/apps/handlers/user_message_relay.py`) and rides the engine as a guest.
`presence_release` is a hooks.json entry name pointing at `security/presence_gate.py:handle_stop`.
`cadence_reset` is likewise an entry name — the handler file is `lifecycle/session_start.py`.
`feedback_pulse` is wired but `enabled: false` in this repo, so it is listed and does not fire.

Entry name and filename diverge for others too (`pre_edit_gate` → `security/edit_gate.py`,
`tool_use_sound` → `notification/tool_sound.py`, `branch_prompt` → `prompt/branch_loader.py`,
`identity_injector` → `prompt/identity.py`, `email_notification` → `notification/email.py`,
`auto_fix_diagnostics` → `lifecycle/auto_fix.py`, `subagent_stop_gate` → `security/subagent_gate.py`,
`notification_sound` → `notification/announce.py`, `pre_compact` → `lifecycle/compact.py`,
`pre_compact_rollover` → `lifecycle/rollover.py`). **`.claude/provider_manifest.json` keys by the
entry name, not the filename** — `claude.py UserPromptSubmit:branch_prompt`, never `:branch_loader`.
Wire a new per-handler entry with the name as it appears in `hooks.json`.

### auto_watchdog — retirement decided, not yet executed

`auto_watchdog` is **live and enabled** in this repo and fires on every PostToolUse. Its retirement
has been decided (its arming path is owner-only, which makes it a refusal for 17 of 18 citizens), but
it is gated on a Patrick-present ceremony: both `hooks.json` entries set `enabled: false`, then
`aipass trust` re-enrol, then the file rename. Until that runs, the handler stays as documented above.
Do not disable or rename it out-of-band — an un-re-enrolled config edit takes *every* hook dark.

## Git Gate

The `git_gate` handler (`security/git_gate.py`) enforces git access via drone to prevent state conflicts between agents. It is **enabled by default** in every project created by `aipass init`.

**What it blocks:** Raw `git` write commands (push, commit, checkout, merge, etc.) and raw `gh` commands (except `gh api`). Read-only git verbs (status, log, diff, show, blame, grep, etc.) are allowed raw.

**What it protects:** Edits to `.claude/settings.json`, `.claude/hooks/`, and `.git/hooks/` — the enforcement layer itself.

**Disabling for a project:** Set `git_gate.enabled` to `false` in your project's `.aipass/hooks.json`. This disables git enforcement in isolation — all other hooks (edit_gate, rm_gate, prompt injection, etc.) continue to work normally. No sync, rebase, or PR flows depend on git_gate being active; those are handled independently by `drone @git`.

```json
"git_gate": {
    "enabled": false,
    "handler": "aipass.hooks.apps.handlers.security.git_gate.handle",
    "matcher": "Bash|Edit|MultiEdit|Write|NotebookEdit"
}
```

**Why it's on by default:** Agents reflexively reach for raw git, which causes state chaos in a multi-agent system. The gate redirects to `drone @git` which enforces access tiers (read-only for most branches, write-only for devpulse). External users who don't need multi-agent git orchestration can safely disable it.

## Edit Gate — the project boundary

The `edit_gate` handler (`security/edit_gate.py`) fences writes at two levels. Inside one project it enforces the branch boundary (`hooks` cannot write to `drone`; `devpulse`, `seedgo`, `spawn` are trusted cross-writers). Across projects it enforces the project boundary.

A **project root** is the nearest ancestor directory holding a `*_REGISTRY.json` — the same marker `@ai_mail` uses to refuse cross-project mail. The two fences share a definition on purpose: an agent that is refused a send must not be allowed the equivalent write (GH #733).

The project fence is directional, unlike the mail fence:

| Direction | Example | Verdict |
|---|---|---|
| Inside own project | `projects/baud` → `projects/baud/src/...` | allowed |
| Downward (host → hosted) | `src/aipass/devpulse` → `projects/baud/...` | allowed |
| Upward (hosted → host) | `projects/baud` → `src/aipass/drone/...` | **blocked** |
| Sideways (project → sibling) | `projects/baud` → `projects/earmark/...` | **blocked** |

Trust runs downward. Downward writes also have to stay open because the host tree carries artifact registries of its own — `flow/flow_json/PLAN_REGISTRY.json`, `.backup/snapshots/` — which a strict rule would read as foreign projects to the very branches that own them.

Where no project root is resolvable on either side, the gate allows the write: a fence that cannot locate a boundary must not invent one.

### The diagnostics block

After an edit leaves type errors behind, `auto_fix` records them in `.diagnostics_state.json` and `edit_gate` stops you editing *other* files in that branch until they are fixed. Two rules keep that block honest (both reported by @seedgo with a live repro, 2026-08-13):

**The block must be satisfiable.** An error that can only be resolved in another file — `"X" is unknown import symbol`, `Import "Y" could not be resolved` — never blocks edits to other files. Red-first is mandated fleet-wide and the test and the implementation always live in different files, so blocking the resolving edit is unsatisfiable by any allowed action. One locally-fixable error among them keeps the block.

**The block must be live, not remembered.** Before blocking, the gate re-runs pyright on the recorded file. Clean now → the state is dropped and the edit proceeds; still failing → the block quotes the *current* errors, not the recorded ones. Any resolving write the hook never observed (a Bash heredoc, an external editor) used to leave a block behind that outlived the error. If the file cannot be re-checked (pyright missing, timed out), the recorded errors stand — unknown is not clean.

Re-validation is not free, and — measured 2026-08-13, correcting an earlier claim here — the cost is
**not** confined to the blocking path. Of the `pre_edit_gate` invocations over 500ms in a live window,
7 of 8 **allowed** the edit, and 3 of the 4 blocks returned in ~0.1s. Common-path median is 6.8ms; the
slow path runs ~1.35s. So the expensive work is real but is not gated on blocking the way this section
originally described. `drone @hooks diagnostics_state` shows what is recorded and re-checks it live.

Known gap (reported by @seedgo, 2026-08-13, unfixed and escalated): if the recorded file no longer
exists — hard-deleted, renamed to `name(disabled).py`, or moved to `.archive/` — re-validation returns
"unknown" rather than "clean", and the block stands forever, quoting a path with nothing on it. Two of
those three are the house cleanup pattern. Escape: recreate the file clean, let re-validation drop the
state, then remove it.

## Persistent Alerts

The `persistent_alert` handler (`prompt/persistent_alert.py`) injects advisory banners into every prompt when active alerts exist. General-purpose — any agent can raise alerts (prax for runaway logs, trigger for medic, backup for sync failures).

**How it works:** Reads `.aipass/alerts.json` at the project root. Each alert has an ID, source, severity (`warning`/`critical`), title, body, and optional `expires_at`. Active alerts render as a banner every turn until dismissed or expired. Expired alerts are auto-cleaned on read.

**Sound:** Piper TTS fires on first injection per alert ID — subsequent turns are silent for known alerts. New alerts trigger a fresh announcement.

**Dismissing alerts:** `drone @hooks dismiss <alert-id>` removes an alert by ID from `alerts.json`.

**Schema:**
```json
{
  "alerts": [{
    "id": "uuid", "source": "prax", "severity": "warning",
    "title": "High log rate", "body": "commons exceeds 50 lines/s",
    "created_at": "iso", "expires_at": "iso or null"
  }]
}
```

## Kernel Sandbox (srt/bwrap)

The sandbox module (`apps/modules/sandbox.py`) provides the kernel-level filesystem boundary for agent sessions. It wraps Anthropic's `@anthropic-ai/sandbox-runtime` (srt) library, which uses bubblewrap (bwrap) + Landlock + seccomp on Linux to enforce write/read restrictions at the OS level.

### Key Functions

| Function | What it does |
|---|---|
| `build_policy(branch_path)` | Generates per-role writable/RO map from branch passport |
| `sandbox_launch(command, *, cwd=None, policy, env=None)` | Resolves bwrap command via srt, spawns sandboxed process |
| `resolve_bwrap_command(...)` | Resolves the bwrap argv without spawning — what external callers actually consume |
| `build_srt_config(policy)` | Converts policy dict to srt config format |

### Policy Rules

- **Every agent**: own branch tree + the system temp dir (`tempfile.gettempdir()`, plus `$TMPDIR` when it differs) + shared channels (system_logs, .ai_central, memory_pool, AIPASS_REGISTRY.json, flow_json) + sibling `.ai_mail.local/` and `DASHBOARD.local.json` carve-ins + its **own** `~/.claude/projects/<encoded-cwd>/` (added only if that directory already exists — not the whole `projects/` tree)
- **devpulse only**: .git writable (the only committer)
- **All other agents**: .git read-only, sibling source trees read-only
- **Deny**: broker_secret (deny_read + deny_write for all roles)

Bind-mount, not isolation: the sandbox preserves the shared live filesystem. Reads stay open everywhere. Only writes to protected paths are blocked at the kernel level (EROFS).

### Architecture

The Node helper (`_srt_resolve.mjs`) resolves the globally-installed srt library via `process.execPath` (ESM resolution doesn't walk to global node_modules). The resolver runs with CWD set to `/var/tmp` to prevent srt's mandatory-deny mask files from polluting the branch directory.

@ai_mail's `dispatch_monitor` wires the launch seam with `build_policy` + `build_srt_config` +
`resolve_bwrap_command` — **not** `sandbox_launch`, which this section previously claimed. Corrected
2026-08-13 against `ai_mail/apps/handlers/dispatch/dispatch_monitor.py:69`, whose call order is pinned
by `ai_mail/tests/test_dispatch_monitor.py:1759`. An earlier claim here that the @drone broker
validates sandbox policy before agent launch could not be substantiated — the broker is a privileged
delete daemon and no policy validation was found in its tree — so it has been removed rather than
restated.

## Integration Points

### Depends On

| Branch | What for |
|---|---|
| prax | Logging (system_logger for prax monitor visibility) — 50 imports across `apps/` |
| cli | Rich console rendering for every command surface — 17 imports across `apps/` |

### Provides To

- All branches via hook dispatch — every Claude Code session routes through the engine
- @ai_mail dispatch_monitor — `build_policy` + `build_srt_config` + `resolve_bwrap_command` at the agent launch boundary

*Last Updated: 2026-08-25*

---

[← Back to AIPass](../../../README.md)
