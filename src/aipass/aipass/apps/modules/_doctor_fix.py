# =================== AIPass ====================
# Name: _doctor_fix.py
# Description: Structure remediation report for aipass doctor --fix
# Version: 1.6.0
# Created: 2026-05-15
# Modified: 2026-11-24
# =============================================

"""
doctor_fix — structure remediation report for aipass doctor --fix
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import List, NamedTuple, Optional

from aipass.cli import console
from aipass.prax import logger

from aipass.aipass.shared.registry_discovery import find_registry as _discover_registry
from aipass.aipass.shared.project_home import _detect_aipass_home

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.ui.progress import GLYPH_FAIL, GLYPH_PASS, GLYPH_WARN
from aipass.aipass.apps.handlers.structure_scan.structure_scanner import (
    TREE_REGISTRY_NAME,
    VAULT_RELATIVE_PATH,
    check_placement,
    check_pyproject,
    check_registry_consistency,
    check_root_artifacts,
    detect_pollution,
    has_passport_vault,
    scan_agents,
)


class RemediationItem(NamedTuple):
    """Single remediation suggestion with severity and spawn command."""

    severity: str
    category: str
    description: str
    fix_command: str


def detect_project_name(project_root: Path) -> str:
    """Derive project name from registry filename or directory name."""
    reg = _discover_registry(start_path=project_root)
    if reg and reg.exists():
        name = reg.stem.replace("_REGISTRY", "").lower()
        if name:
            return name
    return project_root.name.lower()


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


_DOCTOR_CURES = {"no_passport": "No readable passport", "no_seed": "No passport vault"}


def _build_registry_items(project_root: Path, agents: list, project: str) -> List[RemediationItem]:
    """Build remediation items for registry consistency issues."""
    items: List[RemediationItem] = []
    reg_path = _discover_registry(start_path=project_root)
    if not reg_path or not reg_path.exists():
        return items
    for issue in check_registry_consistency(reg_path, agents):
        if issue.problem in _DOCTOR_CURES:
            items.append(
                RemediationItem(
                    severity="critical",
                    category="registry",
                    description=f"{_DOCTOR_CURES[issue.problem]}: {issue.branch_name} at {issue.registered_path}",
                    fix_command="aipass doctor --fix",
                )
            )
            continue
        items.append(
            RemediationItem(
                severity="warning",
                category="registry",
                description=f"Registry {issue.problem}: {issue.branch_name} at {issue.registered_path}",
                fix_command=f"drone @spawn repair @{project} --dedup-registry --apply",
            )
        )
    return items


REINSTALL = "Run the installer again: ./aipass install (rebuilds the environment, keeps personal files)"
NO_SEED_BACKUP = (
    "No passport vault was written while the passport existed: restore .trinity/passport.json from a backup"
)


def _registry_for(project_root: Optional[Path]) -> Optional[Path]:
    """The project's registry, or None when doctor runs outside one."""
    reg_path = _discover_registry(start_path=project_root) if project_root else None
    return reg_path if reg_path is not None and reg_path.exists() else None


def _unseated(project_root: Path, reg_path: Path, problem: str) -> dict:
    """Registered citizens showing one registry problem, name -> citizen folder."""
    issues = check_registry_consistency(reg_path, scan_agents(project_root), project_root=project_root)
    return {i.branch_name: project_root / i.registered_path for i in issues if i.problem == problem}


def _export_refusal(folder_name: str, output: str) -> str:
    """spawn's refusal for this citizen, verbatim: its export prints '<branch>: <reason>' per refused vault."""
    prefix = f"{folder_name.lower()}: "
    for line in output.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()[len(prefix) :]
    lines = output.strip().splitlines()
    return lines[-1].strip() if lines else "export-vault wrote no vault"


def rebuild_corrupt_registry(reg_path: Path) -> List[tuple]:
    """doctor --fix: rebuild an unreadable registry from the passports on disk, preview first, then write.

    drone cannot route to @spawn while its registry is corrupt, so spawn's door function runs in-process.
    Rows are (label, glyph, detail, remediation); a refusal is a FAIL carrying spawn's reason, nothing written.
    The seat flags a rebuild cannot restore come back as one WARN row per ceremony command spawn names.
    """
    from aipass.spawn import rebuild_registry

    label = "registry rebuild"
    try:
        preview = rebuild_registry(reg_path, confirm=False)
        if preview["refused"]:
            raise ValueError(preview["refused"])
        names = ", ".join(row["name"] for row in preview["rows"])
        rows = [(label, GLYPH_PASS, f"plan: {len(preview['rows'])} row(s) from the passports: {names}", "")]
        receipt = rebuild_registry(reg_path, confirm=True)
        if receipt["refused"] or not receipt["written"]:
            raise ValueError(receipt["refused"] or "spawn wrote nothing")
    except (OSError, ValueError) as exc:
        logger.error("[doctor] registry rebuild of %s refused: %s", reg_path, exc)
        return [(label, GLYPH_FAIL, f"not rebuilt: {exc}", "")]
    written = f"written: {len(receipt['rows'])} row(s); corrupt file kept at {receipt['aside']}"
    rows.append((label, GLYPH_PASS, written, ""))
    rows += [(label, GLYPH_WARN, "seat flag to restore", command) for command in receipt["ceremonies"]]
    return rows


def export_missing_seeds(project_root: Optional[Path]) -> List[tuple]:
    """doctor --fix: write each missing passport vault through spawn's export-vault, then re-read the check.

    Rows are (label, glyph, detail, remediation). spawn's door does not serve the export, so the command
    runs, the way the owner fix runs sync-registry. A refused vault is a FAIL carrying spawn's reason.
    """
    reg_path = _registry_for(project_root)
    if project_root is None or reg_path is None:
        return []
    unseeded = _unseated(project_root, reg_path, "no_seed")
    refusals: dict = {}
    for name, folder in unseeded.items():
        cmd = ["drone", "@spawn", "export-vault", "--confirm", "--root", str(reg_path.parent), "--only", folder.name]
        env = {**os.environ, "COLUMNS": "1000"}  # an unwrapped refusal line is the reason, verbatim
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=reg_path.parent, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            refusals[name] = str(exc)
        else:
            refusals[name] = _export_refusal(folder.name, proc.stdout + "\n" + proc.stderr)

    still = _unseated(project_root, reg_path, "no_seed")
    rows: List[tuple] = []
    for name, folder in unseeded.items():
        if name not in still:
            rows.append((f"registry: {name}", GLYPH_PASS, f"vault written: {folder / VAULT_RELATIVE_PATH}", ""))
            continue
        logger.error("[doctor] passport vault for %s not written: %s", name, refusals[name])
        rows.append((f"registry: {name}", GLYPH_FAIL, f"vault not written: {refusals[name]}", ""))
    return rows


def _restore_advice(reg_path: Path, folder: Path) -> str:
    """The installer rebuilds the AIPass tree's own citizens only; a project citizen gets its own truth."""
    if reg_path.name == TREE_REGISTRY_NAME:
        return REINSTALL
    return "" if has_passport_vault(folder) else NO_SEED_BACKUP


def repair_passports(project_root: Optional[Path]) -> List[tuple]:
    """doctor --fix: restore each damaged citizen's passport through spawn's door, then re-read the check.

    Rows are (label, glyph, detail, remediation). spawn's restore_citizen writes only the missing .trinity
    files; a restore that raises, or a passport still unreadable afterwards, is a FAIL with spawn's reason.
    """
    reg_path = _registry_for(project_root)
    if project_root is None or reg_path is None:
        return []
    damaged = _unseated(project_root, reg_path, "no_passport")
    if not damaged:
        return []

    from aipass.spawn import restore_citizen

    rows: List[tuple] = []
    for name, folder in damaged.items():
        try:
            written = restore_citizen(name, reg_path)
        except (LookupError, OSError, ValueError) as exc:
            logger.error("[doctor] passport restore for %s failed: %s", name, exc)
            advice = _restore_advice(reg_path, folder)
            rows.append((f"registry: {name}", GLYPH_FAIL, f"passport not restored: {exc}", advice))
            continue
        rows.append((f"registry: {name}", GLYPH_PASS, "passport restored: " + ", ".join(map(str, written)), ""))

    still = _unseated(project_root, reg_path, "no_passport")
    for i, (label, glyph, detail, _fix) in enumerate(rows):
        if glyph == GLYPH_PASS and (name := label.removeprefix("registry: ")) in still:
            logger.error("[doctor] passport for %s is still not readable after its restore", label)
            rows[i] = (label, GLYPH_FAIL, f"{detail}; still not readable", _restore_advice(reg_path, still[name]))
    return rows


def _build_root_artifact_items(project_root: Path, project: str) -> List[RemediationItem]:
    """Remediation items for stray root-level artifacts."""
    items: List[RemediationItem] = []
    aipass_home = _detect_aipass_home()
    if aipass_home is None:
        # Without the home, its own .venv cannot be told from a stray one.
        items.append(
            RemediationItem("critical", "aipass_home", "AIPass home not found", "Set AIPASS_HOME=/path/to/AIPass")
        )
    for hit in check_root_artifacts(project_root, aipass_home=aipass_home):
        if hit.severity == "pass":
            continue
        severity = "info" if hit.severity == "info" else "warning"
        if hit.name == ".venv":
            # Hooks call AIPASS_HOME/.venv/bin/python3 by absolute path, so spawn repair
            # has no --relocate-root for it.
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


def format_json_report(
    items: List[RemediationItem], project_name: str, provider_settings: Optional[dict] = None
) -> str:
    """Format remediation items as JSON for spawn consumption.

    *provider_settings*, when given, is the settings plan (planned lines, diff,
    ``applied``) and rides under its own key.
    """
    report: dict = {
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
    if provider_settings is not None:
        report["provider_settings"] = provider_settings
    return json.dumps(report, indent=2)


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


def print_json_report(project_root: Path, provider_settings: Optional[dict] = None) -> int:
    """Print JSON remediation report to stdout. Returns issue count.

    Printed with markup off: a diff line or a rule in the JSON must never be read as Rich markup.
    """
    project_name = detect_project_name(project_root)
    items = generate_remediation(project_root)
    console.print(format_json_report(items, project_name, provider_settings), markup=False, highlight=False)
    return len(items)
