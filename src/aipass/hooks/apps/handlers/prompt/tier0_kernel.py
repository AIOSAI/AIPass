# =================== AIPass ====================
# Name: tier0_kernel.py
# Version: 1.0.0
# Description: Tier 0 kernel — always-on minimal prompt injection (UserPromptSubmit)
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-06-18
# Modified: 2026-06-18
# =============================================

"""Loads .aipass/tier0_kernel.md — tiny always-on identity + reflex block."""

import os
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger


def _find_project_file(filename: str) -> Path | None:
    """Walk up from CWD to find the nearest .aipass/<filename>."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".aipass" / filename
        if candidate.is_file():
            return candidate
        if parent == parent.parent:
            break
    return None


def handle(hook_data: dict) -> dict:
    """Load tier0 kernel — cadence-gated (period from cadence_config.json, default 5)."""
    try:
        import importlib

        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        if not cadence.should_fire("tier0", hook_data):
            return {"stdout": "", "exit_code": 0}
    except Exception as exc:
        logger.info("[HOOKS] tier0_kernel: cadence check failed, firing anyway: %s", exc)

    try:
        aipass_home = os.environ.get("AIPASS_HOME", "")
        cwd = str(Path.cwd())

        if aipass_home and cwd.startswith(aipass_home):
            prompt_file = Path(aipass_home) / ".aipass" / "tier0_kernel.md"
        else:
            prompt_file = _find_project_file("tier0_kernel.md")

        if not prompt_file or not prompt_file.exists():
            return {"stdout": "", "exit_code": 0}

        content = prompt_file.read_text(encoding="utf-8")
        return {"stdout": content, "exit_code": 0, "sound": "tier0 kernel"}

    except Exception as exc:
        logger.info("[HOOKS] tier0_kernel: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
