# =================== AIPass ====================
# Name: run_record.py
# Description: Machine pre-flight Run Record generator for the cross-OS checklist
# Version: 1.0.0
# Created: 2026-07-02
# Modified: 2026-07-02
# =============================================

"""Cross-OS Run Record generator — Layer-3-lite machine pre-flight DRAFT.

Emits a text Run Record block modelled on the "## Run Record" fenced template in
``tests/CROSS_OS_TESTING.md`` (that block is the format source-of-truth). The
block is *constructed in code* rather than string-substituted into the parsed
template on purpose: the load-bearing invariant here is the machine/human
boundary — the machine fills ONLY what it can prove (env facts + the
non-mutating pre-flight rows) and every human-only row (clean install,
interactive init, daemons, audible sound, PTY, per-branch matrix, overall
verdict, commit, tester) is left blank or marked ``— human``. Constructing the
block gives exact control over that boundary; substituting values line-by-line
into the free-text template would be brittle and could silently tick a human row.

Env facts are detected with stdlib (``platform`` / ``os``) directly — the same
detection ``system_detector`` performs — because the seedgo cross-handler rule
forbids this handler importing another handler.

A machine can NEVER claim the checklist's human green ("you watched it work on
that OS"). This artifact is explicitly a pre-flight DRAFT that a person must
complete by running the real Layer-3 acceptance pass.
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

# Marker glyphs for the record. Match the doc's Run Record block, which uses the
# ✅ / ❌ emoji rather than the terminal ✓ / ✗ glyphs.
_PASS = "✅"
_FAIL = "❌"
# Un-ticked human box — a person must still run and mark the real pass.
_HUMAN = "⬜ — human"

# Horizontal rule used by the doc's Run Record block.
_RULE = "─────────────────────────────────────────────"


class RunRecordError(RuntimeError):
    """Raised when the Run Record file cannot be written."""


def _os_name() -> str:
    """OS family name (e.g. 'Linux', 'Darwin', 'Windows')."""
    return platform.system() or "unknown"


def _resolve_aipass_home() -> str:
    """Resolve AIPASS_HOME from the env, else the discovered registry parent.

    Returns "" (blank) if neither is available — a blank row is honest; we never
    invent a path.
    """
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
        # Commit stays blank — no git here; a human fills it (hint inline).
        "Commit (drone @git log -1) :            ← fill via drone @git log -1",
        # Tester stays blank (human); Date is machine-knowable.
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
        # Infra could not run the suite — WARN-ish, not a proven fail.
        return f"{label} ⚠️ could not run (machine)   notes: {result.detail}"
    return f"{label} {_verdict(False)}   notes: {result.detail}"


def _phase_lines(run_heavy_e2e: bool) -> List[str]:
    """Build the Phase 0–7 + per-branch lines, machine-proving only what it can."""
    routing = check_routing()
    hooks = check_hookstatus()

    return [
        # Phase 0 — the machine captured the env above, so this is proven.
        f"Phase 0 env capture .......... {_verdict(True)}   notes: captured above",
        # Phase 1 — clean install (setup.sh / .venv) is pre-init + human.
        f"Phase 1 clean install ........ {_HUMAN}   notes:",
        _phase2_line(run_heavy_e2e),
        # Phase 3 — real scaffold + interactive init is human (PTY).
        f"Phase 3 aipass init .......... {_HUMAN}   notes:",
        # Phase 4 — drone routing is non-mutating and machine-provable.
        f"Phase 4 drone routing ........ {_verdict(routing.ok)}   notes: {routing.detail}",
        # Phase 5 — daemons (os.kill / start_new_session) are mutating + human.
        f"Phase 5 daemons .............. {_HUMAN}   notes:",
        # Phase 6 — hookstatus config renders (machine); audible sound is human.
        f"Phase 6 hooks + sound ........ {_verdict(hooks.ok)} hookstatus; 🔊 sound {_HUMAN}   notes: {hooks.detail}",
        # Phase 7 — interactive PTY layer is human-only.
        f"Phase 7 interactive .......... {_HUMAN}   notes:",
        # Per-branch smoke matrix is a human pass.
        f"Per-branch matrix (13) ....... {_HUMAN}   reds:",
    ]


def _watch_lines(platform_name: str) -> List[str]:
    """Build the tracked-gap watch-item lines for this platform.

    Reads the live gap registry; on any registry error, degrades to a single
    note line (never crashes the record — it is primarily an env artifact).
    """
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
    """Build the full machine pre-flight Run Record text block.

    Auto-fills the env header + the machine-provable phase rows (0/4/6, plus 2
    when ``run_heavy_e2e``); leaves every human-only row blank/marked. The output
    mirrors the "## Run Record" template in tests/CROSS_OS_TESTING.md.
    """
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
    """Build and write the Run Record; return the written path.

    Args:
        path: Destination file (``--record`` value). If None, a sensible default
            in CWD is used.
        run_heavy_e2e: When True, run and record the heavy Phase-2 e2e result.

    Raises:
        RunRecordError: if the file cannot be written (OSError) — never crashes.
    """
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
