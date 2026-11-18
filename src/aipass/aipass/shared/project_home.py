# =================== AIPass ====================
# Name: project_home.py
# Description: Shared AIPass-home detection, project-path validation, and settings content
# Version: 1.5.0
# Created: 2026-07-21
# Modified: 2026-11-17
# =============================================

"""Project home — AIPASS_HOME detection, path validation, settings content.

One copy per helper for init, new and adopt. Logs through prax; no branch but prax loads at import.
"""

import json
import os
import tempfile
from pathlib import Path

from aipass.aipass.shared.scaffold_content import agents_md
from aipass.prax import logger


def is_throwaway_path(path: str | Path) -> bool:
    """True if path is under a temp dir or Claude Code scratchpad."""
    resolved = str(Path(path).resolve())
    tmp_roots = [tempfile.gettempdir()]
    tmp_roots.append("/tmp")
    for root in tmp_roots:
        r = str(Path(root).resolve())
        if resolved == r or resolved.startswith(r + os.sep):
            return True
    if "scratchpad" in resolved.lower():
        return True
    return False


def _detect_aipass_home() -> str | None:
    """The AIPass home drone's resolve_aipass_home names; None, logged as an ERROR, and every caller refuses."""
    from aipass.drone import resolve_aipass_home

    if (home := resolve_aipass_home()).path is None:
        logger.error("No AIPass home found (tried: %s); set AIPASS_HOME=/path/to/AIPass", "; ".join(home.tried))
    return None if home.path is None else str(home.path)


def _claude_settings() -> str:
    """Generate .claude/settings.json — permissions only, no machine-local paths.

    No hooks (provider settings carry them) and no AIPASS_HOME: it is machine-local, so it
    goes in the gitignored settings.local.json (claude_local_settings)."""
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


def claude_md_excludes(aipass_home: str) -> list[str]:
    """Absolute POSIX paths of the host instruction files a nested project must fence out.

    Claude Code loads every ancestor AGENTS.md and CLAUDE.md regardless of git; the CLAUDE.md
    pair covers a host clone that still has one. claude_local_settings writes this fence."""
    home = Path(aipass_home)
    return [
        (home / "CLAUDE.md").as_posix(),
        (home / ".claude" / "CLAUDE.md").as_posix(),
        (home / "AGENTS.md").as_posix(),
        (home / ".claude" / "AGENTS.md").as_posix(),
    ]


def agents_md_seed(name: str, aipass_home: str | None) -> str:
    """A project's AGENTS.md, the template ``init update`` manages it against: ``.aipass/project_AGENTS.md``
    with ``{name}`` filled, else the host root ``AGENTS.md``, else the generated ``agents_md``."""
    if aipass_home:
        home = Path(aipass_home)
        template = home / ".aipass" / "project_AGENTS.md"
        if template.is_file():
            return template.read_text(encoding="utf-8").replace("{name}", name)
        host_file = home / "AGENTS.md"
        if host_file.is_file():
            return host_file.read_text(encoding="utf-8")
    return agents_md(name)


def _normalize_exclude(entry: str) -> str:
    """Separator-insensitive form for comparing claudeMdExcludes entries.

    A backslash fence written by hand must still count; user-authored values are never rewritten."""
    return entry.replace("\\", "/")


AUTO_COMPACT_WINDOW = 350000


def claude_local_settings(aipass_home: str, *, nested: bool = False) -> str:
    """Generate .claude/settings.local.json — machine-local env (gitignored).

    *nested* (under ``<host>/projects/<name>``) also emits ``claudeMdExcludes``. ``autoCompactWindow`` is the
    manager seat's default; the settings gate refuses the seat itself, and a merge never adds it to an existing file."""
    data: dict = {"env": {"AIPASS_HOME": aipass_home}, "autoCompactWindow": AUTO_COMPACT_WINDOW}
    if nested:
        data["claudeMdExcludes"] = claude_md_excludes(aipass_home)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def merge_local_settings(existing: dict, generated: dict) -> dict:
    """Merge generated .claude/settings.local.json content into existing (retrofit-safe).

    Unions ``env`` and ``claudeMdExcludes``, so a hand-edited file is never clobbered."""
    merged = dict(existing)

    merged_env = {**existing.get("env", {}), **generated.get("env", {})}
    if merged_env:
        merged["env"] = merged_env

    combined_excludes = list(existing.get("claudeMdExcludes", []))
    seen = {_normalize_exclude(e) for e in combined_excludes}
    for item in generated.get("claudeMdExcludes", []):
        if _normalize_exclude(item) not in seen:
            combined_excludes.append(item)
            seen.add(_normalize_exclude(item))
    if combined_excludes:
        merged["claudeMdExcludes"] = combined_excludes

    return merged


def _enroll_project(target: Path) -> bool:
    """Enroll a project in the trusted-project registry: True enrolled, False skipped (throwaway) or refused.

    hooks is imported here, not at the top, so @spawn's process never loads it; it ships in the same
    wheel, so an ImportError is a broken install and raises."""
    if is_throwaway_path(target):
        logger.info("Skipping trust enrollment for throwaway path: %s", target)
        return False
    from aipass.hooks import enroll

    if enroll(str(target)):
        logger.info("Enrolled project in trust registry: %s", target)
        return True
    logger.warning("Trust enrollment failed for %s", target)
    return False


def not_enrolled_note(target: Path) -> str:
    """What a caller shows when _enroll_project did not return True: the project's hooks stay off."""
    return f"Not in the trust registry, so its hooks stay inactive: aipass trust {target}"


def is_projects_child(target: Path) -> bool:
    """True if *target* is ``<host>/projects/<name>`` — a valid nested project path.

    An unreadable host raises RuntimeError, not a 'no': init and adopt catch it and print it."""
    resolved = target.resolve()
    if resolved.parent.name != "projects":
        return False
    host = resolved.parent.parent
    try:
        return any(f.is_file() and f.name.endswith("_REGISTRY.json") for f in host.iterdir())
    except OSError as exc:
        logger.info("is_projects_child: could not read host dir %s: %s", host, exc)
        raise RuntimeError(f"Could not read {host} to tell whether {target} is its projects/ child: {exc}") from exc


def find_fenceless_projects(aipass_home: str) -> list[Path]:
    """Nested ``<aipass_home>/projects/<name>`` dirs missing the instruction-file ancestor fence.

    Fenceless: ``.claude/settings.local.json`` missing, unparseable or lacking the excludes; unreadable raises."""
    projects_dir = Path(aipass_home) / "projects"
    if not projects_dir.is_dir():
        return []
    expected = set(claude_md_excludes(aipass_home))
    fenceless: list[Path] = []
    for child in sorted(projects_dir.iterdir()):
        if not child.is_dir():
            continue
        try:
            is_project = any(f.is_file() and f.name.endswith("_REGISTRY.json") for f in child.iterdir())
        except OSError as exc:
            logger.warning("find_fenceless_projects: could not read %s: %s", child, exc)
            raise RuntimeError(f"Could not read {child} to tell whether it is fenced: {exc}") from exc
        if not is_project:
            continue
        local_settings = child / ".claude" / "settings.local.json"
        if not local_settings.is_file():
            fenceless.append(child)
            continue
        try:
            data = json.loads(local_settings.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.info("find_fenceless_projects: unparseable %s: %s", local_settings, exc)
            fenceless.append(child)
            continue
        present = {_normalize_exclude(e) for e in data.get("claudeMdExcludes", [])}
        if not {_normalize_exclude(e) for e in expected}.issubset(present):
            fenceless.append(child)
    return fenceless


NO_HOME = "No AIPass home found, so nothing was written: set AIPASS_HOME=/path/to/AIPass and run it again"
