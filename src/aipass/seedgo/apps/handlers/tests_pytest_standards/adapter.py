# =================== AIPass ====================
# Name: adapter.py
# Description: the pytest execution adapter - the 8-function contract
# Version: 1.2.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""The pytest adapter. Eight functions, two constants, and nothing else.

There is deliberately no `check_module` or `check_branch`: `discover_checkers()`
keeps only modules defining one, so this pack stays invisible to the audit's
file-walk engine. An adapter returns measurements and never scores, decides
status, writes the artifact or renders; the core applies the laws. `payload/`
runs inside the foreign copy and is stdlib-only (Law M10).
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

#: Published namespaced (`pytest.<name>`). Also self-discovered from `<name>_check.py`;
#: a test pins the two together so a new nominator cannot silently change the list (Law S3).
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

#: Built engines that run only when asked for by name: opt-in is about wall-clock
#: cost, never confidence. Names come from the engines so they cannot drift (Law S3).
OPT_IN_EXECUTION_GROUPS: tuple = (
    gutting.GROUP,
    envdiff.GROUP,
    statement_deletion.GROUP,
)

#: Declared but not built; published `not_applicable` with a reason so their
#: contracts land before the capability does.
UNBUILT_EXECUTION_GROUPS: tuple = (
    "scoped_survival",
    "targeted_mutation",
)

#: Published order: reordering shows as a reshuffle in every artifact diff.
ADAPTER_GROUPS: tuple = STATIC_GROUPS + OPT_IN_EXECUTION_GROUPS + UNBUILT_EXECUTION_GROUPS

#: Law S3: a group may only vanish by a recorded ruling, and the ruling travels
#: in the artifact.
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

TEST_DIR_NAMES: tuple = ("tests", "test")

#: Default wall-clock budget for one suite (Law T-BUDGET).
DEFAULT_BUDGET_SECONDS = 900

#: Named once so the verb, the spec and this module agree on the spelling.
OPTION_EXECUTION_GROUPS = "execution_groups"

#: Execution groups are `measure_only`: scoring is the core's job, so `score` is always None here.
EXEC_TIER = "exec"
EXEC_KIND = "measure_only"
STATUS_MEASURED = "measured"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_REFUSED = "refused"

#: Quoted in each opt-in group's reason, so `not_applicable` says how to ask for it.
OPT_IN_FLAGS: Dict[str, str] = {
    gutting.GROUP: "--pseudo-tested",
    envdiff.GROUP: "--width-coupling",
    statement_deletion.GROUP: "--statement-deletion",
}


def detect(target: Path) -> dict:
    """Does this adapter claim the target? Cheap, read-only, never raises.

    Never imports or executes the target: that would violate M10 before the copy exists.
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


def build_env(target: Path, workdir: Path, options: dict) -> envcopy.EnvSpec:
    """Copy-first (Law M10). Returns the spec naming everything that was made.

    `symlink_siblings` is off by default: a write through a symlinked sibling lands in
    the real tree. The fast mode stamps `m10_complete: false`.
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
        campaign_budget_seconds=options.get("budget_seconds"),
    )


def assert_env_is_live(spec: envcopy.EnvSpec) -> dict:
    """Harness check 3 — prove the COPY is what actually loads."""
    verified, detail = envcopy.assert_copy_is_live(spec)
    return {
        "live": verified,
        "resolved_to": detail,
        "how": "imported the target module in a child interpreter and read its __file__",
    }


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
        # Canary point C: gate deliberately off; must end in a refusal and publish no group.
        environment["AUDIT_TESTS_DISABLE_HOOK"] = "1"
    return environment


def run_gated(spec: envcopy.EnvSpec, budget_seconds: int, options: dict) -> dict:
    """Run the units with the write-gate installed, under a wall-clock budget.

    On expiry: `timed_out=True` and no measurement (a partial suite is forgery by omission).
    `-p no:cacheprovider` and `-B` keep stale bytecode from measuring code that is gone.
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
    """The gate log, or an empty list when the plugin never wrote one."""
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


def fire_canary(spec: envcopy.EnvSpec) -> dict:
    """The canary result from the run that just happened.

    The payload fires the canary inside the gated session; a parent-side canary would
    test a hook the suite never ran under.
    """
    try:
        records = gatelog.read_records(spec.log_path)
    except gatelog.GateLogError as exc:
        # Not swallowed: an unreadable log leaves the gate unproven; the reason travels in `error`.
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


def nominate(spec: envcopy.EnvSpec) -> dict:
    """Every group this adapter publishes, static and execution alike.

    The corpus is the copy, never the real tree, so every group measures the same program.
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


def _opt_in_reason(group: str) -> str:
    """Why a BUILT execution group did not run on a run that never asked for it.

    Not the "not built" sentence: it names the cost and the exact flag that buys the run.
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

    Counts are absent, not zeroed (Law S1); the empty `mutants` list stays because Law S9 iterates it.
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


def _campaign_budget(spec: envcopy.EnvSpec) -> int:
    """The wall-clock ceiling a mutation campaign runs under: the operator's `--budget`, else 1800 s."""
    return int(spec.campaign_budget_seconds or gutting.DEFAULT_BUDGET_SECONDS)


def _pseudo_tested_group(spec: envcopy.EnvSpec, requested: bool) -> Dict[str, object]:
    """The per-function extreme-mutation campaign, when it was asked for.

    Opts into coverage selection; the engine refuses rather than falling back when the
    map cannot be built. An engine that raises becomes `not_applicable`: an escape here
    would turn one group into a whole-target refusal.
    """
    if not requested:
        return _execution_not_applicable(gutting.GROUP, _opt_in_reason(gutting.GROUP))

    try:
        sites = gutting.discover_functions(spec.target_copy)
        campaign = gutting.run_campaign(
            _suite_target(spec),
            sites,
            selection=gutting.SELECTION_COVERAGE,
            budget_seconds=_campaign_budget(spec),
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
    # T-BUDGET: an exhausted campaign is `refused`, never `measured` (a partial sweep is not a whole tree).
    document["budget_exhausted"] = exhausted
    return document


def _campaign_outcome(campaign: gutting.CampaignResult) -> Tuple[str, str, bool]:
    """`(status, reason, budget_exhausted)` for a finished campaign.

    Unbuildable map, exhausted clock and finished run are three statuses; collapsing two breaks Law S1.
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
    """Run the statement-deletion campaign, or say why it did not."""
    if not requested:
        return _execution_not_applicable(statement_deletion.GROUP, _opt_in_reason(statement_deletion.GROUP))

    try:
        discovered = statement_deletion.discover_statements(spec.target_copy)
        sites = discovered if spec.diff_scope is None else diff_scope.apply(discovered, spec.diff_scope)
        campaign = statement_deletion.run_campaign(_suite_target(spec), sites, budget_seconds=_campaign_budget(spec))
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
        # The scope changes the denominator, so it travels with the numbers.
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

    The engine owns both document shapes; this decides only whether. `budget_seconds` is
    the engine's own default: the lane's `--budget` has no channel into `nominate()`.
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


def teardown(spec: Optional[envcopy.EnvSpec]) -> None:
    """Remove the scratch env. Idempotent, and never touches the real target.

    Deletes a tree, so it refuses any path that is not the env it was handed (M10).
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
