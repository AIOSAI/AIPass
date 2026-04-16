# =================== AIPass ====================
# Name: scanner.py
# Description: Module scanning for command discovery
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""Core scanning logic for discovering available commands in a branch.

Combines two discovery strategies:
1. Run the branch entry point with ``--help`` and parse the output.
2. Scan ``apps/modules/*.py`` for files containing ``handle_command()``.

Results are merged and deduplicated, then returned as a flat list of dicts
suitable for display or downstream activation.

Reuses existing discovery-handler functions where possible.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.discovery_handler import (
    get_entry_point,
    parse_help_for_commands,
)


# ---------------------------------------------------------------------------
# Help-output scanning
# ---------------------------------------------------------------------------


def scan_help_output(branch_path: str, branch_name: str) -> list[dict]:
    """Run the branch entry point with ``--help`` and parse discovered commands.

    Args:
        branch_path: Absolute path to the branch directory.
        branch_name: Branch name (without ``@`` prefix).

    Returns:
        List of command dicts ``{"name": ..., "description": ..., "source": "help"}``.
    """
    entry_point = get_entry_point(branch_path, branch_name)
    if entry_point is None:
        return []

    try:
        result = subprocess.run(
            [sys.executable, str(entry_point.relative_to(branch_path)), "--help"],
            cwd=branch_path,
            capture_output=True,
            timeout=10,
            shell=False,
        )
        help_text = result.stdout.decode("utf-8", errors="replace")
        if not help_text:
            help_text = result.stderr.decode("utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.info("scan_help_output: entry point execution failed for %s: %s", branch_name, exc)
        return []

    command_names = parse_help_for_commands(help_text)

    # Build richer dicts by re-scanning the help text for descriptions
    description_map = _extract_descriptions(help_text, command_names)

    return [
        {
            "name": name,
            "description": description_map.get(name, ""),
            "source": "help",
        }
        for name in command_names
    ]


def _extract_descriptions(help_text: str, command_names: list[str]) -> dict[str, str]:
    """Best-effort extraction of one-line descriptions from help text.

    Looks for lines like ``  command_name   Description text`` and pairs
    the first token with the rest of the line.
    """
    descriptions: dict[str, str] = {}
    name_set = set(command_names)

    for line in help_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        if len(parts) == 2 and parts[0] in name_set:
            descriptions[parts[0]] = parts[1].strip()

    return descriptions


# ---------------------------------------------------------------------------
# Module-file scanning
# ---------------------------------------------------------------------------


def scan_module_files(branch_path: str) -> list[dict]:
    """Scan ``apps/modules/*.py`` for files that define ``handle_command()``.

    Args:
        branch_path: Absolute path to the branch directory.

    Returns:
        List of command dicts ``{"name": ..., "description": ..., "source": "module"}``.
    """
    modules_dir = Path(branch_path) / "apps" / "modules"
    if not modules_dir.is_dir():
        return []

    excluded = {"__init__", "__main__"}
    results: list[dict] = []

    for py_file in sorted(modules_dir.glob("*.py")):
        if py_file.stem in excluded:
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except OSError:
            logger.warning("scan_module_files: could not read %s", py_file)
            continue

        if "def handle_command" not in source:
            continue

        # Extract a description from the module docstring (first line).
        description = _extract_module_description(source)

        results.append(
            {
                "name": py_file.stem,
                "description": description,
                "source": "module",
            }
        )

    return results


def _extract_module_description(source: str) -> str:
    """Extract the first line of a module-level docstring, if present."""
    for delimiter in ('"""', "'''"):
        idx = source.find(delimiter)
        if idx == -1:
            continue
        start = idx + len(delimiter)
        end = source.find(delimiter, start)
        if end == -1:
            continue
        docstring = source[start:end].strip()
        first_line = docstring.split("\n", 1)[0].strip()
        if first_line:
            return first_line
    return ""


# ---------------------------------------------------------------------------
# Full branch scan (merge + deduplicate)
# ---------------------------------------------------------------------------


def scan_branch(branch_path: str, branch_name: str) -> list[dict]:
    """Perform a full scan of a branch to discover available commands.

    Combines both ``--help`` parsing and ``apps/modules/*.py`` file scanning,
    deduplicates by command name (``--help`` wins on conflict), and returns
    the merged result.

    Args:
        branch_path: Absolute path to the branch directory.
        branch_name: Branch name (without ``@`` prefix).

    Returns:
        List of command dicts with keys ``name``, ``description``, ``source``.
    """
    help_commands = scan_help_output(branch_path, branch_name)
    module_commands = scan_module_files(branch_path)

    # Merge: help results take priority for duplicates.
    seen: dict[str, dict] = {}
    for cmd in help_commands:
        seen[cmd["name"]] = cmd
    for cmd in module_commands:
        if cmd["name"] not in seen:
            seen[cmd["name"]] = cmd

    merged = sorted(seen.values(), key=lambda c: c["name"])

    json_handler.log_operation(
        "scan_branch",
        {
            "branch": branch_name,
            "help_count": len(help_commands),
            "module_count": len(module_commands),
            "total": len(merged),
        },
    )

    return merged
