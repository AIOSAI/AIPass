# =================== AIPass ====================
# Name: report.py
# Description: assemble every row, declare the blind spots, publish the artifact
# Version: 1.0.2
# Created: 2026-09-01
# Modified: 2026-10-24
# =============================================

"""
THE ARTIFACT. One row per test function, a summary a human can read, and the
list of everything this report cannot see.

Blind spots sit beside the numbers and the writer refuses to publish without
them; a published label carrying delete-family vocabulary refuses the write.
"""

import json
import statistics
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file
from aipass.seedgo.apps.handlers.test_inventory import collection, exclusions, history, ranking, shape

#: Where the inventory is published. Seedgo's own state directory, never the
#: target's - `.seedgo` is seedgo-owned storage under gateway_boundary.
SEEDGO_ROOT = module_file(__file__).parents[3]
ARTIFACT_DIR = SEEDGO_ROOT / ".seedgo"

ROWS_NAME = "test_inventory_rows.jsonl"
SUMMARY_NAME = "test_inventory.json"
READABLE_NAME = "test_inventory.md"

ARTIFACT_VERSION = "test-inventory/1"
TOOL_VERSION = "1.0.0"

#: What this report cannot see; the writer refuses to publish an empty list.
BLIND_SPOTS: tuple = (
    "NO COVERAGE DATA. Nothing here knows which lines any test executes. Phase B adds "
    "--cov-context=test to the existing CI coverage job; until then no row can say whether a "
    "test touches production code at all.",
    "NO MUTATION DATA. Nothing here knows whether a test would catch a change. This is the only "
    "signal with a published relationship to fault detection and it is absent by design in a "
    "static pass - and per ISSTA 2018 even having it would not authorise a deletion.",
    "NO RUNTIME. No duration, no pass/fail, no flake history. Phase C adds two pytest hooks to the "
    "audit-tests payload; a test that has never failed is invisible here, and at Google that "
    "describes 91.3% of all tests including the ones that later caught real breakages.",
    "ASSERTION SHAPE IS STATIC. A test whose checking lives in a helper it calls reads as "
    "assertion-free from here. Every such row carries delegated_oracle=true and the two counts "
    "are published separately, but the split is a name heuristic, not a resolution of the call.",
    "TWINS AND CROWDING ARE UNVALIDATED PROXIES. They find generated batches and they also find "
    "thorough parametrised families. 39-75% of real tests execute a strict line-subset of another "
    "test AND ARE STILL NOT DELETABLE; both columns are marked weak in every row.",
    "AGE IS A LOWER BOUND. Blame reports when each surviving line was last touched, so a test "
    "written a year ago and reformatted last week reads as a week old. This under-states age and "
    "never over-states it.",
    "AUTHORSHIP BARELY DISCRIMINATES ON THIS FLEET. Over 99% of rows are agent-authored, so the "
    "column separates almost nothing here. Names the bucket table does not know go to OTHER, not "
    "to human, and the full author census is published so the residual is auditable.",
    "STATIC COLLECTION CANNOT SEE EVERY EXCLUSION. A collect_ignore_glob built by a loop, a "
    "pytest_collection_modifyitems hook, a skipif true on the running host, and any -k/-m "
    "selection are all invisible. Every one of those makes this report count MORE tests as "
    "running than really do.",
    "ONE CONFIGURATION, NOT ALL OF THEM. The corpus is built from the repo-root pytest config, "
    "which is what CI runs. Five branches carry their own pytest.ini that governs when that "
    "branch is run alone; this report does not model those rootdirs.",
)


@dataclass
class Inventory:
    """Everything one run produced, before it is written anywhere."""

    rows: List[dict]
    summary: dict


def build(
    root: Path,
    found: collection.Collection,
    statuses: Dict[str, str],
    blames: Dict[str, history.LineHistory],
    now: float,
) -> Inventory:
    """One row per test function, plus the summary computed over them."""
    shapes = {func.nodeid: shape.classify(func.node) for func in found.functions}
    histories = {
        func.nodeid: history.attribute(blames[func.relpath], func.blame_from, func.end_lineno, now)
        for func in found.functions
    }
    twins = _twin_counts(found, shapes)
    per_file = found.per_file
    per_class = found.per_class

    rows = [
        _row(func, shapes[func.nodeid], histories[func.nodeid], statuses, twins, per_file, per_class)
        for func in found.functions
    ]
    return Inventory(rows=rows, summary=_summary(root, found, statuses, rows, histories, now))


def _twin_counts(found: collection.Collection, shapes: Dict[str, shape.Shape]) -> Counter:
    """How many functions share a (file, class, body-shape) signature."""
    return Counter((func.relpath, func.class_name, shapes[func.nodeid].fingerprint) for func in found.functions)


def _row(
    func: collection.TestFunction,
    unit_shape: shape.Shape,
    unit_history: history.FunctionHistory,
    statuses: Dict[str, str],
    twins: Counter,
    per_file: Dict[str, int],
    per_class: Dict[tuple, int],
) -> dict:
    """One published row. Every column the score reads is in it."""
    twin_count = twins[(func.relpath, func.class_name, unit_shape.fingerprint)]
    file_tests = per_file.get(func.relpath, 1)
    score = ranking.score(unit_shape, unit_history, twin_count, file_tests)

    return {
        "nodeid": func.nodeid,
        "file": func.relpath,
        "line": func.lineno,
        "end_line": func.end_lineno,
        "class": func.class_name,
        "function": func.name,
        "collection_status": statuses.get(func.relpath, exclusions.STATUS_COLLECTED),
        "assertion_shape": unit_shape.shape,
        "oracle_evidence": unit_shape.evidence,
        "delegated_oracle": unit_shape.delegated_oracle,
        "statements": unit_shape.statements,
        "body_fingerprint": unit_shape.fingerprint,
        "twins_in_class": twin_count,
        "tests_in_file": file_tests,
        "tests_in_class": per_class.get((func.relpath, func.class_name), file_tests),
        "author": unit_history.author,
        "author_bucket": unit_history.author_bucket,
        "age_days": unit_history.age_days,
        "days_since_touch": unit_history.days_since_touch,
        "score": score.as_dict(),
    }


def _summary(
    root: Path,
    found: collection.Collection,
    statuses: Dict[str, str],
    rows: Sequence[dict],
    histories: Dict[str, history.FunctionHistory],
    now: float,
) -> dict:
    """The readable half: counts, distributions, and what they rest on."""
    running = [row for row in rows if statuses.get(row["file"]) in exclusions.RUNNING_STATUSES]
    nones = [row for row in rows if row["assertion_shape"] == shape.SHAPE_NONE]

    return {
        "artifact_version": ARTIFACT_VERSION,
        "run_identity": _run_identity(root, now, len(rows)),
        "corpus_definition": _corpus_definition(found, len(running)),
        "blind_spots": list(BLIND_SPOTS),
        "ranking": {
            "weights": dict(ranking.WEIGHTS),
            "weak_components": list(ranking.WEAK_COMPONENTS),
            "crowding_ceiling": ranking.CROWDING_CEILING,
            "recency_horizon_days": ranking.RECENCY_HORIZON_DAYS,
            "means": ranking.NEVER_A_DELETE_VERDICT,
            "authorises_deletion": False,
        },
        "assertion_shape": {
            "counts": dict(Counter(row["assertion_shape"] for row in rows)),
            "none_with_delegated_oracle": sum(1 for row in nones if row["delegated_oracle"]),
            "none_with_no_check_of_any_kind": sum(1 for row in nones if not row["delegated_oracle"]),
        },
        "authorship": {
            "buckets": dict(Counter(row["author_bucket"] for row in rows)),
            "census": history.author_census(list(histories.values())),
        },
        "age_days": _distribution([row["age_days"] for row in rows if row["age_days"] is not None]),
        "review_priority": _distribution([row["score"]["review_priority"] for row in rows]),
        "exclusions": _exclusions(found, statuses),
        "busiest_files": _busiest(rows),
        "top_review_priority": _top(rows),
    }


def _run_identity(root: Path, now: float, row_count: int) -> dict:
    """Which run produced this file, so a quote can be checked against it."""
    return {
        "tool_version": TOOL_VERSION,
        "generated_at_epoch": int(now),
        "root": str(root),
        "head": _head_commit(root),
        "rows": row_count,
    }


def _head_commit(root: Path) -> str:
    """The commit the tree sat on, or a stated absence."""
    try:
        completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(f"[INVENTORY] could not read the head commit, the run is unstamped: {exc}")
        return "unknown"
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _corpus_definition(found: collection.Collection, running: int) -> dict:
    """What was counted, under which rules, and how it was cross-checked."""
    definition = dict(found.rules.as_dict())
    definition.update(
        {
            "files_matched": len(found.files),
            "files_unparseable": len(found.unparseable),
            "unparseable": found.unparseable,
            "functions_found": len(found.functions),
            "functions_that_run": running,
            "functions_that_never_run": len(found.functions) - running,
            "cross_check": (
                "This definition was validated against `pytest --collect-only` on the machine that "
                "built it: the set of running functions matched pytest's collected nodeids exactly, "
                "with the parametrize suffix stripped, in both directions. A host missing an "
                "optional dependency collects fewer, because CONDITIONAL_SKIP files run only where "
                "their import succeeds."
            ),
            "differs_from_earlier_counts": (
                "An earlier pass reported 478 assertion-free functions over 626 files / 19,471 "
                "functions, and a second reported 466 over 584 files / 18,283. This run publishes "
                "its own numbers under the rules above; the differences are corpus definition, not "
                "disagreement about any individual test."
            ),
        }
    )
    return definition


def _exclusions(found: collection.Collection, statuses: Dict[str, str]) -> dict:
    """Files that match the collection globs and are not collected anyway."""
    by_status: Dict[str, List[str]] = {}
    for relpath, status in sorted(statuses.items()):
        if status != exclusions.STATUS_COLLECTED:
            by_status.setdefault(status, []).append(relpath)

    tests_lost = Counter(
        statuses.get(func.relpath, exclusions.STATUS_COLLECTED)
        for func in found.functions
        if statuses.get(func.relpath) not in (exclusions.STATUS_COLLECTED, None)
    )
    return {"files": by_status, "test_functions": dict(tests_lost)}


def _distribution(values: Sequence[float]) -> dict:
    """Count, median and the tails, or a stated absence."""
    if not values:
        return {"count": 0, "note": "no values - nothing was measured, which is not the same as zero"}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p50": round(statistics.median(ordered), 3),
        "p90": ordered[int(len(ordered) * 0.9)],
        "max": ordered[-1],
    }


def _busiest(rows: Sequence[dict], limit: int = 15) -> List[dict]:
    """The files holding the most test functions."""
    counts = Counter(row["file"] for row in rows)
    return [{"file": name, "tests": count} for name, count in counts.most_common(limit)]


def _top(rows: Sequence[dict], limit: int = 25) -> List[dict]:
    """The highest review priorities. A reading queue, in order."""
    ordered = sorted(rows, key=lambda row: (-row["score"]["review_priority"], row["nodeid"]))
    return [
        {
            "nodeid": row["nodeid"],
            "review_priority": row["score"]["review_priority"],
            "assertion_shape": row["assertion_shape"],
            "delegated_oracle": row["delegated_oracle"],
            "twins_in_class": row["twins_in_class"],
            "author_bucket": row["author_bucket"],
            "age_days": row["age_days"],
        }
        for row in ordered[:limit]
    ]


def publish(inventory: Inventory, directory: Optional[Path] = None) -> Dict[str, Path]:
    """Write the rows, the summary and the readable digest. Returns the paths."""
    assert_publishable(inventory.summary)

    directory = directory or ARTIFACT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "rows": directory / ROWS_NAME,
        "summary": directory / SUMMARY_NAME,
        "readable": directory / READABLE_NAME,
    }

    with paths["rows"].open("w", encoding="utf-8") as handle:
        for row in inventory.rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    paths["summary"].write_text(json.dumps(inventory.summary, indent=2, sort_keys=True), encoding="utf-8")
    paths["readable"].write_text(readable(inventory.summary), encoding="utf-8")

    json_handler.log_operation(
        "test_inventory_published",
        {
            "rows": len(inventory.rows),
            "head": inventory.summary["run_identity"]["head"],
            "artifact": str(paths["summary"]),
        },
    )
    logger.info(f"[INVENTORY] published {len(inventory.rows)} rows to {paths['summary']}")
    return paths


def assert_publishable(summary: dict) -> None:
    """Refuse a summary with no blind spots or with verdict vocabulary in it."""
    if not summary.get("blind_spots"):
        raise ValueError("refusing to publish an inventory that declares no blind spots")

    offenders = ranking.delete_language_in(" ".join(sorted(_keys(summary))))
    if offenders:
        raise ValueError(f"refusing to publish: delete-family vocabulary in a published key: {offenders}")


def _keys(value) -> List[str]:
    """Every key name the summary publishes, at any depth.

    Values are data: a test named `test_remove` or prose that says the word is not a verdict."""
    if isinstance(value, dict):
        return [name for key, child in value.items() for name in (str(key), *_keys(child))]
    if isinstance(value, list):
        return [name for child in value for name in _keys(child)]
    return []


def readable(summary: dict) -> str:
    """The human digest: what was counted, what it cannot see, what to read."""
    corpus = summary["corpus_definition"]
    shapes = summary["assertion_shape"]
    lines = [
        "# Test inventory - a report, not a verdict",
        "",
        f"Commit `{summary['run_identity']['head'][:12]}` · {summary['run_identity']['rows']} rows · "
        f"tool {summary['run_identity']['tool_version']}",
        "",
        "## What this number means",
        "",
        summary["ranking"]["means"],
        "",
        "## Corpus",
        "",
        f"- {corpus['functions_found']} test functions in {corpus['files_matched']} files",
        f"- {corpus['functions_that_run']} of them run; {corpus['functions_that_never_run']} never do",
        f"- unit: {corpus['unit']}",
        f"- config: {corpus['config_source']}",
        "",
        "## Assertion shape",
        "",
    ]
    lines += [f"- {name}: {count}" for name, count in sorted(shapes["counts"].items())]
    lines += [
        f"- of the assertion-free rows, {shapes['none_with_delegated_oracle']} call a check-shaped helper "
        f"and {shapes['none_with_no_check_of_any_kind']} check nothing at all",
        "",
        "## Authorship",
        "",
    ]
    lines += [f"- {bucket}: {count}" for bucket, count in sorted(summary["authorship"]["buckets"].items())]
    lines += ["", "## Blind spots", ""]
    lines += [f"{index}. {spot}" for index, spot in enumerate(summary["blind_spots"], start=1)]
    lines += ["", "## Read these first", ""]
    lines += [
        f"{index}. `{row['nodeid']}` - priority {row['review_priority']}, {row['assertion_shape']}"
        for index, row in enumerate(summary["top_review_priority"], start=1)
    ]
    return "\n".join(lines) + "\n"
