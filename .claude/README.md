# .claude/ — Claude Code Configuration

This directory configures Claude Code for the AIPass project.

## Settings — Two Files, Clear Separation

| File | Name | What it does |
|------|------|-------------|
| `~/.claude/settings.json` | **Anthropic settings** | All hooks, sounds, statusline, plugins. Fires everywhere. |
| `.claude/settings.json` (this dir) | **Project settings** | Permissions only. No hooks. |

**Why this split:** Claude Code project settings only fire when launched from the repo root. We launch from branch subdirectories (`src/aipass/{name}/`), so hooks must live in Anthropic settings with absolute paths.

Project settings = permissions. That's it.

## Hooks — Two Locations, No Duplication

### Anthropic hooks (`~/.claude/hooks/`)

General-purpose scripts that work on any project.

| Script | Event | What it does |
|--------|-------|-------------|
| `tool_use_sound.py` | PreToolUse | Plays keypress sound on tool calls |
| `auto_fix_diagnostics.py` | PostToolUse | Syntax check after file edits |
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

```
.claude/
├── settings.json              # Permissions only (no hooks)
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
