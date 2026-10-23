# =================== AIPass ====================
# Name: triage.py
# Description: CI red lane triage - run list parsing, newest per workflow, infra steps, owner mapping
# Version: 1.0.0
# Created: 2026-10-22
# Modified: 2026-10-22
# =============================================

"""
CI Triage Handler - turns `drone @git run list` and `run view --log-failed` text into lane facts
"""

import re
from typing import Any, Dict, List

from aipass.trigger.apps.handlers.json import json_handler

RUN_LIST_FIELDS = ("status", "conclusion", "title", "workflow", "branch", "event", "run_id", "elapsed", "created")

# A run that ended this way never reached anyone's code, so it has no owner to wake.
INFRA_CONCLUSIONS = {"cancelled", "timed_out", "startup_failure", "stale", "skipped", "action_required", "neutral"}
INFRA_STEP = re.compile(r"^(Set up |Initialize |Checkout|Post |Complete job|Run actions/)", re.IGNORECASE)

_LOG_STAMP = re.compile(r"^﻿?\d{4}-\d\d-\d\dT[\d:.]+Z ?")
_AUDIT_OWNER = re.compile(r"^\s*([a-z][a-z0-9_-]*): (\d{1,2})%(\s|$)")
_TEST_OWNER = re.compile(r"src/aipass/([a-z][a-z0-9_-]*)/")
_FAILING = re.compile(r"FAILED|ERROR|Error|##\[error\]|└|^\s*[a-z][a-z0-9_-]*: \d{1,2}%(\s|$)")
MAX_FAILING_LINES = 30


def parse_run_list(text: str) -> List[Dict[str, str]]:
    """Rows of `drone @git run list` (gh's tab-separated table); lines of another shape are skipped."""
    rows = []
    for line in text.splitlines():
        cells = line.split("\t")
        if len(cells) != len(RUN_LIST_FIELDS) or not cells[6].strip().isdigit():
            continue
        rows.append(dict(zip(RUN_LIST_FIELDS, (c.strip() for c in cells))))
    json_handler.log_operation("ci_run_list_parsed", {"rows": len(rows)})
    return rows


def newest_per_workflow(rows: List[Dict[str, str]], branch: str = "dev") -> Dict[str, Dict[str, str]]:
    """The newest run of each workflow on *branch*, keyed by workflow name."""
    newest: Dict[str, Dict[str, str]] = {}
    for row in rows:
        if row["branch"] != branch:
            continue
        held = newest.get(row["workflow"])
        if held is None or (row["created"], int(row["run_id"])) > (held["created"], int(held["run_id"])):
            newest[row["workflow"]] = row
    return newest


def _log_text(line: str) -> tuple:
    """Split one `--log-failed` line into (job, step, text without its timestamp)."""
    cells = line.split("\t", 2)
    if len(cells) < 3:
        return "", "", _LOG_STAMP.sub("", line)
    return cells[0], cells[1], _LOG_STAMP.sub("", cells[2])


def _failing_step(parsed: List[tuple]) -> str:
    """The step that raised the error annotation, else the step of the last log line."""
    for _job, step, text in parsed:
        if "##[error]" in text and step:
            return step
    return parsed[-1][1] if parsed else ""


def _owners(lines: List[str]) -> List[str]:
    """Branches named by a sub-100 audit score or by a failing test path, first seen first."""
    owners: List[str] = []
    for text in lines:
        audit = _AUDIT_OWNER.match(text)
        names = [audit.group(1)] if audit else []
        if not audit and ("FAILED" in text or "ERROR" in text):
            names = _TEST_OWNER.findall(text)
        owners.extend(name for name in names if name not in owners)
    return owners


def triage_log(log_text: str) -> Dict[str, Any]:
    """Failing step, failing lines and owners from a `run view --log-failed` dump."""
    parsed = [_log_text(line) for line in log_text.splitlines() if line.strip()]
    lines = [text.rstrip() for _job, _step, text in parsed if _FAILING.search(text)][-MAX_FAILING_LINES:]
    result = {"step": _failing_step(parsed), "lines": lines, "owners": _owners(lines)}
    json_handler.log_operation("ci_log_triaged", {"step": result["step"], "owners": result["owners"]})
    return result


def is_infra(conclusion: str, step: str) -> bool:
    """True when the red is the runner's, not a branch's: cancelled, timed out, or a setup step."""
    return conclusion in INFRA_CONCLUSIONS or bool(INFRA_STEP.match(step or ""))
