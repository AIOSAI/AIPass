# =================== AIPass ====================
# Name: report.py
# Description: Dispatch Completion Report
# Version: 1.0.0
# Created: 2026-08-22
# Modified: 2026-08-22
# =============================================

"""The completion report — what the finishing agent says about its own run.

v1.0.0 — FPLAN-0452 P1

Patrick's rules 3 and 4 (DPLAN-0317): the COMPLETING AGENT pushes the news
outward, and what it pushes is a REPORT, not a ping — which agent, when
dispatched, how long it took, whether it wrote its memories, what mail it sent
and to whom.

THE REPORT IS DURABLE; DELIVERY IS OPPORTUNISTIC (rule 6). This is the
load-bearing idea and it is why the report is a FILE THAT WAITS rather than a
message that must be caught. A manager whose session is grey misses nothing:
the report sits until someone reads it. Nothing here needs a retry, a queue, or
a crash-recovery path, because nothing here can be missed by being late.

Written BEFORE the dispatch lock is released. Under the old design the report
was a garnish and losing it was a nuisance; now the report IS the event, so
losing it means the dispatch never happened as far as the system is concerned
while the lock says it finished cleanly. Ordering the write first turns that
silent hole into a HELD LOCK — visible, and recoverable by the stale-lock path
that already exists.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root

REPORTS_DIRNAME = "dispatch_reports"

# The environment variable carrying a running agent's own dispatch id. Set on
# the spawn env by wake.py, inherited by the agent, and read at send time so
# every mail the agent writes is STAMPED with the dispatch it belongs to.
DISPATCH_ID_ENV = "AIPASS_DISPATCH_ID"

# Ceiling for the reports directory, mirroring the feed's trim policy: reports
# are durable, not eternal. Oldest are pruned on write.
REPORTS_MAX_FILES = 400
REPORTS_KEEP_FILES = 200

# How much of the agent's own result text to carry. Enough to read what it
# said, short enough that a report stays a report and not a transcript.
RESULT_EXCERPT_CHARS = 600


def reports_dir(repo_root: Optional[Path] = None) -> Path:
    """Where completion reports wait to be read.

    Same discipline as ``register.register_file``, including the fix: the
    transplant uses the root ``find_repo_root()`` just returned rather than
    re-deriving it by hunting for a marker file. On a fresh checkout no marker
    exists anywhere, and the old walk raised for every caller who passed a
    ``repo_root``.

    A caller who asks for ``repo_root`` can never be handed the live directory:
    the return is always rooted at what they passed.
    """
    root = find_repo_root()
    resolved = root / ".aipass" / REPORTS_DIRNAME
    if repo_root is None:
        return resolved

    return repo_root / resolved.relative_to(root)


def memories_edited(branch_path: Path, since: float) -> bool:
    """Whether any ``.trinity`` memory file was WRITTEN after *since*.

    THIS DETECTS A WRITE, NOT A GOOD ONE. An agent that rewrites local.json
    with byte-identical content still trips it, and one that writes its memory
    through a path this does not know about does not. It answers "did this run
    touch its memories at all", which is the honest limit of a timestamp
    comparison — do not let it grow into "did it update them well", because
    nothing here can see that.

    Args:
        branch_path: The dispatched branch's directory
        since: Unix timestamp the run started (``time.time()`` at spawn)

    Returns:
        True if at least one .trinity/*.json is newer than *since*
    """
    trinity = Path(branch_path) / ".trinity"

    try:
        candidates = list(trinity.glob("*.json"))
    except OSError as e:
        logger.warning("[report] could not list %s: %s", trinity, e)
        return False

    for memory_file in candidates:
        try:
            if memory_file.stat().st_mtime > since:
                return True
        except OSError as e:
            logger.warning("[report] could not stat %s: %s", memory_file, e)

    return False


def emails_sent(branch_path: Path, dispatch_id: Optional[str]) -> List[Dict[str, str]]:
    """Every mail this dispatch sent, read from the sender's own sent records.

    A RECORD, NOT AN INFERENCE. Each sent file carries the ``dispatch_id`` that
    was live when it was written, so attribution is by AUTHORSHIP. The earlier
    proposal — scanning ``sent/`` by mtime against the run window — attributes
    by TIME, which credits the agent with anything else that wrote the mailbox
    during its run. Patrick's ruling, on @ai_mail's reasoning: two sources
    answering one question is the shape that cost $1.41 on 2026-08-20.

    Returns an empty list when *dispatch_id* is None — an unregistered run
    cannot attribute its mail, and guessing is exactly what this avoids.

    Returns:
        [{"to": "@devpulse", "kind": "reply"}, ...], oldest first
    """
    if not dispatch_id:
        return []

    sent_folder = Path(branch_path) / ".ai_mail.local" / "sent"

    try:
        records = sorted(sent_folder.glob("*.json"))
    except OSError as e:
        logger.warning("[report] could not list %s: %s", sent_folder, e)
        return []

    found = []
    for record in records:
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("[report] unreadable sent record %s: %s", record, e)
            continue

        if data.get("dispatch_id") != dispatch_id:
            continue

        found.append(
            {
                "to": str(data.get("to", "")),
                "kind": "reply" if data.get("in_reply_to") else "send",
                "subject": str(data.get("subject", "")),
            }
        )

    return found


def build_report(
    dispatch_id: Optional[str],
    sender: str,
    target: str,
    branch_path: Path,
    start_time: float,
    duration: int,
    exit_code: int,
    status: str,
    attempts: List[Dict],
    bg_orphaned: bool,
    max_turns_hit: bool,
    wake_result: str,
    result_json: Optional[Dict] = None,
) -> Dict:
    """Assemble the completion report from what is already known at the terminal moment.

    Everything here is free or nearly so: the run's own local variables, one
    read of the result JSON the monitor already parses, three or four stats on
    ``.trinity``, and a scan of the sent records this dispatch stamped.

    ``bg_orphaned`` and ``max_turns_hit`` ship BESIDE ``emails_sent``, always,
    and this is not decoration. When ``bg_orphaned`` is true the agent exited 0
    while its background tasks were killed at the headless ceiling — its reply
    may never have been sent — so the report will honestly say ZERO EMAILS SENT
    for an agent that believed it had replied. Without those two flags beside
    it, a reader concludes the agent ignored its mail. Never a bare exit 0.
    """
    parsed = result_json or {}
    sent = emails_sent(branch_path, dispatch_id)

    return {
        "dispatch_id": dispatch_id,
        "sender": sender,
        "target": target,
        "dispatched_at": datetime.fromtimestamp(start_time).astimezone().isoformat(),
        "reported_at": datetime.now().astimezone().isoformat(),
        "duration_s": duration,
        "exit_code": exit_code,
        "status": status,
        "attempts": len(attempts),
        "bg_orphaned": bg_orphaned,
        "max_turns_hit": max_turns_hit,
        "wake_result": wake_result,
        "total_cost_usd": parsed.get("total_cost_usd"),
        "output_tokens": _output_tokens(parsed),
        "num_turns": parsed.get("num_turns"),
        "result_excerpt": str(parsed.get("result", ""))[:RESULT_EXCERPT_CHARS],
        "memories_edited": memories_edited(branch_path, start_time),
        "emails_sent": sent,
        "agents_contacted": sorted({mail["to"] for mail in sent if mail.get("to")}),
    }


def _output_tokens(parsed: Dict) -> Optional[int]:
    """Output tokens from the result JSON's usage block, or None when absent."""
    usage = parsed.get("usage")
    if isinstance(usage, dict):
        return usage.get("output_tokens")
    return None


def write_report(report: Dict, repo_root: Optional[Path] = None) -> Optional[str]:
    """Write the report where it can wait, and prune the directory's tail.

    Returns:
        The report's path as a string, or None if it could not be written.
        The caller must treat None as a LOST DISPATCH RECORD and say so at
        warning level — this is the one file the whole design rests on.
    """
    dispatch_id = report.get("dispatch_id") or "unregistered"
    json_handler.log_operation("write_dispatch_report", {"dispatch_id": dispatch_id})

    directory = reports_dir(repo_root)
    path = directory / f"{dispatch_id}.json"

    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.error("[report] could not write %s: %s", path, e)
        return None

    _prune_reports(directory)
    return str(path)


def _prune_reports(directory: Path) -> int:
    """Drop the oldest reports once the directory passes its ceiling.

    Reports are durable, not eternal — the same reasoning as the feed's trim.
    A report old enough to be pruned has either been read or has outlived
    anyone who would.

    Returns:
        How many reports were removed
    """
    try:
        reports = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime)
    except OSError as e:
        logger.warning("[report] could not list %s for prune: %s", directory, e)
        return 0

    if len(reports) <= REPORTS_MAX_FILES:
        return 0

    removed = 0
    for stale in reports[: len(reports) - REPORTS_KEEP_FILES]:
        try:
            stale.unlink()
            removed += 1
        except OSError as e:
            logger.warning("[report] could not prune %s: %s", stale, e)

    if removed:
        logger.info("[report] pruned %d old reports from %s", removed, directory)

    return removed


def fire_completed(dispatch_id: Optional[str], sender: str, target: str, report_path: Optional[str]) -> bool:
    """Push the completion to in-process consumers via @trigger's existing bus.

    trigger.fire() IS IN-PROCESS ONLY. @trigger cannot cross process boundaries
    (DPLAN-0314), so this reaches consumers living inside THIS monitor process
    and nothing else. Anyone who expects it to reach @devpulse's watchdog will
    build something that silently never fires and never errors.

    THE FEED FILE IS WHAT CARRIES THIS EVENT ACROSS THE PROCESS BOUNDARY. The
    monitor's feed line — carrying dispatch_id, sender and report_path — is the
    delivery mechanism for anything outside this process. This call is the
    in-process half, and the two are not interchangeable.

    Returns:
        True if the event was fired
    """
    try:
        from aipass.trigger.apps.modules.core import trigger

        trigger.fire(
            "dispatch_completed",
            dispatch_id=dispatch_id,
            sender=sender,
            target=target,
            report_path=report_path,
        )
        return True
    except Exception as e:
        logger.warning("[report] dispatch_completed trigger fire failed: %s", e)
        return False


def current_dispatch_id() -> Optional[str]:
    """This process's own dispatch id, or None when not running under one.

    None is a DEFINED EMPTY STATE, not a failure: an interactive agent, a test,
    or a human at a terminal genuinely has no dispatch id, and mail they send
    is correctly stamped with nothing.
    """
    value = os.environ.get(DISPATCH_ID_ENV, "").strip()
    return value or None


def stamp_dispatch_id(email_data: Dict) -> Dict:
    """Stamp a sent record with the dispatch that authored it, if there is one.

    The one place this stamping happens. Sends and replies write their sent
    records through two different functions, and two hand-rolled copies of this
    is how one of them silently stops carrying the id — leaving a completion
    report that under-counts an agent's mail with nothing to show it did.

    An unstamped record is CORRECT for mail sent outside a dispatch. It simply
    belongs to no dispatch, and ``emails_sent`` will not claim it for one.
    """
    dispatch_id = current_dispatch_id()
    if dispatch_id:
        email_data["dispatch_id"] = dispatch_id
    return email_data
