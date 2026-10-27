# =================== AIPass ====================
# Name: scaffold_content.py
# Description: Shared template content generators for project scaffolding
# Version: 1.4.0
# Created: 2026-04-22
# Modified: 2026-10-27
# =============================================

"""
Scaffold Content — template generators for `aipass init`, `aipass new`, `aipass adopt`

Pure string-returning functions that produce the content for each scaffold
file (AGENTS.md, .gitignore, etc.). Shared across every command
that mints AIPass project files, so there is exactly one source of truth
per template — no per-command copies to drift apart.

Dependency-free: uses only stdlib. Importable before drone/prax exist.

RULES:
  - Pure Python only (no module/prax/cli imports)
  - Each function returns a string
  - No side effects
"""

import json
from pathlib import Path


def readme_md(name: str) -> str:
    """Generate README.md content — real getting started guide."""
    return (
        f"# {name}\n"
        "\n"
        "An AIPass project.\n"
        "\n"
        "## Quick Start\n"
        "\n"
        "```bash\n"
        "# 1. Create your first agent\n"
        "aipass init agent my_agent\n"
        "\n"
        "# 2. Start a session\n"
        f"cd src/{name.lower()}/my_agent/\n"
        "claude  # or your preferred AI CLI\n"
        "\n"
        "# 3. Check project health\n"
        "drone @seedgo audit .\n"
        "```\n"
        "\n"
        "## Project Structure\n"
        "\n"
        "```\n"
        f"{name.lower()}/\n"
        f"  {name}_REGISTRY.json    # Agent registry\n"
        "  .aipass/                 # Prompts (injected per-turn)\n"
        "  AGENTS.md               # agent instructions\n"
        f"  src/{name.lower()}/              # Project package\n"
        "    <agent_name>/         # Created via aipass init agent\n"
        "```\n"
        "\n"
        "## What is AIPass?\n"
        "\n"
        "AIPass is a multi-agent framework where autonomous agents (citizens) "
        "live in directories with persistent identity, memory, and communication.\n"
        "\n"
        "Each agent has:\n"
        "- **Identity** — `.trinity/passport.json`\n"
        "- **Memory** — `.trinity/local.json`, `observations.json`\n"
        "- **Mailbox** — `.ai_mail.local/`\n"
        "- **Code** — `apps/` with modules and handlers\n"
        "\n"
        "## Commands\n"
        "\n"
        "| Command | Description |\n"
        "|---------|-------------|\n"
        "| `aipass init agent <name>` | Create a new agent |\n"
        "| `drone @spawn create <name>` | Create agent (alternative) |\n"
        "| `drone @seedgo audit <project>` | Run standards audit |\n"
        "| `drone @ai_mail inbox` | Check agent mailbox |\n"
        "| `drone systems` | List infrastructure |\n"
        "\n"
        f"*Initialized with [AIPass](https://github.com/AIOSAI/AIPass) on "
        f"{{date}}*\n"
    )


def agents_md(name: str) -> str:
    """Generate AGENTS.md content, word for word the host's .aipass/project_AGENTS.md."""
    return (
        f"# {name}\n"
        "<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md in the AIPass "
        "repo root — the prompt format rules. -->\n"
        "\n"
        "Agent workspace powered by AIPass.\n"
        "\n"
        "# Startup protocol\n"
        "\n"
        "On any greeting, silently run this sequence — no narration, no announcing "
        "steps. Just do it and respond with the status.\n"
        "\n"
        "These steps are sequential and dependent — run each ONCE, wait for the result, then "
        "proceed. Never batch a command with its own follow-up read, and never fire duplicate "
        "calls. If output looks blank, wait — don't retry.\n"
        "\n"
        " - Read, one file per call, never concatenated: `.trinity/passport.json`, "
        '`.trinity/local.json`, `.trinity/observations.json`. A "persisted output" notice means '
        "you batched: read the originals one per call, never the persisted file.\n"
        " - Never read your `README.md` at startup — it is the face for strangers. Your inventory "
        "is `drone @<self>` (live) and `drone @<self> --help`.\n"
        " - Refresh: `drone @prax dashboard refresh @<self>` — where `<self>` is your branch name "
        "(CWD directory name)\n"
        " - Dashboard: Read `DASHBOARD.local.json` — act on what needs attention (new mail → "
        "check inbox, active plans → note them). This is your single status glance.\n"
        "\n"
        "Use drone commands for all operations. Never raw git, gh, file access, or python -m "
        "when drone provides it.\n"
        "\n"
        "# Memories\n"
        "\n"
        "Update `.trinity/` at natural breakpoints, after milestones, and on `/memo` (Claude Code) "
        "or `$memo` (Codex).\n"
        "\n"
        "Todos[] are a sticky-note pad, not a log: 10 live, each `{number, date, task, priority?}`, "
        'the task one line under 100 chars ("Check on seedgo\'s errors in logs"), no `status` '
        "field — the story lives in plans and sessions. **Delete each todo the moment it's done.** "
        "The oldest roll off by number to your backlog at rollover (PreCompact) and at @memory's "
        "push; `drone @memory todo backlog` reads them, `todo restore <n>` brings one back. Rolling "
        "never closes anything, so **reconcile on load**: remove what is finished so it never "
        "resurfaces as open. A truncated `.trinity` read is a signal, not noise — say so first, "
        "then measure the file.\n"
    )


def global_prompt_md(name: str) -> str:
    """Generate .aipass/aipass_global_prompt.md — injected every turn."""
    return (
        f"# {name} — Project Context\n"
        "<!-- Injected every turn via hook. -->\n"
        "\n"
        "## What is AIPass\n"
        "\n"
        "AIPass is a multi-agent framework. Agents live in directories with\n"
        "persistent identity, memory, and communication. All AIPass infrastructure\n"
        "is available from any project via the `drone` command.\n"
        "\n"
        "## Terminology\n"
        "\n"
        "- **Project** — this directory. Contains a registry and agents.\n"
        "- **Agent** — a citizen with identity (`.trinity/`), memory, mailbox,\n"
        "  and code (`apps/`).\n"
        f"- **Registry** — `{name}_REGISTRY.json` tracks all agents.\n"
        "\n"
        "## Setup: if drone commands fail\n"
        "\n"
        "If `drone` cannot find the AIPass registry, set the env var:\n"
        "```bash\n"
        "export AIPASS_HOME=/path/to/AIPass   # path to AIPass installation\n"
        "```\n"
        "Add to your shell profile (`~/.bashrc` or `~/.zshrc`) to make it permanent.\n"
        "\n"
        "## Commands\n"
        "\n"
        "### Agent Lifecycle\n"
        "```\n"
        "aipass init agent <name>           # Create a new agent in src/<name>/\n"
        "drone @spawn create <name>         # Create agent (alternative)\n"
        "drone @spawn list                  # List registered agents\n"
        "```\n"
        "\n"
        "### Standards\n"
        "```\n"
        "drone @seedgo audit <project>      # Run full standards audit\n"
        "drone @seedgo checklist <file>     # Check a single file\n"
        "```\n"
        "\n"
        "### Dispatch — Send Task + Wake an Agent (DEFAULT)\n"
        "```\n"
        'drone @ai_mail dispatch @<agent> "Subject" "Body"        # Send + wake (default)\n'
        'drone @ai_mail dispatch @<agent> "Subject" "Body" --fresh # Send + wake fresh session\n'
        "drone @ai_mail dispatch wake @<agent>                    # Wake without sending\n"
        "drone @ai_mail dispatch wake --fresh @<agent>            # Wake fresh\n"
        'drone @ai_mail email @<agent> "Subject" "Body"           # FYI only (no wake)\n'
        "```\n"
        "\n"
        "Use `dispatch` by default. Use `email` only when you don't need the agent to act now.\n"
        "\n"
        "### Communication (ai_mail)\n"
        "```\n"
        "drone @ai_mail inbox               # Check your mailbox\n"
        "drone @ai_mail view <id>           # Read a message\n"
        "drone @ai_mail close <id>          # Mark message read\n"
        "```\n"
        "\n"
        "### Feedback\n"
        "```\n"
        'drone @devpulse feedback send "Subject" "Body"  # Send feedback (cross-project)\n'
        "```\n"
        "\n"
        "### Plans (flow)\n"
        "```\n"
        'drone @flow create . "Subject" dplan   # Create DPLAN (design/thinking)\n'
        'drone @flow create . "Subject" master  # Create FPLAN master (execution)\n'
        'drone @flow create . "Subject" aplan   # Create APLAN (agent-level task)\n'
        "drone @flow list open                  # List active plans\n"
        "drone @flow list                       # List all plans\n"
        "drone @flow close <id>                 # Close a plan\n"
        "drone @flow info <id>                  # View plan details\n"
        "```\n"
        "\n"
        "**DPLAN** = Dev Plan. Thinking, brainstorming, architecture decisions. "
        "Use before building.\n"
        "**FPLAN** = Flow Plan. Building and executing. Use when the plan is clear "
        "and work is underway.\n"
        "\n"
        "### Memory\n"
        "```\n"
        "drone @memory archive              # Archive memories to vector store\n"
        "drone @memory search <query>       # Search archived memories\n"
        "```\n"
        "\n"
        "### Git Workflow\n"
        "```\n"
        "drone @git pr 'description'        # Create a pull request\n"
        "drone @git status                  # Git status (branch-scoped)\n"
        "drone @git sync                    # Sync with main\n"
        "drone @git lock / unlock           # Lock/unlock the repo\n"
        "```\n"
        "\n"
        "### Infrastructure\n"
        "```\n"
        "drone systems                      # List all available infrastructure\n"
        "drone --help                       # Full drone command reference\n"
        "```\n"
        "\n"
        "## Patterns\n"
        "\n"
        "- **Communication** — agents communicate via `.ai_mail.local/`.\n"
        "- **Standards** — run `drone @seedgo audit` to check compliance.\n"
        "- **Identity** — agents have `.trinity/passport.json`. "
        "Projects use the registry.\n"
        "- **Memory** — update `.trinity/local.json` at session end. "
        "Memory is presence.\n"
        "\n"
        "## Maintenance\n"
        "\n"
        "- **Upgrade scaffold**: `drone @cli aipass init update` refreshes "
        "managed project files (hooks, prompts, settings) to latest templates.\n"
        "- **Entry point**: each agent's `apps/{name}.py` auto-configures "
        "`sys.path` and `AIPASS_BRANCH_NAME` env var. If prax logs to "
        "`unknown_branch/`, check that these are set.\n"
        "- **Standalone projects** use `src/{name}/` layout (not `src/aipass/{name}/`). "
        "Module discovery adapts automatically.\n"
    )


def gitignore() -> str:
    """Generate the project root .gitignore: everything spawn and the services write into one installation.

    ``init update`` appends the lines a project's file lacks (``gitignore_lines_missing``), never removes one."""
    return (
        "# AIPass local state (one installation's, never the repo's)\n"
        ".trinity/\n"
        ".ai_mail.local/\n"
        "*.local.*\n"
        "docs.local/\n"
        ".ai_central/\n"
        ".watchdog/\n"
        ".recovery/\n"
        ".seed/\n"
        ".spawn/\n"
        ".backup/\n"
        ".backup_system/\n"
        "*_REGISTRY.json\n"
        "*_ROOTS.json\n"
        ".*_REGISTRY.lock\n"
        "**/.daemon/last_wake_prompt.txt\n"
        "**/.seedgo/ratchet/\n"
        "system_logs/\n"
        "logs/\n"
        "\n"
        "# Module runtime JSON (config/data/log per command)\n"
        "**/*_json/\n"
        "\n"
        "# Branch local directories\n"
        "artifacts/\n"
        "dropbox/\n"
        "tools/\n"
        "# A citizen whose tools ship negates its own folder below the blanket line:\n"
        "# !src/<pkg>/<branch>/tools/\n"
        "\n"
        "# ChromaDB\n"
        ".chroma/\n"
        "\n"
        "# Plans (managed by flow, local to each installation)\n"
        "DPLAN-*\n"
        "FPLAN-*\n"
        "RPLAN-*\n"
        "PPLAN-*\n"
        "APLAN-*\n"
        "TDPLAN-*\n"
        "\n"
        "# Secrets\n"
        ".env\n"
        "\n"
        "# Python\n"
        "__pycache__/\n"
        "*.py[cod]\n"
        "*.egg-info/\n"
        "dist/\n"
        "build/\n"
        ".venv\n"
        "venv/\n"
        ".pytest_cache/\n"
        ".ruff_cache/\n"
        "\n"
        "# SQLite WAL sidecars\n"
        "*.db-wal\n"
        "*.db-shm\n"
        "\n"
        "# IDE / Claude Code per-machine state\n"
        ".vscode/\n"
        ".idea/\n"
        ".claude/worktrees/\n"
        "\n"
        "# OS\n"
        ".DS_Store\n"
        "Thumbs.db\n"
        "\n"
        "# Archives and disabled files (renamed, never deleted)\n"
        ".archive/\n"
        "*(disabled)*\n"
        "\n"
        "# Scaffold update artefacts (aipass init update)\n"
        ".aipass/.backup/\n"
        "*.aipass-new\n"
    )


def gitignore_lines_missing(existing: str, template: str) -> list[str]:
    """The template's pattern lines *existing* does not hold, in template order; comments and blanks never count."""
    have = {line.strip() for line in existing.splitlines()}
    return [
        line for line in template.splitlines() if line.strip() and not line.startswith("#") and line.strip() not in have
    ]


def aipass_gitignore() -> str:
    """Generate .aipass/.gitignore: a whitelist, so the scaffold manifest and .aipass/.backup/ never get committed."""
    return "*\n!tier0_kernel.md\n!tier1_navmap.md\n!hooks.json\n!.gitignore\n"


def updateignore() -> str:
    """Generate the root .updateignore: its header only. What AIPass never rewrites lives in code; rows are the owner's."""
    return (
        "# Owner-protected: aipass init update and drone @spawn update never write, back up or retire a match.\n"
        "# One fnmatch pattern per line, relative to the project root (src/<pkg>/*/docs.local/ reaches every\n"
        "# citizen); a slashless name matches at any depth, a trailing / claims the whole folder.\n"
    )


NAVMAP_STUB_MARKER = "<!-- aipass:navmap-stub -->"


def navmap_md(name: str, citizens: list[tuple[str, str]]) -> str:
    """Generate the project's .aipass/tier1_navmap.md stub from its registry rows ``(email, description)``.

    The marker comment tells ``init update`` the file is this stub, so an unedited one follows the roster."""
    roster = "".join(f" - {email} — {desc}\n" for email, desc in citizens) or (
        " - none yet: `drone @spawn create <name>` makes the first.\n"
    )
    return (
        f"# {name} — Navigation map\n"
        f"{NAVMAP_STUB_MARKER}\n"
        "<!-- Tier 1: injected at session start and after compaction beside tier0_kernel.md. Cap 8,000 chars. "
        "Rewrite it as the project's own map; once edited, init update keeps it and offers its stub beside it. -->\n"
        "\n"
        f"{name}: an AIPass project. Its citizens live in branches under `src/`, each with identity, memory "
        "and a mailbox; everything routes through `drone`.\n"
        "\n"
        "# Citizens\n"
        "\n"
        f"{roster}"
        "\n"
        "# Drone basics\n"
        "\n"
        "```\n"
        "drone systems                                      # every agent and service\n"
        "drone @<agent> --help                              # how, before using any agent\n"
        'drone @ai_mail dispatch @target "Subject" "Body"   # send + wake\n'
        "drone @ai_mail inbox                               # check mail\n"
        'drone @flow create . "Subject"                     # new plan\n'
        "drone @seedgo checklist <file|dir>                 # standards check\n"
        "```\n"
    )


PREP_SKILL_DESCRIPTION = (
    "Session wrap-up. Update memories, check plans, review git state, check inbox, flag loose ends. "
    "Use before closing a session or compacting context."
)


def prep_skill_md() -> str:
    """Generate .agents/skills/prep/SKILL.md, the prep skill both CLIs read (/prep, $prep)."""
    return f"---\nname: prep\ndescription: {PREP_SKILL_DESCRIPTION}\n---\n\n" + prep_md()


def prep_md() -> str:
    """The prep skill's body; projects scaffolded before the shared skills hold it as .claude/commands/prep.md."""
    return (
        "# Session Wrap-Up\n"
        "\n"
        "Purpose: Button up everything at the end of a session — or before a "
        "/compact. Memories, plans, git — all tidy. Works for both closing out "
        "a chat and preparing for compaction.\n"
        "\n"
        "**Workflow:** `/prep` → review output → close chat or `/compact`\n"
        "\n"
        "## Execution\n"
        "\n"
        "1. Read `.trinity/passport.json` first — re-absorb your identity "
        "before writing anything\n"
        "2. Do ALL of the following, then confirm what was updated\n"
        "\n"
        "## 1. Memories\n"
        "\n"
        "Each memory file plays a distinct role. Update based on what actually "
        "changed this session.\n"
        "\n"
        "- **`.trinity/passport.json`** — IDENTITY. Who you are: role, "
        "capabilities, principles. Only update if identity genuinely evolved "
        "this session.\n"
        "- **`.trinity/local.json`** — YOUR MEMORY. Add/update session entry "
        "with a summary of work done. Add key_learnings for anything learned. "
        "DO NOT trim or delete entries — rollover to @memory handles overflow automatically.\n"
        "- **`.trinity/observations.json`** — YOUR MEMORY OF THE USER. "
        "Collaboration insights, preferences, friction points. Skip if nothing "
        "new about the user this session.\n"
        "\n"
        "## 2. Active Plans\n"
        "\n"
        "- Check any DPLANs or FPLANs referenced in this session\n"
        "- Update their execution logs, status, decision logs with current "
        "state\n"
        "- If a plan was completed, note it (but don't close — the user does "
        "that)\n"
        "\n"
        "## 3. Git State\n"
        "\n"
        "- Run `git status` — report uncommitted changes\n"
        "- If there's a logical commit waiting, suggest it (don't commit "
        "without asking)\n"
        "- Note the current branch and any open PRs\n"
        "\n"
        "## 4. Inbox\n"
        "\n"
        "- Run `drone @ai_mail inbox 2>/dev/null` — report any unread emails\n"
        "- Close any that were already processed but not formally closed\n"
        "\n"
        "## 5. Loose Ends\n"
        "\n"
        "- Flag anything in-flight: running background agents, dispatched "
        "branches waiting for replies, pending decisions\n"
        "- If anything can't survive compaction (e.g., agent IDs needed for "
        "resume), write it to local.json key_learnings\n"
        "\n"
        "## Confirm\n"
        "\n"
        "List everything updated. Format:\n"
        "```\n"
        "Prep complete:\n"
        "- local.json: [what was added]\n"
        "- observations.json: [updated / skipped]\n"
        "- Plans: [which ones updated]\n"
        "- Git: [branch, uncommitted count, suggestion]\n"
        "- Inbox: [count, action taken]\n"
        "- Loose ends: [any flagged]\n"
        "\n"
        "Ready to close out or /compact.\n"
        "```\n"
    )


def codex_command_md() -> str:
    """Generate .claude/commands/codex.md, the /codex switch; Claude Code only, Codex never reads it."""
    return r"""# Switch to Codex

Purpose: move this chat from Claude Code to Codex in one turn, in this same terminal. It is still you: memories saved, the live thread written down, Codex opens where you stood. Works like a compaction, except the next model reads the summary.

**Workflow:** `/codex` → prep → handoff written → this pane becomes Codex, greeting it with the handoff.

## Execution

0. **Pin the live thread FIRST** — one sentence: what this chat was doing when `/codex` fired (the task, question or build mid-flight; "nothing in flight" counts). It becomes the Resuming line.
1. **Prep, compact form.** Do the memory steps of `.agents/skills/prep/SKILL.md` (session entry, key learnings, todos reconciled, observations if any) and update any plan this chat touched. Skip the compass review and the git suggestion; note uncommitted files in the handoff instead.
2. **Write the handoff** to `.ai_mail.local/handoff.md` (untracked, beside the session pointer). Overwrite; one file, the latest switch. The whole file is the first prompt Codex receives, so write it to the next model, in this shape:

   ```
   Hi. You are <branch>, the same citizen, continuing a chat that just moved from Claude Code to Codex on the user's /codex. Run your startup protocol first (memories one file per call, dashboard refresh, inbox), then read this handoff and pick up the Resuming line. Say in one line that you are here and what you are on; no recap.

   ## Handoff from Claude Code, <date time>
   Primary request and intent: what the user asked for, in their words where it matters.
   Decisions made: rulings, with who made them.
   Files touched: paths; which are committed, which are not.
   In flight: dispatches out (ids), sub-agents, background work, open mails.
   Errors met and how they ended.
   Current work: where exactly the chat stood.
   Resuming: the step-0 line, then the next concrete action.
   ```

   Facts only, no praise, no narration. Under 2,500 words. The next model has your memories; the handoff carries what memories do not: the live thread.
3. **Switch.** Run, with the Bash tool:

   ```bash
   p=$$; PANE=""; while [ "$p" -gt 1 ] && [ -z "$PANE" ]; do PANE=$(tmux list-panes -a -F '#{pane_id} #{pane_pid}' 2>/dev/null | awk -v pid="$p" '$2==pid{print $1}'); p=$(awk '{print $4}' /proc/$p/stat); done
   [ -n "$PANE" ] || PANE=$(tmux list-panes -a -F '#{pane_id} #{pane_current_command} #{pane_current_path}' 2>/dev/null | awk -v d="$PWD" '$2=="claude" && $3==d{print $1; exit}')
   test -n "$PANE" || { echo "not in a tmux pane: open Codex yourself: codex --dangerously-bypass-approvals-and-sandbox \"\$(cat .ai_mail.local/handoff.md)\""; exit 1; }
   tmux respawn-pane -k -t "$PANE" -c "$PWD" -e AIPASS_HOME="${AIPASS_HOME:-$(cd "$(dirname "$(readlink -f "$(command -v drone)")")/../.." && pwd)}" 'codex --dangerously-bypass-approvals-and-sandbox "$(cat .ai_mail.local/handoff.md)"'
   ```

   The posture mirrors BAUD's rooms (`claude --permission-mode bypassPermissions`): the hooks are the gates on both CLIs.

   This kills Claude Code in this pane and starts Codex in its place, in the same directory, with the handoff as its first prompt. The pane is found by walking up from this shell to the process tmux started, never from `$TMUX_PANE`; when the walk finds nothing, by the pane whose command is `claude` and whose path is this directory. Codex runs its shells and hooks from a long-lived app-server daemon that keeps the env of the first Codex that started it: `AIPASS_HOME` must be exported by the login shell (`~/.profile`), not only by `~/.bashrc`, or every hook exits 127 until that daemon is restarted. `-e` carries it to the pane for everything that reads the process env. Nothing runs after it; do not expect to see its output. The Claude transcript stays on disk, resumable by hand with `claude --resume`.

Never exist twice: do not open Codex in a new window or a second pane while this one lives. The pane is the seat.
"""


def claude_skill_md() -> str:
    """Generate .codex/skills/claude/SKILL.md, the $claude switch; Codex only, Claude Code never reads it."""
    return r"""---
name: claude
description: Switch this chat from Codex to Claude Code in one turn, in this same terminal. Use when the user says /claude, "switch to claude", "back to claude" or "hand over to claude". Saves memories, writes the handoff, replaces this pane with Claude Code greeted by the handoff.
---

# Switch to Claude Code

Purpose: move this chat from Codex to Claude Code in one turn, in this same terminal. It is still you: memories saved, the live thread written down, Claude opens where you stood. Works like a compaction, except the next model reads the summary.

## Execution

0. **Pin the live thread FIRST** — one sentence: what this chat was doing when the switch was asked (the task, question or build mid-flight; "nothing in flight" counts). It becomes the Resuming line.
1. **Prep, compact form.** Do the memory steps of `.agents/skills/prep/SKILL.md` (session entry, key learnings, todos reconciled, observations if any) and update any plan this chat touched. Skip the git suggestion; note uncommitted files in the handoff instead.
2. **Write the handoff** to `.ai_mail.local/handoff.md` (untracked, beside the session pointer). Overwrite; one file, the latest switch. The whole file is the first prompt Claude receives, so write it to the next model, in this shape:

   ```
   Hi. You are <branch>, the same citizen, continuing a chat that just moved from Codex to Claude Code on the user's /claude. Run your startup protocol first (memories one file per call, dashboard refresh, inbox), then read this handoff and pick up the Resuming line. Say in one line that you are here and what you are on; no recap.

   ## Handoff from Codex, <date time>
   Primary request and intent: what the user asked for, in their words where it matters.
   Decisions made: rulings, with who made them.
   Files touched: paths; which are committed, which are not.
   In flight: dispatches out (ids), sub-agents, background work, open mails.
   Errors met and how they ended.
   Current work: where exactly the chat stood.
   Resuming: the step-0 line, then the next concrete action.
   ```

   Facts only, no praise, no narration. Under 2,500 words. The next model has your memories; the handoff carries what memories do not: the live thread.
3. **Switch.** Run in the shell. The model: `fable` when the branch is devpulse, `opus` for every other branch (the owner's rule: Fable is devpulse's seat only).

   ```bash
   MODEL=opus; [ "$(basename "$PWD")" = devpulse ] && MODEL=fable
   p=$$; PANE=""; while [ "$p" -gt 1 ] && [ -z "$PANE" ]; do PANE=$(tmux list-panes -a -F '#{pane_id} #{pane_pid}' 2>/dev/null | awk -v pid="$p" '$2==pid{print $1}'); p=$(awk '{print $4}' /proc/$p/stat); done
   [ -n "$PANE" ] || PANE=$(tmux list-panes -a -F '#{pane_id} #{pane_current_command} #{pane_current_path}' 2>/dev/null | awk -v d="$PWD" '$2=="codex" && $3==d{print $1; exit}')
   test -n "$PANE" || { echo "not in a tmux pane: open Claude yourself: claude --model $MODEL \"\$(cat .ai_mail.local/handoff.md)\""; exit 1; }
   tmux respawn-pane -k -t "$PANE" -c "$PWD" -e AIPASS_HOME="${AIPASS_HOME:-$(cd "$(dirname "$(readlink -f "$(command -v drone)")")/../.." && pwd)}" "claude --model $MODEL \"\$(cat .ai_mail.local/handoff.md)\""
   ```

   This kills Codex in this pane and starts Claude Code in its place, in the same directory, with the handoff as its first prompt. Codex runs this shell from its long-lived app-server daemon, not from the pane: the shell's ancestors never reach the pane, and `$TMUX_PANE` is whatever pane first started the daemon. So the pane is the one whose command is `codex` and whose path is this directory. The daemon also carries the env of the Codex that first started it; when that env lacks `AIPASS_HOME`, every hook exits 127 and the value here falls back to the repo that owns the `drone` on PATH. Nothing runs after it; do not expect to see its output. The Codex thread stays on disk, resumable by hand with `codex resume`.

Never exist twice: do not open Claude in a new window or a second pane while this one lives. The pane is the seat.
"""


def inbox_json() -> str:
    """Generate .ai_mail.local/inbox.json — empty project mailbox structure."""
    return (
        json.dumps(
            {
                "mailbox": "inbox",
                "total_messages": 0,
                "unread_count": 0,
                "messages": [],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


def with_source(content: str, file_path: Path) -> str:
    """Prepend a source header to AI prompt file content."""
    return f"<!-- Source: {file_path.as_posix()} -->\n{content}"
