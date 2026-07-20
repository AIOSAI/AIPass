# =================== AIPass ====================
# Name: pre_compact_prep.py
# Version: 1.0.0
# Description: Stamps a mechanical AUTO-COMPACT SNAPSHOT into the compacting branch's memory (PreCompact)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-07-20
# Modified: 2026-07-20
# =============================================

"""Mechanical /prep AT compact time (DPLAN-0253).

Resolves the compacting branch from cwd, then prepends a session entry to its
.trinity/local.json — context fill, in-flight dispatch locks across the
system, this branch's open plan count, git state, and inbox unread count.
Templated from live state, no model turn needed. The judgment layer (todo
reconcile, thoughtful summary) is handled separately by the context gauge
nudge, which fires early enough for a live model turn to run /prep.

Defensive: a missing or malformed .trinity/local.json is logged and skipped —
this handler must never corrupt memory or raise out of PreCompact."""

import importlib
import json
import subprocess
from datetime import date
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

_DEFAULT_SUMMARY_CAP = 300


def _find_repo_root(start: Path) -> Path | None:
    for parent in [start, *start.parents]:
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return None


def _context_fill_pct(hook_data: dict, cwd: str) -> str | None:
    context_window = importlib.import_module("aipass.hooks.apps.modules.context_window")
    usage = context_window.read_latest_usage(hook_data.get("transcript_path", ""))
    if usage is None:
        return None
    fill = context_window.context_fill_tokens(usage)
    window = context_window.resolve_compact_window(cwd)
    if window <= 0:
        return None
    pct = round(fill / window * 100)
    return f"~{fill // 1000}k/{window // 1000}k ({pct}%)"


def _count_active_dispatch_locks(repo_root: Path | None) -> int | None:
    if repo_root is None:
        return None
    registry_path = repo_root / "AIPASS_REGISTRY.json"
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[HOOKS] pre_compact_prep: registry read failed: %s", exc)
        return None

    count = 0
    for branch in data.get("branches", []):
        branch_path = repo_root / branch.get("path", "")
        lock_path = branch_path / ".ai_mail.local" / ".dispatch.lock"
        if lock_path.is_file():
            count += 1
    return count


def _count_open_plans(branch_dir: Path) -> int | None:
    try:
        from aipass.flow.apps.handlers.plan.get_open_plans import get_open_plans

        target = str(branch_dir.resolve())
        return sum(1 for _num, info in get_open_plans() if info.get("location") == target)
    except Exception as exc:
        logger.info("[HOOKS] pre_compact_prep: open plans read failed: %s", exc)
        return None


def _git_snapshot(branch_dir: Path) -> str | None:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(branch_dir),
        )
        last_commit = subprocess.run(
            ["git", "log", "-1", "--format=%h %s"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(branch_dir),
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(branch_dir),
        )
    except Exception as exc:
        logger.info("[HOOKS] pre_compact_prep: git snapshot failed: %s", exc)
        return None

    bits: list[str] = []
    if branch.returncode == 0 and branch.stdout.strip():
        bits.append(branch.stdout.strip())
    if last_commit.returncode == 0 and last_commit.stdout.strip():
        bits.append(last_commit.stdout.strip())
    if dirty.returncode == 0:
        dirty_lines = [ln for ln in dirty.stdout.strip().split("\n") if ln]
        bits.append(f"{len(dirty_lines)} dirty")
    return " / ".join(bits) if bits else None


def _inbox_unread(branch_dir: Path) -> int | None:
    inbox_path = branch_dir / ".ai_mail.local" / "inbox.json"
    if not inbox_path.is_file():
        return None
    try:
        data = json.loads(inbox_path.read_text(encoding="utf-8"))
        unread = data.get("unread_count")
        return unread if isinstance(unread, int) else None
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[HOOKS] pre_compact_prep: inbox read failed: %s", exc)
        return None


def _summary_cap(repo_root: Path | None) -> int:
    if repo_root is None:
        return _DEFAULT_SUMMARY_CAP
    config_path = repo_root / "src" / "aipass" / "memory" / "memory_json" / "custom_config" / "memory.config.json"
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        cap = data["entry_limits"]["entry_types"]["sessions"]["max_chars"]
        if isinstance(cap, int) and cap > 0:
            return cap
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.info("[HOOKS] pre_compact_prep: entry_limits read failed, using default: %s", exc)
    return _DEFAULT_SUMMARY_CAP


def _build_snapshot(hook_data: dict, branch_dir: Path, repo_root: Path | None) -> str:
    cwd = hook_data.get("cwd", "") or str(branch_dir)
    parts: list[str] = []

    fill = _context_fill_pct(hook_data, cwd)
    if fill:
        parts.append(f"context {fill}")

    locks = _count_active_dispatch_locks(repo_root)
    if locks is not None:
        parts.append(f"{locks} active dispatch(es)")

    open_plans = _count_open_plans(branch_dir)
    if open_plans is not None:
        parts.append(f"{open_plans} open plan(s)")

    git_info = _git_snapshot(branch_dir)
    if git_info:
        parts.append(f"git: {git_info}")

    unread = _inbox_unread(branch_dir)
    if unread is not None:
        parts.append(f"{unread} unread")

    body = ", ".join(parts) if parts else "no live state available"
    return f"AUTO-COMPACT SNAPSHOT: {body}"


def _stamp_session_entry(branch_dir: Path, summary: str, cap: int) -> bool:
    local_path = branch_dir / ".trinity" / "local.json"
    if not local_path.is_file():
        logger.info("[HOOKS] pre_compact_prep: no local.json at %s — skipping stamp", local_path)
        return False

    try:
        data = json.loads(local_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[HOOKS] pre_compact_prep: local.json unreadable, skipping stamp: %s", exc)
        return False

    if not isinstance(data, dict):
        logger.warning("[HOOKS] pre_compact_prep: local.json malformed (not a dict), skipping stamp")
        return False

    sessions = data.get("sessions")
    if not isinstance(sessions, list):
        logger.warning("[HOOKS] pre_compact_prep: sessions container malformed, skipping stamp")
        return False

    truncated = summary if len(summary) <= cap else summary[: cap - 1].rstrip() + "…"

    existing_numbers = [
        entry.get("number", 0) for entry in sessions if isinstance(entry, dict) and isinstance(entry.get("number"), int)
    ]
    next_number = max(existing_numbers, default=0) + 1

    sessions.insert(
        0,
        {
            "date": date.today().isoformat(),
            "summary": truncated,
            "status": "auto-compact",
            "number": next_number,
        },
    )
    data["sessions"] = sessions

    try:
        local_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("[HOOKS] pre_compact_prep: local.json write failed: %s", exc)
        return False

    return True


def handle(hook_data: dict) -> dict:
    """Stamp a mechanical AUTO-COMPACT SNAPSHOT into the compacting branch's memory."""
    try:
        cwd = hook_data.get("cwd", "") or str(Path.cwd())
        context_window = importlib.import_module("aipass.hooks.apps.modules.context_window")
        branch_dir = context_window.find_branch_dir(cwd)
        if branch_dir is None:
            logger.info("[HOOKS] pre_compact_prep: no branch dir resolved from cwd=%s", cwd)
            return {"stdout": "", "exit_code": 0}

        repo_root = _find_repo_root(branch_dir)
        cap = _summary_cap(repo_root)
        snapshot = _build_snapshot(hook_data, branch_dir, repo_root)

        stamped = _stamp_session_entry(branch_dir, snapshot, cap)
        logger.info("[HOOKS] pre_compact_prep: snapshot stamped=%s branch=%s", stamped, branch_dir.name)

        return {"stdout": snapshot, "exit_code": 0}

    except Exception as exc:
        logger.info("[HOOKS] pre_compact_prep: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
