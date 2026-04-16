# =================== AIPass ====================
# Name: branch_audit.py
# Description: Branch Audit Handler
# Version: 2.0.0
# Created: 2026-03-05
# Modified: 2026-03-09
# =============================================
"""Branch Audit Handler — auto-discovers checkers from handlers/standards/ via glob."""

import importlib.util
from pathlib import Path
from typing import Any, Dict, List
from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass import ignore_handler
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.test_map.function_scanner import scan_branch


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


def _collect_py_files(branch_path: Path) -> List[Dict[str, str]]:
    """Collect auditable .py files from apps/, respecting ignore patterns."""
    apps_dir = branch_path / "apps"
    if not apps_dir.exists():
        return []
    ign = ignore_handler.get_audit_ignore_patterns()
    return [
        {"file": str(f), "name": f.name}
        for f in apps_dir.rglob("*.py")
        if f.name != "__init__.py" and not any(p in str(f).lower() for p in ign)
    ]


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


def _run_all_files(checker, name: str, files: List[Dict], bypass_rules: list) -> tuple:
    """Run checker on every file. Returns (violations, scores)."""
    violations, scores, ff = [], [], getattr(checker, "FILE_FILTER", None)
    for fi in files:
        if ff and ff not in fi["name"]:
            continue
        try:
            r = checker.check_module(fi["file"], bypass_rules=bypass_rules)
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


def audit_branch(branch: Dict[str, str], bypass_rules: list, pack_path: Path | None = None) -> Dict:
    """Audit a branch for standards compliance. Returns backward-compatible dict."""
    entry_file, branch_path = branch["entry_file"], Path(branch["path"])
    checkers, all_files = discover_checkers(pack_path), _collect_py_files(branch_path)

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
                results[name], scores[name] = r, r.get("score", 0)
                all_violations[name] = _extract_branch_level_violations(r)
            except Exception as e:
                logger.info("Branch-level checker %s failed: %s", name, e)
                results[name], scores[name] = {"passed": False, "score": 0, "error": str(e)}, 0
            continue
        # Entry-point: always run on entry file
        try:
            r = checker.check_module(entry_file, bypass_rules=bypass_rules)
            results[name], scores[name] = r, r.get("score", 0)
        except Exception as e:
            logger.info("Entry-point checker %s failed: %s", name, e)
            results[name], scores[name] = {"passed": False, "score": 0, "error": str(e)}, 0
        # All-files scope: scan every .py file, override score with average
        if scope == "all_files" and all_files:
            v, s = _run_all_files(checker, name, all_files, bypass_rules)
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
                pv, ps = checker.check_branch_post(str(branch_path))
                all_violations.setdefault(name, []).extend(pv)
                if ps:
                    scores[name] = int(sum(ps + [scores[name]]) / (len(ps) + 1))
            except Exception:
                logger.info("Post-check %s failed for branch %s", name, branch["name"])

    json_handler.log_operation("branch_audit_completed", {"branch": branch["name"], "checkers": len(checkers)})
    avg = int(sum(scores.values()) / len(scores)) if scores else 0

    # Deprecated DOCUMENTS/ directory check
    deprecated = []
    if (branch_path / "DOCUMENTS").is_dir():
        deprecated.append(
            {
                "type": "directory",
                "old": "DOCUMENTS/",
                "new": "docs/",
                "path": str(branch_path / "DOCUMENTS"),
                "message": "Rename DOCUMENTS/ to docs/",
            }
        )

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
        "average": avg,
        "deprecated_patterns": deprecated,
        "files_checked": len(all_files),
        "type_errors": diag_result.get("total_errors", 0),
        "type_error_files": diag_result.get("results", []),
        "test_map": test_map_result,
    }
    for name in checkers:
        output[f"{name}_violations"] = all_violations.get(name, [])
    return output
