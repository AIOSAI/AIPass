# =================== AIPass ====================
# Name: init_flow.py
# Description: 10-stage guided first-run setup — aipass init command
# Version: 1.2.1
# Created: 2026-04-16
# Modified: 2026-08-11
# =============================================

"""
aipass init — guided first-run setup

10 resumable stages. State persists to .aipass/init_progress.json.
Ctrl-C at any stage resumes next time from that stage.

Usage:
    aipass init                          # show progress / introspection
    aipass init run                      # interactive
    aipass init run --non-interactive    # CI/headless, all defaults
    aipass init run --name YourName --cli claude
    aipass init run --dry-run            # walk all 10 stages, no destructive ops
                                         #   - skips drone @spawn create (stage 6)
                                         #   - skips tmux/wt handoff (stage 9)
                                         #   - does NOT write .aipass/init_progress.json
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from aipass.cli.apps.modules import console, error as cli_error, success, warning
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.ui.progress import activity_spinner, render_step_header
from aipass.aipass.apps.handlers.system_detect.system_detector import (
    detect_cpu,
    detect_git,
    detect_install_method,
    detect_os,
    detect_python,
    detect_ram,
    detect_shell,
    detect_tmux,
    detect_wt,
)
from aipass.aipass.shared.registry_discovery import registries_in

try:
    import questionary as _questionary  # type: ignore[import-untyped]

    HAS_QUESTIONARY = True
except ImportError as _qe:
    logger.info("[init_flow] questionary not installed, using numbered-list menus: %s", _qe)
    _questionary = None  # type: ignore[assignment]
    HAS_QUESTIONARY = False

COMMAND = "init"
TOTAL_STAGES = 10

_BRANCH_ROOT = Path(__file__).resolve().parents[2]


def _get_local_json_path() -> Path:
    """Resolve init progress file from CWD (user's project)."""
    return Path.cwd() / ".aipass" / "init_progress.json"


def _resolve_package_dir() -> str | None:
    """Find the src/<package>/ path in CWD project.

    Looks for a directory under src/ that contains an __init__.py.
    Returns the relative path like 'src/my_project' or None if not found.
    """
    src_dir = Path.cwd() / "src"
    if not src_dir.is_dir():
        return None
    for child in src_dir.iterdir():
        if child.is_dir() and (child / "__init__.py").is_file():
            return f"src/{child.name}"
    return None


CLI_CHOICES = ["claude", "codex", "other"]
# Flag variants for CLI launch — these are user-facing config values, not code-level flags
FLAG_CHOICES = ["default", "skip-permissions"]
STYLE_CHOICES = ["building-my-own-project", "improving-aipass", "just-exploring"]

TEMPLATE_EMPTY = "empty project"
TEMPLATE_AIPASS = "aipass_framework"
TEMPLATE_CHOICES = [TEMPLATE_EMPTY, TEMPLATE_AIPASS]
# first_agent, ping_sweep, handoff, done — skipped for empty (non-framework) projects
AIPASS_SPECIFIC_STAGES = {6, 7}


# --- LOCAL JSON HELPERS ---
def _read_local_json() -> dict:
    """Read init progress file, returning empty dict on failure."""
    local_json = _get_local_json_path()
    if not local_json.exists() or local_json.stat().st_size == 0:
        return {}
    try:
        with open(local_json, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[init_flow] local.json read error: %s", exc)
        return {}


def _fire_file_deleted(path: str) -> None:
    """Fire trigger event for temp file deletion, ignoring ImportError."""
    try:
        from aipass.trigger.apps.modules.core import trigger

        trigger.fire("file_deleted", path=path, reason="write_failure_cleanup")
    except ImportError as exc:
        logger.warning("[init_flow] trigger unavailable for file_deleted event: %s", exc)


def _write_local_json(data: dict) -> None:
    """Write init progress file atomically via temp-file rename."""
    local_json = _get_local_json_path()
    dir_ = local_json.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(dir_), prefix=".local_", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, local_json)
    except OSError as exc:
        logger.warning("[init_flow] write failed, cleaning up %s: %s", tmp_path, exc)
        _fire_file_deleted(tmp_path)
        try:
            os.unlink(tmp_path)
        except OSError as _ue:
            logger.warning("[init_flow] temp file cleanup failed: %s", _ue)
        raise


def _get_setup_progress() -> dict:
    """Return setup_progress section from local.json."""
    data = _read_local_json()
    return data.get("setup_progress", {"last_completed_stage": 0, "stages": {}})


def _get_last_completed_stage() -> int:
    """Return the last completed stage number (0 if fresh)."""
    return _get_setup_progress().get("last_completed_stage", 0)


def _save_stage(stage: int, stage_data: dict | None = None, dry_run: bool = False) -> None:
    """Persist stage completion to local.json setup_progress.

    When dry_run=True the call is a no-op (pure read flow).
    """
    if dry_run:
        logger.info("[init_flow] dry-run: skipping _save_stage(%d)", stage)
        return
    data = _read_local_json()
    progress = data.get("setup_progress", {"last_completed_stage": 0, "stages": {}})
    progress["last_completed_stage"] = stage
    progress["stages"][str(stage)] = {
        "status": "done",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **(stage_data or {}),
    }
    data["setup_progress"] = progress
    _write_local_json(data)


def _prompt(msg: str, default: str = "") -> str:
    """Simple input prompt with optional default."""
    display = f"{msg} [{default}]: " if default else f"{msg}: "
    try:
        val = input(display).strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        raise KeyboardInterrupt


def _choose(msg: str, choices: List[str], default: str | None = None) -> str:
    """Arrow-key menu via questionary, or numbered-list fallback."""
    if HAS_QUESTIONARY and _questionary is not None:
        try:
            result = _questionary.select(msg, choices=choices, default=default).ask()
            if result is None:
                raise KeyboardInterrupt
            return result
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            logger.warning("[init_flow] questionary.select failed, using fallback: %s", exc)

    console.print(f"\n{msg}")
    for i, choice in enumerate(choices, 1):
        marker = " [dim](default)[/dim]" if choice == default else ""
        console.print(f"  {i}. {choice}{marker}")
    default_idx = str(choices.index(default) + 1) if default in choices else "1"
    while True:
        raw = _prompt("Choice (number)", default_idx)
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError as exc:
            logger.info("[init_flow] invalid menu input %r: %s", raw, exc)
        cli_error("Invalid choice.")


# --- STAGE FUNCTIONS ---
def stage_1_welcome(dry_run: bool = False) -> Dict[str, Any]:
    """Print welcome banner and greeting."""
    console.print()
    console.print("[bold cyan]  █████╗ ██╗██████╗  █████╗ ███████╗███████╗[/bold cyan]")
    console.print("[bold cyan] ██╔══██╗██║██╔══██╗██╔══██╗██╔════╝██╔════╝[/bold cyan]")
    console.print("[bold cyan] ███████║██║██████╔╝███████║███████╗███████╗ [/bold cyan]")
    console.print("[bold cyan] ██╔══██║██║██╔═══╝ ██╔══██║╚════██║╚════██║[/bold cyan]")
    console.print("[bold cyan] ██║  ██║██║██║     ██║  ██║███████║███████║[/bold cyan]")
    console.print("[bold cyan] ╚═╝  ╚═╝╚═╝╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝[/bold cyan]")
    console.print()
    console.print("[bold]Hi, I am AIPass — your AI passport and front door to the ecosystem.[/bold]")
    console.print("Let's walk through setup together. This takes about 5 minutes.")
    if shutil.which("drone"):
        console.print()
        console.print(
            "[dim]Tip: Open another terminal and run [cyan]drone @prax monitor run[/cyan] to watch activity live.[/dim]"
        )
    if dry_run:
        console.print("[yellow]\\[dry-run][/yellow] No state will be written, no subprocesses launched.")
    console.print()
    console.print(render_step_header(1, TOTAL_STAGES, "Welcome"))
    _save_stage(1, dry_run=dry_run)
    return {}


def _print_os_gap_heads_up() -> None:
    """Print tracked cross-OS gaps that apply to this OS (machine pre-flight, not a guarantee).

    Lightweight: one doc read + parse. Failures are non-fatal — init must not
    crash here. This is NOT the human acceptance pass; it just surfaces tracked
    gaps at the moment the user is on the box.
    """
    try:
        from aipass.aipass.apps.handlers.cross_os import CrossOsGapError, gaps_for_platform
    except ImportError as exc:
        logger.warning("[init_flow] cross_os handler unavailable: %s", exc)
        return

    try:
        gaps = gaps_for_platform(sys.platform)
    except CrossOsGapError as exc:
        logger.warning("[init_flow] cross-OS gap registry unavailable: %s", exc)
        warning("cross-OS gap registry unavailable — skipping OS heads-up.")
        return

    if not gaps:
        return

    console.print()
    console.print(
        f"[dim]Heads-up — {len(gaps)} tracked cross-OS gap(s) may apply on this OS "
        "(machine pre-flight, not a guarantee):[/dim]"
    )
    for gap in gaps:
        console.print(f"  [yellow]![/yellow] [dim]gap #{gap.number}: {gap.symptom} [{gap.status}][/dim]")


def stage_2_system_detect(non_interactive: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Detect OS, Python, shell, RAM, CPU, install method, and optional tools."""
    console.print()
    console.print(render_step_header(2, TOTAL_STAGES, "System detection"))

    from rich.table import Table

    py = detect_python()
    git = detect_git()
    sh = detect_shell()
    os_info = detect_os()
    ram = detect_ram()
    cpu = detect_cpu()
    install = detect_install_method()
    has_tmux = detect_tmux()
    has_wt = detect_wt()

    table = Table(show_header=False, box=None)
    table.add_column("key", style="cyan")
    table.add_column("value")
    table.add_row("OS", f"{os_info['os_name']} {os_info['release']}")
    table.add_row("Python", py["version"])
    table.add_row("shell", sh["name"])
    table.add_row("RAM", f"{ram['total_gb']} GB")
    table.add_row("CPU", f"{cpu['count']} cores")
    table.add_row("install", install)
    table.add_row("git", git["version"] if git["found"] else "not found")
    table.add_row("tmux", "yes" if has_tmux else "no")
    if sys.platform == "win32":
        table.add_row("wt.exe", "yes" if has_wt else "no")
    console.print(table)

    console.print()
    console.print(f"You are on [cyan]{os_info['os_name']}[/cyan] with Python [cyan]{py['version']}[/cyan].")
    install_labels = {"dev": "development (editable source)", "pip": "pip", "clone": "git clone", "unknown": "unknown"}
    console.print(f"Install type: [cyan]{install_labels.get(install, install)}[/cyan]")

    _print_os_gap_heads_up()

    system_data: Dict[str, Any] = {
        "os": os_info["os_name"],
        "python": py["version"],
        "shell": sh["name"],
        "ram_gb": ram["total_gb"],
        "install": install,
        "has_tmux": has_tmux,
    }
    _save_stage(2, system_data, dry_run=dry_run)
    return system_data


def stage_3_user_profile(
    non_interactive: bool = False,
    name_override: str | None = None,
    system_data: dict | None = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Collect user name and OS, save to profile."""
    console.print()
    console.print(render_step_header(3, TOTAL_STAGES, "User profile"))

    from aipass.aipass.apps.modules import profile as profile_mod

    if name_override:
        name = name_override
    elif non_interactive:
        name = "User"
    else:
        name = _prompt("What's your name?", "User")

    os_name = (system_data or {}).get("os") or detect_os()["os_name"]

    existing = profile_mod.get_user_profile()
    existing.update(
        {
            "name": name,
            "os": os_name,
            "shell": (system_data or {}).get("shell"),
            "install_method": (system_data or {}).get("install"),
            "first_seen": existing.get("first_seen") or datetime.now(timezone.utc).isoformat(),
        }
    )
    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would save profile: {existing}")
    else:
        profile_mod.save_profile(existing)

    success(f"Hello, {name}!")
    _save_stage(3, {"name": name}, dry_run=dry_run)
    return {"name": name}


def stage_4_style_questions(
    non_interactive: bool = False,
    style_override: str | None = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Ask what the user wants to do — routes tone of later stages."""
    console.print()
    console.print(render_step_header(4, TOTAL_STAGES, "What brings you here?"))

    if style_override and style_override in STYLE_CHOICES:
        style = style_override
    elif non_interactive:
        style = STYLE_CHOICES[0]
    else:
        style = _choose("What are you looking to do?", STYLE_CHOICES, default=STYLE_CHOICES[0])

    success(f"Got it: {style}")
    _save_stage(4, {"style": style}, dry_run=dry_run)
    return {"style": style}


def _install_claude_code() -> bool:
    """Run the canonical Claude Code installer, platform-aware. Returns True on success."""
    if sys.platform == "win32":
        cmd = ["powershell", "-Command", "irm https://claude.ai/install.ps1 | iex"]
    else:
        cmd = ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"]

    try:
        result = subprocess.run(cmd, timeout=300)
        if result.returncode == 0 and shutil.which("claude"):
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("[init_flow] Claude Code installer failed: %s", exc)

    if shutil.which("npm"):
        console.print("[dim]Native installer didn't work — trying npm fallback...[/dim]")
        try:
            result = subprocess.run(
                ["npm", "install", "-g", "@anthropic-ai/claude-code"],
                timeout=300,
            )
            if result.returncode == 0 and shutil.which("claude"):
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            logger.warning("[init_flow] npm fallback install failed: %s", exc)

    return False


def _handle_missing_claude(non_interactive: bool) -> None:
    """Prompt to install Claude Code when missing, or warn in non-interactive mode."""
    if non_interactive:
        warning("[bold yellow]Claude Code ('claude') is not installed.[/bold yellow]")
        console.print("  Stage 9 handoff requires it. Install manually before then.")
        return

    raw = _prompt("Claude Code ('claude') not found. Install now? [Y/n]", "Y")
    if raw.lower() in ("y", "yes", ""):
        console.print("[cyan]Installing Claude Code[/cyan] [dim](this can take a minute)…[/dim]")
        if _install_claude_code():
            success("Claude Code installed successfully.")
        else:
            warning("[bold yellow]Installation failed.[/bold yellow]")
            console.print("  Install manually: https://claude.ai/download")
    else:
        console.print("[dim]Skipped. Stage 9 handoff will need 'claude' on PATH.[/dim]")


def stage_5_tool_choice(
    non_interactive: bool = False,
    cli_override: str | None = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Choose CLI tool and launch flag variant."""
    console.print()
    console.print(render_step_header(5, TOTAL_STAGES, "CLI tool choice"))

    if cli_override and cli_override in CLI_CHOICES:
        cli_choice = cli_override
    elif non_interactive:
        cli_choice = "claude"
    else:
        cli_choice = _choose("Which CLI tool do you use?", CLI_CHOICES, default="claude")

    if cli_choice == "claude" and not shutil.which("claude"):
        _handle_missing_claude(non_interactive)

    if non_interactive:
        flag_variant = "default"
    else:
        flag_variant = _choose(
            f"How should I launch {cli_choice}?",
            FLAG_CHOICES,
            default="default",
        )

    success(f"{cli_choice} ({flag_variant})")
    _save_stage(5, {"cli": cli_choice, "flag_variant": flag_variant}, dry_run=dry_run)

    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would save preferred_cli={cli_choice} to profile")
    else:
        try:
            from aipass.aipass.apps.modules import profile as profile_mod

            p = profile_mod.get_user_profile()
            p["preferred_cli"] = cli_choice
            profile_mod.save_profile(p)
        except Exception as exc:
            logger.warning("[init_flow] could not persist cli to profile: %s", exc)

    return {"cli": cli_choice, "flag_variant": flag_variant}


def stage_6_first_agent(non_interactive: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Create the user's first AI agent via drone @spawn."""
    console.print()
    console.print(render_step_header(6, TOTAL_STAGES, "Create your first agent"))
    console.print("Let's create your first AI agent (citizen).")

    if non_interactive:
        agent_name = "my_agent"
    else:
        agent_name = _prompt("Agent name (letters, underscores, no spaces)", "my_agent") or "my_agent"

    package_dir = _resolve_package_dir()
    if package_dir:
        agent_path = f"{package_dir}/{agent_name}"
    else:
        agent_path = f"src/{agent_name}"
    console.print(f"[cyan]Creating your first agent[/cyan] [dim](drone @spawn create {agent_path})…[/dim]")

    spawned = False
    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would run: drone @spawn create {agent_path}")
        spawned = True
    else:
        try:
            proc = subprocess.run(["drone", "@spawn", "create", agent_path], timeout=60)
            spawned = proc.returncode == 0
        except FileNotFoundError as exc:
            logger.warning("[init_flow] drone not found in stage 6: %s", exc)
            warning("drone not found — skipping agent creation.")
        except subprocess.TimeoutExpired as exc:
            logger.warning("[init_flow] spawn timed out in stage 6: %s", exc)
            warning("spawn timed out — agent may still be created.")

    if spawned:
        success(f"Agent created at {agent_path}")

    _save_stage(6, {"agent_name": agent_name, "agent_path": agent_path, "success": spawned}, dry_run=dry_run)
    return {"agent_name": agent_name, "agent_path": agent_path}


def stage_7_ping_sweep(non_interactive: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Ping all registered branches via test-convention emails."""
    console.print()
    console.print(render_step_header(7, TOTAL_STAGES, "Pinging agents"))

    from aipass.aipass.apps.handlers import ping_sweep

    branches = ping_sweep._discover_branches()
    if not branches:
        console.print("[dim]  No branches registered yet — skipping ping sweep.[/dim]")
        _save_stage(7, {"results": {}, "skipped": True}, dry_run=dry_run)
        return {"ping_results": {}}

    # Standalone projects can't ping agents via drone (drone only knows AIPass's registry).
    # Only attempt ping if we're inside the AIPass source tree.
    aipass_registry = _BRANCH_ROOT.parent / "AIPASS_REGISTRY.json"
    if not aipass_registry.exists():
        if len(branches) == 1:
            console.print("[dim]  1 agent registered. Ping skipped — ping is for multi-agent projects.[/dim]")
        else:
            console.print(f"[dim]  Found {len(branches)} agent(s) in this project.[/dim]")
            console.print("[dim]  Ping skipped — agents will be reachable after handoff (next step).[/dim]")
        _save_stage(7, {"results": {}, "skipped_standalone": True}, dry_run=dry_run)
        return {"ping_results": {}}

    console.print(f"[dim]  Found {len(branches)} agent(s). Checking reachability...[/dim]")
    console.print(
        "[dim]  (Agents with a running session will auto-ack; new agents will time out — that's normal.)[/dim]"
    )

    with activity_spinner("Pinging agents…"):
        results = ping_sweep.sweep_all_branches(timeout=10)

    for branch, status in results.items():
        if status == "ack":
            glyph = "[green]✓[/green]"
        elif status == "timeout":
            glyph = "[yellow]—[/yellow]"
        else:
            glyph = "[red]✗[/red]"
        label = "reachable" if status == "ack" else "not running" if status == "timeout" else "error"
        console.print(f"  {glyph} @{branch}: {label}")

    summary = ping_sweep.sweep_summary(results)
    console.print(f"  {summary}")
    _save_stage(7, {"results": results}, dry_run=dry_run)
    return {"ping_results": results}


def stage_8_smoke_test(non_interactive: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Verify drone and aipass binaries are on PATH."""
    console.print()
    console.print(render_step_header(8, TOTAL_STAGES, "Smoke test"))

    drone_bin = shutil.which("drone")
    aipass_bin = shutil.which("aipass")

    if drone_bin:
        success(f"drone: {drone_bin}")
    else:
        warning("drone not on PATH — clone the repo and run setup.sh")

    if aipass_bin:
        success(f"aipass: {aipass_bin}")
    else:
        warning("aipass not on PATH — clone the repo and run setup.sh")

    console.print("[dim]Full cross-OS pre-flight: aipass doctor --cross-os[/dim]")

    _save_stage(8, {"drone": drone_bin, "aipass": aipass_bin}, dry_run=dry_run)
    return {"drone": drone_bin, "aipass": aipass_bin}


def stage_9_handoff(
    cli_choice: str = "claude",
    flag_variant: str = "default",
    agent_path: str = "src/my_agent",
    non_interactive: bool = False,
    dry_run: bool = False,
    accumulated: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Launch user's chosen CLI — inline (same terminal) or new window."""
    console.print()
    console.print(render_step_header(9, TOTAL_STAGES, "Handoff"))

    from aipass.aipass.apps.modules.handoff import INIT_PROMPT

    init_prompt = INIT_PROMPT

    _template = (accumulated or {}).get("template", TEMPLATE_AIPASS)
    console.print()
    if _template == TEMPLATE_AIPASS:
        console.print("  Your agent is ready.")
        console.print(f"  [dim]CLI: {cli_choice} | Agent: {agent_path}[/dim]")
    else:
        _display = str(Path(agent_path).resolve()) if agent_path == "." else agent_path
        console.print("  Your project is ready — launching your CLI.")
        console.print(f"  [dim]CLI: {cli_choice} | Project: {_display}[/dim]")

    from aipass.aipass.apps.handlers.handoff_platform import build_manual_command

    display_path = str(Path(agent_path).resolve()) if agent_path == "." else agent_path
    command = build_manual_command(cli_choice, init_prompt, display_path, flag_variant)
    inline = False

    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would launch handoff: {command}")
        launched = False
    elif non_interactive:
        console.print()
        console.print("  [dim]Next step (run manually):[/dim]")
        console.print(f"  [cyan]{command}[/cyan]")
        console.print()
        launched = False
    else:
        console.print()
        console.print("  [bold]1.[/bold] Stay here — launch agent in this terminal")
        console.print("  [bold]2.[/bold] New window — open agent in a separate terminal")
        console.print()
        choice = input("  Choice [1]: ").strip()
        inline = choice != "2"

        if inline:
            _save_stage(9, {"command": command, "launched": True, "inline": True}, dry_run=dry_run)
            _save_stage(10, dry_run=dry_run)
            if accumulated:
                _write_init_report(accumulated.get("agent_path", agent_path), accumulated, dry_run=dry_run)
            console.print()
            success("Setup complete!")
            console.print()
            from aipass.aipass.apps.handlers.handoff_platform import launch_inline

            launch_inline(cli_choice, init_prompt, agent_path, flag_variant)
            launched = False
        else:
            from aipass.aipass.apps.modules import handoff as handoff_mod

            launched = handoff_mod.do_handoff(
                cli=cli_choice,
                prompt=init_prompt,
                cwd=agent_path,
                flag_variant=flag_variant,
            )

    if not inline:
        _save_stage(9, {"command": command, "launched": launched}, dry_run=dry_run)
    return {"handoff_command": command, "launched": launched}


def _collect_provider_gaps() -> Dict[str, Any]:
    """Gather provider-manifest gaps for the init report — standalone, no full doctor run."""
    gaps: Dict[str, Any] = {}
    try:
        from aipass.aipass.apps.modules import doctor

        for r in doctor._check_provider_manifest():
            if r.glyph != doctor.GLYPH_PASS:
                gaps[r.label] = r.detail
    except Exception as exc:
        logger.warning("[init_flow] provider manifest check failed: %s", exc)
    return gaps


def _write_init_report(agent_path: str, accumulated: Dict[str, Any], dry_run: bool = False) -> None:
    """Drop init_report.json into the agent's dropbox."""
    if dry_run or not agent_path:
        return
    dropbox = Path(agent_path) / "dropbox"
    dropbox.mkdir(parents=True, exist_ok=True)
    system_data = {k: accumulated.get(k) for k in ("os", "python", "shell", "ram_gb", "install") if accumulated.get(k)}
    report = {
        "created": datetime.now(timezone.utc).isoformat(),
        "project_name": Path.cwd().name,
        "project_path": str(Path.cwd()),
        "agent_name": accumulated.get("agent_name", Path(agent_path).name.upper()),
        "agent_number": 1,
        "is_orchestrator": True,
        "install_method": accumulated.get("install", "unknown"),
        "cli_choice": accumulated.get("cli", "claude"),
        "total_agents": 1,
        "system": system_data,
        "note": (
            "You are the first agent created in this project. You are the orchestrator."
            " After dispatching work to other agents, monitor them with:"
            " drone @devpulse watchdog agent @target"
        ),
    }
    provider_gaps = _collect_provider_gaps()
    if provider_gaps:
        report["provider_gaps"] = provider_gaps
        report["provider_action"] = (
            "Provider settings need configuring. Tell the user what is missing"
            " and point them to provider_manifest.json for details."
        )
    report_path = dropbox / "init_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    logger.info("[init_flow] init report written to %s", report_path)


def stage_10_done(accumulated: Dict[str, Any] | None = None, dry_run: bool = False) -> Dict[str, Any]:
    """Print completion summary and drop init report."""
    console.print()
    console.print(render_step_header(10, TOTAL_STAGES, "Done!"))
    console.print()
    success("Setup complete!")
    console.print()
    console.print("  [cyan]aipass help[/cyan]     [dim]# Ask any question[/dim]")
    console.print("  [cyan]aipass doctor[/cyan]   [dim]# Check system health[/dim]")
    console.print("  [cyan]aipass profile[/cyan]  [dim]# View your profile[/dim]")
    console.print()
    if accumulated:
        _write_init_report(accumulated.get("agent_path", ""), accumulated, dry_run=dry_run)
    _save_stage(10, dry_run=dry_run)
    return {}


# --- MAIN RUNNER ---
def _preflight_check(*, allow_projects_child: bool = False) -> str | None:
    """Return an error message if CWD is unsafe for init, else None.

    When *allow_projects_child* is True, the nested-project check is skipped
    if CWD is ``<host>/projects/<name>``.
    """
    cwd = Path.cwd()
    # Block if inside an agent directory
    if (cwd / ".trinity" / "passport.json").is_file():
        return (
            "This directory is an agent branch (has .trinity/passport.json).\n"
            "Agents are managed by 'drone @spawn', not 'aipass init'."
        )
    # Early exit: if CWD is a valid <host>/projects/<name>, skip nesting check
    if allow_projects_child:
        from aipass.aipass.apps.handlers.init.bootstrap import is_projects_child

        if is_projects_child(cwd):
            return None
    # Block if inside an existing AIPass project (registry above us).
    # Walking up to the filesystem root can hit ancestors that can't be
    # enumerated or stat'd — e.g. locked Windows system entries at the drive
    # root (pagefile.sys) raise OSError. Skip those rather than crash; on
    # POSIX everything up to / is readable so behaviour is unchanged there.
    for parent in [cwd] + list(cwd.parents):
        try:
            entries = list(parent.iterdir())
        except OSError as exc:
            logger.info("[init_flow] skipping unreadable ancestor %s: %s", parent, exc)
            entries = []
        for f in entries:
            try:
                is_registry = f.is_file() and f.name.endswith("_REGISTRY.json")
            except OSError as exc:
                logger.info("[init_flow] skipping unstattable entry %s: %s", f, exc)
                continue
            if is_registry:
                if f.name == "AIPASS_REGISTRY.json":
                    return (
                        f"This is the AIPass engine repo itself (found {f.name} at {parent}),\n"
                        "not a project. Projects live in their own directory — cd into one "
                        "(e.g. ~/aipass-project) and run 'aipass init run' there."
                    )
                return (
                    f"Already inside an AIPass project (found {f.name} at {parent}).\n"
                    f"Use 'aipass init update {parent}' to upgrade it."
                )
        if parent == parent.parent:
            break
    return None


def run_init(
    non_interactive: bool = False,
    name: str | None = None,
    cli: str | None = None,
    style: str | None = None,
    dry_run: bool = False,
    template: str | None = None,
) -> int:
    """Run the 10-stage init flow. Returns 0 on success."""
    if not sys.stdin.isatty():
        non_interactive = True

    # Pre-flight: refuse to run inside existing projects or agent dirs
    err = _preflight_check()
    if err:
        cli_error(str(err))
        return 1

    # Template selection — before scaffold
    if template is None:
        if non_interactive:
            template = TEMPLATE_EMPTY
        else:
            template = _choose(
                "Choose a project template:",
                TEMPLATE_CHOICES,
                default=TEMPLATE_EMPTY,
            )

    # Ensure scaffold exists — only for aipass_framework
    cwd = Path.cwd()
    if template == TEMPLATE_AIPASS and not registries_in(cwd):
        from aipass.aipass.apps.handlers.init.bootstrap import init_project

        if not dry_run:
            with activity_spinner("Building project scaffold…"):
                init_project(cwd)
            success("Project scaffold ready")
        else:
            console.print("[yellow]\\[dry-run][/yellow] would create project scaffold")

    # In dry-run we ignore on-disk progress so the full flow always walks.
    last_done = 0 if dry_run else _get_last_completed_stage()

    if last_done >= TOTAL_STAGES:
        success("Setup already complete.")
        console.print("[dim]Run 'aipass doctor' to check status.[/dim]")
        return 0

    if last_done > 0:
        warning(f"Resuming from stage {last_done + 1}...")

    accumulated: Dict[str, Any] = {"template": template}
    if template != TEMPLATE_AIPASS:
        accumulated["agent_path"] = "."

    stage_fns = [
        (1, lambda: stage_1_welcome(dry_run=dry_run)),
        (2, lambda: stage_2_system_detect(non_interactive, dry_run=dry_run)),
        (3, lambda: stage_3_user_profile(non_interactive, name, accumulated, dry_run=dry_run)),
        (4, lambda: stage_4_style_questions(non_interactive, style, dry_run=dry_run)),
        (5, lambda: stage_5_tool_choice(non_interactive, cli, dry_run=dry_run)),
        (6, lambda: stage_6_first_agent(non_interactive, dry_run=dry_run)),
        (7, lambda: stage_7_ping_sweep(non_interactive, dry_run=dry_run)),
        (8, lambda: stage_8_smoke_test(non_interactive, dry_run=dry_run)),
        (
            9,
            lambda: stage_9_handoff(
                accumulated.get("cli", "claude"),
                accumulated.get("flag_variant", "default"),
                accumulated.get("agent_path", "src/my_agent"),
                non_interactive,
                dry_run=dry_run,
                accumulated=accumulated,
            ),
        ),
        (10, lambda: stage_10_done(accumulated=accumulated, dry_run=dry_run)),
    ]

    for stage_num, fn in stage_fns:
        if stage_num <= last_done:
            continue
        if stage_num in AIPASS_SPECIFIC_STAGES and template != TEMPLATE_AIPASS:
            logger.info("[init_flow] skipping stage %d (not aipass_framework)", stage_num)
            if not non_interactive:
                console.print(f"\n[dim]  (skipping step {stage_num} — framework-only)[/dim]")
            continue
        try:
            result = fn() or {}
            accumulated.update(result)
        except KeyboardInterrupt:
            logger.info("[init_flow] init paused at stage %d by user", stage_num)
            warning(f"Paused at stage {stage_num}. Run 'aipass init run' to resume.")
            return 0
        except Exception as exc:
            logger.warning("[init_flow] stage %d error: %s", stage_num, exc)
            warning(f"Stage {stage_num} error: {exc} — continuing.")
            _save_stage(stage_num, {"error": str(exc)}, dry_run=dry_run)

    return 0


# --- INTROSPECTION + HELP ---
def print_introspection() -> None:
    """Show module info and current setup progress."""
    progress = _get_setup_progress()
    last = progress.get("last_completed_stage", 0)
    console.print()
    console.print("[bold cyan]init_flow Module[/bold cyan]")
    console.print("10-stage guided first-run setup, resumable")
    console.print()
    if last == 0:
        console.print("[dim]Setup not started. Run: aipass init run[/dim]")
    elif last >= TOTAL_STAGES:
        success("Setup complete.")
    else:
        console.print(f"[yellow]In progress:[/yellow] stage {last}/{TOTAL_STAGES} completed.")
        console.print(f"[dim]Run 'aipass init run' to resume from stage {last + 1}.[/dim]")
    console.print()


def print_help() -> None:
    """Print usage help for the init command."""
    console.print()
    console.print("[bold cyan]aipass init[/bold cyan] — guided first-run setup")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass init run[/green]                      [dim]# interactive[/dim]")
    console.print("  [green]aipass init run --non-interactive[/green]    [dim]# CI/headless[/dim]")
    console.print("  [green]aipass init run --name YourName[/green]      [dim]# pre-fill name[/dim]")
    console.print("  [green]aipass init run --cli claude[/green]         [dim]# pre-fill CLI[/dim]")
    console.print("  [green]aipass init run --template <name>[/green]    [dim]# select template[/dim]")
    console.print("  [green]aipass init run --dry-run[/green]            [dim]# walk all stages, no writes[/dim]")
    console.print("  [green]aipass init --list[/green]                   [dim]# list available templates[/dim]")
    console.print("  [green]aipass init update \\[target][/green]          [dim]# refresh scaffold + git auth[/dim]")
    console.print("  [green]aipass init update --dry-run[/green]         [dim]# preview git-auth repairs only[/dim]")
    console.print()
    console.print("[yellow]STAGES:[/yellow] 10 stages, each saved — resume on ctrl-C")
    console.print()


# --- COMMAND HANDLER ---
def _handle_init_scaffold(args: list[str]) -> int:
    """Handle `aipass init [target] [name]` — instant project scaffold."""
    from aipass.aipass.apps.handlers.init.bootstrap import init_project

    target = Path(args[0]) if args else Path.cwd()
    project_name = args[1] if len(args) > 1 else None
    try:
        result = init_project(target, project_name)
        success(f"Project initialized at {target}")
        console.print()

        # Find the package directory to show in guidance
        package_dir = None
        for child in (target / "src").iterdir():
            if child.is_dir() and (child / "__init__.py").is_file():
                package_dir = child
                break

        console.print("[bold]Project structure:[/bold]")
        console.print(f"  {target}/")
        if package_dir:
            rel_pkg = package_dir.relative_to(target)
            console.print(f"  └── {rel_pkg}/    [dim]← agents live here[/dim]")
        console.print()
        console.print("[bold]Next steps:[/bold]")
        if str(target) != str(Path.cwd()):
            console.print(f"  [cyan]cd {target}[/cyan]")
        console.print("  [cyan]aipass init agent <name>[/cyan]    [dim]# create your first agent[/dim]")
        console.print("  [cyan]aipass init run[/cyan]             [dim]# full guided setup (optional)[/dim]")
        console.print()

        json_handler.log_operation("aipass_init", {"target": str(target), "result": result})
        return 0
    except Exception as exc:
        logger.warning("[init_flow] scaffold failed: %s", exc)
        cli_error(f"Init failed: {exc}")
        return 1


def _run_git_auth_provisioning(target: Path, dry_run: bool = False) -> int:
    """Provision the project for manager-class git; print every repair.

    Returns 0 when the four owner-tier conditions hold (or already held), 1 when
    the run refused. A refusal is not a crash — it names what a human must add,
    and nothing was written.
    """
    from aipass.aipass.apps.handlers.init.git_auth import GitAuthRefusal, provision_git_auth

    console.print()
    console.print("[bold]Git authorization (owner-tier)[/bold]")
    try:
        result = provision_git_auth(target, dry_run=dry_run)
    except GitAuthRefusal as exc:
        cli_error(f"Cannot provision git authorization: {exc}")
        logger.warning("[init_flow] git-auth provisioning refused: %s", exc)
        json_handler.log_operation("aipass_git_auth", {"target": str(target), "refusal": str(exc)})
        return 1

    repairs = result["repairs"]
    verb = "would repair" if dry_run else "repaired"
    if repairs:
        success(f"Owner '{result['owner']}' — {verb} {len(repairs)} item(s):")
        for item in repairs:
            console.print(f"  + {item}")
    else:
        success(f"Owner '{result['owner']}' already holds owner-tier — nothing to repair.")
    for item in result["already_ok"]:
        console.print(f"  [dim]· {item}[/dim]")

    if dry_run:
        console.print("[dim]Preview only — no files written.[/dim]")
    elif result["verified"]:
        success("Verified against all four owner-tier checks.")
    else:
        cli_error("Repairs written, but verification still fails:")
        for item in result["verify_failures"]:
            console.print(f"  - {item}")

    # No log_operation on this path — the handler already recorded exactly what
    # it wrote; a second entry here would only duplicate it.
    return 0 if dry_run or result["verified"] else 1


def _handle_init_update(args: list[str]) -> int:
    """Handle `aipass init update [target] [--dry-run]` — refresh scaffold + git auth."""
    from aipass.aipass.apps.handlers.init.bootstrap import update_project

    dry_run = "--dry-run" in args
    positional = [a for a in args if not a.startswith("--")]
    target = Path(positional[0]) if positional else Path.cwd()

    if dry_run:
        # Scaffold refresh has no preview mode, so say so rather than implying
        # this previewed the whole command.
        console.print("[dim]Preview mode — scaffold refresh skipped; git-auth provisioning is planned only.[/dim]")
        return _run_git_auth_provisioning(target, dry_run=True)

    try:
        result = update_project(target)
        updated = result.get("updated_files", [])
        current = result.get("already_current", [])
        if updated:
            success(f"Updated {len(updated)} file(s):")
            for f in updated:
                console.print(f"  + {f}")
        else:
            success("All files already current.")
        if current:
            console.print(f"  ({len(current)} already up to date)")
        if result.get("trust_enrolled"):
            success("Enrolled in trust registry — hooks active.")
        # Owner/identity check + heal via the frozen sync-registry contract
        try:
            check_proc = subprocess.run(
                ["drone", "@spawn", "sync-registry", "--check"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if check_proc.returncode != 0:
                warning("Owner/identity issues detected — auto-repairing…")
                fix_proc = subprocess.run(
                    ["drone", "@spawn", "sync-registry", "--fix"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if fix_proc.returncode == 0:
                    success("Registry owner/identity reconciled.")
                else:
                    logger.warning("[init_flow] sync-registry --fix exit %s", fix_proc.returncode)
            else:
                success("Owner/identity OK.")
        except FileNotFoundError:
            logger.info("[init_flow] drone not on PATH — skipping owner check")
        except subprocess.TimeoutExpired:
            logger.warning("[init_flow] sync-registry timed out during update")
        except Exception as sync_exc:
            logger.warning("[init_flow] registry sync during update skipped: %s", sync_exc)

        json_handler.log_operation("aipass_init_update", {"target": str(target), "result": result})
    except Exception as exc:
        logger.warning("[init_flow] update failed: %s", exc)
        cli_error(f"Update failed: {exc}")
        return 1

    # Last, so it wins: sync-registry above may migrate a legacy citizen_class,
    # and the owner's class must end up 'manager' for drone to grant git. Outside
    # the try so a git-auth fault is never reported as a scaffold-update failure.
    return _run_git_auth_provisioning(target)


def _handle_init_agent(args: list[str]) -> int:
    """Handle `aipass init agent <name>` — create a new agent via spawn."""
    if not args:
        cli_error("Usage: aipass init agent <name>")
        return 1
    agent_name = args[0]
    import subprocess as _sp

    package_dir = _resolve_package_dir()
    if package_dir:
        agent_path = f"{package_dir}/{agent_name}"
    else:
        agent_path = f"src/{agent_name}"

    cmd = ["drone", "@spawn", "create", agent_path]
    console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
    result = _sp.run(cmd, capture_output=False)
    return result.returncode


def handle_command(command: str, args: list[str]) -> bool:
    """Route init subcommands. Returns True if handled, False otherwise."""
    if command != COMMAND:
        return False

    if not args:
        print_help()
        return True

    if wants_help(args):
        print_help()
        return True

    if args[0] == "--info":
        print_introspection()
        return True

    if args[0] == "agent":
        sys.exit(_handle_init_agent(args[1:]))
        return True

    if args[0] == "update":
        sys.exit(_handle_init_update(args[1:]))
        return True

    if args[0] == "--list":
        console.print()
        console.print("[bold cyan]Available project templates:[/bold cyan]")
        for t in TEMPLATE_CHOICES:
            marker = " [dim](default)[/dim]" if t == TEMPLATE_EMPTY else ""
            console.print(f"  • {t}{marker}")
        console.print()
        return True

    if args[0] == "run" or args[0].startswith("--"):
        run_args = args[1:] if args[0] == "run" else args
        non_interactive = "--non-interactive" in run_args

        def _flag_value(flag: str) -> str | None:
            """Extract the value after a named flag, or None if absent."""
            if flag not in run_args:
                return None
            idx = run_args.index(flag)
            return run_args[idx + 1] if idx + 1 < len(run_args) else None

        name = _flag_value("--name")
        cli = _flag_value("--cli")
        style = _flag_value("--style")
        template = _flag_value("--template")
        dry_run = "--dry-run" in run_args

        result = run_init(
            non_interactive=non_interactive,
            name=name,
            cli=cli,
            style=style,
            dry_run=dry_run,
            template=template,
        )
        json_handler.log_operation(
            "init_run",
            {"non_interactive": non_interactive, "dry_run": dry_run, "exit": result},
        )
        sys.exit(result)
        return True

    # Template name as positional arg
    if args[0] in TEMPLATE_CHOICES:
        result = run_init(template=args[0])
        sys.exit(result)
        return True

    # Positional args = target path and/or project name for scaffold
    err = _preflight_check()
    if err:
        cli_error(str(err))
        sys.exit(1)
    sys.exit(_handle_init_scaffold(args))
    return True


if __name__ == "__main__":
    # Windows terminals/pipes default to cp1252, which can't encode the Unicode
    # Rich emits (✓/✗, box-drawing). Reconfigure live streams to UTF-8 in place
    # so a direct `python -m ...init_flow` run doesn't crash printing its banner.
    # Guarded to win32 — mirrors apps/aipass.py (S190 / gap #1).
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONUTF8", "1")
        for _stream in (sys.stdout, sys.stderr):
            if hasattr(_stream, "reconfigure"):
                _stream.reconfigure(encoding="utf-8", errors="replace")

    handle_command("init", sys.argv[1:])
