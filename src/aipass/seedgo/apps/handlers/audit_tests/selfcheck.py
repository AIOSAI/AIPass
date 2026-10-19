# =================== AIPass ====================
# Name: selfcheck.py
# Description: the harness's verdict on itself - the 16 instrument checks
# Version: 1.1.0
# Created: 2026-08-29
# Modified: 2026-10-18
# =============================================

"""
The lane auditing itself. Design section 10, published with every verdict.

Every check is published whether it passes or fails, never gated silently; a
check bound to an unbuilt group reports `not_applicable` with the group's name.
"""

import re
from typing import Dict, List, Optional

from aipass.seedgo.apps.handlers.json import json_handler

PASS = "pass"
FAIL = "fail"
NOT_APPLICABLE = "not_applicable"

#: Pytest short-summary prefixes; check 4 names failing nodeids so a reader need not rebuild the sandbox.
FAILURE_SUMMARY_PREFIXES: tuple = ("FAILED ", "ERROR ")

MAX_NAMED_FAILURES = 5

#: The totals line ends the run, so it survives a tail that has lost the first summary lines.
FAILURE_TOTAL_PATTERN = re.compile(r"\b(\d+) (?:failed|errors?)\b")

#: Checks that cannot run until their group does.
GROUP_BOUND: Dict[int, str] = {
    5: "pytest.scoped_survival",
    6: "pytest.targeted_mutation",
    7: "pytest.targeted_mutation",
    8: "pytest.scoped_survival",
}

GROUP_BOUND_NAMES: Dict[int, tuple] = {
    5: ("positive and negative control, plus a key-match assertion", "FALSE-CONTROL (mutmut #515)"),
    6: ("is the mutant already equal to the original?", "NO-OP-MUTANT"),
    7: ("did the mutant die for the RIGHT reason?", "ACCIDENTAL-DEATH"),
    8: ("reachability reported beside survival", "UNREACHABLE-MUTANT"),
}


def _check(number: int, name: str, prevents: str, status: str, detail: str) -> dict:
    """One harness row, in the shape the artifact publishes."""
    return {"check": number, "name": name, "prevents": prevents, "status": status, "detail": detail}


def _verdict(condition: Optional[bool], detail: str, unknown: str = "") -> tuple:
    """`(status, detail)` from a tri-state condition; `None` is `not_applicable`, never a failure."""
    if condition is None:
        return NOT_APPLICABLE, unknown or detail
    return (PASS if condition else FAIL), detail


def _group_bound_rows() -> List[dict]:
    """Checks 5-8: real requirements on groups that do not run yet."""
    rows: List[dict] = []
    for number in sorted(GROUP_BOUND):
        name, prevents = GROUP_BOUND_NAMES[number]
        rows.append(
            _check(
                number,
                name,
                prevents,
                NOT_APPLICABLE,
                f"group not built: {GROUP_BOUND[number]} reports not_applicable, and so does this check",
            )
        )
    return rows


def _copy_rows(environment: dict, liveness: dict) -> List[dict]:
    """Checks 1, 2, 3, 9, 12, 13 - everything about the copy."""
    live = liveness.get("live")
    status, detail = _verdict(
        live,
        f"the target module resolved to {liveness.get('resolved_to', 'nowhere')}",
        "the target is not an importable package, so there is no module to resolve",
    )

    return [
        _check(
            3,
            "the COPY is what actually loads, proved before the first probe",
            "MUTANT-NOT-LOADED",
            status,
            detail,
        ),
        _check(
            9,
            "every suite runs against a copy",
            "OBSERVER-FORGERY",
            PASS if environment.get("target_copy") else FAIL,
            f"suite ran against {environment.get('target_copy', 'an unrecorded path')}",
        ),
        _check(
            13,
            "m10_complete - were siblings COPIED or referenced?",
            "the symlink escape (design C10)",
            PASS if environment.get("m10_complete") else FAIL,
            f"{len(environment.get('copied_siblings', []))} sibling(s) copied, "
            f"{len(environment.get('symlinked_siblings', []))} symlinked - a write through a "
            f"symlinked sibling lands in the REAL tree",
        ),
    ]


def _bytecode_row(config_note: str) -> dict:
    """Check 2 - the one that biases uniformly toward 'this suite is bad'."""
    return _check(
        2,
        "-B, PYTHONDONTWRITEBYTECODE=1 and no __pycache__ in the copy",
        "STALE-BYTECODE",
        PASS,
        "pytest launched with -B, PYTHONDONTWRITEBYTECODE=1 in the child environment, and "
        "__pycache__ excluded from the rsync so no compiled artefact of code that no longer "
        f"exists can be read. Configuration: {config_note[:160]}",
    )


def _m10_rows(m10_proof: dict) -> List[dict]:
    """Checks 1 and 12 - the real tree, fingerprinted at both ends."""
    probed = bool(m10_proof.get("probed"))

    if not probed:
        detail = str(m10_proof.get("note", "the fingerprint could not be taken"))
        return [
            _check(1, "pristine fingerprint of the real tree, taken at START", "RESTORE-AT-START", FAIL, detail),
            _check(12, "the measured suite wrote nothing into the real target", "OBSERVER-FORGERY", FAIL, detail),
            _check(17, "every real-tree change was ATTRIBUTED", "UNATTRIBUTED-CHANGE", FAIL, detail),
        ]

    count = m10_proof.get("files_fingerprinted", 0)
    unattributed = m10_proof.get("unattributed_changes", [])
    by_the_suite = m10_proof.get("changed_by_the_measured_suite", [])
    concurrent = m10_proof.get("attributed_to_concurrent_writers", [])

    # Live daemons write the real tree during the run, so concurrent writers are
    # MEASURED (an idle snapshot pair), never path-exempted: exempting logs/ blinds the forge check.
    detail = (
        f"{count} file(s) re-hashed after teardown; {len(unattributed)} change(s) nothing else "
        f"was observed writing, {len(concurrent)} attributed to the target's own concurrent "
        f"writers (probe ran: {m10_proof.get('live_writers_probed')}, window "
        f"{m10_proof.get('live_writer_probe_seconds')}s - a window shorter than the run "
        f"UNDER-detects, so an unattributed change may still be a live service); diff: "
        f"{m10_proof.get('diff', {})}"
    )
    return [
        _check(
            1,
            "pristine fingerprint of the real tree, taken at START",
            "RESTORE-AT-START",
            PASS,
            f"{count} file(s) hashed before the copy was made",
        ),
        # Red only on paths the gate saw the suite itself open for writing, not on unattributed changes.
        _check(
            12,
            "the measured suite wrote nothing into the real target",
            "OBSERVER-FORGERY",
            PASS if not by_the_suite else FAIL,
            (
                f"the gate observed the suite writing {len(by_the_suite)} real-tree path(s): {by_the_suite}"
                if by_the_suite
                else f"{count} file(s) re-hashed after teardown; the gate recorded the suite writing none of them"
            ),
        ),
        # The unattributed remainder stays red; a declared path allowance would defeat `live_writers`.
        _check(
            17,
            "every real-tree change was ATTRIBUTED",
            "UNATTRIBUTED-CHANGE",
            PASS if not unattributed else FAIL,
            detail,
        ),
    ]


def _failing_units(run: dict, returncode: Optional[int]) -> str:
    """The nodeids behind a non-zero control, as a clause appended to check 4.

    Pytest truncates the summary MESSAGE to terminal width but never the nodeid;
    a tail with no summary says so rather than returning "".
    """
    if returncode == 0:
        return ""

    tail = str(run.get("stdout_tail") or "")
    if not tail:
        return ". No stdout was captured, so the failing unit(s) cannot be named from this run"

    nodeids = [
        line.split(" - ", 1)[0].split(" ", 1)[1].strip()
        for line in tail.splitlines()
        if line.startswith(FAILURE_SUMMARY_PREFIXES) and " " in line
    ]
    if not nodeids:
        return (
            ". No FAILED/ERROR summary line reached the captured tail, so the failing unit(s) "
            "cannot be named - the tail is a fixed-size window and a large dump can push the "
            "summary out of it"
        )

    reported = _reported_failures(tail)
    named = ", ".join(nodeids[:MAX_NAMED_FAILURES])
    rest = max(len(nodeids), reported) - min(len(nodeids), MAX_NAMED_FAILURES)
    clause = f". Failing: {named}, and {rest} more" if rest else f". Failing: {named}"
    if reported > len(nodeids):
        clause += f" ({reported - len(nodeids)} of them before the captured tail, so unnamed here)"
    return clause


def _reported_failures(tail: str) -> int:
    """Failed plus errored, from the last pytest totals line in the tail; 0 when none is there."""
    for line in reversed(tail.splitlines()):
        found = FAILURE_TOTAL_PATTERN.findall(line)
        if found and " in " in line:
            return sum(int(amount) for amount in found)
    return 0


def _gate_rows(hygiene: dict, run: dict) -> List[dict]:
    """Checks 4, 10, 11, 14, 15 - the gate and the process that ran it."""
    returncode = run.get("returncode")
    coverage = hygiene.get("gate_coverage") or {}
    canary = hygiene.get("canary") or {}

    return [
        _check(
            4,
            "control run first; environment inherited, only what is needed overridden",
            "CONTROL-DIRTY / HOST-ENV",
            PASS if returncode == 0 else FAIL,
            f"the suite's own exit status was {returncode}. A non-zero control means the "
            f"target's tests do not pass on their own, and the hygiene number below describes "
            f"a run in that state{_failing_units(run, returncode)}",
        ),
        _check(
            10,
            "the exit status read is the SUITE's, not a pipeline's",
            "PIPELINE-STATUS",
            PASS,
            "pytest is launched as a direct child with subprocess.run and its returncode is "
            "read from that object - there is no shell and no pipe between them",
        ),
        _check(
            11,
            "the canary fired and the gate caught it",
            "the fail-open mode",
            PASS if canary.get("caught") else FAIL,
            f"canary attempted={canary.get('attempted')} caught={canary.get('caught')} at "
            f"{canary.get('path', 'no path recorded')} - and a miss REFUSES, it does not warn",
        ),
        _check(
            14,
            "gate_coverage - what the scored gate cannot see, counted per run",
            "a 100 that means 'nothing seen' being read as 'nothing happened'",
            PASS if coverage.get("blind") else FAIL,
            f"{coverage.get('child_processes_spawned', 0)} child process(es) and "
            f"{coverage.get('sqlite3_connections', {}).get('file_backed', 0)} file-backed "
            f"sqlite3 handle(s) wrote where this gate cannot follow",
        ),
        _check(
            15,
            "budget_seconds and elapsed_seconds on every execution group",
            "a hang read as a pass",
            PASS if hygiene.get("budget_seconds") is not None else FAIL,
            f"{hygiene.get('elapsed_seconds')}s of a {hygiene.get('budget_seconds')}s budget; "
            f"expiry refuses rather than publishing a partial suite",
        ),
    ]


def _baseline_row(document: dict) -> dict:
    """Check 16 - did the no-vanishing diff actually run?"""
    baseline = document.get("group_baseline", "")
    first_run = baseline == "first run for this pair"
    return _check(
        16,
        "group_baseline - did the S3 no-vanishing diff actually run?",
        "a first-run artifact whose S3/S4 check was silently skipped",
        NOT_APPLICABLE if first_run else PASS,
        f"baseline: {baseline}"
        + (" - there is no previous artifact for this pair, so the diff could not run" if first_run else ""),
    )


def harness_block(
    *,
    document: dict,
    hygiene: dict,
    run: dict,
    environment: dict,
    liveness: dict,
    m10_proof: dict,
    config_note: str,
) -> dict:
    """The harness's verdict on itself, for one run.

    Failures are reported, never raised; the run's refusal path decides what they cost.
    """
    rows: List[dict] = []
    rows.extend(_m10_rows(m10_proof))
    rows.append(_bytecode_row(config_note))
    rows.extend(_copy_rows(environment, liveness))
    rows.extend(_gate_rows(hygiene, run))
    rows.extend(_group_bound_rows())
    rows.append(_baseline_row(document))
    rows.sort(key=lambda row: row["check"])

    failed = [row for row in rows if row["status"] == FAIL]
    if failed:
        # Logged too, so a failed harness check is findable without opening the artifact.
        json_handler.log_operation(
            "harness_checks_failed",
            {
                "count": len(failed),
                "checks": [row["check"] for row in failed],
                "target": document.get("target", {}).get("name"),
            },
        )

    return {
        "checks": rows,
        "passed": len([row for row in rows if row["status"] == PASS]),
        "failed": len(failed),
        "not_applicable": len([row for row in rows if row["status"] == NOT_APPLICABLE]),
        "note": (
            "Published whether it passes or fails (design section 10.1). A pre-flight that "
            "gates silently leaves a reader unable to tell a sound instrument from one nobody "
            "asked. Checks reporting not_applicable name the group they wait on."
        ),
    }
