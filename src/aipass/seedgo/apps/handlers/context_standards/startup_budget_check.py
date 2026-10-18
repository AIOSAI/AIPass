# =================== AIPass ====================
# Name: startup_budget_check.py
# Description: Startup Budget Standards Checker — the greeting cost of one citizen
# Version: 1.1.0
# Created: 2026-09-15
# Modified: 2026-10-17
# =============================================

"""Startup Budget Standards Checker — what a greeting costs, in characters.

Reference: startup_budget.md
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

# Guarded: discover_checkers() drops a pack module that raises on exec, so a
# bare import failure would delete the standard instead of printing the error row.
# Caps are read off the module at call time; a `from ... import` binding is a copy.

try:
    from aipass.hooks.apps.modules import grounding_content as hooks_grounding
except Exception as exc:  # an unimportable owner is a row, not a dead pack
    hooks_grounding = None
    _HOOKS_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    _HOOKS_IMPORT_ERROR = ""

try:
    from aipass.prax.apps.modules import dashboard as prax_dashboard
except Exception as exc:
    prax_dashboard = None
    _PRAX_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    _PRAX_IMPORT_ERROR = ""

AUDIT_SCOPE = "branch_level"

#: branch_audit keeps every ADVISORY standard out of the gating average.
ADVISORY = True

STANDARD_NAME = "startup_budget"

#: The incremental cache watches these; without them a README edit never marks
#: the branch dirty and the cached row is served past the edit.
BRANCH_INPUTS = (
    "README.md",
    ".aipass/aipass_local_prompt.md",
    ".trinity/*.json",
    "DASHBOARD.local.json",
)

#: Weights sum to 100; _weighted_score() shares an unmeasured group's weight.
GROUP_WEIGHTS: Dict[str, int] = {
    "README": 30,
    "Branch prompt": 25,
    "Trinity files": 25,
    "Dashboard": 20,
}

README_REL = "README.md"
PROMPT_REL = ".aipass/aipass_local_prompt.md"

#: The pack.json caps key for every docs/*.md page; docs_page_check scores it.
DOCS_PAGE_KEY = "docs/*.md"
DASHBOARD_REL = "DASHBOARD.local.json"
TRINITY_DIR = ".trinity"

#: The names are @memory's own file_budgets keys.
TRINITY_FILES: Tuple[Tuple[str, str], ...] = (
    ("local.json", "LOCAL"),
    ("observations.json", "OBS"),
    ("passport.json", "PASSPORT"),
)

MEASURED_FILES: Tuple[Tuple[str, str], ...] = (
    (README_REL, "README"),
    (PROMPT_REL, "PROMPT"),
    *((f"{TRINITY_DIR}/{name}", label) for name, label in TRINITY_FILES),
    (DASHBOARD_REL, "DASH"),
)

#: Carried in the row so the display arm needs no knowledge of this pack.
TABLE_TITLE = "STARTUP BUDGET (ADVISORY) — chars (wc -m) against each layer's cap"

#: Over-cap footnotes per branch; the overflow is announced, never silent.
MAX_NOTES = 6

_STATE_UNDER = "under"
_STATE_OVER = "over"
_STATE_ABSENT = "absent"
_STATE_ERROR = "error"


def _repo_root() -> Path | None:
    """Walk up from this file to the repo root — the dir holding src/aipass.

    module_file(), not Path.resolve(): resolve() reads the cwd on Windows.
    """
    for parent in module_file(__file__).parents:
        if (parent / "src" / "aipass").is_dir():
            return parent
    logger.warning("startup_budget: cannot locate repo root from %s", __file__)
    return None


def memory_config_path() -> Path | None:
    """@memory's memory.config.json — the file that owns the .trinity caps.

    Same spelling as trinity_check; public as the seam tests point at a broken config.
    """
    root = _repo_root()
    if root is None:
        return None
    return root / "src" / "aipass" / "memory" / "memory_json" / "custom_config" / "memory.config.json"


def pack_manifest_path() -> Path:
    """This pack's own ``pack.json`` — where seedgo keeps the README cap."""
    return module_file(__file__).parent / "pack.json"


def external_inputs() -> List[Path]:
    """The files OUTSIDE the audited branch whose content decides the score.

    The incremental cache watches these, so an owner moving a cap re-scores every
    branch. Spelled from the repo root: prax's operations.py defines
    DASHBOARD_CHAR_BUDGET and is never imported here, only its re-export.
    """
    root = _repo_root()
    if root is None:
        return []
    fleet = root / "src" / "aipass"
    candidates = [
        fleet / "memory" / "memory_json" / "custom_config" / "memory.config.json",
        fleet / "hooks" / "apps" / "modules" / "grounding_content.py",
        fleet / "prax" / "apps" / "handlers" / "dashboard" / "operations.py",
        fleet / "prax" / "apps" / "modules" / "dashboard.py",
    ]
    return [path for path in candidates if path.is_file()]


def _as_cap(value: Any) -> int | None:
    """*value* as a usable cap, or None. ``True`` is not a cap of 1."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def readme_cap() -> Tuple[int | None, str]:
    """seedgo's own README cap, read from this pack's pack.json.

    Config, not a constant: the CI ratchet moves it without importing Python.
    """
    return _pack_cap(README_REL)


def docs_page_cap() -> Tuple[int | None, str]:
    """The per-page cap on every ``docs/*.md``, read from this pack's pack.json."""
    return _pack_cap(DOCS_PAGE_KEY)


def _pack_cap(key: str) -> Tuple[int | None, str]:
    """``caps[key].max_chars`` from this pack's pack.json, or the reason it is not there."""
    path = pack_manifest_path()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        logger.warning("startup_budget: cannot read %s: %s", path, exc)
        return None, f"seedgo: cannot read its own {path.name} ({type(exc).__name__}: {exc}) — cap not measured"
    caps = manifest.get("caps") if isinstance(manifest, dict) else None
    entry = caps.get(key) if isinstance(caps, dict) else None
    cap = _as_cap(entry.get("max_chars")) if isinstance(entry, dict) else None
    if cap is None:
        return None, f"seedgo: {path.name} has no caps['{key}'].max_chars — cap not measured"
    return cap, ""


def _cap_from_module(module: Any, name: str, owner: str, import_error: str, dotted: str) -> Tuple[int | None, str]:
    """One borrowed cap, read off the owner's live module by name at call time."""
    if module is None:
        return None, f"{owner}: cannot import {dotted} ({import_error}) — cap not measured"
    cap = _as_cap(getattr(module, name, None))
    if cap is None:
        return None, f"{owner}: {dotted}.{name} is missing or not a positive int — cap not measured"
    return cap, ""


def prompt_cap() -> Tuple[int | None, str]:
    """The branch-prompt cap, read from @hooks — the branch that enforces it."""
    return _cap_from_module(
        hooks_grounding,
        "BRANCH_CHAR_BUDGET",
        "hooks",
        _HOOKS_IMPORT_ERROR,
        "aipass.hooks.apps.modules.grounding_content",
    )


def dashboard_cap() -> Tuple[int | None, str]:
    """The dashboard cap, read from @prax's exported name."""
    return _cap_from_module(
        prax_dashboard,
        "DASHBOARD_CHAR_BUDGET",
        "prax",
        _PRAX_IMPORT_ERROR,
        "aipass.prax.apps.modules.dashboard",
    )


def trinity_budgets() -> Tuple[Dict[str, Any] | None, str]:
    """@memory's whole-file budgets for the three .trinity files.

    Read from the config, not @memory's loader, which serves a regeneration seed
    when the key is absent (startup_budget.md, "Read, never copied").
    """
    path = memory_config_path()
    if path is None:
        return None, "memory: cannot locate the repo root, so memory.config.json cannot be read — caps not measured"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        logger.warning("startup_budget: memory.config.json unreadable at %s: %s", path, exc)
        return None, (
            f"memory: {path.name} is unreadable ({type(exc).__name__}: {exc}) — .trinity caps not measured; "
            "the loader's regeneration seed is NOT scored"
        )
    section = config.get("entry_limits") if isinstance(config, dict) else None
    budgets = section.get("file_budgets") if isinstance(section, dict) else None
    if not isinstance(budgets, dict) or not budgets:
        return None, (
            f"memory: {path.name} publishes no entry_limits.file_budgets — .trinity caps not measured; "
            "the loader's regeneration seed is NOT scored"
        )
    return budgets, ""


def measure_chars(path: Path) -> Tuple[int | None, str]:
    """A file's size in CHARACTERS (``wc -m``, never ``st_size`` bytes), or why it has none."""
    if not path.is_file():
        return None, ""
    try:
        return len(path.read_text(encoding="utf-8")), ""
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("startup_budget: cannot read %s: %s", path, exc)
        return None, f"{type(exc).__name__}: {exc}"


def _cell(label: str, rel: str, chars: int | None, cap: int | None, state: str, detail: str = "") -> Dict[str, Any]:
    """One table cell — the shape the display arm renders and the artifact keeps."""
    return {"label": label, "path": rel, "chars": chars, "cap": cap, "state": state, "detail": detail}


def _measure_one(branch_path: Path, rel: str, label: str, cap: int | None, cap_error: str) -> Dict[str, Any]:
    """Measure one file against one cap and return its cell.

    An unreadable cap is an ERROR even when the file is absent, or it reads as a pass.
    """
    if cap is None:
        return _cell(label, rel, None, None, _STATE_ERROR, cap_error)
    chars, read_error = measure_chars(branch_path / rel)
    if read_error:
        return _cell(label, rel, None, cap, _STATE_ERROR, f"{rel} exists but cannot be read ({read_error})")
    if chars is None:
        return _cell(label, rel, None, cap, _STATE_ABSENT, f"{rel} is absent")
    state = _STATE_OVER if chars > cap else _STATE_UNDER
    return _cell(label, rel, chars, cap, state, "")


def _group_from_cells(name: str, cells: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Roll a group's cells into the check dict branch_audit stores; absent cells leave the denominator."""
    units = [cell for cell in cells if cell["state"] != _STATE_ABSENT]
    absent = [cell for cell in cells if cell["state"] == _STATE_ABSENT]
    if not units:
        return {
            "name": name,
            "passed": True,
            "score": None,
            "message": f"{name}: not measured — {', '.join(cell['path'] for cell in absent)} absent",
        }
    failed = [cell for cell in units if cell["state"] != _STATE_UNDER]
    score = int(round((len(units) - len(failed)) / len(units) * 100))
    parts = [_cell_sentence(cell) for cell in units]
    parts.extend(f"{cell['path']}: absent (not a violation)" for cell in absent)
    return {"name": name, "passed": not failed, "score": score, "message": f"{name} — " + "; ".join(parts)}


def _cell_sentence(cell: Dict[str, Any]) -> str:
    """One cell as the audit's per-check message says it; the per-string unit carries no ``chars``."""
    if cell["state"] == _STATE_ERROR:
        return f"{cell['path']}: ERROR — {cell['detail']}"
    if cell["chars"] is None:
        return f"{cell['path']}: {cell['detail']}"
    over_by = f" — OVER by {cell['chars'] - cell['cap']:,}" if cell["state"] == _STATE_OVER else ""
    return f"{cell['path']}: {cell['chars']:,}/{cell['cap']:,} chars{over_by}"


def _trinity_cells(branch_path: Path, budgets: Dict[str, Any] | None, budget_error: str) -> Tuple[list, list]:
    """Cells and over-cap notes for the three .trinity files.

    ``max_string_chars`` hits become footnotes and one extra scored unit.
    """
    cells: List[Dict[str, Any]] = []
    notes: List[str] = []
    for name, label in TRINITY_FILES:
        rel = f"{TRINITY_DIR}/{name}"
        if budgets is None:
            cells.append(_cell(label, rel, None, None, _STATE_ERROR, budget_error))
            continue
        spec = budgets.get(name)
        spec = spec if isinstance(spec, dict) else {}
        cap = _as_cap(spec.get("max_chars"))
        if cap is None:
            cells.append(
                _cell(label, rel, None, None, _STATE_ERROR, f"memory: file_budgets has no max_chars for {name}")
            )
            continue
        chars, read_error = measure_chars(branch_path / rel)
        if read_error:
            cells.append(_cell(label, rel, None, cap, _STATE_ERROR, f"{rel} exists but cannot be read ({read_error})"))
            continue
        if chars is None:
            cells.append(_cell(label, rel, None, cap, _STATE_ABSENT, f"{rel} is absent"))
            continue
        cells.append(_cell(label, rel, chars, cap, _STATE_OVER if chars > cap else _STATE_UNDER, ""))
        string_cap = _as_cap(spec.get("max_string_chars"))
        if string_cap is None:
            continue
        over_strings = _strings_over_cap((branch_path / rel).read_text(encoding="utf-8"), string_cap)
        cells.append(_string_cell(label, rel, string_cap, over_strings))
        notes.extend(
            f"{rel} {key or '<root>'} {length:,}/{string_cap:,} chars" for key, length in over_strings[:MAX_NOTES]
        )
        if len(over_strings) > MAX_NOTES:
            notes.append(f"{rel} +{len(over_strings) - MAX_NOTES} more strings over {string_cap:,}")
    return cells, notes


def _walk_strings(value: Any, path: str = "") -> List[Tuple[str, str]]:
    """Every string in a parsed JSON document, with its dotted path.

    Duplicates @memory's entry_limits._walk_strings: a cross-branch handler import is forbidden.
    """
    found: List[Tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(_walk_strings(child, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk_strings(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        found.append((path, value))
    return found


def _strings_over_cap(text: str, string_cap: int) -> List[Tuple[str, int]]:
    """Every string in *text* longer than *string_cap*, as (dotted path, chars).

    Unparseable yields nothing on purpose: the size is measured; trinity fails the parse.
    """
    try:
        data = json.loads(text)
    except ValueError as exc:
        logger.warning("startup_budget: cannot parse for the per-string cap: %s", exc)
        return []
    return [(path, len(value)) for path, value in _walk_strings(data) if len(value) > string_cap]


def _string_cell(label: str, rel: str, string_cap: int, over_strings: List[Tuple[str, int]]) -> Dict[str, Any]:
    """The per-string unit: scored, with no ``chars`` so the table folds it away."""
    if not over_strings:
        return _cell(
            f"{label}:str", rel, None, string_cap, _STATE_UNDER, f"every string within the {string_cap:,}-char cap"
        )
    longest = max(length for _key, length in over_strings)
    return _cell(
        f"{label}:str",
        rel,
        None,
        string_cap,
        _STATE_OVER,
        f"{len(over_strings)} string(s) over the {string_cap:,}-char per-string cap (longest {longest:,})",
    )


def measure_corpus(branch_path: Path | str) -> int:
    """How many startup files this branch actually has — the banner's number.

    Named by pack.json ``measured_by``, so the banner counts this pack's corpus.
    """
    root = Path(branch_path)
    return sum(1 for rel, _label in MEASURED_FILES if (root / rel).is_file())


def _weighted_score(checks: List[Dict[str, Any]]) -> int | None:
    """Weighted mean over the groups that measured something; None when none did."""
    scored = [check for check in checks if check["score"] is not None]
    if not scored:
        return None
    weight = sum(GROUP_WEIGHTS[check["name"]] for check in scored)
    if weight <= 0:
        return None
    total = sum(check["score"] * GROUP_WEIGHTS[check["name"]] for check in scored) / weight
    score = int(round(total))
    if score >= 100 and any(check["score"] < 100 for check in scored):
        return 99
    return score


def _not_applicable(branch: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """Neither 0 nor 100 — nothing on this branch could be measured."""
    reason = (
        f"startup_budget: NOT MEASURED on {branch} — none of "
        f"{', '.join(rel for rel, _label in MEASURED_FILES)} is present. "
        "Not scored and not gating; a branch that has these files and busts a cap still fails."
    )
    return {
        "standard": STANDARD_NAME.upper(),
        "score": None,
        "passed": None,
        "not_applicable": True,
        "advisory": True,
        "checks": [{"name": "Measurable", "passed": None, "score": None, "message": reason}],
        "fleet_row": row,
    }


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict[str, Any]:
    """Measure one branch's startup files against the caps their owners publish.

    ``bypass_rules`` is accepted for the scoring API and never read (no bypass by design).
    """
    root = Path(branch_path).resolve()
    branch = root.name

    readme_value, readme_error = readme_cap()
    prompt_value, prompt_error = prompt_cap()
    dash_value, dash_error = dashboard_cap()
    budgets, budget_error = trinity_budgets()

    readme_cells = [_measure_one(root, README_REL, "README", readme_value, readme_error)]
    prompt_cells = [_measure_one(root, PROMPT_REL, "PROMPT", prompt_value, prompt_error)]
    trinity_cells, notes = _trinity_cells(root, budgets, budget_error)
    dash_cells = [_measure_one(root, DASHBOARD_REL, "DASH", dash_value, dash_error)]

    checks = [
        _group_from_cells("README", readme_cells),
        _group_from_cells("Branch prompt", prompt_cells),
        _group_from_cells("Trinity files", trinity_cells),
        _group_from_cells("Dashboard", dash_cells),
    ]
    cells = [*readme_cells, *prompt_cells, *trinity_cells, *dash_cells]
    notes = [
        *(
            f"{cell['path']}: {cell['detail']}"
            for cell in cells
            if cell["state"] == _STATE_ERROR and not cell["detail"].startswith(cell["path"])
        ),
        *notes,
    ]
    row = {
        "branch": branch,
        "title": TABLE_TITLE,
        "cells": [cell for cell in cells if not cell["label"].endswith(":str")],
        "notes": notes,
    }

    score = _weighted_score(checks)
    if score is None:
        return _not_applicable(branch, row)

    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": score, "standard": STANDARD_NAME},
    )
    return {
        "standard": STANDARD_NAME.upper(),
        "score": score,
        "passed": score == 100,
        "advisory": True,
        "checks": checks,
        "fleet_row": row,
    }
