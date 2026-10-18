# =================== AIPass ====================
# Name: scanner.py
# Description: Module scanning for command discovery
# Version: 1.1.0
# Created: 2026-03-17
# Modified: 2026-10-17
# =============================================

"""Core scanning logic for discovering available commands in a branch."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.discovery_handler import (
    get_entry_point,
    parse_help_for_commands,
)
from aipass.drone.apps.handlers.registry_handler import branch_interpreter


def scan_help_output(branch_path: str, branch_name: str) -> list[dict]:
    """Run the branch entry point with ``--help`` and parse discovered commands.

    Raises TimeoutExpired/OSError rather than return [], which would read as "no commands".
    """
    entry_point = get_entry_point(branch_path, branch_name)
    if entry_point is None:
        return []

    result = subprocess.run(
        [branch_interpreter(branch_path), str(entry_point.relative_to(branch_path)), "--help"],
        cwd=branch_path,
        capture_output=True,
        timeout=10,
        shell=False,
    )
    help_text = result.stdout.decode("utf-8", errors="replace")
    if not help_text:
        help_text = result.stderr.decode("utf-8", errors="replace")

    command_names = parse_help_for_commands(help_text)

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
    """Best-effort extraction of one-line descriptions from help text."""
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


def scan_module_files(branch_path: str) -> list[dict]:
    """Scan ``apps/modules/*.py`` for files that define ``handle_command()``."""
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


def scan_branch(branch_path: str, branch_name: str, help_errors: list[str] | None = None) -> list[dict]:
    """Perform a full scan of a branch to discover available commands.

    ``--help`` wins on a name conflict. A failed ``--help`` scan appends its error to
    ``help_errors`` when given, and the result is then module files only.
    """
    help_error = ""
    try:
        help_commands = scan_help_output(branch_path, branch_name)
    except (subprocess.TimeoutExpired, OSError) as exc:
        help_error = str(exc)
        help_commands = []
        logger.warning("@%s: the --help scan failed (%s); module files only", branch_name, exc)
        if help_errors is not None:
            help_errors.append(help_error)
    module_commands = scan_module_files(branch_path)

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
            "help_error": help_error,
        },
    )

    return merged
