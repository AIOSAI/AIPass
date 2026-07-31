# =================== AIPass ====================
# Name: handoff_platform/__init__.py
# Description: OS-dispatched CLI session launch — tmux, wt.exe, fallback
# Version: 1.0.0
# Created: 2026-04-20
# Modified: 2026-04-20
# =============================================

"""
handoff_platform — OS-dispatched CLI session launch.

Consumers: modules/handoff.py, modules/init_flow.py (stage 11).

Linux/Mac: tmux new-session -d -s aipass-handoff -c <cwd>; send-keys '<cli> "<prompt>"'
Windows:   wt.exe -w 0 nt -d <cwd> <cli> "<prompt>"  (Windows Terminal)
Fallback:  caller receives command string for manual display — no silent fail.

All public functions return data; presentation is handled by the module layer.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Optional

from aipass.prax import logger

# Platform constants — consistent with setup.sh naming
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

_TMUX_SESSION = "aipass-handoff"


def build_cli_cmd(cli: str, flag_variant: str) -> str:
    """Build the CLI invocation string from cli name and flag variant."""
    parts = [cli]
    if cli == "claude" and flag_variant == "skip-permissions":
        parts.append("--dangerously-skip-permissions")  # noqa: S603
    return " ".join(parts)


def build_manual_command(cli: str, prompt: str, cwd: str, flag_variant: str = "default") -> str:
    """Return the equivalent manual shell command for user display."""
    cli_cmd = build_cli_cmd(cli, flag_variant)
    safe_prompt = prompt.replace('"', '\\"')
    return f'cd {cwd} && {cli_cmd} "{safe_prompt}"'


def return_path_breadcrumb(cwd: str) -> str:
    """The exact line to get back into this agent's Claude Code session.

    Claude Code's own exit hint prints a bare `--resume <id>` with no cwd —
    session stores are per-directory, so that hint fails from anywhere else.
    `--continue` from the right directory needs no id.
    """
    return f"cd {cwd} && claude --continue"


def _find_terminal_emulator() -> str | None:
    """Find an available terminal emulator on the system."""
    for term in ("gnome-terminal", "xfce4-terminal", "konsole", "xterm"):
        if shutil.which(term):
            return term
    return None


def launch_terminal(cli: str, prompt: str, cwd: str, flag_variant: str = "default") -> bool:
    """Open a new terminal window running the CLI directly. No tmux needed."""
    term = _find_terminal_emulator()
    if not term:
        logger.warning("[handoff_platform] no terminal emulator found")
        return False

    cli_cmd = build_cli_cmd(cli, flag_variant)
    safe_prompt = prompt.replace('"', '\\"')
    shell_cmd = f'cd "{cwd}" && {cli_cmd} "{safe_prompt}"'

    try:
        if term == "gnome-terminal":
            subprocess.Popen(["gnome-terminal", "--", "bash", "-c", shell_cmd])
        elif term == "xfce4-terminal":
            subprocess.Popen(["xfce4-terminal", "-e", f"bash -c '{shell_cmd}'"])
        elif term == "konsole":
            subprocess.Popen(["konsole", "-e", "bash", "-c", shell_cmd])
        elif term == "xterm":
            subprocess.Popen(["xterm", "-e", f"bash -c '{shell_cmd}'"])
        else:
            return False
        logger.info("[handoff_platform] opened %s in %s (cwd=%s)", term, cli, cwd)
        from aipass.cli.apps.modules import console

        console.print("\n  [green]✓[/green] Opened your agent in a new terminal window.")
        console.print()
        return True
    except OSError as exc:
        logger.warning("[handoff_platform] failed to open terminal: %s", exc)
        return False


def launch_tmux(cli: str, prompt: str, cwd: str, flag_variant: str = "default") -> bool:
    """Launch CLI in a tmux session (fallback when no terminal emulator available)."""
    if not shutil.which("tmux"):
        logger.warning("[handoff_platform] tmux not found on PATH")
        return False

    cli_cmd = build_cli_cmd(cli, flag_variant)
    safe_prompt = prompt.replace('"', '\\"')

    try:
        subprocess.run(
            ["tmux", "kill-session", "-t", _TMUX_SESSION],
            capture_output=True,
            timeout=5,
        )
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", _TMUX_SESSION, "-c", cwd],
            check=True,
            timeout=10,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", _TMUX_SESSION, f'{cli_cmd} "{safe_prompt}"', "Enter"],
            check=True,
            timeout=10,
        )
        logger.info("[handoff_platform] tmux session '%s' started in %s", _TMUX_SESSION, cwd)
        from aipass.cli.apps.modules import console

        console.print("\n  [green]✓[/green] Your agent is ready! Run this in your terminal:")
        console.print(f"\n    [bold green]tmux attach -t {_TMUX_SESSION}[/bold green]\n")
        console.print()
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("[handoff_platform] tmux launch failed: %s", exc)
        return False
    except subprocess.TimeoutExpired as exc:
        logger.warning("[handoff_platform] tmux command timed out: %s", exc)
        return False


def launch_wt(cli: str, prompt: str, cwd: str, flag_variant: str = "default") -> bool:
    """Launch CLI in Windows Terminal (wt.exe). Returns True on success."""
    if not shutil.which("wt"):
        logger.warning("[handoff_platform] wt.exe not found on PATH")
        return False

    cli_cmd = build_cli_cmd(cli, flag_variant)
    safe_prompt = prompt.replace('"', '\\"')

    try:
        subprocess.run(
            ["wt", "-w", "0", "nt", "-d", cwd, cli_cmd, f'"{safe_prompt}"'],
            check=True,
            timeout=15,
        )
        logger.info("[handoff_platform] wt.exe session started in %s", cwd)
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("[handoff_platform] wt.exe launch failed: %s", exc)
        return False
    except subprocess.TimeoutExpired as exc:
        logger.warning("[handoff_platform] wt.exe command timed out: %s", exc)
        return False


def launch_inline(cli: str, prompt: str, cwd: str, flag_variant: str = "default") -> None:
    """Replace the current process with the CLI in the agent directory. Does not return.

    Wraps the CLI in a shell so a return-path breadcrumb prints once the
    session exits (see ``return_path_breadcrumb``) — ``execvp`` replaces this
    process outright, so nothing after this call can print once the CLI
    starts; the breadcrumb has to be baked into the exec'd command itself.
    """
    import os
    import shlex

    cli_cmd = build_cli_cmd(cli, flag_variant)
    cli_bin = cli_cmd.split()[0]
    cli_path = shutil.which(cli_bin)
    if not cli_path:
        logger.warning("[handoff_platform] %s not found on PATH, cannot exec inline", cli_bin)
        return

    os.chdir(cwd)
    argv = [cli_path, *cli_cmd.split()[1:], prompt]
    breadcrumb = return_path_breadcrumb(cwd)
    shell_cmd = f"{shlex.join(argv)}; printf '\\n%s\\n' {shlex.quote(breadcrumb)}"
    shell = shutil.which("bash") or shutil.which("sh") or "/bin/sh"
    logger.info("[handoff_platform] exec inline via shell: %s (cwd=%s)", shell_cmd, cwd)
    os.execvp(shell, [shell, "-c", shell_cmd])


def launch_handoff(
    cli: str,
    prompt: str,
    cwd: str,
    flag_variant: str = "default",
    platform_override: Optional[str] = None,
    inline: bool = False,
) -> tuple[bool, str]:
    """
    Dispatch CLI launch to the appropriate platform handler.

    Returns (launched, manual_command):
      launched=True  — tmux/wt session was started successfully
      launched=False — auto-launch unavailable; caller displays manual_command
      manual_command — always populated; equivalent command for manual run

    If inline=True, replaces the current process (does not return).

    Order: inline → terminal (Linux/Mac) → wt.exe (Windows) → tmux → fallback.
    """
    manual_cmd = build_manual_command(cli, prompt, cwd, flag_variant)

    if inline:
        launch_inline(cli, prompt, cwd, flag_variant)
        return False, manual_cmd

    target = platform_override or ("windows" if IS_WINDOWS else "unix")

    if target == "windows":
        if launch_wt(cli, prompt, cwd, flag_variant):
            return True, manual_cmd
    else:
        if launch_terminal(cli, prompt, cwd, flag_variant):
            return True, manual_cmd
        if launch_tmux(cli, prompt, cwd, flag_variant):
            return True, manual_cmd

    logger.info("[handoff_platform] auto-launch unavailable — fallback command ready")
    return False, manual_cmd
