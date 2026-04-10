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

Projects are NOT citizens — no .trinity/ directory. Identity lives in the
registry JSON. Init is re-runnable: existing files are skipped, not errors.

RULES:
  - Pure Python only (no module/prax/cli imports)
  - Returns dict, raises exceptions on errors
  - No hardcoded paths
"""

import json
import re
import uuid
from datetime import date
from pathlib import Path


def _sanitize_name(raw: str) -> str:
    """Sanitize a project name for use in filenames.

    Replaces non-alphanumeric characters (except underscore/hyphen) with
    underscores and strips leading/trailing underscores.
    """
    return re.sub(r"[^A-Z0-9_-]", "_", raw.upper()).strip("_")


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
        "cd my_agent/\n"
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
        "## Terminology\n"
        "\n"
        "- **Project** — this directory. Contains a registry and agents.\n"
        "- **Agent** — a citizen with identity (`.trinity/`), memory, mailbox, "
        "and code (`apps/`).\n"
        f"- **Registry** — `{name}_REGISTRY.json` tracks all agents.\n"
        "\n"
        "## Commands\n"
        "\n"
        "```\n"
        "aipass init agent <name>           # Create a new agent\n"
        "drone @spawn create <name>         # Create agent (alternative)\n"
        "drone @seedgo audit <project>      # Standards audit\n"
        "drone @ai_mail inbox               # Check mailbox\n"
        "drone @flow create . \"Subject\"     # Create a plan\n"
        "drone systems                      # List infrastructure\n"
        "```\n"
        "\n"
        "## Patterns\n"
        "\n"
        "- **Communication** — agents communicate via `.ai_mail.local/`.\n"
        "- **Standards** — run `drone @seedgo audit` to check compliance.\n"
        "- **Identity** — agents have `.trinity/passport.json`. "
        "Projects use the registry.\n"
    )


def _gitignore() -> str:
    """Generate .gitignore content — standard AIPass ignores."""
    return (
        "# AIPass local state\n"
        ".trinity/\n"
        ".ai_mail.local/\n"
        "*.local.*\n"
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


def _claude_settings() -> str:
    """Generate .claude/settings.json — minimal hooks for prompt injection."""
    return json.dumps(
        {
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
                    }
                ]
            }
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"


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
        raise ValueError(
            f"Cannot derive project name from '{raw_name}'. "
            "Pass a project name explicitly."
        )

    registry_id = str(uuid.uuid4())
    today = date.today().isoformat()
    created = []

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
        global_prompt_path.write_text(_global_prompt_md(name), encoding="utf-8")
        created.append(str(global_prompt_path))

    # 3. CLAUDE.md
    claude_md_path = target / "CLAUDE.md"
    if not claude_md_path.exists():
        claude_md_path.write_text(_claude_md(name), encoding="utf-8")
        created.append(str(claude_md_path))

    # 4. AGENTS.md (Codex)
    agents_md_path = target / "AGENTS.md"
    if not agents_md_path.exists():
        agents_md_path.write_text(_agents_md(name), encoding="utf-8")
        created.append(str(agents_md_path))

    # 5. GEMINI.md
    gemini_md_path = target / "GEMINI.md"
    if not gemini_md_path.exists():
        gemini_md_path.write_text(_gemini_md(name), encoding="utf-8")
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
            f"# {name}\n\n"
            "**State:** New\n"
            f"**Last update:** {today}\n\n"
            "## Current Work\n\n"
            "## Known Issues\n"
            "- None\n",
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
        settings_path.write_text(_claude_settings(), encoding="utf-8")
        created.append(str(settings_path))

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

    return {
        "registry_id": registry_id,
        "registry_file": registry_filename,
        "project_name": name,
        "target": str(target),
        "created_files": created,
    }
