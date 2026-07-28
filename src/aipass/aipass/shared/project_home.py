# =================== AIPass ====================
# Name: project_home.py
# Description: Shared AIPass-home detection, project-path validation, and settings content
# Version: 1.0.0
# Created: 2026-07-21
# Modified: 2026-07-21
# =============================================

"""Project home — AIPASS_HOME detection, path validation, settings content.

Shared across every command that scaffolds or inspects an AIPass project
(`aipass init`, `aipass new`, `aipass adopt`), so there is exactly one
source of truth per helper — no per-command copies to drift apart.

Dependency-free: uses only stdlib. Importable before drone/prax exist.
"""

import importlib.util
import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def is_throwaway_path(path: str | Path) -> bool:
    """True if path is under a temp dir or Claude Code scratchpad."""
    resolved = str(Path(path).resolve())
    tmp_roots = [tempfile.gettempdir()]
    if os.name == "posix":
        tmp_roots.append("/tmp")
    for root in tmp_roots:
        try:
            r = str(Path(root).resolve())
        except OSError:
            logger.info("is_throwaway_path: could not resolve %s", root)
            continue
        if resolved == r or resolved.startswith(r + os.sep):
            return True
    if "scratchpad" in resolved.lower():
        return True
    return False


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


def _claude_settings() -> str:
    """Generate .claude/settings.json — permissions only, no machine-local paths.

    Hooks are NOT wired at the project level. All AIPass hooks
    (prompt injection, identity, email, pre-compact, edit gates) fire
    from provider settings (~/.claude/settings.json), installed by
    setup.sh. Provider hooks use CWD-walking patterns that work from
    any directory in any project.

    AIPASS_HOME is a machine-local absolute path — it never belongs in this
    tracked file. It goes in .claude/settings.local.json instead, which is
    gitignored and merged over tracked settings by Claude Code natively.
    See _claude_local_settings().
    """
    data: dict = {
        "permissions": {
            "deny": [
                "Bash(git push --force*)",
                "Bash(git reset --hard*)",
                "EnterPlanMode",
            ],
        },
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _claude_local_settings(aipass_home: str) -> str:
    """Generate .claude/settings.local.json — machine-local env (gitignored)."""
    return json.dumps({"env": {"AIPASS_HOME": aipass_home}}, indent=2, ensure_ascii=False) + "\n"


def _enroll_project(target: Path) -> bool:
    """Enroll a project in the trusted-project registry (DPLAN-0244).

    Skips throwaway paths (temp dirs, Claude Code scratchpads) so ephemeral
    test/pytest directories never bloat the registry (GH-712).
    Lazy import to keep this module free of prax/module-level deps.
    """
    if is_throwaway_path(target):
        logger.info("Skipping trust enrollment for throwaway path: %s", target)
        return False
    try:
        from aipass.hooks.apps.handlers.config.trust_registry import enroll

        if enroll(str(target)):
            logger.info("Enrolled project in trust registry: %s", target)
            return True
        logger.warning("Trust enrollment failed for %s", target)
        return False
    except ImportError as exc:
        logger.info("Trust registry unavailable, skipping enrollment: %s", exc)
        return False


def is_projects_child(target: Path) -> bool:
    """True if *target* is ``<host>/projects/<name>`` — a valid nested project path.

    The host is identified by having a ``*_REGISTRY.json`` in the grandparent
    of target (i.e. target's parent is named ``projects``).
    """
    resolved = target.resolve()
    if resolved.parent.name != "projects":
        return False
    host = resolved.parent.parent
    try:
        return any(f.is_file() and f.name.endswith("_REGISTRY.json") for f in host.iterdir())
    except OSError as exc:
        logger.info("is_projects_child: could not read host dir %s: %s", host, exc)
        return False
