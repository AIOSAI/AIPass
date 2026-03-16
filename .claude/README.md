# .claude/ — Claude Code Configuration

This directory configures Claude Code for the AIPass project.

## Settings — Two Files, Clear Separation

| File | Name | What it does |
|------|------|-------------|
| `~/.claude/settings.json` | **Anthropic settings** | All hooks, sounds, statusline, plugins. Fires everywhere. |
| `.claude/settings.json` (this dir) | **Project settings** | Permissions, env vars, project-scoped hooks. |

**Why this split:** Claude Code project settings only fire when launched from the repo root. We launch from branch subdirectories (`src/aipass/{name}/`), so most hooks live in Anthropic settings with absolute paths. Project settings handles permissions, environment configuration, and hooks that need project-level scoping (like SubagentStop).

## Environment

Project settings sets `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` — this makes PostToolUse hooks (like auto-fix) fire inside subagents, not just the parent conversation. Without this, subagents bypass all hook enforcement.

## Hooks — Two Locations, No Duplication

### Anthropic hooks (`~/.claude/hooks/`)

General-purpose scripts that work on any project.

| Script | Event | What it does |
|--------|-------|-------------|
| `tool_use_sound.py` | PreToolUse | Plays keypress sound on tool calls |
| `auto_fix_diagnostics.py` | PostToolUse | Syntax check + seedgo standards checklist after file edits. Fires in subagents too (requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`). |
| `subagent_stop_gate.py` | SubagentStop | Secondary gate — checks modified .py files against seedgo standards before allowing subagent completion. |
| `stop_sound.py` | Stop | Sound on stop |
| `notification_sound.py` | Notification | Sound on notification |

### Project hooks (`AIPass/.claude/hooks/`)

AIPass-specific scripts. Referenced from Anthropic settings with absolute paths.

| Script | Event | What it does |
|--------|-------|-------------|
| `branch_prompt_loader.py` | UserPromptSubmit | Finds `.aipass/aipass_local_prompt.md` from CWD, injects branch context |
| `identity_injector.py` | UserPromptSubmit | Reads `.trinity/passport.json`, injects role/traits/purpose |
| `email_notification.py` | UserPromptSubmit | Checks `.ai_mail.local/inbox.json` for unread messages |
| `pre_compact.py` | PreCompact | Saves session context before compaction |

The global prompt (`aipass_global_prompt.md`) is injected via a `cat` command in Anthropic settings — no script needed.

## What Gets Injected Every Turn

1. **Global Prompt** — `cat .aipass/aipass_global_prompt.md` (system context, terminology, rules)
2. **Branch Prompt** — `branch_prompt_loader.py` (branch-specific instructions from CWD)
3. **Identity** — `identity_injector.py` (compact passport summary: role, traits, purpose)
4. **Email** — `email_notification.py` (notification only if unread mail exists)

## Directory Structure

### Project hooks (`.claude/settings.json`)

Hooks defined in project settings — fire for project-scoped events.

| Hook | Event | What it does |
|------|-------|-------------|
| `auto_fix_diagnostics.py` | PostToolUse | Same Anthropic hook, also wired at project level for subagent coverage |
| `subagent_stop_gate.py` | SubagentStop | Blocks subagent completion if modified files have seedgo violations |

```
.claude/
├── settings.json              # Permissions, env, project hooks
├── hooks/                     # AIPass-specific hook scripts
│   ├── branch_prompt_loader.py
│   ├── identity_injector.py
│   ├── email_notification.py
│   └── pre_compact.py
├── commands/
│   └── memo.md                # /memo — memory update workflow
├── sounds/                    # Audio files (symlinked from ~/.claude/sounds)
└── README.md
```

## Adding a New Hook

1. Create the script in `.claude/hooks/`
2. Add one entry to `~/.claude/settings.json` (Anthropic settings) with the absolute path
3. Done — no changes to project settings

## Permissions

Defined in `settings.json`:
- **Denied**: `git reset`, `git rebase`, `git config`, `git push --force`, `EnterPlanMode`
- **Default mode**: `acceptEdits`

## Subagent Hook Enforcement

Subagents (spawned via the Agent tool) run in isolation by default — parent hooks don't fire inside them. Two mechanisms enforce standards on subagents:

1. **`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`** — env var that makes PostToolUse hooks fire inside all built-in subagent types (builder, Explore, Plan, general-purpose). This means `auto_fix_diagnostics.py` runs after every file edit, even inside subagents.

2. **`SubagentStop` hook** — secondary gate. When a subagent finishes, `subagent_stop_gate.py` checks all modified .py files against seedgo standards. If violations exist, it blocks completion and tells the subagent to fix them.

No custom agents (`.claude/agents/`) are used — this works with all built-in subagent types.
