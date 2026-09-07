# =================== AIPass ====================
# Name: branch_audit.py
# Description: Branch Audit Handler
# Version: 2.0.0
# Created: 2026-03-05
# Modified: 2026-03-09
# =============================================
"""Branch Audit Handler — auto-discovers checkers from handlers/*_standards/ packs via glob."""

import copy
import importlib.util
from pathlib import Path
from typing import Any, Dict, List, Optional
from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass import ignore_handler, inert
from aipass.seedgo.apps.handlers.aipass_standards import applicability
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import is_disabled_file, is_throwaway_path
from aipass.seedgo.apps.handlers.audit import incremental_cache
from aipass.seedgo.apps.handlers.audit.artifact import DEFAULT_PACK_NAME
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.test_map.function_scanner import scan_branch

# Observe-only readings get their own module log rather than sharing
# branch_audit's: that log is FIFO-capped and every audit writes to it, so a
# shared file would evict the observation series the readings exist to build.
OBSERVE_LOG_MODULE = "branch_observe"


def discover_checkers(pack_path: Path | None = None) -> Dict[str, Any]:
    """Auto-discover all *_check.py modules from a pack directory.

    Args:
        pack_path: Path to the pack's standards directory. If None, defaults
                   to handlers/aipass_standards/.
    """
    standards_dir = pack_path if pack_path is not None else Path(__file__).resolve().parent.parent / "aipass_standards"
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


def _collect_py_files(branch_path: Path, include_init: bool = False) -> List[Dict[str, str]]:
    """Collect auditable .py files from apps/, respecting ignore patterns.

    __init__.py package markers are excluded by default — most checkers are
    content-focused (dead code, naming, nesting) and __init__.py is typically
    boilerplate. Pass include_init=True for import-statement checkers, where a
    real cross-handler import hiding in a package marker must not go unseen.

    This is the audit's CORPUS, not its applicability: every file here is
    production source, and which checkers actually run against it is decided
    per checker by applicability.applies_to_file(). is_retired_path() is
    applied on top of the ignore patterns because those match on a substring
    of the whole path ("/.archive/"), which never matches on Windows.
    """
    apps_dir = branch_path / "apps"
    if not apps_dir.exists():
        return []
    root = branch_path.resolve()
    ign = ignore_handler.get_audit_ignore_patterns()
    ignore_entries = ignore_handler.load_ignore_entries(branch_path)
    return [
        {"file": str(f), "name": f.name, "rel": _rel_path(f, root)}
        for f in apps_dir.rglob("*.py")
        if (include_init or f.name != "__init__.py")
        and not is_disabled_file(f.name)
        and not is_throwaway_path(str(f))
        and not applicability.is_retired_path(str(f))
        and not any(p in str(f).lower() for p in ign)
        and not ignore_handler.is_seedgo_ignored(str(f), branch_path, ignore_entries)
    ]


def _declared_input_files(branch_path: Path, checkers: Dict[str, Any] | None, attribute: str) -> List[Path]:
    """Existing files matching one declaration channel's globs.

    Globs are relative to the branch root with ``{branch}`` standing in for
    the branch directory name, so the cache hardcodes no path: a new
    branch_level checker declares its inputs and invalidation follows.

    Only the declaration is watched -- nothing widens incidentally.

    Directories ARE included, because trinity's File set group scores stray
    DIRECTORIES as well as files; leaving them out made the one stray shape
    the ruling is about invisible to the cache, so a branch growing a stray
    directory read 100 on cached audits until someone ran --full. The caller
    watches them by PRESENCE -- a directory's mtime moves whenever any child
    changes, and those children are already tracked as their own entries.

    Args:
        branch_path: Branch root.
        checkers: Discovered checker modules, or None.
        attribute: Declaration attribute to read off each module.

    Returns:
        Matching paths, files and directories, deduplicated and sorted.
    """
    if not checkers:
        return []
    found: set[Path] = set()
    for module in checkers.values():
        for pattern in getattr(module, attribute, ()) or ():
            resolved = pattern.replace("{branch}", branch_path.name)
            found.update(branch_path.glob(resolved))
    return sorted(found)


def _collect_watch_files(branch_path: Path, checkers: Dict[str, Any] | None = None) -> List[Dict[str, str]]:
    """Union of every file whose content can change audit output.

    Superset of _collect_py_files(include_init=True): also includes
    README.md (read by readme_check/readme_quality_check) and every
    tests/**/*.py file (read by test_map's scan_branch). Neither lives
    under apps/, so without this the fingerprint set never marks the
    branch dirty on a README- or tests-only edit and a stale cached
    result gets served forever. .seedgo/bypass.json and .seedgoignore
    files are deliberately NOT included here — they're already covered
    by compute_bypass_stamp()'s separate whole-branch stamp-bust.

    Branch_level checkers declare their own inputs, which live outside apps/
    and so were invisible here (ruling 6). Two channels, because the two
    checkers need different things:

      * ``BRANCH_INPUTS`` -- CONTENT matters. trinity reads and scores the
        bytes of ``.trinity/*``, so an edit must bust the cache. Directories
        matched by such a glob are watched by presence instead, because the
        File set group scores a stray DIRECTORY's existence, not its bytes.
      * ``BRANCH_INPUT_NAMES`` -- PRESENCE only. json_handler scores triplet
        completeness, i.e. which filenames exist, and never reads them. Those
        files include the checkers' own ``*_log.json``, written DURING the
        audit -- fingerprinting their content would mark every branch dirty on
        every run and quietly disable the cache. Add and delete still bust it.

    Also fingerprints {branch}_json/custom_config/ entries: the audit's
    custom_config info line names those files, so an operator adding or
    removing one must mark the branch dirty — otherwise a cache hit keeps
    reporting the old list. Only the name/mtime/size is read; the content
    of an operator config file is never audited.
    """
    root = branch_path.resolve()
    files = _collect_py_files(branch_path, include_init=True)
    readme = branch_path / "README.md"
    if readme.exists():
        files.append({"file": str(readme), "name": readme.name, "rel": _rel_path(readme, root)})
    tests_dir = branch_path / "tests"
    if tests_dir.exists():
        files.extend({"file": str(f), "name": f.name, "rel": _rel_path(f, root)} for f in tests_dir.rglob("*.py"))
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
                # Presence only: existence is what the File set group scores,
                # and a directory mtime would re-report every child edit.
                entry["presence_only"] = "1"
            files.append(entry)
    for f in _declared_input_files(branch_path, checkers, "BRANCH_INPUT_NAMES"):
        rel = _rel_path(f, root)
        if rel not in seen:
            seen.add(rel)
            files.append({"file": str(f), "name": f.name, "rel": rel, "presence_only": "1"})
    return files


def _collect_branch_info(checkers: Dict[str, Any], branch_path: Path, branch_name: str) -> List[Dict[str, str]]:
    """Gather non-scored signpost lines from checkers exposing check_branch_info().

    A separate channel from violations on purpose: info lines carry no score
    and no pass/fail, so a checker can surface context (e.g. operator-owned
    custom_config/ files it deliberately does NOT audit) with no way to move
    a branch's number. Nothing here is ever merged into scores.

    Bypass hygiene is reported here directly rather than through a checker: an
    inert rule belongs to no single standard, and reporting it as a violation
    would score a branch down for housekeeping.
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

    A third channel, below violations and below info lines: an observation
    carries a would-be score and is never merged into scores[], never counted
    in the average, and never turned into a violation. It exists so a
    de-scored check can keep RUNNING and producing evidence while the ruling
    on whether it should score again is still open — running it on the
    scoring lane "just to see" is how a runtime-state reading ends up moving
    a branch's number.

    Called with bypass_rules by keyword, exactly as the post-check lane calls
    check_branch_post: an observe hook that does not accept it is a defect,
    and it now says so in the reading instead of vanishing into a log line.

    Every reading is written to seedgo_json/branch_observe_log.json (its own
    module log, so audit traffic cannot evict it) — one undated snapshot of
    runtime state is not evidence; a dated series is.
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
    """Extract per-file violations from a branch-level checker result.

    Branch-level checkers return checks with violation lists (e.g. 'unused',
    'dead_functions') containing {name, file, line} dicts. This groups them
    by file into the standard violation format for audit_display rendering.
    """
    standard_keys = {"name", "passed", "message", "score"}
    file_violations: dict[str, list[str]] = {}

    for check in result.get("checks", []):
        # Find any list-type key that holds violation items
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

    When rel is in unchanged_files and file_result_cache already holds a
    result for (rel, name), reuse it verbatim. Otherwise compute fresh via
    checker.check_module() and, when a cache dict was supplied, record the
    result back into it (regardless of whether anything was reused elsewhere)
    so the caller ends up with a complete map ready to persist. With both
    cache args left None (the default), this is byte-identical to a bare
    checker.check_module() call — zero behavior change for existing callers.
    """
    if rel is not None and unchanged_files is not None and file_result_cache is not None and rel in unchanged_files:
        cached = file_result_cache.get(rel, {}).get(name)
        if cached is not None:
            return cached
    r = checker.check_module(file_path, bypass_rules=bypass_rules)
    if rel is not None and file_result_cache is not None:
        file_result_cache.setdefault(rel, {})[name] = r
    return r


def _run_all_files(
    checker,
    name: str,
    files: List[Dict],
    bypass_rules: list,
    file_result_cache: Dict[str, Dict[str, Any]] | None = None,
    unchanged_files: set | None = None,
) -> tuple:
    """Run checker on every file. Returns (violations, scores).

    file_result_cache/unchanged_files let unchanged files reuse their prior
    result for this checker instead of recomputing — see _get_or_compute().
    """
    violations, scores, ff = [], [], getattr(checker, "FILE_FILTER", None)
    for fi in files:
        if ff and ff not in fi["name"]:
            continue
        try:
            r = _get_or_compute(
                checker, name, fi["file"], fi.get("rel"), bypass_rules, file_result_cache, unchanged_files
            )
        except Exception:
            logger.info("Checker %s failed on %s", name, fi["name"])
            continue
        score, checks = r.get("score", 0), r.get("checks", [])
        if checks and not any(w in c.get("message", "").lower() for c in checks for w in ("skipped", "not applicable")):
            scores.append(score)
        # Collect violations from ANY file with failing checks, regardless of
        # overall pass/fail.  The old gate (not r["passed"]) hid violations
        # from files scoring 75-99% — score dropped but nothing was reported.
        failed = [c for c in checks if not c.get("passed", False)]
        if failed:
            msgs = [c.get("message", "Unknown") for c in failed]
            v = {"file": fi["name"], "path": fi["file"], "score": score, "issues": msgs, "message": "; ".join(msgs)}
            violations.append(v)
    return violations, scores


def _load_diagnostics_checker():
    """Load diagnostics checker from handlers/diagnostics/ (shared infrastructure)."""
    diag_path = Path(__file__).resolve().parent.parent / "diagnostics" / "diagnostics_check.py"
    if not diag_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("diagnostics_check", diag_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        logger.info("Failed to load diagnostics checker from %s", diag_path)
        return None
    return mod


def _deprecated_patterns(branch_path: Path) -> list:
    """Deprecated DOCUMENTS/ directory check.

    Cheap enough to always recompute fresh — even on an incremental cache
    hit — since it's a directory-existence signal invisible to .py file
    fingerprinting (e.g. DOCUMENTS/ renamed to docs/ with no .py touched).
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

    Every axis the STAMP folds in must also discriminate the KEY, or the two
    runs share a slot: the stamp still catches the mismatch so the score is
    never wrong, but each run evicts the other and both go cold. That is
    exactly what happened - the key was the bare branch name while
    `current_stamp` already included the pack, so alternating `audit aipass`
    and `audit pytest_quality` meant a full fleet re-scan every time. Measured:
    restoring last_audit.json after one shadow cycle cost a cold scan.

    `no_bypass` had solved this shape already by putting the mode in the key.
    The pack simply never got the same treatment.

    The default pack keeps the BARE branch name so existing cache entries stay
    valid; suffixing everything would orphan the whole fleet's cache once, for
    no gain.

    Args:
        branch_name: The branch being audited.
        pack_path: Checker pack directory, or None for the default pack.
        no_bypass: True when the run had every bypass rule switched off.

    Returns:
        The cache key.
    """
    key = branch_name
    pack_name = pack_path.name.removesuffix("_standards") if pack_path is not None else DEFAULT_PACK_NAME
    if pack_name != DEFAULT_PACK_NAME:
        key = f"{key}::pack={pack_name}"
    if no_bypass:
        key = f"{key}::no-bypass"
    return key


def audit_branch(
    branch: Dict[str, str],
    bypass_rules: list,
    pack_path: Path | None = None,
    file_result_cache: Dict[str, Dict[str, Any]] | None = None,
    unchanged_files: set | None = None,
) -> Dict:
    """Audit a branch for standards compliance. Returns backward-compatible dict.

    file_result_cache/unchanged_files are the incremental-audit hooks (see
    audit_branch_incremental): when a file's rel path is in unchanged_files
    and a cached per-checker result already exists, that result is reused
    instead of recomputing. Left at their None defaults, behavior is
    byte-identical to a full audit — nothing here changes for existing callers.
    """
    entry_file, branch_path = branch["entry_file"], Path(branch["path"])
    entry_rel = _rel_path(Path(entry_file), branch_path.resolve())
    checkers, all_files = discover_checkers(pack_path), _collect_py_files(branch_path)
    files_with_init: List[Dict[str, str]] | None = None

    # Discover diagnostics checker from handlers/diagnostics/ (outside pack dirs)
    diag_mod = _load_diagnostics_checker()
    if diag_mod and hasattr(diag_mod, "check_branch") and "diagnostics" not in checkers:
        checkers["diagnostics"] = diag_mod

    results, scores, all_violations = {}, {}, {}

    for name, checker in checkers.items():
        scope = getattr(checker, "AUDIT_SCOPE", "entry_point")
        # Branch-level scope: call check_branch()
        if scope == "branch_level" or (not hasattr(checker, "check_module") and hasattr(checker, "check_branch")):
            try:
                r = checker.check_branch(str(branch_path), bypass_rules=bypass_rules)
                results[name] = r
                # A standard that reports not_applicable measured NOTHING, so it
                # never enters scores[]: a 0 would blame the branch for an
                # environment fact and a 100 would claim a measurement that did
                # not happen. It stays in results[] so the display and the
                # info channel can still say why it stood down.
                if r.get("not_applicable") is True:
                    logger.info("Branch-level checker %s is not applicable for %s", name, branch_path)
                else:
                    scores[name] = r.get("score", 0)
                all_violations[name] = _extract_branch_level_violations(r)
            except Exception as e:
                # A crashed checker scores 0, which is indistinguishable from an honest
                # 0 unless the result says so. Carry the error into checks[] so the
                # number always arrives with its reason attached.
                logger.info("Branch-level checker %s failed: %s", name, e)
                results[name] = {
                    "passed": False,
                    "score": 0,
                    "error": str(e),
                    "checks": [
                        {
                            "name": "Checker ran",
                            "passed": False,
                            "message": (
                                f"{name} checker crashed ({type(e).__name__}: {e}) - "
                                "score 0 is a failure to run, not a measured result"
                            ),
                        }
                    ],
                }
                scores[name] = 0
            continue
        # Per-file lanes only check files the standard applies to. Branch-level
        # checkers above are exempt because they walk the tree themselves —
        # test_quality's whole corpus is tests/, and nothing here could filter
        # it without also filtering it away.
        if not applicability.applies_to_file(checker, entry_file):
            continue
        # Entry-point: always run on entry file. Genuine entry_point-scope
        # checkers (readme_check, cli_ux_check, ...) skip the cache here:
        # AUDIT_SCOPE says where a result is REPORTED, not what a checker
        # reads, and e.g. readme_check reads README.md, a file outside
        # entry_file. So whenever audit_branch() runs at all (the branch is
        # dirty), they must execute fresh rather than risk serving a result
        # cached before some unrelated file changed — one file x ~30
        # checkers is sub-second, no perf reason to reuse it. all_files-scope
        # checkers get their real answer from the _run_all_files scan below
        # (which already recomputes/reuses correctly per file), so their
        # preliminary entry-file pass here may still use the normal cache path.
        try:
            if scope == "all_files":
                r = _get_or_compute(
                    checker, name, entry_file, entry_rel, bypass_rules, file_result_cache, unchanged_files
                )
            else:
                r = checker.check_module(entry_file, bypass_rules=bypass_rules)
                if file_result_cache is not None:
                    file_result_cache.setdefault(entry_rel, {})[name] = r
            results[name], scores[name] = r, r.get("score", 0)
        except Exception as e:
            logger.info("Entry-point checker %s failed: %s", name, e)
            results[name], scores[name] = {"passed": False, "score": 0, "error": str(e)}, 0
        # All-files scope: scan every .py file, override score with average
        if scope == "all_files" and all_files:
            scan_files = all_files
            if getattr(checker, "INCLUDE_INIT_FILES", False):
                if files_with_init is None:
                    files_with_init = _collect_py_files(branch_path, include_init=True)
                scan_files = files_with_init
            scan_files = [f for f in scan_files if applicability.applies_to_file(checker, f["file"])]
            v, s = _run_all_files(checker, name, scan_files, bypass_rules, file_result_cache, unchanged_files)
            all_violations[name] = v
            if s:
                avg_score = int(sum(s) / len(s))
                scores[name] = avg_score
                # Update results to reflect all-files findings
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

    # Dynamic post-checks: call check_branch_post() on any checker that implements it
    for name, checker in checkers.items():
        if hasattr(checker, "check_branch_post") and name in scores:
            try:
                pv, ps = checker.check_branch_post(str(branch_path), bypass_rules=bypass_rules)
                all_violations.setdefault(name, []).extend(pv)
                if ps:
                    scores[name] = int(sum(ps + [scores[name]]) / (len(ps) + 1))
            except Exception as e:
                # A post-check that raises did not measure anything, and the
                # bare except this replaces made that indistinguishable from a
                # clean pass: log_structure's post-check raised TypeError on
                # every branch on every run for months, and no audit ever said
                # so. Same doctrine as the branch-level lane above — the number
                # arrives with its reason attached — but the score is left
                # alone on purpose. The file lane already measured this
                # standard honestly; a crash in a supplementary check is a
                # defect in the CHECKER, and zeroing the branch for it would
                # move a number for a reason that has nothing to do with the
                # branch's code. So the score keeps its measured value and the
                # output carries, loudly, the fact that it is incomplete.
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

    # Custom function coverage scan (informational, not scored)
    try:
        test_map_result = scan_branch(str(branch_path))
    except Exception as e:
        logger.warning("Test map scan failed for %s: %s", branch["name"], e)
        test_map_result = None

    diag_result = results.get("diagnostics", {})
    output = {
        "branch": branch,
        "results": results,
        "scores": scores,
        "advisory_standards": advisory_standards,
        "average": avg,
        "deprecated_patterns": deprecated,
        "files_checked": len(all_files),
        "type_errors": diag_result.get("total_errors", 0),
        "type_error_files": diag_result.get("results", []),
        "test_map": test_map_result,
        "info_lines": info_lines,
        # Observe-only: readings with a would-be score attached. Deliberately
        # NOT folded into scores/average — see _collect_branch_observations.
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

    Output is byte-equivalent to audit_branch() on the same tree — this only
    decides WHAT needs recomputing, never HOW; every actual check still runs
    through audit_branch()'s unmodified code paths.

    - Cold cache / --full / checker-pack or bypass/ignore rules changed:
      full audit_branch() (still populates the per-file cache for next time).
    - Branch clean (no added/changed/deleted files): serve the prior full
      output straight from cache, zero checker executions.
    - Branch dirty: audit_branch() re-runs with file_result_cache/
      unchanged_files so unchanged files reuse cached per-file results and
      only added/changed files actually execute. Branch-level checkers,
      diagnostics, post-checks, and test_map always re-run whole-branch on
      any change (cross-file attribution — DPLAN-0275 re-run matrix).

    Accepted staleness window (DPLAN-0275 §8 HIGH): diagnostics/pyright
    results are cached per-branch and only refreshed when that branch is
    itself dirty. The editable install lets pyright resolve imports across
    branches, so a signature change in branch A can introduce type errors
    in an untouched, clean branch B — B's cached diagnostics stay stale
    until B is touched or `--full` is used. This is deliberate: busting
    diagnostics on any-branch-dirty would gut the fast path (pyright is
    most of the ~5 minute fleet cost). CI's always-full audit is the backstop.

    no_bypass (--no-bypass) audits with every bypass rule switched off. It
    empties bypass_rules itself so the flag and the rules can never disagree —
    a stamp that claimed "no bypasses" over an audit that applied them would be
    a lie told by the cache. The two modes are stamped AND keyed apart, so
    neither is ever served the other's score, and neither evicts the other:
    publishing both numbers is routine, and a shared key would mean a
    guaranteed full re-scan every time either one is refreshed.
    """
    if no_bypass:
        bypass_rules = []
    branch_name, branch_path = branch["name"], Path(branch["path"])
    resolved_pack_path = (
        pack_path if pack_path is not None else Path(__file__).resolve().parent.parent / "aipass_standards"
    )
    cache_key = cache_key_for(branch_name, pack_path, no_bypass=no_bypass)
    diag_path = Path(__file__).resolve().parent.parent / "diagnostics" / "diagnostics_check.py"

    cache = incremental_cache.load_cache()
    branch_entry = incremental_cache.get_branch_entry(cache, cache_key)
    stamp = incremental_cache.current_stamp(branch_path, resolved_pack_path, diag_path, no_bypass=no_bypass)

    watch_files = _collect_watch_files(branch_path, discover_checkers(pack_path))
    current_fp = incremental_cache.collect_fingerprints(watch_files)

    if not force_full and branch_entry and branch_entry.get("stamp") == stamp:
        cached_files_doc = branch_entry.get("files", {})
        cached_fp = {rel: v.get("fp") for rel, v in cached_files_doc.items()}
        added, changed, deleted, unchanged = incremental_cache.diff_fileset(cached_fp, current_fp)

        if not (added or changed or deleted):
            output = copy.deepcopy(branch_entry.get("output", {}))
            output["deprecated_patterns"] = _deprecated_patterns(branch_path)
            # Observations read live runtime state, so a cached one is a
            # reading of a moment that has already passed, served as if it
            # were current. Same reason _deprecated_patterns is recomputed
            # here. Cheap (~50ms incl. checker discovery) and it cannot touch
            # a score — nothing below re-derives scores or the average.
            output["observations"] = _collect_branch_observations(
                discover_checkers(pack_path), branch_path, branch_name, bypass_rules
            )
            output["_cache_hit"] = True
            return output

        file_result_cache = {rel: dict(v.get("results", {})) for rel, v in cached_files_doc.items()}
    else:
        # Cold cache / --full / pack or bypass stamp bust: nothing to reuse.
        unchanged = set()
        file_result_cache = {}

    output = audit_branch(
        branch, bypass_rules, pack_path=pack_path, file_result_cache=file_result_cache, unchanged_files=unchanged
    )

    new_files_doc = {rel: {"fp": current_fp[rel], "results": file_result_cache.get(rel, {})} for rel in current_fp}
    incremental_cache.set_branch_entry(cache, cache_key, {"stamp": stamp, "files": new_files_doc, "output": output})
    incremental_cache.save_cache(cache)
    output["_cache_hit"] = False
    return output
