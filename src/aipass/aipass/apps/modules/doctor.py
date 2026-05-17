# =================== AIPass ====================
# Name: doctor.py
# Description: System health aggregation — aipass doctor command
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""
aipass doctor — system health aggregation

Run: aipass doctor [--verbose] [--fix] [--fix --json]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple

from aipass.cli.apps.modules import console
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.structure_scan.structure_scanner import (
    check_placement,
    check_pyproject,
    check_registry_consistency,
    check_root_artifacts,
    detect_pollution,
    find_project_root,
    find_registry,
    scan_agents,
)
from aipass.aipass.apps.modules.doctor_fix import (
    print_json_report,
    print_remediation_report,
)
from aipass.aipass.apps.modules.doctor_wire import (
    _auto_wire_provider,
    prompt_auto_wire,
)
from aipass.aipass.apps.handlers.system_detect.system_detector import (
    detect_cpu,
    detect_git,
    detect_install_method,
    detect_os,
    detect_python,
    detect_ram,
    detect_shell,
)
from aipass.aipass.apps.handlers.ui.progress import (
    GLYPH_FAIL,
    GLYPH_PASS,
    GLYPH_WARN,
    format_check,
    make_doctor_progress,
)

# =============================================================================
# TYPES
# =============================================================================

_BRANCH_ROOT = Path(__file__).resolve().parents[2]


class CheckResult(NamedTuple):
    """Single doctor check result."""

    label: str
    glyph: str
    detail: str
    remediation: str


# =============================================================================
# IDENTITY HELPERS
# =============================================================================


def _find_registry() -> Path | None:
    """Walk up from CWD first (user's project), then branch root."""
    cwd = Path.cwd()
    for parent in (cwd, *cwd.parents):
        candidates = list(parent.glob("*_REGISTRY.json"))
        if candidates:
            return candidates[0]
        if parent == parent.parent:
            break
    for parent in (_BRANCH_ROOT, *_BRANCH_ROOT.parents):
        candidate = parent / "AIPASS_REGISTRY.json"
        if candidate.exists():
            return candidate
    return None


# =============================================================================
# CHECK GROUPS
# =============================================================================


def _check_system() -> List[CheckResult]:
    """Run System group checks."""
    results: List[CheckResult] = []

    # Python
    py = detect_python()
    if py["ok"]:
        glyph, detail, rem = GLYPH_PASS, py["version"], ""
    elif py["warning"]:
        glyph, detail = GLYPH_WARN, py["version"]
        rem = "Python 3.8 reaches end-of-life — upgrade to 3.9+"
    else:
        glyph, detail = GLYPH_FAIL, py["version"]
        rem = "Upgrade Python: https://python.org/downloads"
    results.append(CheckResult("python", glyph, detail, rem))

    # git
    git = detect_git()
    if git["found"]:
        results.append(CheckResult("git", GLYPH_PASS, git["version"], ""))
    else:
        results.append(CheckResult("git", GLYPH_FAIL, "not found", "Install git: https://git-scm.com/downloads"))

    # shell
    sh = detect_shell()
    results.append(CheckResult("shell", GLYPH_PASS, sh["name"], ""))

    # OS
    os_info = detect_os()
    detail = f"{os_info['os_name']} {os_info['release']}".strip()
    results.append(CheckResult("OS", GLYPH_PASS, detail, ""))

    # RAM
    ram = detect_ram()
    ram_detail = f"{ram['total_gb']} GB"
    if ram["ok"]:
        results.append(CheckResult("RAM", GLYPH_PASS, ram_detail, ""))
    elif ram["warning"]:
        results.append(CheckResult("RAM", GLYPH_WARN, ram_detail, "AIPass runs better with 4 GB+ RAM"))
    else:
        results.append(CheckResult("RAM", GLYPH_FAIL, ram_detail, "AIPass requires at least 2 GB RAM"))

    # CPU
    cpu = detect_cpu()
    results.append(CheckResult("CPU", GLYPH_PASS, f"{cpu['count']} cores", ""))

    # install method
    method = detect_install_method()
    results.append(CheckResult("install", GLYPH_PASS, method, ""))

    return results


def _check_identity() -> List[CheckResult]:
    """Run Identity group checks."""
    results: List[CheckResult] = []

    # Project root — derived from registry location
    reg = _find_registry()
    project_root = str(reg.parent) if reg else ""
    if project_root:
        results.append(CheckResult("AIPASS_HOME", GLYPH_PASS, project_root, ""))
    else:
        home = os.environ.get("AIPASS_HOME", "")
        if home:
            results.append(CheckResult("AIPASS_HOME", GLYPH_PASS, home, ""))
        else:
            results.append(
                CheckResult(
                    "AIPASS_HOME",
                    GLYPH_WARN,
                    "not set",
                    "Set in ~/.bashrc: export AIPASS_HOME=/path/to/aipass",
                )
            )

    # Registry present
    reg_path = _find_registry()
    if reg_path is None:
        results.append(CheckResult("registry", GLYPH_FAIL, "not found", "Run 'aipass init' to create registry"))
        return results

    branch_count = 0
    try:
        with open(reg_path, "r", encoding="utf-8") as f:
            reg_data = json.load(f)
        branch_count = len(reg_data.get("branches", []))
        results.append(CheckResult("registry", GLYPH_PASS, f"{branch_count} branches", ""))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[doctor] registry parse error: %s", exc)
        results.append(CheckResult("registry", GLYPH_FAIL, "corrupt JSON", "Manually inspect AIPASS_REGISTRY.json"))
        return results

    # Registry valid — has branches key
    if "branches" in reg_data:
        results.append(CheckResult("registry valid", GLYPH_PASS, "", ""))
    else:
        results.append(CheckResult("registry valid", GLYPH_FAIL, "missing 'branches' key", "Re-run 'aipass init'"))

    # Passport readable
    passport = _BRANCH_ROOT / ".trinity" / "passport.json"
    if passport.exists():
        try:
            with open(passport, "r", encoding="utf-8") as f:
                pdata = json.load(f)
            role = pdata.get("role", "unknown")
            results.append(CheckResult("passport", GLYPH_PASS, f"role: {role}", ""))
        except Exception as exc:
            logger.warning("[doctor] passport read error: %s", exc)
            results.append(CheckResult("passport", GLYPH_WARN, "unreadable", "Check .trinity/passport.json"))
    else:
        results.append(CheckResult("passport", GLYPH_WARN, "not found", ""))

    return results


def _find_manifest() -> Path | None:
    """Find provider_manifest.json by walking up from CWD, AIPASS_HOME env, or settings.json."""
    aipass_home = os.environ.get("AIPASS_HOME", "")
    if not aipass_home:
        settings_path = Path.home() / ".claude" / "settings.json"
        if settings_path.exists():
            try:
                settings_env = json.loads(settings_path.read_text(encoding="utf-8")).get("env", {})
                aipass_home = settings_env.get("AIPASS_HOME", "")
            except Exception as exc:
                logger.info("[doctor] settings.json read for AIPASS_HOME fallback failed: %s", exc)

    for start in (Path.cwd(), Path(aipass_home) if aipass_home else None):
        if start is None:
            continue
        p = start.resolve()
        for parent in (p, *p.parents):
            candidate = parent / ".claude" / "provider_manifest.json"
            if candidate.exists():
                return candidate
            if parent == parent.parent:
                break
    return None


def _check_provider_manifest(interactive: bool = False, fix: bool = False) -> List[CheckResult]:
    """Check provider settings against manifest. Returns hook/env/permission results."""
    results: List[CheckResult] = []

    manifest_path = _find_manifest()
    if manifest_path is None:
        results.append(
            CheckResult(
                "hooks", GLYPH_WARN, "manifest not found", "Expected .claude/provider_manifest.json in project root"
            )
        )
        return results

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[doctor] manifest read error: %s", exc)
        results.append(CheckResult("hooks", GLYPH_WARN, "manifest unreadable", "Check .claude/provider_manifest.json"))
        return results

    claude_section = manifest.get("cli", {}).get("claude", {})
    if not claude_section:
        results.append(CheckResult("hooks", GLYPH_WARN, "manifest has no claude section", ""))
        return results

    # --- Hook scripts exist ---
    manifest_hooks = claude_section.get("hooks", [])
    hook_scripts = {h["script"] for h in manifest_hooks if "script" in h}
    repo_hooks_dir = manifest_path.parent / "hooks"
    user_hooks_dir = Path.home() / ".claude" / "hooks"

    missing_hooks = []
    for script in sorted(hook_scripts):
        source = next((h.get("source", "repo") for h in manifest_hooks if h.get("script") == script), "repo")
        check_dir = user_hooks_dir if source == "user" else repo_hooks_dir
        if not (check_dir / script).exists():
            missing_hooks.append(script)

    if not missing_hooks:
        results.append(CheckResult("hooks", GLYPH_PASS, f"{len(hook_scripts)} provider hooks present", ""))
    else:
        results.append(
            CheckResult(
                "hooks",
                GLYPH_WARN,
                f"{len(missing_hooks)} hook(s) missing: {', '.join(missing_hooks)}",
                "Copy missing hooks to ~/.claude/hooks/ — see .claude/hooks/README.md",
            )
        )

    # --- Env vars in provider settings ---
    missing_env: List[str] = []
    manifest_env = claude_section.get("env", {})
    if manifest_env:
        provider_settings_path = Path.home() / ".claude" / "settings.json"
        provider_env: dict = {}
        if provider_settings_path.exists():
            try:
                provider_env = json.loads(provider_settings_path.read_text(encoding="utf-8")).get("env", {})
            except Exception as exc:
                logger.warning("[doctor] provider settings read error (env): %s", exc)

        missing_env = [k for k in manifest_env if k not in provider_env]
        if not missing_env:
            results.append(CheckResult("env vars", GLYPH_PASS, f"{len(manifest_env)} provider env vars set", ""))
        else:
            results.append(
                CheckResult(
                    "env vars",
                    GLYPH_WARN,
                    f"{len(missing_env)} env var(s) missing: {', '.join(missing_env)}",
                    "Add to ~/.claude/settings.json env block — see provider_manifest.json",
                )
            )

    # --- Permissions ---
    missing_deny: List[str] = []
    missing_ask: List[str] = []
    manifest_perms = claude_section.get("permissions", {})
    manifest_deny = manifest_perms.get("deny", [])
    manifest_ask = manifest_perms.get("ask", [])
    if manifest_deny or manifest_ask:
        provider_settings_path = Path.home() / ".claude" / "settings.json"
        provider_perms: dict = {}
        if provider_settings_path.exists():
            try:
                provider_perms = json.loads(provider_settings_path.read_text(encoding="utf-8")).get("permissions", {})
            except Exception as exc:
                logger.warning("[doctor] provider settings read error (permissions): %s", exc)

        provider_deny = set(provider_perms.get("deny", []))
        provider_ask = set(provider_perms.get("ask", []))

        # Check deny rules (use ~ form only, skip expanded $HOME duplicates)
        missing_deny = [r for r in manifest_deny if r not in provider_deny]
        # Check ask rules
        missing_ask = [r for r in manifest_ask if r not in provider_ask]
        total_expected = len(manifest_deny) + len(manifest_ask)
        total_missing = len(missing_deny) + len(missing_ask)

        if total_missing == 0:
            results.append(CheckResult("permissions", GLYPH_PASS, f"{total_expected} permission rules set", ""))
        else:
            results.append(
                CheckResult(
                    "permissions",
                    GLYPH_WARN,
                    f"{total_missing} permission rule(s) missing",
                    "Add to ~/.claude/settings.json permissions — see provider_manifest.json",
                )
            )

    # --- Interactive auto-wire prompt / --fix auto-accept ---
    if (interactive or fix) and any(r.glyph != GLYPH_PASS for r in results):
        wired = False
        if fix:
            actions = _auto_wire_provider(manifest_path, interactive=False)
            for action in actions:
                console.print(f"[green]✓[/green] {action}")
            wired = bool(actions)
        else:
            wired = prompt_auto_wire(manifest_path, missing_hooks, missing_env, missing_deny, missing_ask)

        if wired:
            return _check_provider_manifest(interactive=False, fix=False)

    return results


def _check_services(verbose: bool = False) -> List[CheckResult]:
    """Run Services group checks."""
    results: List[CheckResult] = []

    # drone systems
    try:
        proc = subprocess.run(
            ["drone", "systems"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            # Count citizen lines (lines with @)
            citizens = [ln for ln in proc.stdout.splitlines() if "@" in ln]
            detail = f"{len(citizens)} citizens" if citizens else "ok"
            results.append(CheckResult("drone", GLYPH_PASS, detail, ""))
        else:
            results.append(
                CheckResult("drone", GLYPH_FAIL, "exit non-zero", "Ensure aipass is installed: pip install -e .")
            )
    except FileNotFoundError as exc:
        logger.warning("[doctor] drone not found: %s", exc)
        results.append(CheckResult("drone", GLYPH_FAIL, "not found", "Ensure aipass is installed: pip install -e ."))
    except subprocess.TimeoutExpired as exc:
        logger.warning("[doctor] drone systems timed out: %s", exc)
        results.append(CheckResult("drone", GLYPH_WARN, "timed out", ""))

    # pytest --collect-only
    try:
        # Find repo root (where src/ lives)
        repo_root = None
        for parent in _BRANCH_ROOT.parents:
            if (parent / "src").exists() and (parent / "pyproject.toml").exists():
                repo_root = parent
                break
        cwd = str(repo_root) if repo_root else str(_BRANCH_ROOT)

        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "src/aipass/", "--collect-only", "-q"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        output = proc.stdout + proc.stderr
        if proc.returncode == 0:
            # Count collected lines
            collected = [ln for ln in output.splitlines() if "<" in ln or "::" in ln]
            detail = f"{len(collected)} tests collected" if collected else "ok"
            results.append(CheckResult("pytest collect", GLYPH_PASS, detail, ""))
        else:
            results.append(CheckResult("pytest collect", GLYPH_WARN, "collection issues", "Run pytest to diagnose"))
    except FileNotFoundError as exc:
        logger.warning("[doctor] pytest not found: %s", exc)
        results.append(CheckResult("pytest collect", GLYPH_WARN, "pytest not found", "pip install pytest"))
    except subprocess.TimeoutExpired as exc:
        logger.warning("[doctor] pytest collect timed out: %s", exc)
        results.append(CheckResult("pytest collect", GLYPH_WARN, "timed out", ""))

    # hooks + env + permissions — manifest-driven provider check
    manifest_checks = _check_provider_manifest()
    results.extend(manifest_checks)

    return results


def _check_community() -> List[CheckResult]:
    """Run Community group checks."""
    results: List[CheckResult] = []

    # ai_mail readable
    mail_dir = _BRANCH_ROOT / ".ai_mail.local"
    if mail_dir.exists() and mail_dir.is_dir():
        results.append(CheckResult("ai_mail", GLYPH_PASS, "readable", ""))
    else:
        results.append(CheckResult("ai_mail", GLYPH_FAIL, "not found", "Run 'aipass init' to set up mailbox"))

    # dropbox writable — only check if project has agents (dropbox is optional for fresh projects)
    reg_path = _find_registry()
    dropbox = None
    if reg_path:
        dropbox = reg_path.parent / "dropbox"
    if dropbox and dropbox.exists():
        writable = os.access(dropbox, os.W_OK)
        if writable:
            results.append(CheckResult("dropbox", GLYPH_PASS, "writable", ""))
        else:
            results.append(CheckResult("dropbox", GLYPH_WARN, "not writable", "Check dropbox directory permissions"))

    return results


# =============================================================================
# STRUCTURE CHECK GROUP
# =============================================================================


def _check_structure() -> List[CheckResult]:
    """Run Structure group checks — agent placement, pollution, registry consistency."""
    results: List[CheckResult] = []

    project_root = find_project_root(Path.cwd())
    if project_root is None:
        results.append(
            CheckResult("project root", GLYPH_WARN, "not detected", "Run from inside an AIPass project directory")
        )
        return results

    agents = scan_agents(project_root)
    results.append(CheckResult("agents found", GLYPH_PASS, f"{len(agents)} agents", ""))

    # Placement
    placement_issues = check_placement(agents, project_root)
    if placement_issues:
        for issue in placement_issues:
            glyph = GLYPH_WARN if issue.severity == "warn" else GLYPH_FAIL
            results.append(
                CheckResult(f"placement: {issue.agent_name}", glyph, issue.actual_path, issue.expected_pattern)
            )
    else:
        results.append(CheckResult("placement", GLYPH_PASS, "all agents correctly placed", ""))

    # Pollution
    pollution = detect_pollution(agents)
    if pollution:
        for hit in pollution:
            locs = ", ".join(hit.locations)
            results.append(
                CheckResult(
                    f"pollution: {hit.agent_name}",
                    GLYPH_FAIL,
                    f"{len(hit.locations)} copies",
                    f"Duplicate registry_id at: {locs}",
                )
            )
    else:
        results.append(CheckResult("pollution", GLYPH_PASS, "no duplicates", ""))

    # Registry consistency
    reg_path = find_registry(project_root)
    if reg_path:
        reg_issues = check_registry_consistency(reg_path, agents)
        if reg_issues:
            for issue in reg_issues:
                glyph = GLYPH_FAIL if issue.problem == "missing" else GLYPH_WARN
                results.append(
                    CheckResult(f"registry: {issue.branch_name}", glyph, issue.problem, issue.registered_path)
                )
        else:
            results.append(CheckResult("registry paths", GLYPH_PASS, "all paths valid", ""))
    else:
        results.append(CheckResult("registry", GLYPH_WARN, "not found", "Expected *_REGISTRY.json in project root"))

    # Root artifacts
    root_hits = check_root_artifacts(project_root)
    if root_hits:
        for hit in root_hits:
            glyph = GLYPH_WARN if hit.severity == "warn" else GLYPH_PASS
            results.append(CheckResult(f"root: {hit.name}", glyph, hit.description, ""))
    else:
        results.append(CheckResult("root artifacts", GLYPH_PASS, "none misplaced", ""))

    # Pyproject
    pyproject = check_pyproject(project_root)
    if pyproject["found"]:
        results.append(CheckResult("pyproject.toml", GLYPH_PASS, "present", ""))
    else:
        results.append(CheckResult("pyproject.toml", GLYPH_WARN, "missing", "Create pyproject.toml for pip packaging"))

    return results


# =============================================================================
# MAIN DOCTOR RUN
# =============================================================================


def run_doctor(verbose: bool = False, interactive: bool = False, fix: bool = False) -> int:
    """Run all five groups and print results. Returns error count."""
    console.print()
    console.print("[bold cyan]aipass doctor[/bold cyan]")
    console.print()

    group_specs = [
        ("System", _check_system),
        ("Identity", _check_identity),
        ("Services", lambda: _check_services(verbose=verbose)),
        ("Community", _check_community),
        ("Structure", _check_structure),
    ]
    groups: Dict[str, List[CheckResult]] = {}
    with make_doctor_progress() as progress:
        for name, runner in group_specs:
            task_id = progress.add_task(f"checking {name}...", total=None)
            groups[name] = runner()
            progress.remove_task(task_id)

    if interactive or fix:
        manifest_results = _check_provider_manifest(interactive=interactive, fix=fix)
        if manifest_results:
            groups["Services"] = [
                r for r in groups.get("Services", []) if r.label not in ("hooks", "env vars", "permissions")
            ] + manifest_results

    pass_count = 0
    warn_count = 0
    error_count = 0

    for group_name, checks in groups.items():
        console.print(f"  [bold]{group_name}[/bold]")
        for check in checks:
            line = format_check(check.label, check.glyph, check.detail, check.remediation)
            console.print(line)
            if check.glyph == GLYPH_PASS:
                pass_count += 1
            elif check.glyph == GLYPH_WARN:
                warn_count += 1
            else:
                error_count += 1
        console.print()

    console.print("[dim]─────────────────────────────────[/dim]")
    summary_parts = [
        f"[green]✓ pass: {pass_count}[/green]",
        f"[yellow]! warnings: {warn_count}[/yellow]",
        f"[red]✗ errors: {error_count}[/red]",
    ]
    console.print("  " + "  ".join(summary_parts))
    console.print()

    logger.info("[doctor] run complete — pass=%d warn=%d error=%d", pass_count, warn_count, error_count)
    return error_count


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================


def print_introspection() -> None:
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]doctor Module[/bold cyan]")
    console.print("System health aggregation — flutter-doctor-style output")
    console.print()
    console.print("[yellow]Groups:[/yellow] System, Identity, Services, Community, Structure")
    console.print("[yellow]Next:[/yellow]  [green]aipass doctor[/green] / [green]aipass doctor --fix[/green]")
    console.print()


def print_help() -> None:
    """Print help information."""
    console.print()
    console.print("[bold cyan]aipass doctor[/bold cyan] — System health aggregation")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass doctor[/green]           [dim]# Run all checks[/dim]")
    console.print("  [green]aipass doctor --verbose[/green] [dim]# Show sub-check detail[/dim]")
    console.print("  [green]aipass doctor --fix[/green]     [dim]# Auto-wire + remediation report[/dim]")
    console.print("  [green]aipass doctor --fix --json[/green][dim]# Remediation as JSON (for spawn)[/dim]")
    console.print()
    console.print("[yellow]OUTPUT:[/yellow]  [green]✓[/green] pass  [yellow]![/yellow] warn  [red]✗[/red] error")
    console.print("[yellow]EXIT:[/yellow]    0 = pass/warn  |  1 = errors found")
    console.print()


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def handle_command(command: str, args: list[str]) -> bool:
    """Handle 'doctor' command routing.

    Args:
        command: Command name.
        args: Additional arguments.

    Returns:
        True if handled (command == 'doctor'), False otherwise.
    """
    if command != "doctor":
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    if args[0] == "--info":
        print_introspection()
        return True

    verbose = "--verbose" in args or "-v" in args
    fix_mode = "--fix" in args
    json_mode = "--json" in args

    if json_mode and fix_mode:
        project_root = find_project_root(Path.cwd())
        if project_root:
            print_json_report(project_root)
        return True

    error_count = run_doctor(verbose=verbose, interactive=True, fix=fix_mode)
    if fix_mode:
        project_root = find_project_root(Path.cwd())
        if project_root:
            print_remediation_report(project_root)
    json_handler.log_operation("doctor_run", {"error_count": error_count, "fix": fix_mode})
    if error_count > 0:
        raise SystemExit(1)
    return True
