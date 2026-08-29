# =================== AIPass ====================
# Name: runner.py - the audit-tests lane, end to end
# Description: copy, pre-flight, gated run, static nominators, artifact
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Orchestrate one ``audit-tests`` run.

Order is the design, not a convenience:

1. **Refuse early.** No pytest targets, no run (:mod:`.discover`).
2. **Copy first**, before anything executes (Law M10).
3. **Prove the copy is the thing being measured** before the first probe --
   harness-integrity check #3.  The editable install will otherwise resolve
   ``aipass.*`` back to the real repo and every number describes the wrong tree.
4. **Run the suite gated**, single-branch, branch rootdir, the way its own agent
   runs it (``wave2_verification.md`` §4a).
5. **Check the canary.** If the gate did not catch its own deliberate escape, the
   whole run refuses (Law T10).  A zero from a gate that cannot fire and a zero
   from a clean suite look identical, and only this tells them apart.
6. **Nominate statically** over the copy -- suspects only (Law M1).
7. **Publish**, or refuse, with the harness's verdict on itself attached.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from . import artifact, discover, envcopy, hygiene, static_mock, static_ruff, static_skip
from .astutil import SubjectIndex
from .modmap import build_module_map
from .render import render

PLUGIN_MODULE = "audit_hygiene_plugin"
TREE_SAMPLE = 25


@dataclass
class Options:
    """Everything the CLI can vary, with the defaults a real run uses."""

    target: Path
    out: Path | None = None
    keep_copy: bool = False
    env_root: Path | None = None
    python: str | None = None
    ruff: str | None = None
    timeout: int = 900
    tmpdir_allowed: bool = True
    disable_hook: bool = False
    baseline_passed: int | None = None
    skip_static: bool = False
    copy_siblings: bool = False


def _tree_report(before: dict, after: dict) -> dict:
    """What the real tree looked like before and after -- the M10 proof."""
    diff = envcopy.diff_snapshots(before, after)
    changed = diff["added"] + diff["removed"] + diff["modified"]
    return {
        "unchanged": not changed,
        "added": diff["added"][:TREE_SAMPLE],
        "removed": diff["removed"][:TREE_SAMPLE],
        "modified": diff["modified"][:TREE_SAMPLE],
        "changed_total": len(changed),
        "caveat": (
            "the real tree is shared with live agents; a change here is evidence to read, not proof this run caused it"
        ),
    }


def _escape_analysis(run: hygiene.HygieneRun, spec: envcopy.EnvSpec) -> dict:
    """Which violations actually landed outside the scratch env, and where.

    A symlinked sibling is a hole in Law M10, so the artifact names it rather
    than leaving a reader to infer it from paths. ``--copy-siblings`` closes it.
    """
    root = str(spec.env_root)
    reached: dict[str, int] = {}
    for item in run.violations:
        path = item.get("path", "")
        if path.startswith(root + "/"):
            continue
        parent = str(Path(path).parent)
        reached[parent] = reached.get(parent, 0) + 1
    by_where: dict[str, int] = {}
    for item in run.violations:
        by_where[item.get("where", "?")] = by_where.get(item.get("where", "?"), 0) + 1
    return {
        "violations_by_location": by_where,
        "directories_written_outside_the_scratch_env": dict(sorted(reached.items())[:TREE_SAMPLE]),
        "note": (
            "with symlinked siblings a suite can still write into the real repo through them; "
            "--copy-siblings copies every sibling instead and closes that hole"
        ),
    }


def _hygiene_group(run: hygiene.HygieneRun) -> dict:
    """Assemble the one scored group from the gate's log."""
    violations = run.violations
    summary = run.summary
    return {
        "status": "measured",
        "kind": "gate",
        "score": 100 if not violations else 0,
        "passed": not violations,
        "rule": "a test may write only inside the declared sandbox",
        "violation_count": len(violations),
        "convicted_nodeids": sorted({v["nodeid"] for v in violations}),
        "violations": violations,
        "tmpdir_writes": summary.get("tmpdir_writes", 0),
        "tmpdir_samples": summary.get("tmpdir_samples", []),
        "relative_unattributable": summary.get("relative_unattributable", 0),
        "dropped_over_cap": summary.get("dropped_over_cap", 0),
    }


def _refusal(run: hygiene.HygieneRun, copy_live: bool | None, copy_detail: str) -> dict | None:
    """The two conditions that forbid publishing, and why each one is fatal."""
    summary = run.summary
    if not summary:
        return {
            "reason": "the hygiene gate produced no summary record - the run did not complete",
            "detail": [f"pytest exit {run.returncode}", "timed out" if run.timed_out else "", run.stdout_tail],
        }
    canary = summary.get("canary") or {}
    if not canary.get("caught"):
        return {
            "reason": "canary not caught: the gate cannot prove it can fire (Law T10)",
            "detail": [
                f"hook_installed={summary.get('hook_installed')}",
                f"canary={canary}",
                "a zero from a gate that is switched off is indistinguishable from a clean suite",
            ],
        }
    if copy_live is False:
        return {
            "reason": "the suite did not resolve to the copy (Law M10, harness check #3)",
            "detail": [f"target module resolved to {copy_detail}"],
        }
    return None


def execute(options: Options) -> tuple[dict, str]:
    """Run the lane; return ``(artifact_document, terminal_text)``."""
    started = time.time()
    target = options.target.resolve()
    real_test_files = discover.require_tests(target)

    env_root = options.env_root or Path(tempfile.mkdtemp(prefix="audit_tests_env_"))
    plugin_source = Path(__file__).resolve().parent.parent / "plugin" / f"{PLUGIN_MODULE}.py"

    before = envcopy.snapshot_tree(target)
    spec = envcopy.build_env(target, env_root, plugin_source, options.python, options.copy_siblings)
    copy_live_pre, copy_detail_pre = envcopy.assert_copy_is_live(spec)

    run = hygiene.run(
        spec,
        PLUGIN_MODULE,
        timeout=options.timeout,
        tmpdir_allowed=options.tmpdir_allowed,
        disable_hook=options.disable_hook,
    )
    after = envcopy.snapshot_tree(target)

    summary = run.summary
    copy_live = summary.get("copy_verified_live", copy_live_pre)
    copy_detail = summary.get("copy_resolved_to", copy_detail_pre)
    refusal = _refusal(run, copy_live, copy_detail)

    ruff_result = self_skip_result = mock_drift_result = None
    if refusal is None and not options.skip_static:
        ruff_path, ruff_how = static_ruff.find_ruff(options.ruff, beside=spec.python)
        copy_tests = discover.find_test_files(spec.target_copy)
        module_root = spec.env_root / "src" if spec.layout == "aipass" else spec.env_root
        modules = build_module_map(module_root)
        index = SubjectIndex(modules, spec.target_copy)
        ruff_result = static_ruff.run(copy_tests, spec.target_copy, ruff_path)
        ruff_result["resolution"] = ruff_how
        self_skip_result = static_skip.run(copy_tests, index, spec.target_copy)
        self_skip_result["subject_modules"] = len(index.subject_modules)
        mock_drift_result = static_mock.run(copy_tests, modules, spec.target_copy)

    counts = run.counts
    matches_baseline = None
    if options.baseline_passed is not None:
        matches_baseline = counts.get("passed") == options.baseline_passed

    harness = {
        "hook_installed": summary.get("hook_installed"),
        "canary_caught": bool((summary.get("canary") or {}).get("caught")),
        "canary": summary.get("canary"),
        "copy_verified_live": copy_live,
        "copy_resolved_to": copy_detail,
        "copy_verified_preflight": copy_live_pre,
        "suite": {
            "command": run.command,
            "cwd": str(spec.run_cwd),
            "returncode": run.returncode,
            "timed_out": run.timed_out,
            "counts": counts,
            "baseline_passed": options.baseline_passed,
            "matches_baseline": matches_baseline,
            "rootdir_note": (
                "one branch, one path argument - pytest's rootdir lands on the branch's own "
                "pytest.ini, so the repo-root forgery guard is not loaded. That is the "
                "configuration every agent actually uses."
            ),
            "stdout_tail": run.stdout_tail,
        },
        "allowances": (run.header.get("allowances") or []),
        "tmpdir_allowance_enabled": run.header.get("tmpdir_allowed"),
        "pytest_basetemp": run.header.get("pytest_basetemp"),
        "real_target_tree": _tree_report(before, after),
        "symlinked_siblings": spec.symlinked_siblings,
        "copied_siblings": spec.copied_siblings,
        "escape_analysis": _escape_analysis(run, spec),
        "elapsed_seconds": round(time.time() - started, 1),
    }

    if options.keep_copy:
        copy_note = str(spec.target_copy)
    else:
        copy_note = f"{spec.target_copy} (deleted after the run; --keep-copy retains it)"

    document = artifact.build(
        target={
            "name": target.name,
            "path": str(target),
            "copy": copy_note,
            "layout": spec.layout,
            "test_files": len(real_test_files),
            "python": str(spec.python),
        },
        tool={
            "name": "audit-tests",
            "stage": "MVP prototype",
            "version": artifact.ARTIFACT_VERSION,
            "campaign": "FPLAN-0458 / DPLAN-0320",
        },
        harness=harness,
        hygiene_group=None if refusal else _hygiene_group(run),
        ruff_result=ruff_result,
        self_skip_result=self_skip_result,
        mock_drift_result=mock_drift_result,
        refusal=refusal,
    )

    if options.out:
        artifact.write(document, options.out)
    if not options.keep_copy:
        shutil.rmtree(spec.env_root, ignore_errors=True)

    return document, render(document)
