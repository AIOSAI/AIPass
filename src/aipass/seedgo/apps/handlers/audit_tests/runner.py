# =================== AIPass ====================
# Name: runner.py
# Description: audit-tests orchestration - the nine-step pipeline
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The pipeline. Nine steps, and step 7 is the one everything else serves.

    1  resolve target        @branch | directory | "aipass"
    2  select adapter        detect() over registered adapters; none -> REFUSE(4)
    3  cache probe           not built; the artifact stamps that it did not run
    4  build env             copy-first (Law M10), siblings COPIED not symlinked
    5  prove the copy live   import the target and read __file__ (harness #3)
    6  run gated             write-gate installed, under a wall-clock budget
    7  canary or refuse      MANDATORY. not caught -> REFUSE, publish nothing
    8  nominate              static species; suspects, never verdicts (Law M1)
    9  assemble -> validate -> write -> render

STEP 7 IS BEFORE STEP 8 DELIBERATELY. A run that cannot prove its own gate can
fire publishes NOTHING — not "the static groups only". A partial publication
from an unproven harness is exactly the confidently-wrong-number shape the
whole lane refuses.

WHAT A REFUSAL STILL DOES: publishes a complete artifact with every group
`not_applicable` and a reason. An empty file, or no file, is indistinguishable
from a run that never happened, and the entire point of the refusal vocabulary
is that those two are different things.
"""

import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.audit.discovery import discover_branches
from aipass.seedgo.apps.handlers.audit_tests import adapters, artifact, laws, refusal, spine, target as target_module
from aipass.seedgo.apps.handlers.audit_tests import cache, m10, selfcheck
from aipass.seedgo.apps.handlers.json import json_handler

#: Default wall-clock budget for one target's suite (Law T-BUDGET).
DEFAULT_BUDGET_SECONDS = 900

#: Prefix for the scratch env, so a stray directory is identifiable at a glance.
SCRATCH_PREFIX = "audit_tests_"

#: The cache lane is not built. S5 requires the artifact to say what it cannot
#: see rather than leave a reader to assume a check ran and passed.
NO_CACHE_BLOCK = {
    "served_from_cache": False,
    "stamp": "",
    "not_fingerprinted": ["the cache lane is not built in this release; every run is a full measurement"],
}


class RunResult:
    """One target's outcome: the document, where it went, and the exit code."""

    def __init__(self, target: target_module.Target, document: dict, path: Optional[Path], code: int) -> None:
        """Bind a target to what the run produced for it."""
        self.target = target
        self.document = document
        self.path = path
        self.code = code

    @property
    def refused(self) -> bool:
        """True when this run declined to publish a measurement.

        Read from the exit-code vocabulary rather than from the document, so
        one definition of "refused" governs the summary line, the fleet code
        and the artifact together.
        """
        return refusal.is_refusal(self.code)

    def summary_line(self) -> str:
        """One line per target, printed whether or not the fleet code hides it."""
        if self.refused:
            block = self.document.get("refusal") or {}
            line = refusal.Refusal(
                code=int(block.get("code", refusal.EXIT_UNPROVEN)),
                reason=str(block.get("reason", "")),
            ).stdout_line()
            return f"{line}  ({self.target.name})"

        hygiene = self.document.get("groups", {}).get("hygiene", {})
        score = hygiene.get("score")
        count = hygiene.get("violation_count", 0)
        return f"{self.target.name}: hygiene {score} ({count} violation(s)) -> {self.path}"


# =============================================================================
# TARGET RESOLUTION
# =============================================================================


def branch_paths() -> Dict[str, Path]:
    """Registered branch name -> path.

    `target.resolve()` takes this as an argument rather than importing the
    registry itself, which is what keeps it testable without one.
    """
    return {entry["name"]: Path(entry["path"]) for entry in discover_branches()}


def resolve_targets(argument: str) -> List[target_module.Target]:
    """One argument to one or more targets. `aipass` means every citizen."""
    paths = branch_paths()

    if argument == "aipass":
        return [
            target_module.Target(
                name=name,
                path=path,
                kind="branch",
                resolved_from="registry (fleet form)",
            )
            for name, path in sorted(paths.items())
        ]

    return [target_module.resolve(argument, paths)]


# =============================================================================
# THE REFUSAL PATH
# =============================================================================


def refuse(
    target: target_module.Target,
    refused: refusal.Refusal,
    *,
    ecosystem: str = "unknown",
    adapter_name: str = "none",
    group_list: Optional[List[str]] = None,
    retired_groups: Optional[List[dict]] = None,
) -> RunResult:
    """Publish a complete refused artifact and return its result.

    Publication is attempted, not assumed. If the refused artifact is itself
    unlawful the LawViolation propagates rather than being swallowed — an
    enforcer that quietly writes an unlawful document has stopped being one.
    """
    previous = artifact.load_previous(target)
    document = artifact.refused_artifact(
        target,
        refused,
        ecosystem=ecosystem,
        adapter=adapter_name,
        adapter_api=adapters.SUPPORTED_ADAPTER_API,
        group_list=group_list,
        previous=previous,
        retired_groups=retired_groups,
    )
    document["cache"] = dict(NO_CACHE_BLOCK)

    json_handler.log_operation(
        "lane_refused",
        {"target": target.name, "code": refused.code, "law": refused.law, "reason": refused.reason},
    )
    path = artifact.publish(document, target, previous)
    return RunResult(target, document, path, refused.code)


# =============================================================================
# ONE TARGET
# =============================================================================


def run_target(target: target_module.Target, options: Optional[dict] = None) -> RunResult:
    """Run the full pipeline for one target. Never raises past its own edge.

    Every failure mode inside becomes a REFUSAL with a law and a reason, which
    is the difference between a lane that reports it could not measure and a
    lane that looks like it measured nothing.
    """
    options = dict(options or {})
    budget = int(options.get("budget_seconds") or DEFAULT_BUDGET_SECONDS)

    registered, rejections = adapters.discover_adapters()
    for rejection in rejections:
        logger.warning(f"[AUDIT-TESTS] adapter pack rejected: {rejection}")

    adapter, detections = adapters.claim_target(registered, target.path)
    if adapter is None:
        return refuse(
            target,
            refusal.Refusal(
                code=refusal.EXIT_NO_ADAPTER,
                reason="no registered adapter claims this target",
                detail=[f"{name}: {info.get('reason', 'no reason given')}" for name, info in sorted(detections.items())]
                + [f"pack rejected - {r}" for r in rejections],
            ),
        )

    ecosystem = str(getattr(adapter, "ECOSYSTEM", "unknown"))
    group_list = spine.compose_group_list(ecosystem, adapter.declared_groups())
    detection = detections.get(ecosystem, {})
    target.unit_count = int(detection.get("unit_count", 0))
    target.layout = target_module.describe_layout(target)

    if not target.unit_count:
        return refuse(
            target,
            refusal.Refusal(
                code=refusal.EXIT_NO_UNITS,
                reason="the target holds no runnable test units",
                detail=[str(detection.get("reason", "the adapter reported no units"))],
            ),
            ecosystem=ecosystem,
            adapter_name=ecosystem,
            group_list=group_list,
        )

    return _measure(target, adapter, ecosystem, group_list, budget, options)


def _measure(
    target: target_module.Target,
    adapter,
    ecosystem: str,
    group_list: List[str],
    budget: int,
    options: dict,
) -> RunResult:
    """Steps 4-9 for a target an adapter has claimed.

    The real tree is FINGERPRINTED before and after. Law M10 is the lane's
    central promise, and a promise this instrument merely asserted would be the
    same species it exists to catch: a claim nothing could ever falsify. So it
    is measured, on every run, and the result is published whether it is good
    news or not.

    THE CARRIER WINDOW OPENS FIRST, before the before-fingerprint, so that
    every write THIS process makes into the real tree during the comparison
    window is on record. Otherwise the audit's own logger appears in its own
    diff as an unexplained change.
    """
    started = datetime.now(timezone.utc)
    clock = time.monotonic()
    spec = None
    m10.start_carrier_recording(target.path)
    before = _fingerprint_target(target, options)
    _probe_live_writers(target, options)

    try:
        with tempfile.TemporaryDirectory(prefix=SCRATCH_PREFIX) as scratch:
            spec = adapter.build_env(target.path, Path(scratch) / "env", options)
            liveness = adapter.assert_env_is_live(spec)
            run = adapter.run_gated(spec, budget, options)
            nominations = adapter.nominate(spec)
            return _publish(
                target,
                adapter,
                ecosystem,
                group_list,
                spec,
                liveness,
                run,
                nominations,
                started,
                time.monotonic() - clock,
                m10_proof=_m10_proof(target, before, options, run),
            )
    except Exception as exc:
        # A crash mid-measurement is a refusal, never a zero. The lane knows
        # nothing about this target's hygiene and says exactly that.
        logger.error(f"[AUDIT-TESTS] measurement of {target.name} failed: {type(exc).__name__}: {exc}")
        return refuse(
            target,
            refusal.Refusal(
                code=refusal.EXIT_UNPROVEN,
                reason="the measurement could not complete, so nothing about this target is known",
                detail=[f"{type(exc).__name__}: {exc}"],
            ),
            ecosystem=ecosystem,
            adapter_name=ecosystem,
            group_list=group_list,
        )
    finally:
        # The window closes on every path out, including the crash one. A
        # recorder left open would keep attributing the next target's writes
        # to this run's roots.
        m10.stop_carrier_recording()
        if spec is not None:
            adapter.teardown(spec)


def _publish(
    target: target_module.Target,
    adapter,
    ecosystem: str,
    group_list: List[str],
    spec,
    liveness: dict,
    run: dict,
    nominations: dict,
    started: datetime,
    elapsed: float,
    m10_proof: Optional[dict] = None,
) -> RunResult:
    """Steps 7-9: canary or refuse, then assemble, validate, write."""
    gate = dict(run.get("gate") or {})

    # STEP 7, and it is before step 8 deliberately. A run that cannot prove its
    # own gate can fire publishes NOTHING - not "the static groups only". A
    # partial publication from an unproven harness is the confidently-wrong
    # -number shape the whole lane exists to refuse.
    if not gate.get("proven"):
        return refuse(
            target,
            _unproven_refusal(gate, run, elapsed),
            ecosystem=ecosystem,
            adapter_name=ecosystem,
            group_list=group_list,
        )

    environment = spec.to_document()
    config_note = str(run.get("config_note", target.config_note))
    hygiene = _hygiene_group(
        gate,
        budget_seconds=int(run.get("budget_seconds", DEFAULT_BUDGET_SECONDS)),
        elapsed_seconds=float(run.get("elapsed_seconds", elapsed)),
        config_note=config_note,
        environment=environment,
        liveness=liveness,
    )

    groups = _compose_groups(group_list, ecosystem, hygiene, nominations)
    previous = artifact.load_previous(target)
    document = artifact.assemble(
        target,
        groups,
        group_list,
        ecosystem=ecosystem,
        adapter=f"tests_{ecosystem}_standards",
        adapter_api=int(getattr(adapter, "ADAPTER_API", adapters.SUPPORTED_ADAPTER_API)),
        run_id=uuid.uuid4().hex[:12],
        started=started,
        elapsed=elapsed,
        cache=cache.cache_block(_pack_dir(adapter), environment.get("copied_siblings", [])),
        previous=previous,
        retired_groups=_retirements(adapter, ecosystem),
        executed_order=list(run.get("executed_order") or []),
    )
    document["m10_proof"] = m10_proof or _m10_not_probed("the proof was not requested for this run")
    document["harness"] = selfcheck.harness_block(
        document=document,
        hygiene=hygiene,
        run=run,
        environment=environment,
        liveness=liveness,
        m10_proof=document["m10_proof"],
        config_note=config_note,
    )

    path = artifact.publish(document, target, previous)
    return RunResult(target, document, path, artifact.exit_code_for(document))


def _pack_dir(adapter) -> Optional[Path]:
    """The adapter pack's directory, for the cache stamp, or None."""
    payload = getattr(adapter, "PAYLOAD_DIR", None)
    return Path(payload).parent if payload else None


def _retirements(adapter, ecosystem: str) -> List[dict]:
    """The adapter's recorded group retirements, namespaced and validated.

    Law S3 lets a group vanish ONLY by a ruling, and the ruling is published
    in the artifact rather than left in a commit message. An entry with no
    ruling text is dropped here rather than passed on, so that S3's own
    validator refuses the artifact instead of accepting a retirement nobody
    signed - the check that catches an adapter retiring a group by writing an
    empty string.
    """
    entries: List[dict] = []

    for entry in getattr(adapter, "RETIRED_GROUPS", ()) or ():
        group = str(entry.get("group", ""))
        ruling = str(entry.get("ruling", ""))
        if not group or not ruling:
            logger.warning(f"[AUDIT-TESTS] adapter '{ecosystem}' declared a retirement with no group or ruling")
            continue
        entries.append({"group": group, "ruling": ruling, "date": str(entry.get("date", ""))})

    return entries


def _unproven_refusal(gate: dict, run: dict, elapsed: float) -> refusal.Refusal:
    """The refusal for a gate that was never proven able to fire.

    THE PRE-BUILT BUILDERS ARE USED ONLY WHERE THEIR WORDING IS TRUE. A budget
    expiry gets the T-BUDGET refusal and a missed canary gets the canary one;
    everything else carries the measurement's OWN reason. Reaching for the
    canary builder on every unproven run would restate a specific cause the
    run never established — the same invented-diagnosis defect the gate log's
    reason branch already had to be corrected for.
    """
    if run.get("timed_out"):
        return refusal.refusal_for_budget(elapsed, int(run.get("budget_seconds", DEFAULT_BUDGET_SECONDS)), "hygiene")

    canary = gate.get("canary") or {}
    detail = [f"canary: {canary}", f"stdout tail: {str(run.get('stdout_tail', ''))[-400:]}"]

    # The hook check comes FIRST and the ordering is the point. With the gate
    # switched off the canary is still WRITTEN and still not caught, so
    # `attempted and not caught` is true — and reaching for the canary refusal
    # there reports a blind gate when the measured fact is that no gate was
    # installed. `refusal_for_canary` says so in its own words ("the gate was
    # installed but did not fire"), which is exactly why it may not be used
    # here. Caught by running canary point C, after an audit cleanup put these
    # two branches in the wrong order.
    if gate.get("hook_installed") and canary.get("attempted") and not canary.get("caught"):
        return refusal.refusal_for_canary(detail)

    return refusal.Refusal(
        code=refusal.EXIT_UNPROVEN,
        reason=str(gate.get("unproven_reason") or "the gate was never proven able to fire"),
        detail=detail,
    )


def _fingerprint_target(target: target_module.Target, options: dict) -> Optional[Dict[str, tuple]]:
    """The real tree's fingerprint before anything runs, or None if skipped."""
    if options.get("no_m10_proof"):
        return None
    try:
        return m10.snapshot_tree(target.path)
    except OSError as exc:
        logger.warning(f"[AUDIT-TESTS] could not fingerprint {target.path} for the M10 proof: {exc}")
        return None


def _probe_live_writers(target: target_module.Target, options: dict) -> None:
    """Record which of the target's own paths move with no suite running.

    Two back-to-back snapshots, taken before the copy exists. Whatever changes
    between them belongs to something that is not this run - a live citizen's
    daemon, server or logger - and the M10 proof subtracts that set so its
    headline names writes nothing else was seen making.
    """
    if options.get("no_m10_proof"):
        return
    options["live_writer_probe_seconds"] = None
    started = time.perf_counter()
    try:
        options["live_writers"] = m10.live_writers(target.path)
        options["live_writers_probed"] = True
        # PUBLISHED, not just measured. A bare `probed: true` reads as "probed
        # ADEQUATELY", and this window is milliseconds against a run of tens of
        # seconds - so a service writing once a minute is missed and its paths
        # surface as unattributed. @trigger hit exactly that (a systemd user
        # unit, six files) and only found it by identifying the paths by hand.
        # The reader cannot make the comparison unless BOTH numbers are here.
        options["live_writer_probe_seconds"] = round(time.perf_counter() - started, 4)
    except OSError as exc:
        # Recorded, never assumed empty: an unmeasured live-writer set makes
        # every concurrent write read as an M10 violation, which is the safe
        # direction but must not look like a clean probe. The window stays
        # None rather than becoming the elapsed-until-failure, which would
        # read as a window that measured something.
        logger.warning(f"[AUDIT-TESTS] live-writer probe of {target.path} failed: {exc}")
        options["live_writers_probed"] = False


def _m10_proof(
    target: target_module.Target,
    before: Optional[Dict[str, tuple]],
    options: dict,
    run: Optional[dict] = None,
) -> dict:
    """Whether the real tree survived the run untouched, measured both ends.

    A `not_probed` result is published in full rather than omitted. A missing
    proof block and a passing one must never look the same, which is the whole
    argument of Law S1 applied to the lane's own harness.

    THE VERDICT IS JUDGED OVER NON-CARRIER PATHS. The audit's own machinery
    writes into a live branch while it measures it, and the diff is partitioned
    on PROVENANCE - what this process was recorded writing - never on what a
    path looks like. `diff_snapshots` is asked NOT to record here because the
    partition records instead: the alarm belongs to the changes nothing can
    account for, and an ERROR that fires on the audit's own logs teaches
    everyone to ignore Law M10.
    """
    if before is None:
        return _m10_not_probed("the before-fingerprint could not be taken, so no comparison is possible")

    try:
        after = m10.snapshot_tree(target.path)
    except OSError as exc:
        # Never swallowed: without the second fingerprint the M10 claim cannot
        # be made at all, and a proof that quietly stopped running is worse
        # than one that never existed.
        logger.warning(f"[AUDIT-TESTS] after-fingerprint of {target.path} failed, M10 unproven: {exc}")
        return _m10_not_probed(f"the after-fingerprint could not be taken: {exc}")

    recorded = _paths_the_gate_recorded(run)
    writes, swallowed = m10.stop_carrier_recording()
    partition = m10.carrier_partition(m10.diff_snapshots(before, after, record=False), writes, swallowed, recorded)

    diff = partition["diff"]
    intact = not any(diff.values())
    changed = _changed(diff)
    concurrent = _changed(options.get("live_writers") or {})

    # THE SUITE WROTE IT, in this instrument's own words. The strongest of the
    # three signals: the hygiene gate watches the suite in-process and names
    # every path it opens for writing, so a real-tree path in that record was
    # written BY the measurement. This is the finding check 12 exists for, and
    # it is read from the FULL diff: a path the carrier also wrote is never
    # subtracted out of this list, because the suite's record convicts.
    by_the_suite = sorted(_changed(partition["diff_before_carrier_subtraction"]) & recorded)

    return {
        "probed": True,
        "real_tree_unchanged": intact,
        "changed_by_the_measured_suite": by_the_suite,
        "unattributed_changes": sorted(changed - recorded - concurrent),
        "attributed_to_concurrent_writers": sorted((changed & concurrent) - recorded),
        "live_writers_probed": bool(options.get("live_writers_probed")),
        "live_writer_probe_seconds": options.get("live_writer_probe_seconds"),
        "gate_recorded_paths": len(recorded),
        "files_fingerprinted": len(before),
        "diff": diff,
        "diff_before_carrier_subtraction": partition["diff_before_carrier_subtraction"],
        "carrier_writes": partition["carrier_writes"],
        "attribution": partition["attribution"],
        "how": "content hash plus stat fields, before the copy and after teardown",
        "note": (
            "st_ctime alone does NOT catch a same-tick forge-then-restore - measured, "
            "so content is hashed rather than inferred. A target that is a LIVE citizen "
            "writes its own logs during the measurement window, so the paths that moved "
            "with no suite running are measured separately and subtracted here - never "
            "exempted by path, because logs/operations.jsonl is precisely what this "
            "campaign convicted a branch for forging. The subtraction under-detects on "
            "purpose: a service that writes rarely will not appear in the probe window "
            "and its path is reported as unattributed."
        ),
    }


def _changed(diff: dict) -> set:
    """Every path named anywhere in an M10 diff."""
    return {path for paths in diff.values() for path in paths}


def _paths_the_gate_recorded(run: Optional[dict]) -> set:
    """Every path the hygiene gate saw the suite write.

    The gate is per-interpreter, so this record is complete only to the extent
    `gate_coverage` says it is - child processes and file-backed sqlite3
    handles write where it cannot follow, and both are counted there. That is
    why a path's ABSENCE from this set proves nothing on its own, and why the
    M10 verdict treats "absent" as undetermined rather than as innocent.
    """
    if not run:
        return set()
    return {str(record.get("path")) for record in (run.get("violations") or []) if record.get("path")}


def _m10_not_probed(reason: str) -> dict:
    """The M10 block for a run that could not prove anything.

    The carrier block is built by the same partition the measured path uses,
    on an empty diff, so an unprobed proof and a probed one cannot drift into
    two different shapes - the second reader of this document would have no way
    to tell a missing field from a subtraction nobody published.
    """
    empty = m10.carrier_partition({})
    return {
        "probed": False,
        "real_tree_unchanged": None,
        "changed_by_the_measured_suite": [],
        "unattributed_changes": [],
        "attributed_to_concurrent_writers": [],
        "live_writers_probed": False,
        "live_writer_probe_seconds": None,
        "gate_recorded_paths": 0,
        "files_fingerprinted": 0,
        "diff": {},
        "diff_before_carrier_subtraction": empty["diff_before_carrier_subtraction"],
        "carrier_writes": empty["carrier_writes"],
        "attribution": empty["attribution"],
        "how": "not probed",
        "note": reason,
    }


def _compose_groups(group_list: List[str], ecosystem: str, hygiene: dict, nominations: dict) -> Dict[str, dict]:
    """Every published group, in `group_list` order. Law S4 is order-sensitive.

    A spine group no adapter implements stays in the list and reports
    `not_applicable` with a reason. It never disappears and it is never 0.
    """
    groups: Dict[str, dict] = {}

    for name in group_list:
        if name == "hygiene":
            groups[name] = hygiene
        elif name in spine.CORE_SPINE:
            groups[name] = spine.spine_document(name)
        else:
            bare = name.split(".", 1)[-1]
            document = nominations.get(bare)
            groups[name] = document if document else _unclaimed_group(name, ecosystem)

    return groups


def _unclaimed_group(name: str, ecosystem: str) -> dict:
    """A declared adapter group the adapter returned nothing for.

    Law S1 again: the group stays, states it did not run, and says who was
    supposed to fill it. A group that vanished because an adapter forgot it is
    exactly what S3 exists to catch.
    """
    return {
        "tier": "static",
        "kind": "nominate_only",
        "status": "not_applicable",
        "reason": f"the {ecosystem} adapter declared '{name}' but returned no document for it",
        "score": None,
    }


def _hygiene_group(
    gate: dict,
    *,
    budget_seconds: int,
    elapsed_seconds: float,
    config_note: str,
    environment: dict,
    liveness: dict,
) -> dict:
    """The scored group, built from a proven gate's normalized measurement.

    THE SCORE IS A GATE, NOT AN OPINION (design section 4.5): 100 or 0, never a
    percentage. "Your suite forged 31 log entries instead of 79" is not a
    better suite, it is the same defect at a different volume — and a partial
    credit would let a branch improve its number without fixing anything.

    Only reached when the gate is proven. An unproven gate never gets here,
    which is what keeps "no violations seen" and "nothing was watching" from
    ever producing the same document.
    """
    violations = list(gate.get("violations") or [])
    document = dict(gate)
    document.pop("proven", None)
    document.pop("unproven_reason", None)

    document.update(
        {
            "tier": "exec",
            "kind": "gate",
            "status": "measured",
            "score": 100 if not violations else 0,
            "passed": not violations,
            "budget_seconds": budget_seconds,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "budget_exhausted": False,
            "gate_proven": True,
            "config_note": config_note,
            "environment": environment,
            "liveness": liveness,
        }
    )
    return document


# =============================================================================
# THE FLEET FORM
# =============================================================================


def run(argument: str, options: Optional[dict] = None) -> Tuple[List[RunResult], int]:
    """Run every target the argument names. Returns `(results, worst_code)`.

    The fleet code is the WORST per-target code and a per-target summary line
    is available for every target regardless, so the single number is never
    the only signal a caller has.
    """
    results: List[RunResult] = []

    for target in resolve_targets(argument):
        try:
            results.append(run_target(target, options))
        except laws.LawViolation as exc:
            # The lane refused to publish its own artifact. Loud, and never
            # converted into a score.
            logger.error(f"[AUDIT-TESTS] artifact for {target.name} was unlawful and not written: {exc}")
            results.append(RunResult(target, {"status": "refused"}, None, refusal.EXIT_UNPROVEN))

    return results, refusal.worst_code([result.code for result in results])
