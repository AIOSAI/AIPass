# =================== AIPass ====================
# Name: run_record.py
# Description: Machine pre-flight Run Record generator for the cross-OS checklist
# Version: 1.0.0
# Created: 2026-07-02
# Modified: 2026-10-17
# =============================================

"""Cross-OS Run Record generator — Layer-3-lite machine pre-flight DRAFT.

Format source: the "## Run Record" block in tests/CROSS_OS_TESTING.md. Built in code, not
substituted into the template, so the machine fills only what it proves and never ticks a human row.
Env facts use stdlib directly: the cross-handler rule forbids importing system_detector.
"""

from __future__ import annotations

import os
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import List

from aipass.prax import logger
from aipass.aipass.shared.registry_discovery import find_registry

from aipass.aipass.apps.handlers.cross_os.gap_registry import CrossOsGapError, gaps_for_platform
from aipass.aipass.apps.handlers.cross_os.preflight import (
    E2E_UNRUNNABLE_PREFIX,
    check_hookstatus,
    check_routing,
    run_e2e,
)
from aipass.aipass.apps.handlers.json import json_handler

# The doc's Run Record block uses these emoji, not the terminal ✓ / ✗ glyphs.
_PASS = "✅"
_FAIL = "❌"
_HUMAN = "⬜ — human"

_RULE = "─────────────────────────────────────────────"


class RunRecordError(RuntimeError):
    """Raised when the Run Record file cannot be written."""


def _os_name() -> str:
    """OS family name (e.g. 'Linux', 'Darwin', 'Windows')."""
    return platform.system() or "unknown"


def _resolve_aipass_home() -> str:
    """Resolve AIPASS_HOME from the env, else the discovered registry parent; "" over an invented path."""
    home = os.environ.get("AIPASS_HOME", "").strip()
    if home:
        return home
    registry = find_registry(package_root=str(Path(__file__).resolve().parent))
    if registry is not None and registry.exists():
        return str(registry.parent)
    return ""


def _env_lines() -> List[str]:
    """Build the machine-auto-filled environment header lines (Phase 0 facts)."""
    os_desc = f"{_os_name()} {platform.release()}".strip()
    shell_path = os.environ.get("SHELL", "")
    shell_name = Path(shell_path).name if shell_path else "unknown"
    term = os.environ.get("TERM", "").strip() or "unknown"
    today = datetime.now().strftime("%Y-%m-%d")

    return [
        "AIPass Cross-OS Run Record",
        f"Machine/VM   : {platform.node() or 'unknown'}",
        f"OS + version : {os_desc}",
        f"Arch         : {platform.machine() or 'unknown'}",
        f"Python       : {platform.python_version()}",
        f"Shell / term : {shell_name} / {term}",
        f"AIPASS_HOME  : {_resolve_aipass_home()}",
        "Commit (drone @git log -1) :            ← fill via drone @git log -1",
        f"Tester       :            Date : {today}",
    ]


def _verdict(ok: bool) -> str:
    """Map a pre-flight boolean to the machine glyph + a pre-flight label."""
    glyph = _PASS if ok else _FAIL
    return f"{glyph} pre-flight (machine)"


def _phase2_line(run_heavy_e2e: bool) -> str:
    """Phase 2 (e2e) line — only auto-filled when the heavy suite was opted into."""
    label = "Phase 2 e2e suite (14/14) ...."
    if not run_heavy_e2e:
        return f"{label} {_HUMAN}   notes: — not run (pass --e2e to run it)"
    result = run_e2e()
    if result.ok:
        return f"{label} {_verdict(True)}   notes: {result.detail}"
    if result.detail.startswith(E2E_UNRUNNABLE_PREFIX):
        return f"{label} ⚠️ could not run (machine)   notes: {result.detail}"
    return f"{label} {_verdict(False)}   notes: {result.detail}"


def _phase_lines(run_heavy_e2e: bool) -> List[str]:
    """Build the Phase 0–7 + per-branch lines, machine-proving only what it can."""
    routing = check_routing()
    hooks = check_hookstatus()

    return [
        f"Phase 0 env capture .......... {_verdict(True)}   notes: captured above",
        f"Phase 1 clean install ........ {_HUMAN}   notes:",
        _phase2_line(run_heavy_e2e),
        f"Phase 3 aipass init .......... {_HUMAN}   notes:",
        # Machine rows are only the non-mutating ones; daemons (Phase 5) mutate, so stay human.
        f"Phase 4 drone routing ........ {_verdict(routing.ok)}   notes: {routing.detail}",
        f"Phase 5 daemons .............. {_HUMAN}   notes:",
        f"Phase 6 hooks + sound ........ {_verdict(hooks.ok)} hookstatus; 🔊 sound {_HUMAN}   notes: {hooks.detail}",
        f"Phase 7 interactive .......... {_HUMAN}   notes:",
        f"Per-branch matrix (13) ....... {_HUMAN}   reds:",
    ]


def _watch_lines(platform_name: str) -> List[str]:
    """Build the tracked-gap watch-item lines for this platform; a registry error is one note line."""
    lines = ["Watch items (tracked cross-OS gaps for this platform):"]
    try:
        gaps = gaps_for_platform(platform_name)
    except CrossOsGapError as exc:
        logger.warning("[cross_os.run_record] gap registry unavailable: %s", exc)
        lines.append(f"  - registry unavailable — {exc}")
        return lines

    if not gaps:
        lines.append(f"  - none tracked for {platform_name}")
        return lines

    for gap in gaps:
        lines.append(f"  - gap #{gap.number} [{gap.status}] {gap.symptom} — owner {gap.owner}")
    return lines


def build_run_record(run_heavy_e2e: bool = False, platform_name: str | None = None) -> str:
    """Build the full machine pre-flight Run Record text block."""
    plat = platform_name or sys.platform

    header = [
        "NOTE: machine pre-flight DRAFT — rows marked '(machine)' are auto-captured pre-flight",
        "only; they are NOT the checklist's human green. A human must complete every '— human'",
        "row and run the real Layer-3 acceptance pass before this record counts.",
        "",
    ]

    body: List[str] = []
    body.append(_RULE)
    body.extend(_env_lines())
    body.append(_RULE)
    body.extend(_phase_lines(run_heavy_e2e))
    body.append(_RULE)
    body.extend(_watch_lines(plat))
    body.append("")
    body.append("New gaps found (file + assign):")
    body.append("")
    body.append(f"Overall verdict: {_HUMAN} (PASS / PARTIAL / FAIL — after the real pass)")
    body.append(_RULE)

    return "\n".join([*header, *body]) + "\n"


def default_record_path() -> Path:
    """Return the default record path in CWD (mirrors the doc's log naming)."""
    return Path.cwd() / f"aipass-crossos-record-{_os_name().lower()}.txt"


def generate_run_record(path: str | None = None, run_heavy_e2e: bool = False) -> Path:
    """Build and write the Run Record; return the written path. OSError becomes RunRecordError."""
    content = build_run_record(run_heavy_e2e=run_heavy_e2e)
    target = Path(path) if path else default_record_path()
    try:
        parent = target.parent
        if parent and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        logger.error("[cross_os.run_record] could not write record to %s: %s", target, exc)
        raise RunRecordError(f"could not write Run Record to {target}: {exc}") from exc

    json_handler.log_operation(
        "cross_os_run_record",
        {"path": str(target), "e2e": run_heavy_e2e},
    )
    logger.info("[cross_os.run_record] wrote machine pre-flight record to %s", target)
    return target
