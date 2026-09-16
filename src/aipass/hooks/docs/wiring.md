# Provider wiring and events

**Branch** hooks · **Code** `apps/handlers/bridges/`, `.claude/provider_manifest.json`, `.aipass/hooks.json`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

Which events exist, which shape each one is wired in, and what a new handler needs before it fires. The live verb for checking a wire is `drone @hooks verify`.

---

## Two-Tier Hook Model

Hooks operate on two tiers:

**Tier 1 — Provider Settings (wiring).** Claude Code's `~/.claude/settings.json` (or project `.claude/settings.json`) defines hook entries that point to the bridge (`claude.py`). These are installed by `setup.sh` / `doctor` — they're pure wiring. Wiring comes in two shapes. Five events use **one fan-out entry** that dispatches every enabled handler for that event: PreToolUse, PostToolUse, SubagentStop, Stop, Notification. Three events are wired **per handler** (`claude.py EventType:hook_name`, one entry each): UserPromptSubmit (13 entries), PreCompact (8 — four handlers × `manual`/`auto`), SessionStart (1). The per-handler form exists for two reasons: a single fan-out entry answers with ONE merged document whose `additionalContext` shares one 10,000-unit display limit (How It Works, step 7), which the prompt injectors together would cross; and per-entry wiring gives each handler its own timeout budget (in the current manifest, UserPromptSubmit runs at 90s except `auto_process` at 120s; PreCompact runs 60s/120s/120s/30s; SessionStart 30s). Provider settings cannot be changed by branches — only setup tooling manages them.

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

## Event Types

| Event | Hooks | Description |
|---|---|---|
| UserPromptSubmit | presence_gate, persistent_alert, identity, email, branch_loader, tier0_kernel, navmap, compass_recall, feedback_pulse, context_gauge, temporal, auto_process, user_message_relay | Presence gate + alerts + prompt injection + inbox + governance recall + feedback + context gauge + temporal + auto-process + TG mirror |
| PreToolUse | tool_sound, edit_gate, git_gate, rm_gate, testwrite_gate, registry_gate | Security gates + guardrails + sound. `edit_gate` reads Bash too (the scripted cross-project lane — see [bash_writes.md](bash_writes.md), whose matcher widening landed 2026-08-30) |
| PostToolUse | auto_fix, post_compact_regrounding | Diagnostics + post-compaction re-ground backstop |
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

---

## Related

- [engine.md](engine.md) — what the engine does with the event once the bridge hands it over
- [project_config.md](project_config.md) — what a project gets, and the trust hash on `hooks.json`
