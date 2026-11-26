# =================== AIPass ====================
# Name: grouping.py
# Description: Groups for the audit grid, per-rule scores, and the pack_registry row
# Version: 1.0.0
# Created: 2026-11-26
# Modified: 2026-11-26
# =============================================

"""Groups for the audit grid, per-rule scores, and the pack_registry row.

A pack registers its checkers in ``groups.py`` (``GROUPS``: group name to row names, and
``AUDIT_ROWS``: rows the audit adds that no ``*_check.py`` backs). A pack without that file prints
as one group named after the pack. A rule is one named check inside a checker's result; its score
is the share of judged results where that check passed.
"""

import importlib.util
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from aipass.sentry.apps.handlers.json import json_handler

REGISTRY_FILE = "groups.py"
REGISTRY_ROW = "pack_registry"
UNGROUPED = "ungrouped"
_GROUP_NAME = re.compile(r"^[a-z]+$")


def load_registry(pack_dir: Path) -> Tuple[Dict[str, List[str]], frozenset]:
    """The pack's (GROUPS, AUDIT_ROWS); empty when the pack has no registry file."""
    path = pack_dir / REGISTRY_FILE
    if not path.is_file():
        return {}, frozenset()
    spec = importlib.util.spec_from_file_location(f"{pack_dir.name}_groups", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"pack registry {path} has no import spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.GROUPS), frozenset(getattr(module, "AUDIT_ROWS", ()))


def group_choices(pack_dir: Path) -> List[str]:
    """The group names a registered pack prints under, alphabetical; empty for a pack with no registry."""
    groups, _rows = load_registry(Path(pack_dir))
    return sorted({*groups, UNGROUPED}) if groups else []


def group_rows(scores: Dict[str, Any], pack_dir: Path) -> Dict[str, List[str]]:
    """Every scored row under its group, groups and rows alphabetical; an unregistered row under ``ungrouped``."""
    groups, _rows = load_registry(pack_dir)
    if not groups:
        groups = {pack_dir.name.removesuffix("_standards"): sorted(scores)}
    owner = {row: group for group, rows in groups.items() for row in rows}
    out: Dict[str, List[str]] = {}
    for row in sorted(scores):
        out.setdefault(owner.get(row, UNGROUPED), []).append(row)
    return dict(sorted(out.items()))


def registry_problems(pack_dir: Path, loaded: set) -> List[str]:
    """Why the pack's registry disagrees with its checker files; empty when every file is registered once."""
    groups, audit_rows = load_registry(pack_dir)
    files = {path.stem.removesuffix("_check") for path in pack_dir.glob("*_check.py")}
    if not groups:
        return [f"{REGISTRY_FILE} missing: {len(files)} checker files registered under no group"]
    problems = [f"group '{group}' is not one lowercase word" for group in groups if not _GROUP_NAME.match(group)]
    registered: Dict[str, List[str]] = {}
    for group, rows in groups.items():
        for row in rows:
            registered.setdefault(row, []).append(group)
    names = set(registered)
    problems += [f"{row} registered in {len(gs)} groups" for row, gs in sorted(registered.items()) if len(gs) > 1]
    problems += [f"{row}_check.py is registered in no group" for row in sorted(files - names)]
    problems += [f"{row} is registered but no {row}_check.py exists" for row in sorted(names - files - audit_rows)]
    problems += [f"{row}_check.py has no check_module or check_branch" for row in sorted(files - loaded)]
    json_handler.log_operation("pack_registry_checked", {"pack": pack_dir.name, "problems": len(problems)})
    return problems


def registry_result(problems: List[str]) -> Dict[str, Any]:
    """The pack_registry row: 100 with nothing wrong, 0 with any problem, each problem a failed check."""
    if not problems:
        checks = [{"name": REGISTRY_ROW, "passed": True, "message": "every checker file is registered under one group"}]
        return {"passed": True, "score": 100, "checks": checks}
    checks = [{"name": REGISTRY_ROW, "passed": False, "message": problem} for problem in problems]
    return {"passed": False, "score": 0, "checks": checks}


def registry_stood_down() -> Dict[str, Any]:
    """The pack_registry row on a branch that does not hold the pack: consulted, measuring nothing."""
    message = "this branch holds no checker pack; the registry is judged on the branch that does"
    checks = [{"name": REGISTRY_ROW, "passed": True, "message": message}]
    return {"passed": True, "score": 0, "not_applicable": True, "checks": checks}


def tally(counts: Dict[str, List[int]], checks: List[Dict[str, Any]]) -> None:
    """Add one judged result's checks to ``counts`` (rule name to [passed, judged]); each name once per result; an unnamed check is no rule."""
    seen: Dict[str, bool] = {}
    for check in checks:
        name = str(check.get("name") or "")
        if not name:
            continue
        seen[name] = seen.get(name, True) and bool(check.get("passed", True))
    for name, passed in seen.items():
        entry = counts.setdefault(name, [0, 0])
        entry[0] += passed
        entry[1] += 1


def rule_scores(counts: Dict[str, List[int]]) -> Dict[str, int]:
    """Each rule's percentage, rules alphabetical; only a checker with more than one rule has rule rows."""
    if len(counts) < 2:
        return {}
    return {name: int(100 * passed / judged) for name, (passed, judged) in sorted(counts.items()) if judged}
