# =================== AIPass ====================
# Name: branch_audit.py
# Description: Branch Audit Handler
# Version: 2.8.1
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================
"""Branch Audit Handler — auto-discovers checkers from handlers/*_standards/ packs via glob."""

import copy
import functools
import importlib.util
from pathlib import Path
from typing import Any, Dict, List, Optional
from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass import dead_rules, ignore_handler, inert
from aipass.seedgo.apps.handlers.aipass_standards import applicability
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import is_disabled_file, is_throwaway_path
from aipass.seedgo.apps.handlers.audit import incremental_cache
from aipass.seedgo.apps.handlers.audit.artifact import DEFAULT_PACK_NAME
from aipass.seedgo.apps.handlers.audit.discovery import measure_pack_corpus, pack_corpus
from aipass.seedgo.apps.handlers.checklist import verdicts
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.test_map.function_scanner import scan_branch

# Own module log: branch_audit's log is FIFO-capped and would evict the observation series.
OBSERVE_LOG_MODULE = "branch_observe"


def discover_checkers(pack_path: Path | None = None) -> Dict[str, Any]:
    """Auto-discover all *_check.py modules from a pack directory (default handlers/aipass_standards/).

    Memoised on the checker files' stamps; a copy is returned because callers add entries.
    """
    standards_dir = pack_path if pack_path is not None else Path(__file__).resolve().parent.parent / "aipass_standards"
    stamps = tuple(sorted(incremental_cache.compute_checker_stamps(standards_dir).items()))
    return dict(_load_checkers(standards_dir.resolve(), stamps))


@functools.lru_cache(maxsize=16)
def _load_checkers(standards_dir: Path, _stamps: tuple) -> Dict[str, Any]:
    """Execute every checker module in one pack directory once per stamp set."""
    checkers = {}
    for cf in sorted(standards_dir.glob("*_check.py")):
        name = cf.stem.removesuffix("_check")
        spec = importlib.util.spec_from_file_location(cf.stem, cf)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            logger.info("Skipped checker %s: failed to load", cf.name)
            continue
        if hasattr(mod, "check_module") or hasattr(mod, "check_branch"):
            checkers[name] = mod
    return checkers


def _rel_path(path: Path, root: Path) -> str:
    """Path relative to root as posix, falling back to the absolute path if unrelated."""
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as e:
        logger.info("[branch_audit] %s not relative to %s: %s", path, root, e)
        return path.as_posix()


def _is_collectable_test(path: Path) -> bool:
    """Whether a file under tests/ is a TEST file rather than something beside one."""
    return path.name.startswith("test_") or path.name == "conftest.py"


def _collect_py_files(
    branch_path: Path, include_init: bool = False, ignored: Dict[str, List[str]] | None = None
) -> List[Dict[str, str]]:
    """Collect auditable .py files from apps/ AND tests/, respecting ignore patterns.

    include_init=True is for import checkers: a cross-handler import can hide in a package marker.
    is_retired_path() backs up the ignore patterns, whose "/.archive/" substring never matches on Windows.
    """
    root = branch_path.resolve()
    ignore_entries = ignore_handler.load_ignore_entries(branch_path)

    # shared/ beside apps/ is product code too (aipass keeps project_home.py there).
    candidates: List[Path] = []
    for product_dir in (branch_path / "apps", branch_path / "shared"):
        if product_dir.exists():
            candidates += [f for f in product_dir.rglob("*.py") if include_init or f.name != "__init__.py"]
    tests_dir = branch_path / "tests"
    if tests_dir.exists():
        candidates += [f for f in tests_dir.rglob("*.py") if _is_collectable_test(f)]

    collected: List[Dict[str, str]] = []
    for f in candidates:
        if is_disabled_file(f.name) or is_throwaway_path(str(f)) or applicability.is_retired_path(str(f)):
            continue
        rel = _rel_path(f, root)
        pattern = ignore_handler.audit_ignore_match(rel)
        if pattern is not None:
            if ignored is not None:
                ignored.setdefault(pattern, []).append(rel)
            continue
        if not ignore_handler.is_seedgo_ignored(str(f), branch_path, ignore_entries):
            collected.append({"file": str(f), "name": f.name, "rel": rel})
    return collected


def _declared_input_files(branch_path: Path, checkers: Dict[str, Any] | None, attribute: str) -> List[Path]:
    """Existing files matching one declaration channel's globs (``{branch}`` = branch dir name).

    Directories are included: trinity's File set group scores stray directories, so the cache must see them.
    """
    if not checkers:
        return []
    found: set[Path] = set()
    for module in checkers.values():
        for pattern in getattr(module, attribute, ()) or ():
            resolved = pattern.replace("{branch}", branch_path.name)
            found.update(branch_path.glob(resolved))
    return sorted(found)


def _external_input_files(checkers: Dict[str, Any] | None) -> List[Path]:
    """Files OUTSIDE the branch that a checker scores, from its ``external_inputs()``."""
    if not checkers:
        return []
    found: set[Path] = set()
    for module in checkers.values():
        if hasattr(module, "external_inputs"):
            found.update(Path(path) for path in module.external_inputs())
    return sorted(found)


def _collect_watch_files(branch_path: Path, checkers: Dict[str, Any] | None = None) -> List[Dict[str, str]]:
    """Union of every file whose content can change audit output.

    bypass.json/.seedgoignore are absent on purpose: compute_bypass_stamp() busts on them.
    BRANCH_INPUT_NAMES are watched by presence only: they include ``*_log.json`` written
    during the audit, and fingerprinting their content would mark every branch dirty every run.
    """
    root = branch_path.resolve()
    files = _collect_py_files(branch_path, include_init=True)
    readme = branch_path / "README.md"
    if readme.exists():
        files.append({"file": str(readme), "name": readme.name, "rel": _rel_path(readme, root)})
    # Wider than the corpus: test_map's scan_branch reads every .py under tests/.
    tests_dir = branch_path / "tests"
    if tests_dir.exists():
        already = {entry["rel"] for entry in files}
        files.extend(
            {"file": str(f), "name": f.name, "rel": _rel_path(f, root)}
            for f in tests_dir.rglob("*.py")
            if _rel_path(f, root) not in already
        )
    custom_config = branch_path / f"{branch_path.name}_json" / "custom_config"
    if custom_config.is_dir():
        files.extend(
            {"file": str(f), "name": f.name, "rel": _rel_path(f, root)} for f in custom_config.iterdir() if f.is_file()
        )
    seen = {entry["rel"] for entry in files}
    for f in _declared_input_files(branch_path, checkers, "BRANCH_INPUTS"):
        rel = _rel_path(f, root)
        if rel not in seen:
            seen.add(rel)
            entry = {"file": str(f), "name": f.name, "rel": rel}
            if f.is_dir():
                # A directory's mtime would re-report every child edit.
                entry["presence_only"] = "1"
            files.append(entry)
    for f in _declared_input_files(branch_path, checkers, "BRANCH_INPUT_NAMES"):
        rel = _rel_path(f, root)
        if rel not in seen:
            seen.add(rel)
            files.append({"file": str(f), "name": f.name, "rel": rel, "presence_only": "1"})
    for f in _external_input_files(checkers):
        key = f.resolve().as_posix()
        if key not in seen:
            seen.add(key)
            files.append({"file": str(f), "name": f.name, "rel": key})
    return files


def _collect_branch_info(checkers: Dict[str, Any], branch_path: Path, branch_name: str) -> List[Dict[str, str]]:
    """Gather non-scored signpost lines from checkers exposing check_branch_info().

    Never merged into scores. Inert bypass rules are reported here: scoring housekeeping would move a number.
    """
    info: List[Dict[str, str]] = []
    try:
        info.extend({"standard": "bypass", "message": line} for line in inert.check_branch_info(str(branch_path)))
    except Exception as e:
        logger.info("Inert bypass-rule info failed for branch %s: %s", branch_name, e)
    for name, checker in sorted(checkers.items()):
        if not hasattr(checker, "check_branch_info"):
            continue
        try:
            lines = checker.check_branch_info(str(branch_path))
        except Exception as e:
            logger.info("Info check %s failed for branch %s: %s", name, branch_name, e)
            continue
        info.extend({"standard": name, "message": str(line)} for line in lines or [])
    return info


def _collect_branch_observations(
    checkers: Dict[str, Any],
    branch_path: Path,
    branch_name: str,
    bypass_rules: list,
) -> List[Dict[str, Any]]:
    """Gather observe-only readings from checkers exposing check_branch_observe().

    Never merged into scores: a de-scored check keeps producing evidence without moving a number.
    A hook that raises (including on the bypass_rules keyword) yields an error reading, not silence.
    """
    observations: List[Dict[str, Any]] = []
    for name, checker in sorted(checkers.items()):
        if not hasattr(checker, "check_branch_observe"):
            continue
        try:
            readings = checker.check_branch_observe(str(branch_path), bypass_rules=bypass_rules) or []
        except Exception as e:
            logger.warning("Observe check %s failed for branch %s: %s", name, branch_name, e)
            readings = [
                {
                    "standard": name,
                    "branch": branch_name,
                    "error": f"{type(e).__name__}: {e}",
                    "would_be_score": None,
                }
            ]
        observations.extend(readings)
    for reading in observations:
        json_handler.log_operation("branch_observation", dict(reading), module_name=OBSERVE_LOG_MODULE)
    return observations


def _extract_branch_level_violations(result: dict) -> list:
    """Extract per-file violations from a branch-level checker result."""
    standard_keys = {"name", "passed", "message", "score"}
    file_violations: dict[str, list[str]] = {}

    for check in result.get("checks", []):
        for key, val in check.items():
            if key in standard_keys or not isinstance(val, list):
                continue
            for item in val:
                if not isinstance(item, dict) or "file" not in item:
                    continue
                fpath = item["file"]
                msg = f"{item.get('name', 'unknown')}() line {item.get('line', '?')}"
                file_violations.setdefault(fpath, []).append(msg)

    return [
        {"file": fpath, "path": fpath, "score": 0, "issues": issues, "message": "; ".join(issues)}
        for fpath, issues in file_violations.items()
    ]


def _get_or_compute(
    checker,
    name: str,
    file_path: str,
    rel: str | None,
    bypass_rules: list,
    file_result_cache: Dict[str, Dict[str, Any]] | None,
    unchanged_files: set | None,
) -> dict:
    """Return a checker's result for one file — from cache when unchanged, else fresh.

    Fresh results are recorded back so the caller holds a complete map to persist.
    """
    if rel is not None and unchanged_files is not None and file_result_cache is not None and rel in unchanged_files:
        cached = file_result_cache.get(rel, {}).get(name)
        if cached is not None:
            return cached
    r = checker.check_module(file_path, bypass_rules=bypass_rules)
    if rel is not None and file_result_cache is not None:
        file_result_cache.setdefault(rel, {})[name] = r
    return r


def _get_or_compute_branch(
    checker,
    name: str,
    branch_path: Path,
    bypass_rules: list,
    cached_branch_results: Dict[str, Any] | None,
    unchanged_checkers: set | None,
) -> dict:
    """Return a branch-level checker's result — from cache when nothing it reads moved.

    Read-only: branch-level results already persist inside the cached output's results[].
    """
    if unchanged_checkers is not None and cached_branch_results is not None and name in unchanged_checkers:
        cached = cached_branch_results.get(name)
        # A crashed result (a pyright timeout) is a failure to run, never a measurement to serve again.
        if cached is not None and "error" not in cached:
            return cached
    return checker.check_branch(str(branch_path), bypass_rules=bypass_rules)


def _stood_down(name: str) -> Dict[str, Any]:
    """A result that holds a standard's slot without claiming a measurement.

    Dropping the row trips the CI tripwire (it counts standards consulted); 0 or 100 would both lie.
    """
    return {
        "passed": True,
        "score": 0,
        "not_applicable": True,
        "checks": [
            {
                "name": "Applicable files",
                "passed": True,
                "message": f"{name} applies to test files; this branch has none in the corpus",
            }
        ],
    }


def _entry_point_pass(
    checker,
    name: str,
    scope: str,
    runs_on_entry_file: bool,
    entry_file: str,
    entry_rel: str,
    bypass_rules: list,
    file_result_cache: Dict[str, Dict[str, Any]] | None,
    unchanged_files: set | None,
) -> Dict[str, Any]:
    """One checker's result for the branch's entry file.

    entry_point-scope checkers skip the cache: AUDIT_SCOPE says where a result is
    reported, not what it reads (readme_check reads README.md, outside entry_file).
    """
    if not runs_on_entry_file:
        return _stood_down(name)
    try:
        if scope == "all_files":
            return _get_or_compute(
                checker, name, entry_file, entry_rel, bypass_rules, file_result_cache, unchanged_files
            )
        result = checker.check_module(entry_file, bypass_rules=bypass_rules)
        if file_result_cache is not None:
            file_result_cache.setdefault(entry_rel, {})[name] = result
        return result
    except Exception as e:
        logger.warning("Entry-point checker %s failed: %s", name, e)
        return _crashed_result(name, e)


def _run_all_files(
    checker,
    name: str,
    files: List[Dict],
    bypass_rules: list,
    file_result_cache: Dict[str, Dict[str, Any]] | None = None,
    unchanged_files: set | None = None,
) -> tuple:
    """Run checker on every file. Returns (violations, scores, declined).

    A file stands down only by contract: all checks pass and one carries ``"declined": True``;
    the message text is never read to decide it.
    """
    violations, scores, declined = [], [], []
    for fi in files:
        try:
            r = _get_or_compute(
                checker, name, fi["file"], fi.get("rel"), bypass_rules, file_result_cache, unchanged_files
            )
        except Exception as e:
            # A crash is a failing file, never a dropped one: dropping it averages the rest upward.
            logger.warning("Checker %s failed on %s: %s", name, fi["name"], e)
            r = _crashed_result(name, e)
        score, checks = r.get("score", 0), r.get("checks", [])
        failed = verdicts.failed_checks(r)
        if checks and not failed and any(c.get("declined") is True for c in checks):
            declined.append(fi.get("rel") or fi["name"])
        elif checks:
            scores.append(score)
        # A file scoring 75-99 still lowers the score, so its violations must be reported.
        if failed:
            msgs = [c.get("message", "Unknown") for c in failed]
            v = {"file": fi["name"], "path": fi["file"], "score": score, "issues": msgs, "message": "; ".join(msgs)}
            violations.append(v)
    return violations, scores, declined


def _crashed_result(name: str, error: Exception) -> Dict[str, Any]:
    """The result of a checker that failed to run: score 0, with the reason attached."""
    return {
        "passed": False,
        "score": 0,
        "error": str(error),
        "checks": [
            {
                "name": "Checker ran",
                "passed": False,
                "message": (
                    f"{name} checker crashed ({type(error).__name__}: {error}) - "
                    "score 0 is a failure to run, not a measured result"
                ),
            }
        ],
    }


def _load_diagnostics_checker():
    """Load diagnostics checker from handlers/diagnostics/ (shared infrastructure).

    None only when there is nothing to load; a load failure raises so it is recorded as crashed.
    """
    diag_path = Path(__file__).resolve().parent.parent / "diagnostics" / "diagnostics_check.py"
    if not diag_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("diagnostics_check", diag_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _deprecated_patterns(branch_path: Path) -> list:
    """Deprecated DOCUMENTS/ directory check.

    Recomputed even on a cache hit: a directory rename is invisible to .py fingerprinting.
    """
    if not (branch_path / "DOCUMENTS").is_dir():
        return []
    return [
        {
            "type": "directory",
            "old": "DOCUMENTS/",
            "new": "docs/",
            "path": str(branch_path / "DOCUMENTS"),
            "message": "Rename DOCUMENTS/ to docs/",
        }
    ]


def cache_key_for(branch_name: str, pack_path: Optional[Path], no_bypass: bool = False) -> str:
    """The incremental-cache slot for one (branch, pack, bypass mode).

    Every axis the stamp folds in must also discriminate the key, or alternating runs evict each other.
    The default pack keeps the bare branch name so existing entries stay valid.
    """
    key = branch_name
    pack_name = pack_path.name.removesuffix("_standards") if pack_path is not None else DEFAULT_PACK_NAME
    if pack_name != DEFAULT_PACK_NAME:
        key = f"{key}::pack={pack_name}"
    if no_bypass:
        key = f"{key}::no-bypass"
    return key


def _bypass_hygiene(
    branch_path: Path,
    bypass_rules: list,
    checkers: Dict[str, Any],
    pack_path: Path | None,
    files_with_init: List[Dict[str, str]] | None = None,
) -> Dict[str, list]:
    """The branch's dead bypass rules and its inline bypass comments.

    Only the aipass pack reads bypass rules. Read fresh every run: a deleted file kills a rule unwatched.
    """
    default_pack = Path(__file__).resolve().parent.parent / "aipass_standards"
    if pack_path is not None and pack_path.resolve() != default_pack:
        return {"bypass_dead": [], "bypass_markers": []}
    known = set(checkers) | {"diagnostics"}
    if files_with_init is None:
        files_with_init = _collect_py_files(branch_path, include_init=True)
    corpus = [fi["file"] for fi in files_with_init]
    return {
        "bypass_dead": dead_rules.dead_rules(branch_path, bypass_rules, known),
        "bypass_markers": dead_rules.bypass_markers(branch_path, corpus),
    }


def audit_branch(
    branch: Dict[str, str],
    bypass_rules: list,
    pack_path: Path | None = None,
    file_result_cache: Dict[str, Dict[str, Any]] | None = None,
    unchanged_files: set | None = None,
    cached_branch_results: Dict[str, Any] | None = None,
    unchanged_checkers: set | None = None,
) -> Dict:
    """Audit a branch for standards compliance. Returns backward-compatible dict.

    The cache args (see audit_branch_incremental) left at None give a plain full audit.
    """
    entry_file, branch_path = branch["entry_file"], Path(branch["path"])
    entry_rel = _rel_path(Path(entry_file), branch_path.resolve())
    file_result_cache = {} if file_result_cache is None else file_result_cache
    ignored_all: Dict[str, List[str]] = {}
    files_with_init = _collect_py_files(branch_path, include_init=True, ignored=ignored_all)
    all_files = [f for f in files_with_init if f["name"] != "__init__.py"]
    ignored: Dict[str, List[str]] = {}
    for pattern, rels in ignored_all.items():
        kept = [rel for rel in rels if Path(rel).name != "__init__.py"]
        if kept:
            ignored[pattern] = kept
    checkers = discover_checkers(pack_path)
    ignored_paths = sorted(rel for rels in ignored.values() for rel in rels)

    results, scores, all_violations, declined_files = {}, {}, {}, {}

    try:
        diag_mod = _load_diagnostics_checker()
    except Exception as e:
        logger.info("Diagnostics checker failed to load: %s", e)
        results["diagnostics"], scores["diagnostics"] = _crashed_result("diagnostics", e), 0
        diag_mod = None
    if diag_mod and hasattr(diag_mod, "check_branch") and "diagnostics" not in checkers:
        checkers["diagnostics"] = diag_mod

    for name, checker in checkers.items():
        scope = getattr(checker, "AUDIT_SCOPE", "entry_point")
        if scope == "branch_level" or (not hasattr(checker, "check_module") and hasattr(checker, "check_branch")):
            try:
                r = _get_or_compute_branch(
                    checker, name, branch_path, bypass_rules, cached_branch_results, unchanged_checkers
                )
                results[name] = r
                # not_applicable measured nothing, so it stays out of scores[].
                if r.get("not_applicable") is True:
                    logger.info("Branch-level checker %s is not applicable for %s", name, branch_path)
                else:
                    scores[name] = r.get("score", 0)
                all_violations[name] = _extract_branch_level_violations(r)
            except Exception as e:
                logger.info("Branch-level checker %s failed: %s", name, e)
                results[name] = _crashed_result(name, e)
                scores[name] = 0
            continue
        # Branch-level checkers above are exempt: they walk the tree themselves.
        # A tests-only standard fails on the entry file; skip the entry pass, not
        # the checker, or the all_files scan below never hands it a test file.
        runs_on_entry_file = applicability.applies_to_file(checker, entry_file)
        if not runs_on_entry_file and scope != "all_files":
            continue
        r = _entry_point_pass(
            checker,
            name,
            scope,
            runs_on_entry_file,
            entry_file,
            entry_rel,
            bypass_rules,
            file_result_cache,
            unchanged_files,
        )
        results[name] = r
        if r.get("not_applicable") is not True:
            scores[name] = r.get("score", 0)
        if scope == "all_files" and all_files:
            scan_files = files_with_init if getattr(checker, "INCLUDE_INIT_FILES", False) else all_files
            scan_files = [f for f in scan_files if applicability.applies_to_file(checker, f["file"])]
            # The entry pass above already judged entry_file; served from its fresh result, not recomputed.
            reuse: set = set(unchanged_files or ())
            if runs_on_entry_file and "error" not in r:
                reuse.add(entry_rel)
            v, s, d = _run_all_files(checker, name, scan_files, bypass_rules, file_result_cache, reuse)
            all_violations[name] = v
            if d:
                declined_files[name] = d
            if s:
                avg_score = int(sum(s) / len(s))
                scores[name] = avg_score
                all_failed = []
                for vi in v:
                    all_failed.extend({"name": name, "passed": False, "message": iss} for iss in vi.get("issues", []))
                if all_failed:
                    results[name] = {
                        "passed": avg_score >= 75,
                        "checks": all_failed,
                        "score": avg_score,
                        "standard": name.upper(),
                    }

    for name, checker in checkers.items():
        if hasattr(checker, "check_branch_post") and name in scores:
            try:
                pv, ps = checker.check_branch_post(str(branch_path), bypass_rules=bypass_rules)
                all_violations.setdefault(name, []).extend(pv)
                if ps:
                    scores[name] = int(sum(ps + [scores[name]]) / (len(ps) + 1))
            except Exception as e:
                # Score left alone: a supplementary-check crash is a checker defect,
                # but the output must say loudly that the score is incomplete.
                logger.warning("Post-check %s failed for branch %s: %s", name, branch["name"], e)
                detail = (
                    f"{name} post-check crashed on branch {branch['name']} "
                    f"({type(e).__name__}: {e}) — the branch's {name} score of {scores[name]} "
                    "comes from the file lane only and does NOT include this check"
                )
                all_violations.setdefault(name, []).append(
                    {
                        "file": f"{name} post-check",
                        "path": f"{branch_path} ({name} post-check)",
                        "score": scores[name],
                        "issues": [detail],
                        "message": detail,
                    }
                )
                results.setdefault(name, {}).setdefault("checks", []).append(
                    {"name": "Post-check ran", "passed": False, "message": detail}
                )

    info_lines = _collect_branch_info(checkers, branch_path, branch["name"])
    observations = _collect_branch_observations(checkers, branch_path, branch["name"], bypass_rules)

    json_handler.log_operation("branch_audit_completed", {"branch": branch["name"], "checkers": len(checkers)})
    advisory_standards = [name for name, mod in checkers.items() if getattr(mod, "ADVISORY", False) is True]
    gating_scores = {k: v for k, v in scores.items() if k not in advisory_standards}
    avg = int(sum(gating_scores.values()) / len(gating_scores)) if gating_scores else 0

    deprecated = _deprecated_patterns(branch_path)

    try:
        test_map_result = scan_branch(str(branch_path))
    except Exception as e:
        logger.warning("Test map scan failed for %s: %s", branch["name"], e)
        test_map_result = None

    diag_result = results.get("diagnostics", {})
    # The banner describes the pack's corpus, not this walk (discovery.pack_corpus).
    corpus_terms = pack_corpus(pack_path)
    measured = measure_pack_corpus(pack_path, branch_path)
    output = {
        "branch": branch,
        "results": results,
        "scores": scores,
        # The files each row did not judge; its number averages the rest.
        "declined": declined_files,
        "ignored": {pattern: sorted(rels) for pattern, rels in ignored.items()},
        "ignored_tracked": ignore_handler.ignored_tracked_source(branch_path, ignored_paths),
        **_bypass_hygiene(branch_path, bypass_rules, checkers, pack_path, files_with_init),
        "advisory_standards": advisory_standards,
        "average": avg,
        "deprecated_patterns": deprecated,
        "files_checked": len(all_files),
        "corpus_noun": corpus_terms["noun"],
        "corpus_detail": corpus_terms["detail"],
        "corpus_size": len(all_files) if measured is None else measured,
        "type_errors": diag_result.get("total_errors", 0),
        "type_error_files": diag_result.get("results", []),
        "test_map": test_map_result,
        "info_lines": info_lines,
        "observations": observations,
    }
    for name in checkers:
        output[f"{name}_violations"] = all_violations.get(name, [])
    return output


def audit_branch_incremental(
    branch: Dict[str, str],
    bypass_rules: list,
    pack_path: Path | None = None,
    force_full: bool = False,
    no_bypass: bool = False,
) -> Dict:
    """Audit a branch, reusing cached results when nothing relevant changed.

    Output equals audit_branch() on the same tree; this only decides what to recompute.
    Accepted staleness: pyright resolves imports across branches, so an edit in branch A
    can leave clean branch B's cached diagnostics stale until B changes or --full; CI's
    always-full audit is the backstop. no_bypass empties bypass_rules here so the flag
    and the rules cannot disagree; the two modes are stamped and keyed apart.
    """
    if no_bypass:
        bypass_rules = []
    branch_name, branch_path = branch["name"], Path(branch["path"])
    resolved_pack_path = (
        pack_path if pack_path is not None else Path(__file__).resolve().parent.parent / "aipass_standards"
    )
    cache_key = cache_key_for(branch_name, pack_path, no_bypass=no_bypass)
    diag_path = Path(__file__).resolve().parent.parent / "diagnostics" / "diagnostics_check.py"

    branch_entry = incremental_cache.load_branch_entry(cache_key)
    stamp = incremental_cache.current_stamp(branch_path, resolved_pack_path, diag_path, no_bypass=no_bypass)
    checker_stamps = incremental_cache.compute_checker_stamps(resolved_pack_path)

    checkers = discover_checkers(pack_path)
    watch_files = _collect_watch_files(branch_path, checkers)
    current_fp = incremental_cache.collect_fingerprints(watch_files)

    cached_branch_results: Dict[str, Any] = {}
    unchanged_checkers: set = set()
    partial: Dict[str, Any] | None = None
    if not force_full and branch_entry and branch_entry.get("stamp") == stamp:
        stale = incremental_cache.stale_checkers(branch_entry.get("checker_stamps", {}), checker_stamps)
        cached_files_doc = branch_entry.get("files", {})
        cached_fp = {rel: v.get("fp") for rel, v in cached_files_doc.items()}
        added, changed, deleted, unchanged = incremental_cache.diff_fileset(cached_fp, current_fp)

        cached_results = branch_entry.get("output", {}).get("results", {})
        crashed = {n for n, r in cached_results.items() if isinstance(r, dict) and "error" in r}
        if not (added or changed or deleted) and not stale and not crashed:
            output = copy.deepcopy(branch_entry.get("output", {}))
            output["deprecated_patterns"] = _deprecated_patterns(branch_path)
            # Observations read live runtime state; a cached one is a past moment served as current.
            output["observations"] = _collect_branch_observations(checkers, branch_path, branch_name, bypass_rules)
            output.update(_bypass_hygiene(branch_path, bypass_rules, checkers, pack_path))
            output["_cache_hit"] = True
            return output

        # Without this a partial run prints exactly like a cold one.
        partial = {
            "checkers_total": len(checker_stamps),
            "checkers_cached": len(checker_stamps) - len(stale),
            "reran": sorted(stale),
            "files_total": len(current_fp),
            "files_cached": len(unchanged),
        }

        # A READS_BRANCH checker's per-file verdict depends on its siblings: any moved file voids all of them.
        moved = bool(added or changed or deleted)
        drop = stale | {n for n, m in checkers.items() if moved and getattr(m, "READS_BRANCH", False) is True}
        file_result_cache = {
            rel: {cname: r for cname, r in v.get("results", {}).items() if cname not in drop}
            for rel, v in cached_files_doc.items()
        }
        if not (added or changed or deleted):
            # Branch-level reuse only when no watched file moved: the one-checker-edit case.
            cached_branch_results = copy.deepcopy(branch_entry.get("output", {}).get("results", {}))
            unchanged_checkers = set(cached_branch_results) - stale
    else:
        unchanged = set()
        file_result_cache = {}

    output = audit_branch(
        branch,
        bypass_rules,
        pack_path=pack_path,
        file_result_cache=file_result_cache,
        unchanged_files=unchanged,
        cached_branch_results=cached_branch_results,
        unchanged_checkers=unchanged_checkers,
    )

    new_files_doc = {rel: {"fp": current_fp[rel], "results": file_result_cache.get(rel, {})} for rel in current_fp}
    try:
        incremental_cache.save_branch_entry(
            cache_key,
            {"stamp": stamp, "checker_stamps": checker_stamps, "files": new_files_doc, "output": output},
        )
    except Exception as e:
        # The cache is an accelerator: an unwritable one costs the next run time, never this run's result.
        logger.warning("[branch_audit] Cache save failed for %s: %s", cache_key, e)
    output["_cache_hit"] = False
    if partial is not None:
        output["_cache_partial"] = partial
    return output
