# =================== AIPass ====================
# Name: adapter.py
# Description: the pytest execution adapter - the 8-function contract
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
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
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.tests_pytest_standards import envcopy, gatelog, nominators
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
    "static_entry_point_diff",
    "static_mock_drift",
    "static_no_oracle",
    "static_ruff_pt",
    "static_self_skip",
    "static_unentered_assert",
)

#: The execution groups this adapter declares but does not yet run. They are
#: published `not_applicable` with a reason from day one, because the rev-4
#: contracts binding them (kill_cause, the survival naming rule) have to land
#: before the capability or they never land at all.
UNBUILT_EXECUTION_GROUPS: tuple = (
    "scoped_survival",
    "targeted_mutation",
)

ADAPTER_GROUPS: tuple = STATIC_GROUPS + UNBUILT_EXECUTION_GROUPS

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
    """
    return envcopy.build_env(
        Path(target),
        Path(workdir),
        PLUGIN_FILE,
        python_override=options.get("python"),
        symlink_siblings=bool(options.get("symlink_siblings")),
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
    """Static species. Nominate-only, never scored, ever (Law M1).

    THE CORPUS IS THE COPY, NEVER THE REAL TREE. The nominators only read, so
    pointing them at the real target would break nothing visible - and that is
    precisely why it is worth stating: the static tier would then be the one
    part of the lane measuring a different program from the rest of it, and a
    rule reading one tree while the gate reads another produces two numbers
    nobody can reconcile.

    A group whose nominator could not run reports `not_applicable` with the
    reason rather than an empty `measured`. Ruff's absence is the live case.
    """
    documents = nominators.run(spec.target_copy)

    for name in UNBUILT_EXECUTION_GROUPS:
        documents[name] = gatelog.nomination_group(_unbuilt_reason(name))

    for name in ADAPTER_GROUPS:
        if name not in documents:
            documents[name] = gatelog.nomination_group(
                f"declared in ADAPTER_GROUPS but no nominator claimed '{name}' - the group is "
                f"published empty rather than dropped, because a group that vanished is what "
                f"Law S3 exists to catch"
            )

    return documents


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
