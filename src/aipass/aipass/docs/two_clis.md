[<- Back to the README](../README.md)

# One citizen, two CLIs — Claude Code and Codex

*What each CLI reads, how the rituals are spelled on each, how a compaction
runs on each, and where the two differ.*

A citizen is the same citizen on Claude Code and on Codex: the same branch,
`.trinity/` memories, mailbox and identity. The CLI changes, so does what it
reads at startup and how a ritual is typed. This page is the map of both.

## What each CLI reads

| | Claude Code | Codex |
|---|---|---|
| Instructions | `AGENTS.md`, natively | `AGENTS.md`, natively |
| Shared skills | `.claude/skills/`, a symlink to `../.agents/skills` | `.agents/skills/`, natively |
| CLI-only skills | `.claude/commands/codex.md` (the switch to Codex) | `.codex/skills/claude/` (the switch back) |
| Hooks | `~/.claude/settings.json` | the repo's `.codex/hooks.json` |
| Session pointer | `.ai_mail.local/session.json` in the branch | the same file |
| Handoff on a switch | `.ai_mail.local/handoff.md` in the branch | the same file |

**Skills.** `.agents/skills/` holds one copy of each shared skill: a folder with
a `SKILL.md` whose frontmatter has `name` and `description`. Codex scans it
natively. Claude Code reads `.claude/skills/`, which is a tracked symlink to it,
so both CLIs see the one file. `aipass init`, `aipass new` and `aipass adopt`
write a project's prep skill at `.agents/skills/prep/SKILL.md` and make the
link; `aipass doctor` checks both (see [`doctor.md`](doctor.md)).

**Hooks.** `.claude/provider_manifest.json` holds the hook rows for both CLIs:
`cli.claude` and `cli.codex`. `aipass doctor --fix` and `setup.sh` write the
first into `~/.claude/settings.json` and the second, whole, into the repo's
`.codex/hooks.json`. Codex reads the same hook shape as Claude Code. The event
table lives in @hooks' `docs/wiring.md`.

**Doctor's Codex rows.** Beside `codex hooks`, `aipass doctor` reads the Codex
side and never writes it. `codex binary` prints the version, or passes as
optional when `codex` is not on PATH, and then the other three rows are
skipped. `codex login` runs `codex login status` and warns on a non-zero exit.
`codex model` checks that the `model` in `~/.codex/config.toml` (under
`$CODEX_HOME` when that is set) is in the catalog `codex debug models` fetches
for this login. `codex pins` checks four settings that must read `false`:
`memories` and `collaboration_modes` under `[features]`, the top-level
`include_collaboration_mode_instructions`, and `enabled` under
`[tools.experimental_request_user_input]`. Each missing or wrong pin is a
warning naming the line to add by hand. `--fix` never touches `config.toml`.

**Handing off to either CLI.** `aipass handoff launch --cli codex` and an init
run that chose Codex start `codex --dangerously-bypass-approvals-and-sandbox`,
the posture dispatch uses, because the hooks are the gates on both CLIs. The way
back printed after the session is `codex resume --last` from the agent's
directory; Claude Code's is `claude --continue`.

**The session pointer and the handoff.** Each interactive session start writes
the branch's resume target, with the CLI running it, to
`.ai_mail.local/session.json`, so a resume reopens the right CLI. A switch
(`/codex` on Claude Code, `$claude` on Codex) saves memories, writes
`.ai_mail.local/handoff.md` and replaces the pane with the other CLI, greeted
by that file.

## Spelling a ritual on each CLI

| Claude Code | Codex | What it does |
|---|---|---|
| `/prep` | `$prep` | Session wrap-up before a close or a compaction |
| `/memo` | `$memo` | Memory update |
| `/compass` | `$compass` | Record the decision just made, with a rating |
| `/codex` | — | Switch this chat to Codex |
| — | `$claude` | Switch this chat to Claude Code |
| `/compact` | `/compact` | Compact the context (built into both) |
| `/clear` | `/new` | Start a fresh context |

Codex has no `$ARGUMENTS`. A shared skill that takes input says "the words
after the command", which both CLIs understand.

## A compaction, on each CLI

1. **The gauge nudges.** On every prompt the context gauge reads the session's
   transcript for the newest token usage: Claude Code's JSONL transcript (the
   last assistant message's `usage`), or Codex's rollout (the last `token_count`
   event's `last_token_usage`, with the window the rollout reports). At 80% of
   the compact point it asks for prep at the next natural breakpoint, at 95%
   now, once per context window, spelled `/prep` or `$prep` for the CLI.
2. **Prep runs as a model turn.** The model updates memories, plans and inbox,
   and ends on a Resuming line, the thread the next context picks up.
3. **The compact fires.** Auto or by `/compact`, the PreCompact hooks stamp an
   AUTO-COMPACT SNAPSHOT into `local.json` (context fill, dispatches, plans,
   git, inbox), roll memory over, feed @memory's pool and inject recovery
   state. Claude Code compacts at its window minus its reserve; Codex at 90% of
   its model's full window, lower when `model_auto_compact_token_limit` is set
   in its config.
4. **The re-ground.** SessionStart with source `compact` resets the cadence and
   re-injects the kernel and the navigation map; a PostToolUse backstop repeats
   the re-ground in three parts when no prompt followed the compaction.

## Limits

- Claude Code does not read `.agents/skills/`: the `.claude/skills` link is the
  only reason it sees the shared skills.
- On Windows the link needs `git config core.symlinks true` and the right to
  make symlinks. Without them `aipass init`, `aipass doctor --fix` and the
  other scaffold doors write a copy into `.claude/skills/` and say that the
  copy will not follow `.agents/skills`.
- Codex runs hooks and tool shells from its app-server daemon, with the
  daemon's environment, not the terminal's. `AIPASS_HOME` therefore comes from
  `~/.profile`, which `setup.sh` writes.
- Only the portable frontmatter fields of the Agent Skills standard travel:
  `name`, `description`, `license`, `compatibility`, `metadata`,
  `allowed-tools`. A Claude-only field makes a skill unusable elsewhere.

Code: the scaffold doors in
[`apps/handlers/init/bootstrap.py`](../apps/handlers/init/bootstrap.py), the
hook writer in [`apps/handlers/provider_wire.py`](../apps/handlers/provider_wire.py),
the skills rows in [`apps/modules/doctor.py`](../apps/modules/doctor.py).

---

[← Back to the AIPASS README](../README.md)
