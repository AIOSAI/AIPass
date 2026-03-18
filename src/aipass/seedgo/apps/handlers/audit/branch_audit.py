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
from aipass.seedgo.apps.handlers.bypass import ignore_handler
from aipass.seedgo.apps.handlers.json import json_handler

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
    return [{"file": str(f), "name": f.name} for f in apps_dir.rglob("*.py")
            if f.name != "__init__.py" and not any(p in str(f).lower() for p in ign)]

def _run_all_files(checker, name: str, files: List[Dict], bypass_rules: list) -> tuple:
    """Run checker on every file. Returns (violations, scores)."""
    violations, scores, ff = [], [], getattr(checker, "FILE_FILTER", None)
    for fi in files:
        if ff and ff not in fi["name"]:
            continue
        try:
            r = checker.check_module(fi["file"], bypass_rules=bypass_rules)
        except Exception:
            continue
        score, checks = r.get("score", 0), r.get("checks", [])
        if checks and not any(w in c.get("message", "").lower() for c in checks
                              for w in ("skipped", "not applicable")):
            scores.append(score)
        if not r.get("passed", True):
            failed = [c for c in checks if not c.get("passed", False)]
            if failed:
                msgs = [c.get("message", "Unknown") for c in failed]
                v = {"file": fi["name"], "path": fi["file"], "score": score, "issues": msgs}
                if name == "modules":
                    v["message"] = "; ".join(msgs)
                violations.append(v)
    return violations, scores

def _log_structure_post_checks(branch_path: Path) -> tuple:
    """Branch-level log structure checks. Returns (violations, scores).

    Two-tier model:
      - ``system_logs/`` at repo root is managed by prax (runtime dispatch).
        Having many system logs and few local logs is *normal*.
      - ``logs/`` at branch root holds local-only logs. Flat placement is
        fine — the standard does not prescribe internal organisation.
    """
    violations: list[dict] = []
    scores: list[int] = []

    in_dirs = [f for f in branch_path.rglob("*.log") if f.parent.name == "logs"]

    # Check: Verify system_logs/ exists when the branch produces logs.
    # The two-tier model expects prax to dispatch runtime logs to
    # system_logs/.  A mismatch only matters when the branch has NO
    # system logs at all despite having local logs (potential prax
    # misconfiguration).
    repo = next(
        (p for p in [branch_path] + list(branch_path.parents)
         if (p / "AIPASS_REGISTRY.json").is_file()),
        None,
    )
    if repo and (repo / "system_logs").is_dir():
        sd = repo / "system_logs"
        system_count = len(list(sd.glob(f"{branch_path.name}_*.log")))
        if in_dirs and system_count == 0:
            # Branch has local logs but zero system logs -- prax may not
            # be dispatching for this branch.
            scores.append(50)
            violations.append({
                "file": "(branch-level)", "path": str(sd), "score": 50,
                "issues": [f"Branch has {len(in_dirs)} local log(s) but 0 system logs — prax dispatch may be misconfigured"],
            })
        else:
            scores.append(100)

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
            except Exception as e:
                results[name], scores[name] = {"passed": False, "score": 0, "error": str(e)}, 0
            continue
        # Entry-point: always run on entry file
        try:
            r = checker.check_module(entry_file, bypass_rules=bypass_rules)
            results[name], scores[name] = r, r.get("score", 0)
        except Exception as e:
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
                    results[name] = {"passed": avg_score >= 75, "checks": all_failed, "score": avg_score, "standard": name.upper()}

    # Log structure post-checks (audit-level, not in any checker)
    if "log_structure" in scores:
        pv, ps = _log_structure_post_checks(branch_path)
        all_violations.setdefault("log_structure", []).extend(pv)
        if ps:
            scores["log_structure"] = int(sum(ps + [scores["log_structure"]]) / (len(ps) + 1))

    json_handler.log_operation("branch_audit_completed", {"branch": branch["name"], "checkers": len(checkers)})
    avg = int(sum(scores.values()) / len(scores)) if scores else 0

    # Deprecated DOCUMENTS/ directory check
    deprecated = []
    if (branch_path / "DOCUMENTS").is_dir():
        deprecated.append({"type": "directory", "old": "DOCUMENTS/", "new": "docs/",
                           "path": str(branch_path / "DOCUMENTS"), "message": "Rename DOCUMENTS/ to docs/"})

    diag_result = results.get("diagnostics", {})
    output = {"branch": branch, "results": results, "scores": scores, "average": avg,
              "deprecated_patterns": deprecated, "files_checked": len(all_files),
              "type_errors": diag_result.get("total_errors", 0), "type_error_files": diag_result.get("results", [])}
    for name in checkers:
        output[f"{name}_violations"] = all_violations.get(name, [])
    return output
