# =================== AIPass ====================
# Name: discovery_handler.py
# Description: Handler for module and command discovery
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Handler for module and command discovery.

All subprocess execution, file I/O, and text parsing for branch
introspection lives here. Returns data structures, not formatted strings.
"""

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.prax.apps.modules.logger import system_logger
from .exceptions import CommandExecutionError
from aipass.drone.apps.handlers.json import json_handler

logger = system_logger


@dataclass
class HelpResult:
    """Structured result from a help query."""

    branch: str
    command: Optional[str]
    text: str
    commands_found: List[str] = field(default_factory=list)


def get_entry_point(branch_path: str, branch_name: str) -> Optional[Path]:
    """Return the apps/{branch_name}.py entry point path if it exists."""
    entry_point = Path(branch_path) / "apps" / f"{branch_name}.py"
    return entry_point if entry_point.exists() else None


def scan_modules_directory(branch_path: str) -> List[str]:
    """Scan apps/modules/ for .py files and return their stems as command names."""
    modules_dir = Path(branch_path) / "apps" / "modules"
    if not modules_dir.is_dir():
        return []

    excluded = {"__init__", "__main__"}
    return sorted(
        f.stem
        for f in modules_dir.glob("*.py")
        if f.stem not in excluded
    )


def parse_help_for_commands(help_text: str) -> List[str]:
    """Parse --help output to extract a list of available commands."""
    commands: List[str] = []
    in_commands_section = False
    section_markers = {"commands", "subcommands", "available commands"}

    for line in help_text.splitlines():
        stripped = line.strip()

        if any(marker in stripped.lower() for marker in section_markers):
            in_commands_section = True
            continue

        if in_commands_section and not stripped:
            in_commands_section = False
            continue

        if in_commands_section:
            if line.startswith((" ", "\t")) and stripped:
                token = stripped.split()[0]
                if not token.startswith("-"):
                    commands.append(token)

    return commands


def discover_modules(branch_path: str, branch_name: str) -> List[str]:
    """Discover available commands for a branch.

    Args:
        branch_path: Absolute path to the branch directory
        branch_name: Branch name (without @ prefix)

    Returns:
        List of discovered command names
    """
    entry_point = get_entry_point(branch_path, branch_name)
    if entry_point is not None:
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

            commands = parse_help_for_commands(help_text)
            if commands:
                json_handler.log_operation("discover_modules", {"branch": branch_name, "count": len(commands)})
                return commands
        except (subprocess.TimeoutExpired, OSError):
            pass

    modules = scan_modules_directory(branch_path)
    json_handler.log_operation("discover_modules", {"branch": branch_name, "count": len(modules), "source": "scan"})
    return modules


def get_help(branch_path: str, branch_name: str, command: Optional[str] = None) -> HelpResult:
    """Get structured help for a branch or a specific command.

    Args:
        branch_path: Absolute path to the branch directory
        branch_name: Branch name (without @ prefix)
        command: Optional specific command to get help for

    Returns:
        HelpResult with structured help data

    Raises:
        CommandExecutionError: If entry point not found or execution fails
    """
    entry_point = get_entry_point(branch_path, branch_name)
    if entry_point is None:
        raise CommandExecutionError(
            f"Entry point not found for branch '{branch_name}': "
            f"{Path(branch_path) / 'apps' / (branch_name + '.py')}"
        )

    relative_entry = str(entry_point.relative_to(branch_path))
    if command is None:
        cmd_args = [relative_entry, "--help"]
    else:
        cmd_args = [relative_entry, command, "--help"]

    try:
        result = subprocess.run(
            [sys.executable] + cmd_args,
            cwd=branch_path,
            capture_output=True,
            timeout=10,
            shell=False,
        )
    except subprocess.TimeoutExpired as e:
        raise CommandExecutionError(
            f"Help command timed out for branch '{branch_name}'"
        ) from e
    except OSError as e:
        raise CommandExecutionError(
            f"OS error getting help for branch '{branch_name}': {e}"
        ) from e

    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")

    text = stdout if stdout.strip() else stderr
    commands_found = parse_help_for_commands(text)

    return HelpResult(
        branch=branch_name,
        command=command,
        text=text,
        commands_found=commands_found,
    )


def get_system_help(active_branches: List[str]) -> Dict[str, HelpResult]:
    """Aggregate help across a list of branches.

    Args:
        active_branches: List of branch symbolic names (with @ prefix)

    Returns:
        Dict mapping branch names to their HelpResult
    """
    # Import here to avoid circular imports - resolver needs registry_handler
    from aipass.drone.apps.handlers.registry_handler import load_registry

    results: Dict[str, HelpResult] = {}

    for symbolic_name in active_branches:
        branch_name = symbolic_name.lstrip("@")
        try:
            registry = load_registry()
            branch = registry.get("branches", {}).get(branch_name.lower())
            if branch is None:
                continue
            branch_path = branch["path"]
            help_result = get_help(branch_path, branch_name)
            results[branch_name] = help_result
        except Exception as exc:
            logger.info(
                "get_system_help: skipping branch '%s': %s",
                branch_name, exc,
            )

    return results
