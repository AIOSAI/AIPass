# .claude/ — Claude Code Configuration

This directory configures Claude Code for the AIPass project.

**Related:** DPLAN-0053 (Hook Migration) documents the research and decisions behind this architecture.

## Quick Setup

AIPass hooks live in two places. The project hooks (`hooks/`) travel with the repo. The global hooks (`global_hooks/`) need to be copied to your `~/.claude/` directory.

### Step 1: Copy global hooks

```bash
# Copy hook scripts to your Anthropic hooks directory
mkdir -p ~/.claude/hooks
cp .claude/global_hooks/*.py ~/.claude/hooks/
cp .claude/global_hooks/*.sh ~/.claude/

# Optional: copy sounds (if you want audio feedback)
mkdir -p ~/.claude/sounds
cp .claude/sounds/* ~/.claude/sounds/ 2>/dev/null || true
```

### Step 2: Configure global settings

Add these entries to your `~/.claude/settings.json`. These use `git rev-parse` to find the repo — no hardcoded paths needed.

**UserPromptSubmit hooks** (inject prompts every turn):
```json
"UserPromptSubmit": [
  {
    "hooks": [{ "type": "command", "command": "REPO=$(git rev-parse --show-toplevel 2>/dev/null) && [ -f \"$REPO/.aipass/aipass_global_prompt.md\" ] && cat \"$REPO/.aipass/aipass_global_prompt.md\" || true" }]
  },
  {
    "hooks": [{ "type": "command", "command": "REPO=$(git rev-parse --show-toplevel 2>/dev/null) && [ -f \"$REPO/.claude/hooks/branch_prompt_loader.py\" ] && python3 \"$REPO/.claude/hooks/branch_prompt_loader.py\" || true" }]
  },
  {
    "hooks": [{ "type": "command", "command": "REPO=$(git rev-parse --show-toplevel 2>/dev/null) && [ -f \"$REPO/.claude/hooks/identity_injector.py\" ] && python3 \"$REPO/.claude/hooks/identity_injector.py\" || true" }]
  },
  {
    "hooks": [{ "type": "command", "command": "REPO=$(git rev-parse --show-toplevel 2>/dev/null) && [ -f \"$REPO/.claude/hooks/email_notification.py\" ] && python3 \"$REPO/.claude/hooks/email_notification.py\" || true" }]
  }
]
```

**PreCompact hooks** (save context before compaction):
```json
"PreCompact": [
  { "matcher": "manual", "hooks": [{ "type": "command", "command": "REPO=$(git rev-parse --show-toplevel 2>/dev/null) && [ -f \"$REPO/.claude/hooks/pre_compact.py\" ] && python3 \"$REPO/.claude/hooks/pre_compact.py\" || true", "timeout": 60 }] },
  { "matcher": "auto", "hooks": [{ "type": "command", "command": "REPO=$(git rev-parse --show-toplevel 2>/dev/null) && [ -f \"$REPO/.claude/hooks/pre_compact.py\" ] && python3 \"$REPO/.claude/hooks/pre_compact.py\" || true", "timeout": 60 }] }
]
```

**Optional hooks** (sounds, auto-fix — from global_hooks/):
```json
"PreToolUse": [
  { "matcher": "Bash|Edit|MultiEdit|Write|Read|Grep|Glob|WebSearch|WebFetch|Task",
    "hooks": [{ "type": "command", "command": "python3 ~/.claude/hooks/tool_use_sound.py" }] }
],
"PostToolUse": [
  { "matcher": "Edit|MultiEdit|Write|NotebookEdit",
    "hooks": [{ "type": "command", "command": "python3 ~/.claude/hooks/auto_fix_diagnostics.py" }] }
],
"Stop": [
  { "hooks": [{ "type": "command", "command": "python3 ~/.claude/hooks/stop_sound.py" }] }
],
"Notification": [
  { "hooks": [{ "type": "command", "command": "python3 ~/.claude/hooks/notification_sound.py" }] }
]
```

### Step 3: Done

Launch Claude from any branch subdirectory:
```bash
cd src/aipass/devpulse
claude --permission-mode bypassPermissions
```

The hooks will auto-discover the repo root and inject the right prompts.

## Why This Architecture

Claude Code project settings (`.claude/settings.json`) don't fire `UserPromptSubmit` hooks from subdirectories — only from the repo root. Since AIPass citizens launch from `src/aipass/{name}/`, we can't use project settings for prompt injection.

The solution: hooks live in **global settings** (`~/.claude/settings.json`) but use `git rev-parse --show-toplevel` to find the repo dynamically. No hardcoded paths. Works for any clone location, any user. Outside a git repo, hooks silently do nothing.

See DPLAN-0053 for the full investigation and test results.

## What's In This Directory

```
.claude/
├── settings.json              # Project settings (permissions, env vars, PostToolUse, SubagentStop)
├── hooks/                     # AIPass-specific hook scripts (travel with repo)
│   ├── branch_prompt_loader.py    # Injects branch-specific prompt based on CWD
│   ├── identity_injector.py       # Injects passport identity (role, traits, purpose)
│   ├── email_notification.py      # Notifies if unread mail exists
│   ├── pre_compact.py             # Saves session context before compaction
│   ├── prompt_inject.sh           # Combined inject (reference, not used in production)
│   └── .archive/                  # Archived/disabled hooks
├── global_hooks/              # Scripts to copy to ~/.claude/hooks/ (user setup)
│   ├── auto_fix_diagnostics.py    # Syntax check + seedgo checklist after edits
│   ├── subagent_stop_gate.py      # Blocks subagent if modified files have violations
│   ├── tool_use_sound.py          # Keypress sound on tool calls
│   ├── stop_sound.py              # Sound on stop
│   ├── notification_sound.py      # Sound on notification
│   ├── hook_logger.sh             # Optional hook activity logger
│   └── statusline.sh              # Statusline display (branch, model, context, cost)
├── agents/                    # Agent definitions
│   └── builder.md
├── commands/                  # Slash commands
│   └── memo.md                    # /memo — memory update workflow
├── sounds/                    # Audio files for sound hooks
└── README.md                  # This file
```

## What Gets Injected Every Turn

1. **Global Prompt** — system context, terminology, commands, rules (`.aipass/aipass_global_prompt.md`)
2. **Branch Prompt** — branch-specific instructions based on CWD (`.aipass/aipass_local_prompt.md`)
3. **Identity** — passport summary: role, traits, purpose (`.trinity/passport.json`)
4. **Email** — notification only if unread mail exists (`.ai_mail.local/inbox.json`)

## Project Settings

Defined in `settings.json` (this directory). These DO fire from subdirectories.

**Environment:**
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` — makes PostToolUse hooks fire inside subagents

**Permissions:**
- Denied: `git reset`, `git rebase`, `git config`, `git push --force`, `EnterPlanMode`
- Default mode: `acceptEdits`

**Project hooks:**
- `PostToolUse` — auto-fix diagnostics after file edits (fires in subagents via env var)
- `SubagentStop` — secondary gate checking modified files against seedgo standards

## Adding a New Hook

1. Create the script in `.claude/hooks/`
2. Add one entry to `~/.claude/settings.json` using the `git rev-parse` pattern:
   ```
   REPO=$(git rev-parse --show-toplevel 2>/dev/null) && [ -f "$REPO/.claude/hooks/your_script.py" ] && python3 "$REPO/.claude/hooks/your_script.py" || true
   ```
3. Done — no hardcoded paths, works for any clone location
