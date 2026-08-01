# =================== AIPass ====================
# Name: _doctor_fix.py
# Description: Structure remediation report for aipass doctor --fix
# Version: 1.0.0
# Created: 2026-05-15
# Modified: 2026-05-15
# =============================================

"""
doctor_fix — structure remediation report for aipass doctor --fix

Generates remediation items from structure scan results and formats
them as human-readable text or machine-readable JSON with exact
`drone @spawn repair` commands.

Run: aipass doctor --fix [--json]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, NamedTuple

from aipass.cli.apps.modules import console
from aipass.prax import logger

from aipass.aipass.shared.registry_discovery import find_registry as _discover_registry

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.structure_scan.structure_scanner import (
    check_placement,
    check_pyproject,
    check_registry_consistency,
    check_root_artifacts,
    detect_pollution,
    scan_agents,
)


# =============================================================================
# TYPES
# =============================================================================


class RemediationItem(NamedTuple):
    """Single remediation suggestion with severity and spawn command."""

    severity: str
    category: str
    description: str
    fix_command: str


# =============================================================================
# PROJECT NAME DETECTION
# =============================================================================


def detect_project_name(project_root: Path) -> str:
    """Derive project name from registry filename or directory name."""
    reg = _discover_registry(start_path=project_root)
    if reg and reg.exists():
        name = reg.stem.replace("_REGISTRY", "").lower()
        if name:
            return name
    return project_root.name.lower()


# =============================================================================
# REMEDIATION GENERATION
# =============================================================================


def _build_pollution_items(agents: list, project: str) -> List[RemediationItem]:
    """Build remediation items for pollution issues."""
    items: List[RemediationItem] = []
    for hit in detect_pollution(agents):
        items.append(
            RemediationItem(
                severity="critical",
                category="pollution",
                description=(f"Registry pollution: {hit.agent_name} found at {len(hit.locations)} locations"),
                fix_command=f"drone @spawn repair @{project} --clean-pollution --apply",
            )
        )
    return items


def _build_placement_items(agents: list, project_root: Path, project: str) -> List[RemediationItem]:
    """Build remediation items for placement issues."""
    items: List[RemediationItem] = []
    for issue in check_placement(agents, project_root):
        try:
            rel_path = str(Path(issue.actual_path).relative_to(project_root))
        except ValueError:
            logger.info("[doctor_fix] agent %s path not relative to root: %s", issue.agent_name, issue.actual_path)
            rel_path = issue.actual_path
        suggested = f"src/{project}/{issue.agent_name}/"
        items.append(
            RemediationItem(
                severity="warning",
                category="placement",
                description=f"Misplaced agent: {issue.agent_name} at {rel_path}",
                fix_command=f"drone @spawn repair @{project} --relocate {rel_path} {suggested} --apply",
            )
        )
    return items


def _build_registry_items(project_root: Path, agents: list, project: str) -> List[RemediationItem]:
    """Build remediation items for registry consistency issues."""
    items: List[RemediationItem] = []
    reg_path = _discover_registry(start_path=project_root)
    if not reg_path or not reg_path.exists():
        return items
    for issue in check_registry_consistency(reg_path, agents):
        items.append(
            RemediationItem(
                severity="warning",
                category="registry",
                description=f"Registry {issue.problem}: {issue.branch_name} at {issue.registered_path}",
                fix_command=f"drone @spawn repair @{project} --dedup-registry --apply",
            )
        )
    return items


def _build_root_artifact_items(project_root: Path, project: str) -> List[RemediationItem]:
    """Remediation items for stray root-level artifacts."""
    items: List[RemediationItem] = []
    for hit in check_root_artifacts(project_root):
        severity = "info" if hit.severity == "info" else "warning"
        if hit.name == ".venv":
            # Wired hooks reference AIPASS_HOME/.venv/bin/python3 by absolute path —
            # --relocate-root would move it and break every hook. Not implemented
            # in spawn repair for this reason; surface a manual-review note instead.
            fix_command = "Manual review only — relocating .venv breaks hooks wired to AIPASS_HOME/.venv/bin/python3"
        else:
            fix_command = f"drone @spawn repair @{project} --relocate-root {hit.name} --apply"
        items.append(
            RemediationItem(
                severity=severity,
                category="root_artifact",
                description=f"{hit.description}: {hit.name}/",
                fix_command=fix_command,
            )
        )
    return items


def generate_remediation(project_root: Path) -> List[RemediationItem]:
    """Scan project structure and build remediation items with spawn commands."""
    project = detect_project_name(project_root)
    agents = scan_agents(project_root)

    items: List[RemediationItem] = []
    items.extend(_build_pollution_items(agents, project))
    items.extend(_build_placement_items(agents, project_root, project))
    items.extend(_build_registry_items(project_root, agents, project))

    pyproject = check_pyproject(project_root)
    if not pyproject["found"]:
        items.append(
            RemediationItem(
                severity="info",
                category="pyproject",
                description="Missing pyproject.toml",
                fix_command=f"drone @spawn repair @{project} --add-pyproject --apply",
            )
        )

    items.extend(_build_root_artifact_items(project_root, project))

    logger.info("[doctor_fix] generated %d remediation items for %s", len(items), project)
    json_handler.log_operation("generate_remediation", {"count": len(items), "project": project})
    return items


# =============================================================================
# TEXT FORMATTING
# =============================================================================


def format_text_report(items: List[RemediationItem], project_name: str) -> str:
    """Format remediation items as plain text."""
    if not items:
        return f"No structure issues found in @{project_name}."

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    sorted_items = sorted(items, key=lambda i: severity_order.get(i.severity, 99))
    critical_count = sum(1 for i in items if i.severity == "critical")

    lines = [f"STRUCTURE ISSUES ({len(items)} found, {critical_count} critical)", ""]
    for item in sorted_items:
        lines.append(f"[{item.severity.upper()}] {item.description}")
        lines.append(f"  Fix: {item.fix_command}")
        lines.append("")
    lines.append(f"Preview all fixes: drone @spawn repair @{project_name}")
    lines.append(f"Apply all fixes:  drone @spawn repair @{project_name} --apply")
    return "\n".join(lines)


# =============================================================================
# JSON FORMATTING
# =============================================================================


def format_json_report(items: List[RemediationItem], project_name: str) -> str:
    """Format remediation items as JSON for spawn consumption."""
    report = {
        "project": project_name,
        "total_issues": len(items),
        "critical_count": sum(1 for i in items if i.severity == "critical"),
        "warning_count": sum(1 for i in items if i.severity == "warning"),
        "info_count": sum(1 for i in items if i.severity == "info"),
        "issues": [
            {
                "severity": item.severity,
                "category": item.category,
                "description": item.description,
                "fix_command": item.fix_command,
            }
            for item in items
        ],
    }
    return json.dumps(report, indent=2)


# =============================================================================
# RICH OUTPUT
# =============================================================================

_LINE_STYLES = {
    "[CRITICAL]": "bold red",
    "[WARNING]": "yellow",
    "[INFO]": "blue",
    "  Fix:": "green",
    "Preview": "dim",
    "STRUCTURE": "bold",
}


def _style_line(line: str) -> str:
    """Apply Rich markup to a remediation report line."""
    for prefix, style in _LINE_STYLES.items():
        if line.startswith(prefix):
            content = line.strip() if prefix == "  Fix:" else line
            indent = "    " if prefix == "  Fix:" else "  "
            return f"{indent}[{style}]{content}[/{style}]"
    return f"  {line}"


def print_remediation_report(project_root: Path) -> int:
    """Print Rich-formatted remediation report. Returns issue count."""
    project_name = detect_project_name(project_root)
    items = generate_remediation(project_root)

    if not items:
        console.print()
        console.print("[green]No structure issues requiring repair.[/green]")
        return 0

    console.print()
    console.print("[bold cyan]Remediation Report[/bold cyan]")
    console.print()

    report = format_text_report(items, project_name)
    for line in report.split("\n"):
        console.print(_style_line(line))

    return len(items)


def print_json_report(project_root: Path) -> int:
    """Print JSON remediation report to stdout. Returns issue count."""
    project_name = detect_project_name(project_root)
    items = generate_remediation(project_root)
    console.print(format_json_report(items, project_name))
    return len(items)


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================


def print_introspection() -> None:
    """Display module info for doctor_fix."""
    console.print()
    console.print("[bold cyan]doctor_fix Module[/bold cyan]")
    console.print("Structure remediation report — doctor --fix / --fix --json")
    console.print()
    console.print("[yellow]Provides:[/yellow]")
    console.print("  [dim]- generate_remediation() — scan + build fix items[/dim]")
    console.print("  [dim]- format_text_report() — human-readable output[/dim]")
    console.print("  [dim]- format_json_report() — machine-readable for spawn[/dim]")
    console.print()


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def handle_command(command: str, args: list[str]) -> bool:
    """Handle command routing. Helper module — no standalone commands.

    Args:
        command: Command name.
        args: Additional arguments.

    Returns:
        True if handled, False otherwise.
    """
    if command != "doctor_fix":
        return False

    if not args:
        console.print("[dim]Helper module — use: aipass doctor --fix [--json][/dim]")
        json_handler.log_operation("doctor_fix_usage", {"command": command})
        return True

    if args[0] in ("--help", "-h", "help"):
        console.print("[dim]Helper module — use: aipass doctor --fix [--json][/dim]")
        json_handler.log_operation("doctor_fix_help", {"command": command})
        return True

    if args[0] in ("--info", "info"):
        print_introspection()
        json_handler.log_operation("doctor_fix_info", {"command": command})
        return True

    json_handler.log_operation("doctor_fix_noop", {"command": command})
    return False
