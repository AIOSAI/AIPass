# =================== AIPass ====================
# Name: provider_choice.py
# Description: The install's last question: which CLI talks to devpulse; install, wire, open it
# Version: 1.0.0
# Created: 2026-11-24
# Modified: 2026-11-26
# =============================================

"""provider_choice: one provider picked at the end of the install, installed by its vendor, wired, opened.

Only the chosen CLI is wired; a missing one is installed with its vendor's published
installer, never a copy kept in this repo.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.settings_backup import SettingsBackupError
from aipass.prax import logger


class Provider(NamedTuple):
    """One CLI the user may talk to devpulse with."""

    title: str
    binary: str
    installer: List[str]
    install_page: str
    extra_bins: tuple


# Each installer is the line on its install_page (checked 2026-11-24); the page is what a failure prints.
PROVIDERS = {
    "claude": Provider(
        "Claude Code",
        "claude",
        ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"],
        "https://code.claude.com/docs/en/setup",
        (".local/bin/claude",),
    ),
    "codex": Provider(
        "Codex", "codex", ["npm", "install", "-g", "@openai/codex"], "https://github.com/openai/codex#quickstart", ()
    ),
    "opencode": Provider(
        "OpenCode",
        "opencode",
        ["bash", "-c", "curl -fsSL https://opencode.ai/v2/install | bash"],
        "https://github.com/sst/opencode#installation",
        (".opencode/bin/opencode",),
    ),
}
ORDER = ("claude", "codex", "opencode")


def cli_path(key: str) -> Optional[str]:
    """Where the provider's CLI is, PATH first then its installer's own bin; None when absent."""
    provider = PROVIDERS[key]
    found = shutil.which(provider.binary)
    if found:
        return found
    for rel in provider.extra_bins:
        candidate = Path.home() / rel
        if candidate.is_file():
            return str(candidate)
    return None


def later_lines() -> List[str]:
    """The three commands that do the ending later."""
    return [f"aipass provider {key}   # {PROVIDERS[key].title}" for key in ORDER]


def ask_provider(prompt: Callable[[str], str], say: Callable[[str], None]) -> Optional[str]:
    """The one question; the chosen key, or None on 'q', Ctrl-C or Ctrl-D (all mean skip). Enter asks again."""
    say("Which do you want to talk to devpulse with?")
    for number, key in enumerate(ORDER, 1):
        mark = "   (installed)" if cli_path(key) else ""
        say(f"  [{number}] {PROVIDERS[key].title}{mark}")
    say("  [q] skip: run 'aipass provider <name>' later")
    while True:
        try:
            answer = prompt("> ").strip().lower()
        except (KeyboardInterrupt, EOFError) as exc:
            logger.info("[provider_choice] question left with %s: skipped like q", type(exc).__name__)
            say("")
            return None
        if answer == "q":
            return None
        if answer in ("1", "2", "3"):
            return ORDER[int(answer) - 1]
        if answer in PROVIDERS:
            return answer


def install_cli(key: str, say: Callable[[str], None]) -> bool:
    """Run the vendor's installer with its output visible; True when the CLI is then found."""
    provider = PROVIDERS[key]
    if provider.installer[0] == "npm" and not shutil.which("npm"):
        say(f"{provider.title} installs with npm, and npm is not on PATH. Install Node.js and npm, then rerun.")
        return False
    say(f"Installing {provider.title} with its vendor's installer: {provider.installer[-1]}")
    result = subprocess.run(provider.installer, check=False)
    json_handler.log_operation("provider_install", {"provider": key, "exit": result.returncode})
    if result.returncode != 0 or not cli_path(key):
        logger.warning("[provider_choice] %s installer exit %s, cli found: %s", key, result.returncode, cli_path(key))
        return False
    return True


def wire_provider(key: str, home: Path) -> List[str]:
    """Wire the chosen provider only, through the doors doctor --fix uses; setup.sh wires none.

    Claude's wiring is its settings rows, the /memo command (an existing one kept) and the boot shim.
    """
    from aipass.aipass.apps.handlers import provider_wire

    manifest = home / ".claude" / "provider_manifest.json"
    if key == "codex":
        return provider_wire.refresh_codex(manifest)
    if key == "opencode":
        return provider_wire.install_opencode_plugin(manifest)
    actions = provider_wire.refresh_provider_hooks(manifest)
    memo_src = home / ".claude" / "templates" / "memo.md"
    memo_dst = Path.home() / ".claude" / "commands" / "memo.md"
    if memo_src.is_file() and not memo_dst.exists():
        memo_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(memo_src, memo_dst)
        actions.append(f"memo.md -> {memo_dst.parent}/ (installed)")
    shim = home / "src" / "aipass" / "hooks" / "tools" / "install_boot_shim.sh"
    shim_run = subprocess.run(["bash", str(shim)], check=False)
    actions.append("boot shim installed" if shim_run.returncode == 0 else f"boot shim exit {shim_run.returncode}")
    return actions


def open_argv(key: str, binary: str, greeting: str, home: Path) -> List[str]:
    """How devpulse opens: Claude through the boot shim's own entry, the others with the greeting.

    Claude runs what the claude() shim runs, never a shell rc: no prompt, as the shim's
    first-run rule starts the chat on the greeting. Forms read from each CLI's --help:
    `codex [PROMPT]`, `opencode --prompt <string>`.
    """
    if key == "codex":
        return [binary, greeting]
    if key == "opencode":
        return [binary, "--prompt", greeting]
    return [str(home / ".venv" / "bin" / "python3"), "-m", "aipass.hooks.apps.handlers.lifecycle.session_boot"]


def _record_provider(report_path: Path, key: str) -> None:
    """Add the chosen provider to the install report doctor reads; absent report = nothing to record."""
    if not report_path.is_file():
        logger.info("[provider_choice] no install report at %s; provider %s not recorded", report_path, key)
        return
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["provider"] = key
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def run_ending(
    key: Optional[str],
    home: Path,
    greeting: str,
    *,
    non_interactive: bool,
    dry_run: bool,
    prompt: Callable[[str], str],
    say: Callable[[str], None],
) -> int:
    """The install's last step: pick, install when missing, wire the pick only, open devpulse.

    0 when devpulse opened, was skipped, or a headless run named no provider; 1 when the
    vendor installer or the wiring failed, each with its retry line: AIPass itself is installed either way.
    """
    if key is None and non_interactive:
        say("No provider chosen (headless). Pick one later:")
        for line in later_lines():
            say(f"  {line}")
        return 0
    key = key or ask_provider(prompt, say)
    if key is None:
        say("Skipped. Pick one later: aipass provider claude|codex|opencode")
        return 0
    provider = PROVIDERS[key]
    if dry_run:
        say(f"[dry-run] would install {provider.title} if missing, wire it, and open devpulse in it")
        return 0
    if not cli_path(key) and not install_cli(key, say):
        say(f"{provider.title} did not install. AIPass itself is installed; install it from {provider.install_page}")
        say(f"then run: aipass provider {key}")
        return 1
    _record_provider(home / "src" / "aipass" / "devpulse" / "dropbox" / "install_report.json", key)
    try:
        actions = wire_provider(key, home)
    except (OSError, ValueError, SettingsBackupError) as exc:
        logger.error("[provider_choice] wiring %s failed: %s", key, exc)
        say(f"{provider.title} is installed but not wired: {exc}")
        say(f"Fix that, then run: aipass provider {key}")
        return 1
    for action in actions:
        say(f"  {action}")
    devpulse = home / "src" / "aipass" / "devpulse"
    found = cli_path(key)
    argv = open_argv(key, found or provider.binary, greeting, home)
    # A fresh installer's bin (~/.local/bin) is not on this process's PATH; the shim looks claude up there.
    path = os.pathsep.join(([str(Path(found).parent)] if found else []) + [os.environ.get("PATH", "")])
    subprocess.run(argv, cwd=devpulse, env={**os.environ, "AIPASS_HOME": str(home), "PATH": path}, check=False)
    return 0


# The Claude rows doctor's Services group builds from the manifest; codex/opencode rows carry their name.
CLAUDE_ROW_LABELS = frozenset({"hooks", "env vars", "permissions", "global settings", "wire verify"})


def row_provider(label: str) -> Optional[str]:
    """The provider a doctor row checks, or None for a row that is not one provider's."""
    for key in ("codex", "opencode"):
        if label.startswith(f"{key} "):
            return key
    return "claude" if label in CLAUDE_ROW_LABELS else None


def chosen_provider(home: Path) -> Optional[str]:
    """The provider the install report records for *home*; None when none is recorded or the report is unreadable."""
    report_path = home / "src" / "aipass" / "devpulse" / "dropbox" / "install_report.json"
    try:
        chosen = json.loads(report_path.read_text(encoding="utf-8")).get("provider")
    except (OSError, ValueError, AttributeError) as exc:
        logger.info("[provider_choice] no provider recorded at %s: %s", report_path, exc)
        return None
    return chosen if chosen in PROVIDERS else None
