# =================== AIPass ====================
# Name: handoff_platform/__init__.py
# Description: Inline CLI session launch and its return-path line
# Version: 2.0.0
# Created: 2026-04-20
# Modified: 2026-11-14
# =============================================

"""handoff_platform — `aipass new` replaces its process with a CLI session in the agent's directory."""

from __future__ import annotations

import shlex
import shutil
from typing import Callable, List, Optional

from aipass.prax import logger

CODEX_BYPASS_FLAG = "--dangerously-bypass-approvals-and-sandbox"
OPENCODE_LAUNCH = 'PATH="$HOME/.opencode/bin:$PATH" opencode --standalone --auto --prompt'


def build_cli_cmd(cli: str) -> str:
    """Build the CLI invocation string from the cli name."""
    if cli == "codex":
        # The hooks gate every CLI, so Codex runs in the posture the rooms and dispatch use.
        return f"{cli} {CODEX_BYPASS_FLAG}"
    if cli == "opencode":
        # BAUD's room shape: PATH for the curl install; --standalone so AIPASS_HOME reaches the hooks.
        return OPENCODE_LAUNCH
    return cli


def return_path_breadcrumb(cwd: str, cli: str = "claude") -> str:
    """The line back into this agent's session: Claude's own `--resume <id>` hint omits the per-directory cwd."""
    resume = "codex resume --last" if cli == "codex" else "claude --continue"
    return f"cd {shlex.quote(cwd)} && {resume}"


def launch_inline(
    cli: str,
    prompt: str,
    cwd: str,
    which: Optional[Callable[[str], Optional[str]]] = None,
    chdir: Optional[Callable[[str], None]] = None,
    execvp: Optional[Callable[[str, List[str]], None]] = None,
) -> None:
    """Exec the CLI in *cwd*, breadcrumb baked into the shell line; which/chdir/execvp are test seams."""
    import os

    which = shutil.which if which is None else which
    chdir = os.chdir if chdir is None else chdir
    execvp = os.execvp if execvp is None else execvp
    cli_cmd = build_cli_cmd(cli)
    cli_bin = cli_cmd.split()[0]
    cli_path = which(cli_bin)
    if not cli_path:
        logger.warning("[handoff_platform] %s not found on PATH, cannot exec inline", cli_bin)
        return

    chdir(cwd)
    argv = [cli_path, *cli_cmd.split()[1:], prompt]
    breadcrumb = return_path_breadcrumb(cwd, cli)
    shell_cmd = f"{shlex.join(argv)}; printf '\\n%s\\n' {shlex.quote(breadcrumb)}"
    shell = which("bash") or which("sh") or "/bin/sh"
    logger.info("[handoff_platform] exec inline via shell: %s (cwd=%s)", shell_cmd, cwd)
    execvp(shell, [shell, "-c", shell_cmd])
