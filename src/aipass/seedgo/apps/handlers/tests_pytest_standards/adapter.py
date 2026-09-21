# =================== AIPass ====================
# Name: adapter.py
# Description: the pytest execution adapter - the 8-function contract
# Version: 1.1.0
# Created: 2026-08-29
# Modified: 2026-09-19
# =============================================

"""
The pytest adapter. Eight functions, two constants, and nothing else.

WHAT THIS MODULE DELIBERATELY DOES NOT DEFINE. There is no `check_module` and
no `check_branch` here, and their absence is load-bearing rather than
incidental: `discover_checkers()` keeps a module only if it defines one of
them, so this pack is invisible to the audit's file-walk engine with ZERO
change to that engine. A flag can be forgotten; a function that does not exist
cannot be called. And since `.github/scripts/seedgo_audit.py` calls
`audit_branch()` directly without ever reading a pack manifest, this shape gate
is the only gate CI has.

WHAT AN ADAPTER MAY NEVER DO: compute a score, decide `not_applicable` versus
`refused`, write the artifact, choose an exit code, or render. It returns
measurements; the core applies the laws. That seam is what makes S1-S9
enforceable once instead of re-implemented per ecosystem — the exact mistake
that would force a rebuild when a third ecosystem lands.

THE PAYLOAD IS NOT PART OF THIS MODULE'S RESIDENCY. This file runs in seedgo's
own process and complies fully with seedgo's standards. `payload/` runs inside
a copy of a foreign tree and is stdlib-only by mandate (Law M10), under a
path-scoped bypass @devpulse granted conditional on the machine check in
`adapters.execution_isolation()`.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.tests_pytest_standards import (
    diff_scope,
    envcopy,
    envdiff,
    gatelog,
    gutting,
    nominators,
    statement_deletion,
)
from aipass.seedgo.apps.handlers.module_root import module_file

ADAPTER_API = 1
ECOSYSTEM = "pytest"

#: Groups this adapter contributes beyond the core spine. They are published
#: NAMESPACED (`pytest.<name>`), so a Rust adapter never has to know these
#: exist and a Rust species has somewhere to go.
#:
#: THE LIST IS EXPLICIT AND THE DISCOVERY IS MACHINE-CHECKED AGAINST IT. The
#: static groups are also self-discovered from `<name>_check.py` files, so a
#: nominator added without a line here would silently change the published
#: group list - which is exactly what Law S3 exists to stop. A test pins the
#: two together; adding a species stays three files and one line.
STATIC_GROUPS: tuple = (
    "static_assertion_shape",
    "static_capture_never_read",
    "static_coverage_slot",
    "static_drifted_inventory",
    "static_empty_parametrize",
    "static_entry_point_diff",
    "static_mock_drift",
    "static_no_oracle",
    "static_posix_literal",
    "static_raw_needle",
    "static_ruff_pt",
    "static_self_skip",
    "static_tautology_assert",
    "static_unentered_assert",
    "static_unread_redirect",
)

#: The execution groups whose ENGINES EXIST and which still do not run unless
#: an operator asks for them by name on the command line.
#:
#: "Opt-in" is a statement about COST, never about confidence. Both engines
#: are built, measured and published here; what neither of them may do is
#: spend an operator's wall clock without being asked. `pseudo_tested` runs
#: one whole suite execution per FUNCTION - projected at ~2.44h on seedgo even
#: with coverage-based test selection - and `width_coupling` runs the suite
#: twice more on top of the gated run. A default that quietly did either would
#: turn `audit-tests` from a thing you run into a thing you schedule.
#:
#: THE NAMES COME FROM THE ENGINES rather than being spelled again here. A
#: group name restated in a second file is a group name that can drift, and
#: the published list is exactly what Law S3 refuses to let drift.
OPT_IN_EXECUTION_GROUPS: tuple = (
    gutting.GROUP,
    envdiff.GROUP,
    statement_deletion.GROUP,
)

#: The execution groups this adapter declares but does not run in this
#: release. They are published `not_applicable` with a reason from day one,
#: because the rev-4 contracts binding them (kill_cause, the survival naming
#: rule) have to land before the capability or they never land at all.
#:
#: `pseudo_tested` LEFT THIS TUPLE on 2026-09-19 and that is an honesty fix,
#: not a promotion: the engine had been built and measured for a day while
#: this list still said "not built", because `nominate(spec)` carried no
#: options channel to opt a campaign in per run. It has one now - the request
#: rides on `EnvSpec`, which both `build_env()` and `nominate()` already hold -
#: so the group runs when it is asked for and says it is AVAILABLE when it is
#: not. Nothing vanished: it moved to OPT_IN_EXECUTION_GROUPS and is published
#: on every run either way (Law S3).
UNBUILT_EXECUTION_GROUPS: tuple = (
    "scoped_survival",
    "targeted_mutation",
)

#: Every group this adapter publishes, in published order. The opt-in pair
#: sits where `pseudo_tested` already sat so that an artifact diff across this
#: change shows an ADDITION and not a reshuffle.
ADAPTER_GROUPS: tuple = STATIC_GROUPS + OPT_IN_EXECUTION_GROUPS + UNBUILT_EXECUTION_GROUPS

#: Law S3 - a group may only VANISH by a recorded ruling, and the ruling
#: travels in the artifact rather than in a commit message nobody will find.
#:
#: `pytest.static_nominators` was a phase-4 PLACEHOLDER. It was published by
#: three real runs (@backup, @canary, @daemon) as a single `not_applicable`
#: group standing in for the whole static tier, and the signed design never
#: named it: design revision 2 section 4.2 specifies the nine namespaced
#: `pytest.static_*` groups now shipping. Nothing it covered stopped being
#: published - the placeholder split into the nine groups that measure the
#: species it named. It is recorded here as a retirement anyway, because S3
#: does not have a category for "split" and inventing one to avoid writing a
#: ruling would be the paperwork version of a group quietly disappearing.
RETIRED_GROUPS: tuple = (
    {
        "group": "pytest.static_nominators",
        "date": "2026-08-29",
        "ruling": (
            "design revision 2 section 4.2 (reviewed and signed by @devpulse) specifies the nine "
            "namespaced pytest.static_* groups; static_nominators was a phase-4 placeholder that "
            "the design never named. Superseded by static_assertion_shape, static_capture_never_read, "
            "static_coverage_slot, static_entry_point_diff, static_mock_drift, static_no_oracle, "
            "static_ruff_pt, static_self_skip and static_unentered_assert - every species the "
            "placeholder stood in for is still published, more finely. No measurement was withdrawn."
        ),
    },
)

#: The injected plugin, by path. Copied into the env, never imported here.
PAYLOAD_DIR = module_file(__file__).parent / "payload"
PLUGIN_FILE = PAYLOAD_DIR / "audit_hygiene_plugin.py"

#: Directory names that mean "this project has pytest units".
TEST_DIR_NAMES: tuple = ("tests", "test")

#: Default wall-clock budget for one suite (Law T-BUDGET).
DEFAULT_BUDGET_SECONDS = 900

#: The key an operator's opt-in arrives under, in the options dict the verb
#: builds and `build_env()` receives. Named once so the verb, the spec and
#: this module cannot disagree about the spelling of it.
OPTION_EXECUTION_GROUPS = "execution_groups"

#: The shape of an execution group's document. `measure_only` is the honest
#: kind for both of these: they report counts and named findings, and neither
#: is in `spine.SCORED_GROUPS`, so `score` is None on every path out of here.
#: Scoring is the core's job and an adapter that computed one would have
#: stepped over the seam this whole pack is built around.
EXEC_TIER = "exec"
EXEC_KIND = "measure_only"
STATUS_MEASURED = "measured"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_REFUSED = "refused"

#: The flag that asks for each opt-in group, quoted in the group's own reason.
#: A `not_applicable` that says a group is available without saying how to ask
#: for it is a reason nobody can act on.
OPT_IN_FLAGS: Dict[str, str] = {
    gutting.GROUP: "--pseudo-tested",
    envdiff.GROUP: "--width-coupling",
    statement_deletion.GROUP: "--statement-deletion",
}


# =============================================================================
# 1 - DETECT
# =============================================================================


def detect(target: Path) -> dict:
    """Does this adapter claim the target? Cheap, read-only, never raises.

    Nothing here imports the target or executes any of it. A detector that ran
    code would already have violated M10 before the copy was even made.
    """
    try:
        return _detect_units(Path(target))
    except OSError as exc:
        logger.warning(f"[AUDIT-TESTS] pytest detect() could not read {target}: {exc}")
        return {"applicable": False, "reason": f"target unreadable: {exc}", "unit_count": 0, "units": []}


def _detect_units(target: Path) -> dict:
    """Count `test_*.py` files under the target's test directories."""
    units: List[str] = []
    for name in TEST_DIR_NAMES:
        directory = target / name
        if directory.is_dir():
            units.extend(sorted(str(p.relative_to(target)) for p in directory.rglob("test_*.py")))

    if not units:
        loose = sorted(str(p.relative_to(target)) for p in target.glob("test_*.py"))
        units.extend(loose)

    if not units:
        return {
            "applicable": False,
            "reason": "no test_*.py files under tests/, test/ or the target root",
            "unit_count": 0,
            "units": [],
        }

    return {
        "applicable": True,
        "reason": f"{len(units)} pytest file(s) found",
        "unit_count": len(units),
        "units": units,
    }


# =============================================================================
# 2 - BUILD ENV
# =============================================================================


def build_env(target: Path, workdir: Path, options: dict) -> envcopy.EnvSpec:
    """Copy-first (Law M10). Returns the spec naming everything that was made.

    `symlink_siblings` is off by default and that inverts the MVP deliberately:
    a symlinked sibling is writable and a write through one lands in the REAL
    tree — measured, five files into the real prax/prax_json/ on the MVP's
    first calibration run. A default that can write the real repo is not a
    default an auditor may ship. Choosing the fast mode stamps
    `m10_complete: false` on the run that chose it.

    THIS IS WHERE THE OPTIONS CHANNEL ALREADY WAS. `nominate(spec)` takes only
    the spec, so for a year the pack's answer to "how does an operator opt a
    campaign in per run" was "bump ADAPTER_API". It never needed one: this
    function receives `options` and returns the very object `nominate()` is
    handed, so the request simply rides across on the spec. No signature in the
    eight-function contract changed to make the two built execution groups
    runnable.
    """
    return envcopy.build_env(
        Path(target),
        Path(workdir),
        PLUGIN_FILE,
        python_override=options.get("python"),
        symlink_siblings=bool(options.get("symlink_siblings")),
        execution_groups=options.get(OPTION_EXECUTION_GROUPS),
        scope_to_diff=bool(options.get("scope_to_diff")),
        diff_scope_ref=options.get("diff_scope_ref"),
    )


# =============================================================================
# 3 - ASSERT ENV IS LIVE
# =============================================================================


def assert_env_is_live(spec: envcopy.EnvSpec) -> dict:
    """Harness check 3 — prove the COPY is what actually loads.

    `live` is None-able through `resolved_to`: a non-package target has no
    module to import, which is a legitimate state rather than a failure. What
    is never legitimate is resolving to the real repo and reporting the number
    as the copy's.
    """
    verified, detail = envcopy.assert_copy_is_live(spec)
    return {
        "live": verified,
        "resolved_to": detail,
        "how": "imported the target module in a child interpreter and read its __file__",
    }


# =============================================================================
# 4 - RUN GATED
# =============================================================================


def _gate_environment(spec: envcopy.EnvSpec, options: dict) -> Dict[str, str]:
    """The environment the gated suite runs under."""
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONPATH": spec.pythonpath,
            "PYTHONDONTWRITEBYTECODE": "1",
            "AUDIT_TESTS_LOG": str(spec.log_path),
            "AUDIT_TESTS_ENV_ROOT": str(spec.env_root),
            "AUDIT_TESTS_TARGET_ROOT": str(spec.target_copy),
            "AUDIT_TESTS_TARGET_MODULE": spec.target_module,
            "AUDIT_TESTS_TMPDIR_ALLOWED": "0" if options.get("no_tmpdir_allowance") else "1",
        }
    )
    if options.get("prove_refusal"):
        # Canary point C: the run with the gate deliberately OFF. It must end
        # in a refusal and publish no group — the fail-open mode, made a test.
        environment["AUDIT_TESTS_DISABLE_HOOK"] = "1"
    return environment


def run_gated(spec: envcopy.EnvSpec, budget_seconds: int, options: dict) -> dict:
    """Run the units with the write-gate installed, under a wall-clock budget.

    ON EXPIRY THIS RETURNS NO MEASUREMENT. `timed_out=True` and nothing else,
    because a partial suite that reports a number is forgery by omission. The
    core converts it into a refusal, and it does so without a special case:
    the plugin's `pytest_sessionfinish` never ran, so there is no canary
    result, so canary-or-refuse fires on its own.

    `-p no:cacheprovider` and `-B` are not tidiness. Stale bytecode bit a live
    mutation run during the MVP's calibration exactly as the research warned,
    and a suite reading a `.pyc` of code that no longer exists measures a tree
    that does not exist either.
    """
    command = [
        str(spec.python),
        "-B",
        "-m",
        "pytest",
        spec.test_arg,
        "-p",
        "audit_hygiene_plugin",
        "-p",
        "no:cacheprovider",
        "-q",
        "--no-header",
    ]

    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=str(spec.run_cwd),
            env=_gate_environment(spec, options),
            capture_output=True,
            text=True,
            timeout=budget_seconds,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"[AUDIT-TESTS] suite exceeded its {budget_seconds}s budget in {spec.env_root}")
        json_handler.log_operation("suite_budget_exhausted", {"budget_seconds": budget_seconds, "layout": spec.layout})
        return {
            "timed_out": True,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "budget_seconds": budget_seconds,
            "returncode": None,
            "gate": gatelog.measure([], timed_out=True),
            "executed_order": [],
            "stdout_tail": "",
            "config_note": _config_note(spec),
        }
    except OSError as exc:
        logger.warning(f"[AUDIT-TESTS] could not launch pytest for {spec.env_root}: {exc}")
        return {
            "timed_out": False,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "budget_seconds": budget_seconds,
            "returncode": None,
            "gate": gatelog.measure([], timed_out=False),
            "executed_order": [],
            "stdout_tail": f"pytest could not be launched: {type(exc).__name__}: {exc}",
            "config_note": _config_note(spec),
        }

    elapsed = time.monotonic() - started
    records = _read_records(spec)
    json_handler.log_operation(
        "suite_run_completed",
        {"returncode": result.returncode, "elapsed_seconds": round(elapsed, 3), "records": len(records)},
    )
    return {
        "timed_out": False,
        "elapsed_seconds": round(elapsed, 3),
        "budget_seconds": budget_seconds,
        "returncode": result.returncode,
        "gate": gatelog.measure(records, timed_out=False),
        "executed_order": gatelog.executed_order(records),
        "stdout_tail": (result.stdout or "")[-2000:],
        "config_note": _config_note(spec),
    }


def _read_records(spec: envcopy.EnvSpec) -> List[dict]:
    """The gate log, or an empty list when the plugin never wrote one.

    An unwritten log is not an error to raise here — it is the evidence that
    produces a refusal upstream, and losing it to an exception would turn a
    diagnosable refusal into a crash.
    """
    try:
        return gatelog.read_records(spec.log_path)
    except gatelog.GateLogError as exc:
        logger.warning(f"[AUDIT-TESTS] no gate log to read: {exc}")
        return []


def _config_note(spec: envcopy.EnvSpec) -> str:
    """Which pytest configuration this run used, and why — in words."""
    return (
        f"pytest launched from {spec.run_cwd} against '{spec.test_arg}', serial, one process, "
        f"no xdist, with the target's own configuration in effect. This is NOT the CI "
        f"configuration and the two execute different test orders."
    )


# =============================================================================
# 5 - FIRE CANARY
# =============================================================================


def fire_canary(spec: envcopy.EnvSpec) -> dict:
    """The canary result from the run that just happened.

    The canary is fired INSIDE the gated session by the payload, not from out
    here, because a canary written by the parent process would test a hook the
    parent installed rather than the one the suite ran under. This function
    reports what the session found; it does not conduct a second experiment.
    """
    try:
        records = gatelog.read_records(spec.log_path)
    except gatelog.GateLogError as exc:
        # Not swallowed: an unreadable log means the gate is UNPROVEN, and the
        # reason travels out in `error` so the refusal names something a reader
        # can act on rather than only saying no.
        logger.warning(f"[AUDIT-TESTS] canary result unavailable for {spec.env_root}: {exc}")
        return {"attempted": False, "caught": False, "path": "", "error": str(exc)}

    for record in records:
        if record.get("rec") == "summary":
            canary = record.get("canary") or {}
            return {
                "attempted": bool(canary.get("attempted")),
                "caught": bool(canary.get("caught")),
                "path": canary.get("path", ""),
                "error": canary.get("error", ""),
            }

    return {
        "attempted": False,
        "caught": False,
        "path": "",
        "error": "the session produced no summary record - it did not reach the end of the run",
    }


# =============================================================================
# 6 - NOMINATE
# =============================================================================


def nominate(spec: envcopy.EnvSpec) -> dict:
    """Every group this adapter publishes, static and execution alike.

    THE CORPUS IS THE COPY, NEVER THE REAL TREE. The nominators only read, so
    pointing them at the real target would break nothing visible - and that is
    precisely why it is worth stating: the static tier would then be the one
    part of the lane measuring a different program from the rest of it, and a
    rule reading one tree while the gate reads another produces two numbers
    nobody can reconcile. The two execution campaigns below run against the
    same copy, through the same interpreter, for the same reason.

    A group whose nominator could not run reports `not_applicable` with the
    reason rather than an empty `measured`. Ruff's absence is the live case.

    THE STATIC TIER IS STILL NOMINATE-ONLY (Law M1). What changed on
    2026-09-19 is that this function also publishes two EXECUTION groups when
    the spec says an operator asked for them. Neither carries a score, neither
    convicts, and both report `not_applicable` with a reason when they were not
    requested - so the default run is byte-for-byte the run it was before,
    except that its two available campaigns now say they are available.
    """
    documents = nominators.run(spec.target_copy)

    for name in UNBUILT_EXECUTION_GROUPS:
        documents[name] = gatelog.nomination_group(_unbuilt_reason(name))

    requested = set(spec.execution_groups)
    documents[gutting.GROUP] = _pseudo_tested_group(spec, gutting.GROUP in requested)
    documents[envdiff.GROUP] = _width_coupling_group(spec, envdiff.GROUP in requested)
    documents[statement_deletion.GROUP] = _statement_deletion_group(spec, statement_deletion.GROUP in requested)

    for name in ADAPTER_GROUPS:
        if name not in documents:
            documents[name] = gatelog.nomination_group(
                f"declared in ADAPTER_GROUPS but no nominator claimed '{name}' - the group is "
                f"published empty rather than dropped, because a group that vanished is what "
                f"Law S3 exists to catch"
            )

    return documents


# =============================================================================
# 6a - THE OPT-IN EXECUTION GROUPS
# =============================================================================


def _opt_in_reason(group: str) -> str:
    """Why a BUILT execution group did not run on a run that never asked for it.

    DELIBERATELY NOT the "not built" sentence its two neighbours carry. That
    wording is false for these groups now, and a reader deciding whether to
    spend the wall clock needs three facts a false sentence withholds: that the
    capability exists, what it costs, and the exact flag that buys it.
    """
    reasons = {
        gutting.GROUP: (
            f"BUILT AND AVAILABLE, not requested for this run - pass "
            f"{OPT_IN_FLAGS[gutting.GROUP]} to opt in. gutting.py replaces one function's whole "
            f"body with `{gutting.GUT_STATEMENT}` and runs the tests that could kill it, once per "
            f"function, so the cost scales with the TREE and not with the run: measured at 2.09s "
            f"per mutant on the banked canary fixture and projected at ~2.44h on seedgo even with "
            f"coverage-based test selection. That is why it is never spent by default. It is a NEW "
            f"group and never a redefinition of scoped_survival (contract 2)"
        ),
        statement_deletion.GROUP: (
            f"BUILT AND AVAILABLE, not requested for this run - pass "
            f"{OPT_IN_FLAGS[statement_deletion.GROUP]} to opt in. statement_deletion.py deletes ONE "
            f"statement at a time instead of a whole body, so it finds the statement no test "
            f"observes inside a function that is otherwise well tested - the shape whole-body "
            f"gutting cannot isolate. It is the most expensive group in the lane: 8.4x gutting's "
            f"mutant count on the banked canary fixture and 6.2x on seedgo, paid down by selecting "
            f"only the tests that execute the statement's OWN lines. Never spent by default"
        ),
        envdiff.GROUP: (
            f"BUILT AND AVAILABLE, not requested for this run - pass "
            f"{OPT_IN_FLAGS[envdiff.GROUP]} to opt in. envdiff.py runs the suite twice, at "
            f"COLUMNS={envdiff.NARROW_COLUMNS} and COLUMNS={envdiff.WIDE_COLUMNS}, and subtracts "
            f"the per-nodeid verdicts; it executes no mutant and is bound by no kill_cause. It is "
            f"cheap - 10.3s on the banked canary fixture, 194s on seedgo - and it still costs two "
            f"more whole suite executions on top of the gated one, so the doubling is asked for "
            f"rather than assumed until it has been ruled on"
        ),
    }
    return reasons.get(
        group,
        f"'{group}' is listed as an opt-in execution group with no reason written for it - "
        f"that is a defect in this adapter and not a statement about the target",
    )


def _execution_not_applicable(group: str, reason: str) -> Dict[str, object]:
    """An execution group that did not run, stated lawfully (Law S1).

    The counts are ABSENT rather than zeroed. A `functions_probed: 0` beside
    `status: not_applicable` invites exactly the reading S1 forbids - that the
    campaign looked and found nothing - and the empty `mutants` list is carried
    only because Law S9 iterates it and an absent list would be a different
    shape from the measured document for no reason a reader benefits from.
    """
    return {
        "group": group,
        "tier": EXEC_TIER,
        "kind": EXEC_KIND,
        "status": STATUS_NOT_APPLICABLE,
        "reason": reason,
        "score": None,
        "mutants": [],
    }


def _suite_target(spec: envcopy.EnvSpec) -> gutting.SuiteTarget:
    """The copy's suite, as gutting invokes it. Built here, never by the engine."""
    return gutting.SuiteTarget(
        python=spec.python,
        cwd=spec.run_cwd,
        pythonpath=spec.pythonpath,
        test_arg=spec.test_arg,
        target_copy=spec.target_copy,
    )


def _axis_target(spec: envcopy.EnvSpec) -> envdiff.Target:
    """The copy's suite, as the environment-diff axis invokes it."""
    return envdiff.Target(
        python=spec.python,
        cwd=spec.run_cwd,
        pythonpath=spec.pythonpath,
        test_arg=spec.test_arg,
    )


def _pseudo_tested_group(spec: envcopy.EnvSpec, requested: bool) -> Dict[str, object]:
    """The per-function extreme-mutation campaign, when it was asked for.

    COVERAGE SELECTION IS THE MODE THIS SEAM OPTS INTO. The full-suite mode
    runs every test for every function and the projection for it on a real
    branch is measured in hours; the coverage mode runs only the tests that
    execute the gutted body. The engine REFUSES rather than silently falling
    back when the map cannot be built, which is why a target without
    pytest-cov gets a `not_applicable` naming that - and not a number quietly
    read off a different campaign than the one it claims to be.

    An engine that raises produces a `not_applicable` carrying the exception,
    never a crash and never a silent clean: `nominate()` is called from inside
    the runner's try block, so an escape here would convert one unavailable
    group into a whole-target refusal that says nothing about the other
    eighteen.
    """
    if not requested:
        return _execution_not_applicable(gutting.GROUP, _opt_in_reason(gutting.GROUP))

    try:
        sites = gutting.discover_functions(spec.target_copy)
        campaign = gutting.run_campaign(
            _suite_target(spec),
            sites,
            selection=gutting.SELECTION_COVERAGE,
        )
    except Exception as exc:
        logger.warning(f"[AUDIT-TESTS] the gutting campaign could not run: {type(exc).__name__}: {exc}")
        return _execution_not_applicable(
            gutting.GROUP,
            f"the gutting campaign raised {type(exc).__name__}: {exc} - nothing about this "
            f"target's oracles was measured, which is not the same as nothing being wrong",
        )

    return _pseudo_tested_document(campaign)


def _pseudo_tested_document(campaign: gutting.CampaignResult) -> Dict[str, object]:
    """One finished campaign as the artifact publishes it."""
    status, reason, exhausted = _campaign_outcome(campaign)
    document: Dict[str, object] = {
        "tier": EXEC_TIER,
        "kind": EXEC_KIND,
        "status": status,
        "reason": reason,
        "score": None,
    }
    document.update(gutting.summarize(campaign))
    # T-BUDGET, stamped from the campaign rather than inferred by a reader from
    # the `not_run` reasons buried three levels down. An exhausted campaign is
    # `refused` and never `measured`: a partial sweep reported as a whole-tree
    # survivor count is forgery by omission.
    document["budget_exhausted"] = exhausted
    return document


def _campaign_outcome(campaign: gutting.CampaignResult) -> Tuple[str, str, bool]:
    """`(status, reason, budget_exhausted)` for a finished campaign.

    THREE OUTCOMES, THREE DOCUMENTS, and none of them share a shape with
    another. A campaign whose map could not be built measured nothing; a
    campaign that ran out of clock measured part of a tree and may not report
    it as the whole; a campaign that finished measured what it says it did.
    Collapsing any two of those into one status is Law S1 broken from the
    inside of an adapter.
    """
    coverage_map = campaign.coverage_map
    if coverage_map is not None and coverage_map.refusal_reason:
        return (
            STATUS_NOT_APPLICABLE,
            f"the coverage map this campaign selects its tests from could not be built, so no "
            f"mutant was executed: {coverage_map.refusal_reason}",
            False,
        )

    if not campaign.baseline.green:
        return (
            STATUS_NOT_APPLICABLE,
            f"the unmutated suite is not green, so survivorship means nothing and no verdict was "
            f"read: {campaign.baseline.refusal_reason}",
            False,
        )

    unprobed = sum(
        1
        for result in campaign.results
        if result.outcome == gutting.OUTCOME_NOT_RUN and result.reason == gutting.REASON_BUDGET_EXHAUSTED
    )
    if unprobed:
        return (
            STATUS_REFUSED,
            f"the {campaign.budget_seconds}s campaign budget expired with {unprobed} function(s) "
            f"still unprobed, so what was measured is a fragment of this tree and is published as "
            f"one rather than as a survivor count for it (Law T-BUDGET)",
            True,
        )

    return STATUS_MEASURED, "", False


def _statement_deletion_group(spec: envcopy.EnvSpec, requested: bool) -> Dict[str, object]:
    """Run the statement-deletion campaign, or say why it did not.

    Mirrors `_pseudo_tested_group` exactly, including the refusal-to-crash
    contract: a campaign that raises becomes `not_applicable` carrying the
    exception, never a silent empty document and never a zero that reads like
    a measurement.
    """
    if not requested:
        return _execution_not_applicable(statement_deletion.GROUP, _opt_in_reason(statement_deletion.GROUP))

    try:
        discovered = statement_deletion.discover_statements(spec.target_copy)
        sites = discovered if spec.diff_scope is None else diff_scope.apply(discovered, spec.diff_scope)
        campaign = statement_deletion.run_campaign(_suite_target(spec), sites)
    except Exception as e:  # the lane reports a failure to run, it never hides one
        logger.info("statement_deletion campaign raised: %s", e)
        return _execution_not_applicable(
            statement_deletion.GROUP,
            f"the statement-deletion campaign raised {type(e).__name__}: {e}",
        )

    document: Dict[str, object] = {
        "tier": "exec",
        "kind": "measure_only",
        "score": None,
    }
    document.update(statement_deletion.summarize(campaign, sites))
    if spec.diff_scope is not None:
        # The DENOMINATOR changes when the scope does, so the scope travels
        # with the numbers rather than only in the environment block. A
        # reader who sees "53 probeable" must be able to see, in the same
        # document, that the tree held 13,743.
        document["scope"] = spec.diff_scope.to_document()
        document["statements_in_tree"] = len(discovered)
    if campaign.refusal_reason:
        document["status"] = "not_applicable"
        document["reason"] = campaign.refusal_reason
    else:
        document["status"] = "measured"
        document["reason"] = (
            f"{document['statements_executed']} statement deletions run, "
            f"{document['survived_unobserved']} survived with a covering test watching"
        )
    return document


def _width_coupling_group(spec: envcopy.EnvSpec, requested: bool) -> Dict[str, object]:
    """The two-width verdict diff, when it was asked for.

    The engine owns both document shapes already - `group_document()` for a run
    that happened and `not_applicable_document()` for one that did not - so
    this function decides only WHETHER, never WHAT. That is the same seam the
    adapter itself sits on one level up.

    `budget_seconds` is stamped here because the axis publishes its elapsed
    time and not its ceiling, and Law T-BUDGET requires both of any execution
    group that reports `measured`. The ceiling is the ENGINE's own default: the
    lane's `--budget` reaches `run_gated()` and has no channel into
    `nominate()`, and inventing a second number here would make the artifact
    claim a budget nothing enforced.
    """
    if not requested:
        return envdiff.not_applicable_document(_opt_in_reason(envdiff.GROUP))

    try:
        result = envdiff.measure_width_coupling(_axis_target(spec))
    except Exception as exc:
        logger.warning(f"[AUDIT-TESTS] the width axis could not run: {type(exc).__name__}: {exc}")
        return envdiff.not_applicable_document(
            f"the width axis raised {type(exc).__name__}: {exc} - no verdict was compared at "
            f"either width, which is not the same as no test being width-coupled"
        )

    document: Dict[str, object] = dict(envdiff.group_document(result))
    document["budget_seconds"] = envdiff.DEFAULT_BUDGET_SECONDS
    return document


def _unbuilt_reason(group: str) -> str:
    """Why a declared execution group has nothing to report yet."""
    reasons = {
        "scoped_survival": (
            "not built - module gutting is not implemented in this release. When it is, it "
            "measures ORACLE SURVIVAL and is never to be read as pseudo-testedness (contract 2)"
        ),
        "targeted_mutation": (
            "not built - no mutant is executed by this release, so there is no kill to split "
            "and Law S9's kill_cause requirement has nothing to check yet (contract 1)"
        ),
    }
    return reasons.get(group, "not built in this release")


def declared_groups() -> List[str]:
    """The bare group names this adapter contributes. The core namespaces them."""
    return list(ADAPTER_GROUPS)


# =============================================================================
# 7 - TEARDOWN
# =============================================================================


def teardown(spec: Optional[envcopy.EnvSpec]) -> None:
    """Remove the scratch env. Idempotent, and never touches the real target.

    The guard is not defensive coding, it is the M10 boundary: this function
    deletes a directory tree, so it refuses any path that is not the scratch
    env it was handed. A teardown that could be pointed at the real tree is a
    worse defect than anything the lane measures.
    """
    if spec is None:
        return

    root = Path(spec.env_root)
    if not root.exists():
        return
    if root == root.parent or str(root) in ("/", str(Path.home())):
        logger.error(f"[AUDIT-TESTS] refusing to tear down an implausible env root: {root}")
        return

    try:
        shutil.rmtree(root)
    except OSError as exc:
        logger.warning(f"[AUDIT-TESTS] scratch env {root} could not be removed: {exc}")
