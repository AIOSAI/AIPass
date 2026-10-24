# =================== AIPass ====================
# Name: gatelog.py
# Description: reads the payload's JSONL gate log into a normalized measurement
# Version: 1.0.1
# Created: 2026-08-29
# Modified: 2026-10-24
# =============================================

"""The gate log reader — and the exact place the pytest ecosystem stops.

A budget-killed suite leaves no summary, so the core refuses via canary-or-refuse.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

#: "per-interpreter" is the whole reason the blind list below is not empty.
GATE_MECHANISM = "sys.addaudithook (PEP 578), per-interpreter"

#: Law S8 refuses a scored group whose blind list is empty.
GATE_BLIND: tuple = (
    "writes by child processes - the hook is not installed in their interpreter",
    "writes through an open sqlite3 handle - CREATE/INSERT/COMMIT and the -wal/-journal "
    "siblings emit no event at all; only the connect is visible",
    "writes from any other C extension that bypasses the io/os layer",
    "reads of any kind - a test that READS live state is invisible to this gate",
)


class GateLogError(RuntimeError):
    """The gate log could not be read, so nothing about the run is known."""


def read_records(log_path: Path) -> List[dict]:
    """Every JSONL record the payload wrote, in order.

    A malformed line is dropped and counted; a missing file raises: "no log" is not "empty log".
    """
    if not log_path.exists():
        raise GateLogError(f"the gate wrote no log at {log_path} - the plugin did not run")

    records: List[dict] = []
    malformed = 0
    with open(log_path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = decode_line(line, Path(log_path), number)
            if record is None:
                malformed += 1
            else:
                records.append(record)

    if malformed:
        logger.warning(f"[AUDIT-TESTS] {malformed} malformed line(s) in {log_path}")
        records.append({"rec": "malformed_lines", "count": malformed})

    return records


def decode_line(line: str, path: Path, number: int) -> Optional[dict]:
    """One JSONL line as a dict, or None (blank, not JSON, or not an object) with a warning naming where it broke."""
    text = line.strip()
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning(f"[AUDIT-TESTS] log {path.name} line {number} is not JSON: {exc}")
        return None
    if not isinstance(decoded, dict):
        logger.warning(f"[AUDIT-TESTS] log {path.name} line {number} is not an object")
        return None
    return decoded


def first_record(records: List[dict], kind: str) -> dict:
    """The first record of a kind, or an empty dict when the run never wrote one."""
    for record in records:
        if record.get("rec") == kind:
            return record
    return {}


def _violations(records: List[dict]) -> List[dict]:
    """Every violation record, published untruncated (design section 4.5)."""
    return [record for record in records if record.get("rec") == "violation"]


def gate_coverage(summary: dict) -> dict:
    """The S8 block: what the gate saw, what it cannot see, and how much."""
    return {
        "mechanism": GATE_MECHANISM,
        "observed": list(summary.get("observed_events", [])) or ["see the run's header record"],
        "blind": list(GATE_BLIND),
        "child_processes_spawned": summary.get("child_processes_spawned", 0),
        "spawning_nodeids": list(summary.get("spawning_nodeids", [])),
        "sqlite3_connections": dict(summary.get("sqlite3_connections", {})),
        "sqlite3_nodeids": list(summary.get("sqlite3_nodeids", [])),
        "note": (
            f"{summary.get('child_processes_spawned', 0)} child process(es) ran and "
            f"{summary.get('sqlite3_connections', {}).get('file_backed', 0)} file-backed sqlite3 "
            f"handle(s) were opened during this suite. Neither's writes were observed. A score of "
            f"100 means 'no violation seen by this gate', not 'no violation'."
        ),
    }


def measure(records: List[dict], *, timed_out: bool) -> dict:
    """Turn one run's records into a NORMALIZED gate measurement.

    Decides no status or score: turning `proven` into `refused` is the core's ruling.
    """
    header = first_record(records, "header")
    summary = first_record(records, "summary")
    copy_check = first_record(records, "copy_check")
    violations = _violations(records)

    canary = summary.get("canary") or {"attempted": False, "caught": False, "path": "", "error": ""}
    proven = bool(canary.get("attempted")) and bool(canary.get("caught")) and bool(header.get("hook_installed"))

    if not proven:
        # Logged where the fact is established, so no unproven measurement exists unrecorded.
        json_handler.log_operation(
            "gate_unproven",
            {"hook_installed": bool(header.get("hook_installed")), "canary": dict(canary), "timed_out": timed_out},
        )

    return {
        "proven": proven,
        "unproven_reason": "" if proven else _unproven_reason(header, canary, timed_out, has_records=bool(records)),
        "hook_installed": bool(header.get("hook_installed")),
        "canary": dict(canary),
        "copy_verified_live": copy_check.get("verified_live"),
        "copy_resolved_to": copy_check.get("resolved_to", ""),
        "allowances": list(header.get("allowances", [])),
        "violation_count": len(violations),
        "violations": violations,
        "attribution": "nodeid",
        "tmpdir_writes": summary.get("tmpdir_writes", 0),
        "relative_unattributable": summary.get("relative_unattributable", 0),
        "dropped_over_cap": summary.get("dropped_over_cap", 0),
        "swallowed_errors": list(summary.get("swallowed_errors", [])),
        "gate_coverage": gate_coverage(summary),
    }


def executed_order(records: List[dict]) -> List[str]:
    """The order units actually ran in, as the session itself recorded it.

    Read from the summary, not derived from violations, which would omit clean tests.
    """
    summary = first_record(records, "summary")
    return [nodeid for nodeid in summary.get("executed_order", []) if isinstance(nodeid, str)]


def _unproven_reason(header: dict, canary: dict, timed_out: bool, *, has_records: bool = True) -> str:
    """Why this gate is not entitled to publish a number.

    No records is its own reason: inferring "gate not installed" from it invents a cause.
    """
    if timed_out:
        return "the wall-clock budget expired before the suite finished, so the gate never reported (Law T-BUDGET)"
    if not has_records:
        return "the gate produced no records at all - the plugin never reported, so nothing about this run is known"
    if not header.get("hook_installed"):
        return "the write gate was not installed, so a clean result would mean nothing (Law T10)"
    if not canary.get("attempted"):
        return "no canary was fired, so nothing proves the gate could have caught a violation (Law T10)"
    detail = canary.get("error") or "no error reported"
    return f"the canary was written and the gate did NOT catch it - the gate is blind: {detail}"


def nomination_group(reason: str) -> Dict[str, object]:
    """A static group that has not been built yet, stated lawfully."""
    return {
        "tier": "static",
        "kind": "nominate_only",
        "status": "not_applicable",
        "reason": reason,
        "score": None,
        "nominations": [],
    }
