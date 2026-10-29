# =================== AIPass ====================
# Name: _doctor_smoke.py
# Description: aipass doctor --smoke — one live turn per provider through hooks' smoke door
# Version: 1.0.0
# Created: 2026-10-28
# Modified: 2026-10-28
# =============================================

"""doctor_smoke — the opt-in live rows, read from ``drone @hooks smoke --json``."""

from __future__ import annotations

import json
import subprocess
from typing import List, Tuple

from aipass.cli.apps.modules import console
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.ui.progress import GLYPH_FAIL, GLYPH_PASS

# hooks gives each provider up to 180 s, and runs the three in turn
SMOKE_TIMEOUT = 600


class SmokeUnavailable(Exception):
    """hooks' smoke did not run or gave no result array."""


def smoke_results(model: str = "") -> List[dict]:
    """hooks' smoke objects as hooks gives them: one live model turn per provider, in the cwd's branch."""
    argv = ["drone", "@hooks", "smoke", "--json"] + (["--model", model] if model else [])
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=SMOKE_TIMEOUT)
    except FileNotFoundError as exc:
        raise SmokeUnavailable("drone not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise SmokeUnavailable(f"timed out after {SMOKE_TIMEOUT} s") from exc
    # hooks exits 1 on any fail and still prints the array
    try:
        results = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("[doctor] hooks smoke returned non-JSON: %s", proc.stdout[:200])
        raise SmokeUnavailable(f"no result array (exit {proc.returncode})") from exc
    if not isinstance(results, list):
        raise SmokeUnavailable(f"no result array (exit {proc.returncode})")
    json_handler.log_operation("doctor_smoke", {"count": len(results), "rc": proc.returncode})
    return results


def check_smoke(model: str = "") -> List[Tuple[str, str, str, str]]:
    """One row per provider: pass and skip are ✓ with the reason, fail is ✗ with hooks' why."""
    try:
        results = smoke_results(model)
    except SmokeUnavailable as exc:
        return [("smoke", GLYPH_FAIL, str(exc), "Run: drone @hooks smoke")]
    rows: List[Tuple[str, str, str, str]] = []
    for result in results:
        provider, status, why = result.get("provider", "?"), result.get("status"), result.get("why", "")
        label = f"smoke {provider}"
        if status == "pass":
            rows.append((label, GLYPH_PASS, f"pass ({result.get('elapsed_ms', 0) / 1000:.1f} s)", ""))
        elif status == "skip":
            rows.append((label, GLYPH_PASS, f"skip ({why})", ""))
        else:
            rows.append((label, GLYPH_FAIL, f"{status}: {why}", f"Run: drone @hooks smoke --provider {provider}"))
    return rows


def print_smoke_json(model: str = "") -> int:
    """--smoke --json: hooks' array on stdout as given. Returns 1 when it did not run or any provider failed."""
    try:
        results = smoke_results(model)
    except SmokeUnavailable as exc:
        logger.warning("[doctor] smoke unavailable: %s", exc)
        console.print(json.dumps({"error": str(exc)}), markup=False, highlight=False)
        return 1
    console.print(json.dumps(results, indent=2), markup=False, highlight=False)
    return int(any(r.get("status") == "fail" for r in results))


def print_introspection() -> None:
    """Display module info for doctor_smoke."""
    console.print()
    console.print("[bold cyan]doctor_smoke Module[/bold cyan]")
    console.print("Live provider rows — doctor --smoke / --smoke --json")
    console.print()


def handle_command(command: str, args: list[str]) -> bool:
    """Handle command routing. Helper module — no standalone commands."""
    if command != "doctor_smoke":
        return False
    if args and args[0] in ("--info", "info"):
        print_introspection()
        return True
    if not args or wants_help(args):
        console.print("[dim]Helper module — use: aipass doctor --smoke [--json][/dim]")
        return True
    return False
