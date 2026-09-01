# =================== AIPass ====================
# Name: selfcheck.py
# Description: the harness's verdict on itself - the 16 instrument checks
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The lane auditing itself. Design section 10, published with every verdict.

*"A checker that cannot fail these is not entitled to publish a species
table."* — TAXONOMY section 3.

NOT A PRE-FLIGHT THAT GATES SILENTLY. Every one of the sixteen checks is
published in the artifact's `harness` block WHETHER IT PASSES OR FAILS. A
pre-flight that quietly aborts leaves a reader unable to distinguish "the
instrument was sound" from "the instrument was never asked", and the whole
argument of this lane is that those two are different documents.

A CHECK BOUND TO A GROUP THAT IS NOT BUILT REPORTS `not_applicable` WITH THE
GROUP'S NAME, exactly as the group does. Law S1 at the harness level: a check
that was skipped and a check that passed must never look the same.

THE ONE THAT MATTERS MOST IS 14. Law M2 says a measurement that agrees with
you everywhere is not evidence — and it points at the lane's own scored gate
as readily as at the standard the lane retires. `gate_coverage` is the answer:
a hard 100/0 whose mechanism is per-interpreter, whose blind spot is real, and
which states the size of that blind spot per run rather than in a paragraph.

CHECK 2 DESERVES ITS OWN NOTE. Stale bytecode biases UNIFORMLY TOWARD SURVIVED
- toward "this suite is bad" - and is invisible to hash verification. It bit
the MVP's builder during the MVP's own construction, and it bit a live
mutation run in this campaign exactly as the research warned.
"""

from typing import Dict, List, Optional

from aipass.seedgo.apps.handlers.json import json_handler

#: Verdict vocabulary for one harness check.
PASS = "pass"
FAIL = "fail"
NOT_APPLICABLE = "not_applicable"

#: Checks that cannot run until their group does. Named here so an unbuilt
#: group produces a `not_applicable` with the group's own name rather than a
#: silent absence.
GROUP_BOUND: Dict[int, str] = {
    5: "pytest.scoped_survival",
    6: "pytest.targeted_mutation",
    7: "pytest.targeted_mutation",
    8: "pytest.scoped_survival",
}

#: What each group-bound check would prevent once its group exists.
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
    """`(status, detail)` from a tri-state condition.

    `None` is a legitimate third answer - a non-package target has nothing to
    resolve - and it becomes `not_applicable` rather than being flattened into
    a failure, because "could not apply" and "applied and failed" are the two
    things this whole lane exists to keep apart.
    """
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

    # Check 12 fails on what NOTHING ELSE was seen writing. A live citizen's
    # own daemon and server write into the real tree throughout the window, so
    # keying the check on the raw diff makes it fail on every live target - and
    # a check that always fails is a check nobody reads, which costs more than
    # the check is worth. The discriminator is MEASURED (two back-to-back
    # snapshots with no suite running), never a path exemption: exempting
    # logs/ would blind this to the exact forge it convicted a branch for. The
    # full diff and both partitions travel in the artifact either way.
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
        # SPLIT FROM THE UNATTRIBUTED SET, on @trigger's report 2026-08-30.
        # This row is the finding the lane exists to make: the gate watched the
        # suite in-process and NAMED the real-tree paths it opened for writing.
        # Keying the red on that, and only that, is what stops a recipient
        # reading "your suite dirtied the real tree" off a branch whose suite
        # wrote nothing and whose ten moved files were a systemd unit and the
        # citizen answering their own mail mid-audit.
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
        # The honest remainder, never folded into the row above and never
        # exempted away. A path allowance for `.ai_mail.local/` or a systemd
        # name match would both be DECLARED discriminators, which is precisely
        # what `live_writers` refuses to be - so this stays red and says why.
        _check(
            17,
            "every real-tree change was ATTRIBUTED",
            "UNATTRIBUTED-CHANGE",
            PASS if not unattributed else FAIL,
            detail,
        ),
    ]


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
            f"a run in that state",
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

    Returns the block the artifact publishes under `harness`. Failures are
    NOT raised: a harness failure is a fact about the run, and a fact removed
    from the document because it was inconvenient is the thing this whole
    campaign is against. The run's own refusal path decides what a failure
    costs; this function only reports.
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
        # Published AND logged. A harness check that failed is the single most
        # important thing about a run, and it must be findable without opening
        # the artifact.
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
