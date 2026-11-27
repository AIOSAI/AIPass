# =================== AIPass ====================
# Name: wire_verify.py
# Description: doctor's wire verify row: one wired hook run for real, then drone @hooks verify
# Version: 1.0.0
# Created: 2026-11-26
# Modified: 2026-11-26
# =============================================

"""Doctor's wire verify row: wiring that inspects clean but cannot execute FAILs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NamedTuple

from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.ui.progress import GLYPH_FAIL, GLYPH_PASS, GLYPH_WARN


class WireCheckResult(NamedTuple):
    """Single doctor check result (mirrors doctor.CheckResult without importing it)."""

    label: str
    glyph: str
    detail: str
    remediation: str


def _hook_run_failure(settings_path: "Path | None" = None) -> str:
    """Run one wired hook command as Claude Code would; the shell's error when it cannot run, else "".

    Inspecting the wiring is not enough: a home path that splits in the shell passes every
    structural check while each hook dies with 'not found'. *settings_path* is a test seam.
    """
    settings_path = settings_path or Path.home() / ".claude" / "settings.json"
    settings = (json_handler.read_json(settings_path) if settings_path.exists() else None) or {}
    hooks = settings.get("hooks") or {}
    events = ["UserPromptSubmit", *[e for e in hooks if e != "UserPromptSubmit"]]
    commands = (h.get("command") for e in events for entry in hooks.get(e) or [] for h in entry.get("hooks") or [])
    command = next((c for c in commands if c), None)
    if not command:
        return ""
    env = {**os.environ, **{k: str(v) for k, v in (settings.get("env") or {}).items()}}
    proc = subprocess.run(["sh", "-c", command], input="{}", capture_output=True, text=True, timeout=20, env=env)
    if proc.returncode in (126, 127):
        lines = [ln for ln in proc.stderr.splitlines() if ln.strip()]
        return lines[-1] if lines else f"exit {proc.returncode}"
    return ""


def check_wire_verify() -> list[WireCheckResult]:
    """Run the hooks wire_verify guard, then one wired hook for real: wiring that cannot execute FAILs."""
    try:
        broken = _hook_run_failure()
        json_handler.log_operation("wire_verify", {"hook_runs": not broken, "error": broken})
        if broken:
            return [
                WireCheckResult(
                    "wire verify",
                    GLYPH_FAIL,
                    f"a wired hook cannot run: {broken}",
                    "AIPASS_HOME in the provider settings env splits in the shell (a space or shell "
                    "character); reinstall AIPass to a plain path",
                )
            ]
        proc = subprocess.run(
            ["drone", "@hooks", "verify"],
            capture_output=True,
            text=True,
            timeout=10,
            # hooks prints its report to stderr through Rich, which wraps a pipe at 80 columns.
            env={**os.environ, "COLUMNS": "1000"},
        )
        if proc.returncode == 0:
            return [WireCheckResult("wire verify", GLYPH_PASS, "provider hooks wired correctly", "")]
        lines = [ln.strip() for ln in f"{proc.stdout}\n{proc.stderr}".splitlines() if ln.strip()]
        found = [ln.removeprefix("ERROR").strip() for ln in lines if ln.startswith("ERROR")]
        detail = "; ".join(found) or (lines[-1] if lines else f"drone @hooks verify exited {proc.returncode}")
        return [
            WireCheckResult(
                "wire verify",
                GLYPH_FAIL,
                detail,
                "'aipass doctor --fix' re-wires only the provider manifest's rows; "
                "if this stays after it, the full report is 'drone @hooks verify' and the fix is @hooks'",
            )
        ]
    except FileNotFoundError as exc:
        logger.warning("[doctor] drone not found for wire_verify: %s", exc)
        return [WireCheckResult("wire verify", GLYPH_WARN, "drone not found", "")]
    except subprocess.TimeoutExpired as exc:
        logger.warning("[doctor] wire_verify timed out: %s", exc)
        return [WireCheckResult("wire verify", GLYPH_WARN, "timed out", "")]
