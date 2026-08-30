# =================== AIPass ====================
# Name: gatelog.py
# Description: reads the payload's JSONL gate log into a normalized measurement
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The gate log reader — and the exact place the pytest ecosystem stops.

The payload writes JSONL inside the copy and knows nothing about scoring. This
module turns those records into a NORMALIZED measurement: a vocabulary any
ecosystem could fill, containing no pytest concept the core would have to
learn. The core applies S1-S9 to that vocabulary once instead of per language.

THE SEAM IS WHY THE CORE DOES NOT IMPORT THIS FILE. A core that reached into
`tests_pytest_standards` to read a gate log would have made pytest a core
dependency, and the second ecosystem would then arrive as a rewrite rather
than as a directory. The adapter hands the measurement UP; nothing reaches
down.

WHAT A MISSING SUMMARY MEANS. If the wall-clock budget killed the suite, the
payload's `pytest_sessionfinish` never ran, so there is no summary record and
no canary result. That reads here as `canary.attempted = False`, which the
core converts into a refusal. The T-BUDGET law therefore falls out of
canary-or-refuse rather than needing a special case — which is why it is safe
from a future author "fixing" a hang into a partial publication.

The score itself is the core's to compute, and it is a gate rather than an
opinion (design section 4.5): 100 or 0, never a percentage. "Your suite forged
31 log entries instead of 79" is not a better suite; it is the same defect at
a different volume.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

#: The mechanism string published in `gate_coverage`. Named precisely because
#: "per-interpreter" is the whole reason the blind list below is not empty.
GATE_MECHANISM = "sys.addaudithook (PEP 578), per-interpreter"

#: What this gate structurally cannot see. Law S8 refuses a scored group whose
#: blind list is empty: every real instrument is blind to something, and an
#: empty list is a claim of omniscience nobody has earned.
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

    A malformed line is DROPPED AND COUNTED rather than silently skipped: the
    caller sees a record shortfall instead of a clean-looking log. A missing
    file raises, because "no log" and "empty log" are different facts and only
    one of them means the plugin ran.
    """
    if not log_path.exists():
        raise GateLogError(f"the gate wrote no log at {log_path} - the plugin did not run")

    records: List[dict] = []
    malformed = 0
    with open(log_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                # Counted here and reported below as its own record. The debug
                # line names WHICH line was lost; the count is what travels to
                # the artifact, because a silent shortfall reads as a clean log.
                logger.debug(f"[AUDIT-TESTS] unparseable gate-log line in {log_path}: {exc}")
                malformed += 1

    if malformed:
        logger.warning(f"[AUDIT-TESTS] {malformed} malformed line(s) in {log_path}")
        records.append({"rec": "malformed_lines", "count": malformed})

    return records


def _first(records: List[dict], kind: str) -> Optional[dict]:
    """The first record of a kind, or None if the run never produced one."""
    for record in records:
        if record.get("rec") == kind:
            return record
    return None


def _violations(records: List[dict]) -> List[dict]:
    """Every violation record, published untruncated (design section 4.5)."""
    return [record for record in records if record.get("rec") == "violation"]


def gate_coverage(summary: dict) -> dict:
    """The S8 block: what the gate saw, what it cannot see, and how much.

    The counted fields are the argument. A static paragraph says the same
    thing about a suite that spawns no children and a suite that spawns fifty;
    a per-run number lets a reader weigh the 100 beside it. Two attempts at a
    static population table were both wrong, in both directions — the number
    comes from the run or it does not come.
    """
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

    This is the whole seam in one function. Everything pytest-shaped stops
    here — JSONL records, nodeids, `pytest_sessionfinish` — and what leaves is
    a vocabulary any ecosystem could fill: was the gate proven, what did it
    catch, what can it not see. The core then applies S1-S9 to that vocabulary
    ONCE rather than re-implementing the laws per language, which is the exact
    mistake that would force a rebuild when a third ecosystem lands.

    NOTHING HERE DECIDES A STATUS OR A SCORE. `proven` is a fact about the
    canary; turning it into `refused` is the core's ruling, not the adapter's.
    """
    header = _first(records, "header") or {}
    summary = _first(records, "summary") or {}
    copy_check = _first(records, "copy_check") or {}
    violations = _violations(records)

    canary = summary.get("canary") or {"attempted": False, "caught": False, "path": "", "error": ""}
    proven = bool(canary.get("attempted")) and bool(canary.get("caught")) and bool(header.get("hook_installed"))

    if not proven:
        # The run that will refuse. Recorded at the point the fact is
        # established rather than where it is acted on, so a caller cannot
        # obtain an unproven measurement without the record existing.
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

    Rev-4 requirement (design section 9.2): a serial run and an xdist run
    execute DIFFERENT orders, so a v1 baseline is order-specific. Captured
    from run one because it costs nothing now and cannot be reconstructed
    later — without it the v1-to-v2 comparison is unfalsifiable.

    Read from the summary rather than derived from the violation records. The
    derived version was BUILT FIRST and a live run refuted it: it listed only
    the units that wrote something, so a clean test was absent from the "order
    the tests executed in" — a different sequence under the right name, which
    is the shape of wrongness this whole lane exists to refuse.
    """
    summary = _first(records, "summary") or {}
    return [nodeid for nodeid in summary.get("executed_order", []) if isinstance(nodeid, str)]


def _unproven_reason(header: dict, canary: dict, timed_out: bool, *, has_records: bool = True) -> str:
    """Why this gate is not entitled to publish a number.

    Every branch names something a reader can act on. A refusal whose reason is
    "unproven" is a refusal nobody can fix.

    THE NO-RECORDS BRANCH EXISTS BECAUSE ITS ABSENCE PRODUCED A WRONG DIAGNOSIS.
    An empty log has no header, so `hook_installed` reads False and the run was
    reported as "the write gate was not installed" — a specific, actionable and
    entirely invented claim, when the true fact is that the plugin never
    reported at all. Inferring a precise cause from missing evidence is the
    confidently-wrong-answer species this lane exists to refuse, and it had
    quietly landed in the lane's own refusal path.
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
    """A static group that has not been built yet, stated lawfully.

    Law S1: not-run is `not_applicable` WITH A REASON, never 0. A group that
    quietly scores zero because nothing implemented it is the exact lie this
    lane was built to stop telling.
    """
    return {
        "tier": "static",
        "kind": "nominate_only",
        "status": "not_applicable",
        "reason": reason,
        "score": None,
        "nominations": [],
    }
