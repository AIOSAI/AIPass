# =================== AIPass ====================
# Name: bootstrap.py
# Description: Init handler — bootstrap an AIPass project in any directory
# Version: 2.0.0
# Created: 2026-03-14
# Modified: 2026-04-08
# =============================================

"""
Init Bootstrap Handler - PRIVATE implementation

Business logic for `aipass init`. Creates the project scaffold:
   1. {NAME}_REGISTRY.json            — project registry with UUID
   2. .aipass/aipass_global_prompt.md  — global prompt (injected every turn)
   3. CLAUDE.md                       — project prompt (Claude Code reads this)
   4. AGENTS.md                       — Codex equivalent of CLAUDE.md
   5. GEMINI.md                       — Gemini equivalent of CLAUDE.md
   6. README.md                       — getting started guide
   7. STATUS.local.md                 — project status
   8. .gitignore                      — standard AIPass ignores
   9. .claude/settings.json           — Claude Code hooks configuration
  10. hooks/                          — directory for user hooks
  11. src/                            — directory where agents live
  12. .ai_mail.local/inbox.json       — empty project mailbox

Projects are NOT citizens — no .trinity/ directory. Identity lives in the
registry JSON. Init is re-runnable: existing files are skipped, not errors.

RULES:
  - Pure Python only (no module/prax/cli imports)
  - Returns dict, raises exceptions on errors
  - No hardcoded paths
"""

import importlib.util
import json
import logging
import re
import uuid
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


def _sanitize_name(raw: str) -> str:
    """Sanitize a project name for use in filenames.

    Replaces non-alphanumeric characters (except underscore/hyphen) with
    underscores and strips leading/trailing underscores.
    """
    return re.sub(r"[^A-Z0-9_-]", "_", raw.upper()).strip("_")


def _detect_aipass_home() -> str | None:
    """Detect the AIPass installation root from the aipass package location.

    Returns the parent of the src/ directory (the repo root).
    Returns None if detection fails.
    """
    try:
        spec = importlib.util.find_spec("aipass")
        if spec and spec.origin:
            # aipass/__init__.py lives at src/aipass/__init__.py
            # parent = src/aipass/, parent.parent = src/, parent.parent.parent = AIPass root
            return str(Path(spec.origin).resolve().parent.parent.parent)
    except Exception as exc:
        logger.info("AIPASS_HOME detection skipped: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Template content generators
# ---------------------------------------------------------------------------


def _claude_md(name: str) -> str:
    """Generate CLAUDE.md content — Claude Code reads this on startup."""
    return (
        f"# {name}\n"
        "\n"
        "**User:** (your name here)\n"
        "\n"
        "## What is AIPass\n"
        "\n"
        "AIPass is a multi-agent framework. This project was created with `aipass init`.\n"
        "\n"
        "**Key concepts:**\n"
        "- **Project** — this directory. Contains a registry and one or more agents.\n"
        "- **Agent** — a citizen that lives inside the project. Has identity (`.trinity/`), "
        "memory, mailbox, and its own apps/ directory.\n"
        f"- **Registry** — `{name}_REGISTRY.json` tracks all agents in this project.\n"
        "\n"
        "## Getting Started\n"
        "\n"
        "Create your first agent:\n"
        "```\n"
        "aipass init agent <name>\n"
        "```\n"
        "\n"
        "This creates a full agent scaffold inside `src/<name>/` "
        "(`apps/`, `.trinity/`, `.ai_mail.local/`) "
        "and registers it in your project registry.\n"
        "\n"
        "## Available Commands\n"
        "\n"
        "```\n"
        "aipass init agent <name>           # Create a new agent\n"
        "drone @spawn create <name>         # Create agent (alternative)\n"
        "drone @seedgo audit <project>      # Run standards audit\n"
        "drone @ai_mail inbox               # Check mailbox (per-agent)\n"
        "drone systems                      # List all available infrastructure\n"
        "```\n"
        "\n"
        "## Startup Protocol\n"
        "\n"
        "On any greeting, silently read these files — no narration, just do it "
        "and respond with the status.\n"
        "\n"
        f"**Read:** `{name}_REGISTRY.json`, `README.md`, `STATUS.local.md`\n"
        "**Run:** `git status`\n"
        "\n"
        "Then check the registry for agents and report status.\n"
    )


def _agents_md(name: str) -> str:
    """Generate AGENTS.md content — Codex equivalent of CLAUDE.md."""
    return (
        f"# {name} — Agent Instructions\n"
        "\n"
        "This project uses AIPass, a multi-agent framework.\n"
        "\n"
        "## Key Concepts\n"
        "\n"
        "- **Project** — this directory. Contains a registry and one or more agents.\n"
        "- **Agent** — a citizen that lives inside the project with its own identity, "
        "memory, and code.\n"
        f"- **Registry** — `{name}_REGISTRY.json` tracks all agents.\n"
        "\n"
        "## Getting Started\n"
        "\n"
        "Create your first agent:\n"
        "```\n"
        "aipass init agent <name>\n"
        "```\n"
        "\n"
        "## Available Commands\n"
        "\n"
        "```\n"
        "aipass init agent <name>           # Create a new agent\n"
        "drone @spawn create <name>         # Create agent (alternative)\n"
        "drone @seedgo audit <project>      # Run standards audit\n"
        "drone systems                      # List all infrastructure\n"
        "```\n"
        "\n"
        "## Startup\n"
        "\n"
        f"On startup, read: `{name}_REGISTRY.json`, `README.md`, `STATUS.local.md`\n"
    )


def _gemini_md(name: str) -> str:
    """Generate GEMINI.md content — Gemini equivalent of CLAUDE.md."""
    return (
        f"# {name} — Project Instructions\n"
        "\n"
        "This project uses AIPass, a multi-agent framework.\n"
        "\n"
        "## Key Concepts\n"
        "\n"
        "- **Project** — this directory. Contains a registry and one or more agents.\n"
        "- **Agent** — a citizen that lives inside the project with its own identity, "
        "memory, and code.\n"
        f"- **Registry** — `{name}_REGISTRY.json` tracks all agents.\n"
        "\n"
        "## Getting Started\n"
        "\n"
        "Create your first agent: `aipass init agent <name>`\n"
        "\n"
        "## Available Commands\n"
        "\n"
        "```\n"
        "aipass init agent <name>           # Create a new agent\n"
        "drone @spawn create <name>         # Create agent (alternative)\n"
        "drone @seedgo audit <project>      # Run standards audit\n"
        "drone systems                      # List all infrastructure\n"
        "```\n"
        "\n"
        "## Startup\n"
        "\n"
        f"On startup, read: `{name}_REGISTRY.json`, `README.md`, `STATUS.local.md`\n"
    )


def _readme_md(name: str) -> str:
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
        "cd src/my_agent/\n"
        "claude  # or your preferred AI CLI\n"
        "\n"
        "# 3. Check project status\n"
        "cat STATUS.local.md\n"
        "```\n"
        "\n"
        "## Project Structure\n"
        "\n"
        "```\n"
        f"{name.lower()}/\n"
        f"  {name}_REGISTRY.json    # Agent registry\n"
        "  .aipass/                 # Prompts (injected per-turn)\n"
        "  CLAUDE.md               # Claude Code instructions\n"
        "  AGENTS.md               # Codex instructions\n"
        "  GEMINI.md               # Gemini instructions\n"
        "  STATUS.local.md         # Project status\n"
        "  src/                    # Agent directories live here\n"
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


def _global_prompt_md(name: str) -> str:
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
    )


def _gitignore() -> str:
    """Generate .gitignore content — standard AIPass ignores."""
    return (
        "# AIPass local state\n"
        ".trinity/\n"
        ".ai_mail.local/\n"
        "*.local.*\n"
        "!STATUS.local.md\n"
        "\n"
        "# Plans (local working docs)\n"
        "DPLAN-*\n"
        "FPLAN-*\n"
        "APLAN-*\n"
        "TDPLAN-*\n"
        "\n"
        "# Logs\n"
        "logs/\n"
        "\n"
        "# Python\n"
        "__pycache__/\n"
        "*.py[cod]\n"
        "*.egg-info/\n"
        "dist/\n"
        "build/\n"
        ".venv/\n"
        "venv/\n"
        "\n"
        "# IDE\n"
        ".vscode/\n"
        ".idea/\n"
        "\n"
        "# OS\n"
        ".DS_Store\n"
        "Thumbs.db\n"
        "\n"
        "# Archives\n"
        ".archive/\n"
        "\n"
        "# Disabled files\n"
        "*(disabled)*\n"
    )


def _claude_settings(aipass_home: str | None = None) -> str:
    """Generate .claude/settings.json — minimal hooks for prompt injection.

    Installs two UserPromptSubmit hooks:
    1. Global prompt — injects .aipass/aipass_global_prompt.md from CWD.
    2. Local prompt  — walks up from CWD via pathlib.Path.parents to find
       .aipass/aipass_local_prompt.md (cross-platform; works on Windows).

    Args:
        aipass_home: Optional AIPass installation root to add as env.AIPASS_HOME.
    """
    _local_prompt_cmd = (
        'python3 -c "'
        "from pathlib import Path; "
        "p=next((x/'.aipass'/'aipass_local_prompt.md' "
        "for x in [Path.cwd(),*Path.cwd().parents] "
        "if (x/'.aipass'/'aipass_local_prompt.md').exists()),None); "
        "p and print(p.read_text(encoding='utf-8'),end='')"
        '"'
    )
    data: dict = {
        "hooks": {
            "UserPromptSubmit": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "cat .aipass/aipass_global_prompt.md 2>/dev/null || true",
                        }
                    ],
                },
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": _local_prompt_cmd,
                        }
                    ],
                },
            ]
        }
    }
    if aipass_home:
        data["env"] = {"AIPASS_HOME": aipass_home}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _prep_md() -> str:
    """Generate .claude/commands/prep.md — /prep session wrap-up slash command.

    Project-scoped slash command. Sessions wrap up by buttoning up memories,
    plans, git state, inbox, and loose ends. Ships per-project via aipass init
    so every AIPass project has a consistent /prep flow.
    """
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
        "Trim oldest sessions if over 20.\n"
        "- **`.trinity/observations.json`** — YOUR MEMORY OF THE USER. "
        "Collaboration insights, preferences, friction points. Skip if nothing "
        "new about the user this session.\n"
        "- **`STATUS.local.md`** — PUBLIC STATUS BEACON. Current work, known "
        "issues, todos, notepad. Auto-synced to central STATUS.md on PR events "
        "— this is how other branches see you. Keep Current Work accurate.\n"
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
        "resume), write it to STATUS.local.md Notepad\n"
        "\n"
        "## Confirm\n"
        "\n"
        "List everything updated. Format:\n"
        "```\n"
        "Prep complete:\n"
        "- local.json: [what was added]\n"
        "- observations.json: [updated / skipped]\n"
        "- STATUS.local.md: [updated / skipped]\n"
        "- Plans: [which ones updated]\n"
        "- Git: [branch, uncommitted count, suggestion]\n"
        "- Inbox: [count, action taken]\n"
        "- Loose ends: [any flagged]\n"
        "\n"
        "Ready to close out or /compact.\n"
        "```\n"
    )


def _inbox_json() -> str:
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


def _with_source(content: str, file_path: Path) -> str:
    """Prepend a source header to AI prompt file content.

    Args:
        content: The file content to annotate.
        file_path: The absolute path where the file will be written.

    Returns:
        Content with ``<!-- Source: {file_path} -->`` as the first line.
    """
    return f"<!-- Source: {file_path} -->\n{content}"


def init_project(target: Path, project_name: str | None = None) -> dict:
    """Initialize an AIPass project in the target directory.

    Args:
        target: Directory to initialize
        project_name: Name for the registry (defaults to directory name)

    Returns:
        dict with registry_id, registry_file, project_name, target, created_files

    Raises:
        ValueError: If project name is empty after sanitization
    """
    target = target.resolve()
    if not target.exists():
        target.mkdir(parents=True)

    raw_name = project_name or target.name
    name = _sanitize_name(raw_name)
    if not name:
        raise ValueError(f"Cannot derive project name from '{raw_name}'. Pass a project name explicitly.")

    registry_id = str(uuid.uuid4())
    today = date.today().isoformat()
    created = []
    aipass_home = _detect_aipass_home()

    # 1. Registry (skip if exists — init is re-runnable)
    registry_filename = f"{name}_REGISTRY.json"
    registry_path = target / registry_filename
    if registry_path.exists():
        # Read existing registry to get its ID
        existing = json.loads(registry_path.read_text(encoding="utf-8"))
        registry_id = existing["metadata"]["id"]
    else:
        registry_data = {
            "metadata": {
                "id": registry_id,
                "name": name,
                "version": "1.0.0",
                "created": today,
                "last_updated": today,
                "total_branches": 0,
            },
            "branches": [],
        }
        registry_path.write_text(
            json.dumps(registry_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        created.append(str(registry_path))

    # 2. .aipass/
    aipass_dir = target / ".aipass"
    aipass_dir.mkdir(exist_ok=True)

    global_prompt_path = aipass_dir / "aipass_global_prompt.md"
    if not global_prompt_path.exists():
        global_prompt_path.write_text(
            _with_source(_global_prompt_md(name), global_prompt_path),
            encoding="utf-8",
        )
        created.append(str(global_prompt_path))

    # 3. CLAUDE.md
    claude_md_path = target / "CLAUDE.md"
    if not claude_md_path.exists():
        claude_md_path.write_text(
            _with_source(_claude_md(name), claude_md_path),
            encoding="utf-8",
        )
        created.append(str(claude_md_path))

    # 4. AGENTS.md (Codex)
    agents_md_path = target / "AGENTS.md"
    if not agents_md_path.exists():
        agents_md_path.write_text(
            _with_source(_agents_md(name), agents_md_path),
            encoding="utf-8",
        )
        created.append(str(agents_md_path))

    # 5. GEMINI.md
    gemini_md_path = target / "GEMINI.md"
    if not gemini_md_path.exists():
        gemini_md_path.write_text(
            _with_source(_gemini_md(name), gemini_md_path),
            encoding="utf-8",
        )
        created.append(str(gemini_md_path))

    # 6. README.md
    readme_md_path = target / "README.md"
    if not readme_md_path.exists():
        readme_content = _readme_md(name).replace("{date}", today)
        readme_md_path.write_text(readme_content, encoding="utf-8")
        created.append(str(readme_md_path))

    # 7. STATUS.local.md
    status_md_path = target / "STATUS.local.md"
    if not status_md_path.exists():
        status_md_path.write_text(
            f"# {name}\n\n**State:** New\n**Last update:** {today}\n\n## Current Work\n\n## Known Issues\n- None\n",
            encoding="utf-8",
        )
        created.append(str(status_md_path))

    # 8. .gitignore
    gitignore_path = target / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(_gitignore(), encoding="utf-8")
        created.append(str(gitignore_path))

    # 9. .claude/settings.json
    claude_dir = target / ".claude"
    claude_dir.mkdir(exist_ok=True)

    settings_path = claude_dir / "settings.json"
    if not settings_path.exists():
        settings_path.write_text(_claude_settings(aipass_home), encoding="utf-8")
        created.append(str(settings_path))

    # 9b. .claude/commands/prep.md — /prep session wrap-up slash command
    commands_dir = claude_dir / "commands"
    commands_dir.mkdir(exist_ok=True)
    prep_path = commands_dir / "prep.md"
    if not prep_path.exists():
        prep_path.write_text(_prep_md(), encoding="utf-8")
        created.append(str(prep_path))

    # 10. hooks/ directory
    hooks_dir = target / "hooks"
    if not hooks_dir.exists():
        hooks_dir.mkdir()
        created.append(str(hooks_dir))

    # 11. src/ directory (where agents live)
    src_dir = target / "src"
    if not src_dir.exists():
        src_dir.mkdir()
        created.append(str(src_dir))

    # 12. .ai_mail.local/inbox.json — empty project mailbox
    mail_dir = target / ".ai_mail.local"
    mail_dir.mkdir(exist_ok=True)
    inbox_path = mail_dir / "inbox.json"
    if not inbox_path.exists():
        inbox_path.write_text(_inbox_json(), encoding="utf-8")
        created.append(str(inbox_path))

    return {
        "registry_id": registry_id,
        "registry_file": registry_filename,
        "project_name": name,
        "target": str(target),
        "created_files": created,
        "aipass_home": aipass_home,
    }


def update_project(target: Path) -> dict:
    """Update managed scaffold files in an existing AIPass project.

    Overwrites managed prompt and config files with the latest templates while
    leaving all user-owned files (registry, README, STATUS.local.md, .gitignore,
    hooks/, src/) untouched.

    Args:
        target: Directory containing the AIPass project to update.

    Returns:
        dict with project_name, target, updated_files, skipped_files.

    Raises:
        ValueError: If no ``*_REGISTRY.json`` is found in target (not an AIPass
            project or init has not been run yet).
    """
    target = target.resolve()

    # Locate the project registry to confirm this is an AIPass project and
    # derive the project name without parsing JSON (filename encodes the name).
    registry_files = list(target.glob("*_REGISTRY.json"))
    if not registry_files:
        raise ValueError("No AIPass project found — run 'aipass init' first")
    registry_path = registry_files[0]
    name = registry_path.stem.replace("_REGISTRY", "")

    updated: list[str] = []
    already_current: list[str] = []
    skipped: list[str] = []
    aipass_home: str | None = None

    # Managed directories — create if missing (graceful recovery).
    aipass_dir = target / ".aipass"
    aipass_dir.mkdir(exist_ok=True)

    claude_dir = target / ".claude"
    claude_dir.mkdir(exist_ok=True)

    # --- Managed files: write only when content has changed ---

    global_prompt_path = aipass_dir / "aipass_global_prompt.md"
    generated = _with_source(_global_prompt_md(name), global_prompt_path)
    if not global_prompt_path.exists() or global_prompt_path.read_text(encoding="utf-8") != generated:
        global_prompt_path.write_text(generated, encoding="utf-8")
        updated.append(str(global_prompt_path))
    else:
        already_current.append(str(global_prompt_path))

    # settings.json — smart merge: preserve existing AIPASS_HOME, detect if missing
    settings_path = claude_dir / "settings.json"
    if not settings_path.exists():
        aipass_home = _detect_aipass_home()
        settings_path.write_text(_claude_settings(aipass_home), encoding="utf-8")
        updated.append(str(settings_path))
    else:
        existing_content = settings_path.read_text(encoding="utf-8")
        try:
            existing_env = json.loads(existing_content).get("env", {})
        except json.JSONDecodeError as exc:
            logger.info("settings.json parse failed, rebuilding: %s", exc)
            existing_env = {}
        # Preserve existing AIPASS_HOME; detect and add if missing
        aipass_home = existing_env.get("AIPASS_HOME") or _detect_aipass_home()
        generated = _claude_settings(aipass_home)
        if existing_content != generated:
            settings_path.write_text(generated, encoding="utf-8")
            updated.append(str(settings_path))
        else:
            already_current.append(str(settings_path))

    claude_md_path = target / "CLAUDE.md"
    generated = _with_source(_claude_md(name), claude_md_path)
    if not claude_md_path.exists() or claude_md_path.read_text(encoding="utf-8") != generated:
        claude_md_path.write_text(generated, encoding="utf-8")
        updated.append(str(claude_md_path))
    else:
        already_current.append(str(claude_md_path))

    agents_md_path = target / "AGENTS.md"
    generated = _with_source(_agents_md(name), agents_md_path)
    if not agents_md_path.exists() or agents_md_path.read_text(encoding="utf-8") != generated:
        agents_md_path.write_text(generated, encoding="utf-8")
        updated.append(str(agents_md_path))
    else:
        already_current.append(str(agents_md_path))

    gemini_md_path = target / "GEMINI.md"
    generated = _with_source(_gemini_md(name), gemini_md_path)
    if not gemini_md_path.exists() or gemini_md_path.read_text(encoding="utf-8") != generated:
        gemini_md_path.write_text(generated, encoding="utf-8")
        updated.append(str(gemini_md_path))
    else:
        already_current.append(str(gemini_md_path))

    # .claude/commands/prep.md — managed slash command, refresh to latest
    commands_dir = claude_dir / "commands"
    commands_dir.mkdir(exist_ok=True)
    prep_path = commands_dir / "prep.md"
    generated = _prep_md()
    if not prep_path.exists() or prep_path.read_text(encoding="utf-8") != generated:
        prep_path.write_text(generated, encoding="utf-8")
        updated.append(str(prep_path))
    else:
        already_current.append(str(prep_path))

    # --- User-owned files: always skip ---
    for skip_name in (
        str(registry_path),
        str(target / "README.md"),
        str(target / "STATUS.local.md"),
        str(target / ".gitignore"),
    ):
        skipped.append(skip_name)

    # Mailbox — create if missing, never overwrite existing
    mail_dir = target / ".ai_mail.local"
    mail_dir.mkdir(exist_ok=True)
    inbox_path = mail_dir / "inbox.json"
    if not inbox_path.exists():
        inbox_path.write_text(_inbox_json(), encoding="utf-8")
        updated.append(str(inbox_path))
    else:
        skipped.append(str(inbox_path))

    return {
        "project_name": name,
        "target": str(target),
        "updated_files": updated,
        "already_current": already_current,
        "skipped_files": skipped,
        "aipass_home": aipass_home,
    }
