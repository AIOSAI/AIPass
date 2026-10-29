[<- Back to the README](../README.md)

# Per-project config: the template, the trust hash, and the release notice

**Branch** hooks · **Code** `.aipass/hooks.json`, `.aipass/project_hooks.json`, `apps/handlers/config/loader.py`, `apps/handlers/config/trust_registry.py`, `apps/modules/release_notice.py`

`.aipass/hooks.json` decides what fires for a project; `.aipass/project_hooks.json` is the template `aipass init` stamps into a new one. Which config a session runs, and when trust matters, is the loader's call (below). Security never depends on trust: an untrusted, missing or unreadable config still runs the gates.

---

## Which config runs — `loader.py`

`resolve_config()` walks up from the working directory:

- **Inside AIPass** (AIPASS_HOME), the root `.aipass/hooks.json` is used with NO trust check. Editing it changes what fires; it never turns the hooks off. It is a protected file: only the verified admin seat writes it (see [git_gate.md](git_gate.md)).
- **A branch-level `.aipass/hooks.json` inside AIPass is IGNORED**, with a WARNING naming it. A branch cannot switch its own gates off.
- **An external project** — a nested project root (a directory holding a `*_REGISTRY.json`, like `projects/baud`) or anything outside AIPASS_HOME — runs its own config only when the trust registry vouches for it (`aipass trust <path>`). Changing that file breaks its trust hash, and the trust-break banner fires for external projects only.
- **Never "no hooks".** An untrusted, missing or unreadable config falls back to the gate set: the gate entries of AIPASS_HOME's config, else the built-in set in `handlers/config/gates.py`, logged at ERROR.
- A trusted external project inside AIPASS_HOME gets the gates forced over its config; a trusted project outside AIPass owns its gates.
- A home config that names no gate gets the built-in gates forced over it, logged at ERROR.

`drone @hooks status` explains why a project's own config is not running, and always ends "The AIPass gate set still runs."

### A project's own handlers — `handler_namespace`

A handler row names a dotted function the engine imports. By default only `aipass.*` is imported; anything else is refused before import and logged `handler namespace refused`. A trusted project can declare one package of its own:

```json
{
  "handler_namespace": "hark",
  "Stop": {"record": {"enabled": true, "handler": "hark.hark.apps.modules.hook_events.record", "matcher": ""}}
}
```

Name a function under the project's `apps/modules/`, not `apps/handlers/`: the scaffold's handlers fence refuses every importer outside the branch, the hook engine included, so a handler row pointing into `handlers/` is refused whatever the trust state. A one-function module that calls the handler is the shape.

- **Trust first.** The key is honoured only when the config itself loads, which means the project is enrolled and its hooks.json hash still matches. An unenrolled or edited config does not load at all, so none of its handlers are imported. The refusal line names the cure: `aipass trust <path>`. Adding the key changes the hash, so enroll after the edit.
- **One name.** The value must be a single Python identifier, and it may not be `aipass`. Any other value is refused with a WARNING, and the config runs `aipass.*` only.
- **The root config never takes it.** AIPass's own `.aipass/hooks.json` runs `aipass.*` only, and a key there is refused with a WARNING.
- **`<project>/src` is appended to `sys.path` for that import only**, then removed. It is appended, never prepended, so an `aipass.*` module always resolves to AIPass's copy and a project cannot shadow one.
- **Command rows stay refused** for every project config, namespaced or not. Nothing about the gates changes.
- The loader stamps the trusted name as `_handler_namespace`, with `_project_src`, and it drops either key if the file supplies it, so a config cannot forge them. `drone @hooks status` prints the declared namespace, and says when it was refused.

## The template ruling — what a project gets, and what stays framework-only

`.aipass/project_hooks.json` is the base config `aipass init` copies into a new project. It is not a
mirror of AIPass's own `.aipass/hooks.json`: each framework handler is ruled individually, project or
framework-only, and the table below gives the ruling and the reason. `aipass init update` merges the
template into a project by union, so anything ruled *project* below reaches Vera-Studio, wren and
`projects/*` on their next apply.

| Handler | Event | Ruling | Why |
|---|---|---|---|
| `temporal` | UserPromptSubmit | **project** | One line off the host clock. No AIPass state, no project assumptions, no dependency. |
| `context_gauge` | UserPromptSubmit | **project** | Reads the session's record on each of the three CLIs and nudges the memory call (`/prep` on Claude Code and OpenCode, `$prep` on Codex) before the compact ceiling. **OpenCode:** the newest assistant message in `opencode.db`, read-only, against a 200k window. That is a CLI fact, not an AIPass one — every project manager compacts. The first line decides the shape: a Codex rollout opens with `session_meta`. **Claude Code:** the fill is the newest assistant turn's input + cache read + cache creation; the window is the one Claude Code runs for the transcript's model (`[1m]` or a native-1M id: 1M, else 200k), capped by `CLAUDE_CODE_AUTO_COMPACT_WINDOW` or `autoCompactWindow` (branch, then user settings); the trigger is window − 33k. **Codex:** the fill is the newest `token_count`'s `last_token_usage.total_tokens`; the window is that event's `model_context_window` (the usable 95% of the model's window), else 95% of `model_context_window` in `~/.codex/config.toml` (`$CODEX_HOME`); the trigger is 90% of the full window, lowered by `model_auto_compact_token_limit` when set, as codex-rs computes it. The line prints fill over window as the status line does (`context_window.py`). |
| `persistent_alert` | UserPromptSubmit | **project** | Reads the project's *own* `.aipass/alerts.json`; the walk-up stops at the project root. No file means silent, so it costs nothing and hands projects an alert channel they currently cannot use. |
| `pre_compact_prep` | PreCompact | **project** | Stamps the compacting branch's own `.trinity/local.json`. Memory that survives compaction is the platform's headline promise, and it is not AIPass-specific. |
| `post_compact_regrounding` | PostToolUse | **project** | Re-injects branch/identity/kernel/navmap after a compact — the four files `init` scaffolds into every project — in parts of at most 9,000 chars, one per tool call, branch first. Claude Code shows the agent only a 2,000-char preview of a hook context over 10,000 (issue #752); every part logs `[HOOKS] regroup fired loader=… part=k/N bytes=… chars=…` to `hooks_cadence.log`. Also the carrier for the `release_notice` compact path. |
| `registry_gate` | PreToolUse | **project** | Every project has a `*_REGISTRY.json`. Without this gate a project's sealed registry is an ordinary editable file. |
| `feedback_pulse` | UserPromptSubmit | **project**, ships `enabled: false` | Its own docstring scopes it to "external user projects (not the AIPass host)" — it belongs here more than in the framework file. Off by default, same as in the framework, so a project opts in. |
| `culture` | SessionStart | **project** | Injects the host's `$AIPASS_HOME/.claude/AGENTS.md`, not the project's, on purpose: AIPass culture is every citizen's, and a project's own voice lives in its `AGENTS.md`. Claude Code reads that file natively only inside `AIPASS_HOME`, so the handler is silent for a Claude seat there and injects everywhere else; Codex never reads it natively. Wired per handler (`SessionStart:culture`) on both CLIs. |
| `session_pointer` | SessionStart | **project** | Records an interactive session as its branch's resume target (`.ai_mail.local/session.json`), so a resume reopens the chat the owner just had, on the CLI that ran it. Without it a project's pointer is only ever written by a dispatch. Wired per handler on both CLIs. |
| `settings_gate` | PreToolUse | **project** | The owner's accept on every provider-settings change, Claude's, Codex's and OpenCode's (`~/.config/opencode` and its auth file). Those files are per user, not per project: a project seat reaches them the same way a fleet seat does. |
| `settings_backup` | PreToolUse | **project** | The copy and receipt in `~/.claude/.backup/settings/` before any tool writes a Claude settings file. Same reach as `settings_gate`. |
| `navmap_cap` | PostToolUse | **project** | `prompt/navmap.handle_edit`: after an Edit, Write or shell write of a `.aipass/tier1_navmap.md`, says when the file is over `NAVMAP_CHAR_CAP` (8,000 chars), with the count and the overage. Injection cuts near 10,000; this tells the editor at edit time instead of the reader finding a cut prompt. Never blocks. |
| `comment_budget` | PostToolUse | framework-only | Measures AIPass's house comment standard (under 10% comment lines). A project has its own. |
| `presence_gate` | UserPromptSubmit | framework-only | Enforces one interactive brain per branch across the AIPass fleet. A solo project has no competing citizen to fence, and a false block costs the user their session. |
| `presence_release` | Stop | framework-only | `presence_gate.handle_stop` is a documented no-op (Stop fires every turn; CC-native session files do the cleanup). Shipping it would buy a per-turn dispatch for nothing. |
| `auto_process` | UserPromptSubmit + PreCompact | framework-only | Spawns @memory's vectorize/rollover child. @memory is an AIPass branch, and its deps (`numpy`, `chromadb`, `fastembed`) are an optional extra a project will not have. |
| `compass_recall` | UserPromptSubmit | framework-only | Queries @devpulse's compass FTS, an AIPass-internal decision store. A project has no compass, so the handler would query nothing on every turn. |
| `user_message_relay` | UserPromptSubmit | framework-only | @skills' Telegram guest handler; needs per-branch chat registration and the `telegram` extra. Not a scaffold default. |
| `telegram_response` | Stop | framework-only | Same reason — delivery into the owner's Telegram chats. |
| `auto_watchdog` | PostToolUse | **retired**, not in the template | The handler is retired: its module is not under `apps/handlers/lifecycle/`, so its dotted path resolves to nothing. Its entry stays in `.aipass/hooks.json` with `enabled: false`; that file is protected and only the admin seat writes it. |
| `release_notice` | SessionStart | **project** | See below. |

## `release_notice` — a manager hears that AIPass moved

`apps/handlers/lifecycle/release_notice.py` (wiring) over `apps/modules/release_notice.py` (the
deciding) tells a **project manager** that the installed AIPass is newer than the AIPass that wrote
their scaffold. It reads two files — the nearest `.trinity/passport.json` and the project root's
`.aipass/scaffold_manifest.json` — and writes none. It never runs the update: applying is the owner's
or @devpulse's call.

It is silent for every one of these: a passport whose `citizen_class` is not `manager`; a cwd with no
passport above it; a cwd outside any `*_REGISTRY.json` root; the AIPass source repo itself (`src/aipass`
plus a root `pyproject.toml` — `aipass init update` refuses its own repo, so a notice there could never
be cleared, and @devpulse's passport says `manager`); and a scaffold already at the installed version.
An absent or unparseable manifest counts as **behind** — a project that cannot say which AIPass wrote it
has never been stamped. Versions compare as zero-padded integer tuples rather than through
`packaging.version`, because `packaging` is not in this project's declared `dependencies` and a hook must
not rest on whatever pip left in the venv.

Two doors, one code path:

| Door | Wiring | Provider entry needed |
|---|---|---|
| SessionStart (`source` `startup` / `clear`; `resume` and `compact` skipped) | `project_hooks.json` → `SessionStart.release_notice` | **Yes** — `claude.py SessionStart:release_notice`, in the provider manifest and live settings. SessionStart is wired per handler: without that entry this hook is configured but never dispatched. |
| Post-compact regroup | `post_compact_regrounding` opens its branch section with the block, so it lands in part 1 of the re-ground on every seat | No — PostToolUse is a fan-out event |

---

## Related

- [wiring.md](wiring.md) — the per-handler provider entries a new SessionStart or PreCompact handler needs
