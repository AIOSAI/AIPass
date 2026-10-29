# =================== AIPass ====================
# Name: opencode_cli.py
# Description: Doctor's read-only OpenCode rows — binary, login, model
# Version: 1.1.0
# Created: 2026-10-28
# Modified: 2026-10-28
# =============================================

"""opencode_cli — OpenCode's binary, login and model, read and never written.

Never runs ``opencode run``: it spends free quota and spawns a server. The plugin row is the
wire's (provider_wire.opencode_plugin_state); these rows are the CLI's own state.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, NamedTuple, Optional

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.ui.progress import GLYPH_PASS, GLYPH_WARN

OPENCODE_BINARY_LABEL = "opencode binary"
OPENCODE_LOGIN_LABEL = "opencode login"
OPENCODE_MODEL_LABEL = "opencode model"
NOT_INSTALLED = "not on PATH or in ~/.opencode/bin — OpenCode is optional, rows skipped"
NO_LOGIN = "none (free models only)"
NO_MODEL = "none set — OpenCode's default"
# Seams: the suite's conftest makes opencode absent, so no test runs the real binary.
_which = shutil.which
_run = subprocess.run


class OpenCodeRow(NamedTuple):
    """One doctor check row (the fields of doctor.CheckResult, without importing a module)."""

    label: str
    glyph: str
    detail: str
    remediation: str


def cli_proc(args: List[str], run=None) -> Optional[subprocess.CompletedProcess]:
    """Run one read-only CLI verb; None when it could not run at all. *run* is the caller's seam."""
    try:
        return (run or _run)(args, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[opencode_cli] %s failed: %s", " ".join(args), exc)
        return None


def first_line(proc: Optional[subprocess.CompletedProcess]) -> str:
    """The first line the verb printed, stdout before stderr."""
    text = "" if proc is None else (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0] if text else "no output"


def _read_model(config_dir: Path) -> tuple[str, str]:
    """(the `model` in opencode.json or .jsonc, with its file, '') or ('', why unreadable); ('', '') when unset."""
    for name in ("opencode.json", "opencode.jsonc"):
        path = config_dir / name
        if not path.is_file():
            continue
        try:
            # shortcut: .jsonc full-line // comments only; a trailing comma reads as unreadable.
            config = json.loads(re.sub(r"^\s*//.*$", "", path.read_text(encoding="utf-8"), flags=re.M))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[opencode_cli] opencode config unreadable: %s: %s", path, exc)
            return "", f"{path} unreadable: {exc}"
        model = config.get("model") if isinstance(config, dict) else None
        if model:
            return f"{model} (from {path})", ""
    return "", ""


def _auth_names(proc: Optional[subprocess.CompletedProcess]) -> Optional[List[str]]:
    """The providers `opencode auth list --format json` prints; None when it failed or is not a JSON list."""
    if proc is None or proc.returncode != 0:
        return None
    try:
        listed = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("[opencode_cli] opencode auth list unreadable: %s", exc)
        listed = None
    if not isinstance(listed, list):
        return None
    # shortcut: the signed-in entry shape is unmeasured (signed out prints []); a dict goes by its first id-like key.
    return [str(e.get("provider") or e.get("id") or e) if isinstance(e, dict) else str(e) for e in listed]


def opencode_binary() -> Optional[str]:
    """The opencode executable, or None when OpenCode is not installed."""
    # The curl installer puts opencode in ~/.opencode/bin, on PATH only through ~/.bashrc.
    search = os.pathsep.join([os.environ.get("PATH", ""), str(Path.home() / ".opencode" / "bin")])
    return _which("opencode", path=search)


def check_opencode_cli(config_dir: Path) -> List[OpenCodeRow]:
    """OpenCode's binary, login and model; absent, one PASS row and nothing runs."""
    opencode = opencode_binary()
    if not opencode:
        return [OpenCodeRow(OPENCODE_BINARY_LABEL, GLYPH_PASS, NOT_INSTALLED, "")]
    version = cli_proc([opencode, "--version"])
    if version is None or version.returncode != 0:
        rows = [OpenCodeRow(OPENCODE_BINARY_LABEL, GLYPH_WARN, f"{opencode}: --version failed", "Reinstall OpenCode")]
    else:
        rows = [OpenCodeRow(OPENCODE_BINARY_LABEL, GLYPH_PASS, f"{first_line(version)} ({opencode})", "")]
    auth = cli_proc([opencode, "auth", "list", "--format", "json"])
    names = _auth_names(auth)
    if names is None:
        rows.append(OpenCodeRow(OPENCODE_LOGIN_LABEL, GLYPH_WARN, first_line(auth), "Run: opencode auth list"))
    else:
        rows.append(OpenCodeRow(OPENCODE_LOGIN_LABEL, GLYPH_PASS, ", ".join(names) or NO_LOGIN, ""))
    model, problem = _read_model(config_dir)
    glyph = GLYPH_WARN if problem else GLYPH_PASS
    rows.append(OpenCodeRow(OPENCODE_MODEL_LABEL, glyph, problem or model or NO_MODEL, ""))
    json_handler.log_operation("opencode_cli_rows", {"rows": len(rows)})
    return rows
