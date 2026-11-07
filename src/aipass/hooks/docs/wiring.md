[<- Back to the README](../README.md)

# Provider wiring and events

**Branch** hooks · **Code** `apps/handlers/bridges/`, `.claude/provider_manifest.json`, `.aipass/hooks.json`

Which events exist, which shape each one is wired in, and what a new handler needs before it fires. The live verb for checking a wire is `drone @hooks verify`.

---

## Two-Tier Hook Model

Hooks operate on two tiers:

**Tier 1 — Provider Settings (wiring).** Claude Code's `~/.claude/settings.json` (or project `.claude/settings.json`) defines hook entries that point to the bridge (`claude.py`). These are installed by `setup.sh` / `doctor` — they're pure wiring. Wiring comes in two shapes. Five events use **one fan-out entry** that dispatches every enabled handler for that event: PreToolUse, PostToolUse, SubagentStop, Stop, Notification. Three events are wired **per handler** (`claude.py EventType:hook_name`, one entry each): UserPromptSubmit (14 entries, `project` among them), PreCompact (8 — four handlers × `manual`/`auto`), SessionStart (1). The per-handler form exists for two reasons: a single fan-out entry answers with ONE merged document whose `additionalContext` shares one 10,000-unit display limit (How It Works, step 7), which the prompt injectors together would cross; and per-entry wiring gives each handler its own timeout budget (in the current manifest, UserPromptSubmit runs at 90s except `auto_process` at 120s; PreCompact runs 60s/120s/120s/30s; SessionStart 30s). Provider settings cannot be changed by branches — only setup tooling manages them.

**Tier 2 — Project Config (control).** Each project's `.aipass/hooks.json` controls which hooks fire for that project. Created by `aipass init`. `enabled` flags turn hooks on/off per project, with limits on the gates: inside AIPass only the root config (a protected file) sets them, a branch-level `hooks.json` is ignored, and a project nested in AIPass has the gates forced over its config (see [project_config.md](project_config.md)). Use `drone @hooks status` to view current config.

**Why provider-only wiring?** Claude Code does not fire `PreToolUse`/`PostToolUse` hooks from project-level settings — only from user-level settings (a platform limitation). So all hook entries live in provider settings, and per-project control happens through `.aipass/hooks.json`.

**Deploying new handlers:** whether `.aipass/hooks.json` alone is enough depends on which shape the event uses.

| New handler on | Provider change needed |
|---|---|
| PreToolUse, PostToolUse, SubagentStop, Stop, Notification | **None** — the fan-out entry already dispatches it |
| UserPromptSubmit, SessionStart | **One** new entry: `claude.py <Event>:<hook_name>` |
| PreCompact | **Two** new entries — one `matcher: manual`, one `matcher: auto` |

Provider settings are protected files (`modules/protected_paths.py`, enforced by `git_gate` on the edit tools and Bash): only the verified admin seat writes them, so when an entry is needed, email @devpulse to wire it. Without it the engine never receives the event and the handler never fires — and the suite cannot see the gap, so verify with firing evidence in `engine.jsonl`.

**Keeping the manifest and live settings in sync:** `.claude/provider_manifest.json` (repo root, self-editable by @hooks) is the source of truth; `~/.claude/settings.json` is the live copy Claude Code actually reads, and only `aipass doctor --fix` or the admin seat (@devpulse) writes it. Editing the manifest does NOT apply live. Run `aipass doctor` after any manifest edit to see the drift, then ask @devpulse to apply it.

## Event Types

| Event | Hooks | Description |
|---|---|---|
| UserPromptSubmit | presence_gate, persistent_alert, identity, email, branch_loader, tier0_kernel, navmap, compass_recall, feedback_pulse, context_gauge, temporal, auto_process, user_message_relay | Presence gate + alerts + prompt injection + inbox + governance recall + feedback + context gauge + temporal + auto-process + TG mirror |
| PreToolUse | tool_sound, edit_gate, git_gate, rm_gate, testwrite_gate, registry_gate | Security gates + guardrails + sound. `edit_gate` reads Bash too (the scripted cross-project lane — see [bash_writes.md](bash_writes.md)) |
| PostToolUse | auto_fix, post_compact_regrounding | Diagnostics + post-compaction re-ground backstop |
| SubagentStop | subagent_gate | Sentry validation |
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

One per-handler name is generic: **`UserPromptSubmit:project`**. A trusted project's own handlers
(`handler_namespace`, see [project_config.md](project_config.md)) cannot have rows of their own, because
provider settings are the user's file and list AIPass's handlers only. For the filter `project`, the engine
runs every enabled hook of the event whose handler starts with the config's stamped namespace, and nothing
else. A config with no namespace (AIPass's own tree, any untrusted project) runs nothing and answers
nothing. The row runs at 30s on every CLI. `drone @hooks verify` counts a namespaced hook as wired by
that row, and never reports the row as an orphan. A hook named `project` in a hooks.json is unreachable
per handler, so the name is reserved.

`compass_recall` speaks to manager seats only: its handler walks up from the payload's cwd to the
nearest `.trinity/passport.json` and recalls nothing unless the passport declares `citizen_class: manager`.
Compass is the managers' decision store, so a builder seat, or a directory with no passport, hears nothing.

**Sound is off by default.** `apps/sound.py`'s `speak()` and `play()` check `is_muted()`, which is True
unless `~/.aipass/aipass-hooks-sound-on` exists (outside the temp dir, so a reboot or `TMPDIR` cannot move it).
`hooksound on` creates it, `off` removes it, `--json` prints `{"active": bool}` on stdout; a fresh install is silent. An old mute flag
(`~/.aipass/aipass-hooks-muted`, `<temp dir>/aipass-hooks-muted`) is redundant: `is_muted()` removes it.
`tests/conftest.py` points all three at a temp dir.

---

## Codex

Codex speaks Claude Code's hook protocol (same event names, `tool_input`, `additionalContext`, `permissionDecision`) and reads a `hooks.json` of the same `matcher` + `command` shape, so `codex.py` is Claude's bridge plus four differences:

| Codex | What `codex.py` does |
|---|---|
| Shell tool is `Bash`, `tool_input.command` | Nothing: the gates read it as they read Claude's |
| File tool is `apply_patch`, one patch text over many files | Each file becomes the Claude call the gates judge: Add File → `Write`, Update File → `MultiEdit` (one edit per `@@` hunk), Delete File → a shell `rm`, Move to → a shell `mv`. The engine runs once per call; the first refusal denies the whole patch. A patch naming no file is denied with that reason and logged at WARNING; it is a malformed call, not a broken engine. |
| Blocks by `permissionDecision`, never by exit code | Any exit 2 on PreToolUse becomes a deny envelope, JSON or not. A block on another event passes through as `{"decision": "block"}` |
| No `CLAUDE_CODE_SESSION_ID` in a hook's environment | The payload's `session_id` is set as that variable, so cadence and the ledgers count this seat's turns, never the launcher's |

`codex.py` also names itself in every payload (`"provider": "codex"`; a payload without the key is Claude's). `SessionStart:session_pointer` (`lifecycle/session_start.handle_session_pointer`) writes that provider and the session id into the branch's `.ai_mail.local/session.json` through ai_mail's `door_session_pointer`, so a resume reopens the CLI that last ran. It writes only for a session a person runs: a Codex session whose rollout (`transcript_path`) opens with a `session_meta` `source` other than `exec`, or a Claude session whose nearest `claude` ancestor process has no `-p`/`--print` (`cc_sessions.cli_ancestor`). It skips a headless run, an unreadable rollout, a compact, a cwd without `.trinity/passport.json`, and a missing session id.

Codex has no Notification event and no `manual`/`auto` PreCompact matcher, so a Codex PreCompact row is one per handler. Codex reads the repo-root `AGENTS.md` natively but not `.claude/AGENTS.md`; `SessionStart:culture` (`lifecycle/session_start.handle_culture`) injects that file from `$AIPASS_HOME`. Claude Code reads it natively only inside `AIPASS_HOME`: its `SessionStart:culture` row is silent there and injects the host's file in an external project. `drone @hooks verify` reads the project's `.codex/hooks.json` too: a per-handler row wired only through `codex.py` reports `wired for Codex only`, never `handler never fires`. A Codex hook runs only once trusted: `~/.codex/config.toml` `[hooks.state]` keeps one entry per hook, keyed by file, event and position, with its hash; `codex exec --dangerously-bypass-hook-trust` skips that for automation.

---

## OpenCode

OpenCode 2 is wired through a plugin, not a shell-hook config: [opencode.md](opencode.md) has the plugin, the hook-to-event map, compaction order, the grounding receipt and the context gauge.

---

## Seed

A Seed head (the Seed repo's `src/hooks/hooks.md`) fires Claude Code's events itself and runs the command rows of `hooks.json` in its home (`$SEED_HOME`, else `~/.config/seed`), read once at start. The rows are flat, `{matcher?, command?, builtin?, timeout?}`. `drone @hooks seed install` writes one row per event Seed fires, `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostCompact` and `Stop`: `<the venv python> <absolute path>/bridges/seed.py <Event>`, timeout 120 s, since one row runs every handler of its event. A re-run replaces its own rows and keeps every other; `drone @hooks seed remove` takes them out. The manifest has no `cli.seed` section yet, so the event list is `wire_verify.SEED_EVENTS`.

| What arrives | `seed.py` does | Seed reads |
|---|---|---|
| Claude's payload, `provider: "seed"`, a `session_id` per head run | sets `CLAUDE_CODE_SESSION_ID`, names the provider when the payload does not, renames nothing, calls `run_event` | |
| an engine answer in JSON, exit 0 | stdout as is | the document: `decision`, `hookSpecificOutput`, `systemMessage` |
| plain text, exit 0 | `additionalContext` on SessionStart and UserPromptSubmit, `systemMessage` elsewhere | the document |
| a block, exit 2 | stdout as is, the reason on stderr, exit 2 | stderr as the reason |
| an engine that cannot load or raises | `HOOKS BROKEN` on stderr and in `logs/bridge.log`; exit 2 on PreToolUse, else exit 0 and no stdout | a block, or no answer |

`seed.py` runs from the source tree and mounts the promoted copy, as every bridge does. The engine resolves its config from the working directory, which Seed sets to the agent's directory: an agent outside an AIPass project gets the gate set only, so no grounding and no identity. Seed's `transcript.jsonl` is its own shape (`who`, `text`, `time`, `compaction`), not Claude's. On `provider: "seed"` the context gauge and the PreCompact snapshot read no fill, `context_window` answers no usage and no model without parsing a line, the session pointer is not written (Seed has no resume), the culture file is injected (Seed reads no AGENTS.md), and cadence counts turns by the file's size, as on every CLI. `drone @hooks verify` reads the Seed file too: no file or no AIPass row is a head not wired (INFO), a missing event row an ERROR naming the cure, a duplicate a WARN, a file Seed would refuse at start an ERROR.

---

## Related

- [engine.md](engine.md) — what the engine does with the event once the bridge hands it over
- [project_config.md](project_config.md) — what a project gets, which config runs, and the trust hash on an external project's `hooks.json`
