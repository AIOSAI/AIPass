# =================== AIPass ====================
# Name: startup_budget_check.py
# Description: Startup Budget Standards Checker — the greeting cost of one citizen
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""Startup Budget Standards Checker — what a greeting costs, in characters.

THE INSTRUMENT NOBODY HAD. Every context regression AIPass has taken was found
by Patrick reading a percentage on a status line. Seventeen of eighteen branches
read a 13k–96k-char README at every greeting and no seedgo rule measured a
README, a branch prompt, a ``.trinity`` file or a dashboard: the only size rules
in the aipass pack are Python LINE counts. Boardroom thread 16 converged on
2026-09-15 (DPLAN-0347): every grounding layer gets one cap, one owner, and
seedgo owns the measurement. This is that measurement.

UNITS ARE CHARACTERS. ``len(path.read_text(encoding="utf-8"))`` — what ``wc -m``
reports. Never bytes, never tokens. The boardroom corrected bytes-for-chars
three times in one afternoon, so it is said here once more: a README of 23,478
chars is 23,498 bytes, and a rule that quotes the second number is measuring the
encoding, not the greeting.

ONE CAP, ONE OWNER — READ, NEVER COPIED
---------------------------------------
Five of the six numbers below belong to another branch. This checker imports
the owner's module and reads the owner's name at CALL time; it carries no copy
of any of them, so an owner moving its cap moves this row on the next audit
with nothing to edit here.

===================================  =========  ==============================
file                                 cap        owner and where it is read
===================================  =========  ==============================
README.md                            10,000     seedgo — ``pack.json`` ``caps``
.aipass/aipass_local_prompt.md        9,000     hooks — ``BRANCH_CHAR_BUDGET``
.trinity/local.json                  25,000     memory — ``file_budgets``
.trinity/observations.json           15,000     memory — same config key
.trinity/passport.json          6,000 + 600     memory — same (per-string too)
DASHBOARD.local.json                  6,000     prax — ``DASHBOARD_CHAR_BUDGET``
===================================  =========  ==============================

The README cap is seedgo's own, so it lives in seedgo's own config — this
pack's ``pack.json`` — and not as a constant in this file: Phase 5's per-file CI
ratchet has to be able to read and move that number without importing Python.
Patrick ruled 10,000 at 16:02 on 2026-09-15 ("readme 10k and off from start
up"). The room had proposed 6,000 and FPLAN-0593 lines 179/221 still say 6,000;
those lines are stale, and the manifest says so beside the number.

FAIL HONESTLY — A MISSING CAP IS AN ERROR ROW, NEVER A DEFAULT
--------------------------------------------------------------
trinity_check's law, applied to borrowed numbers: a cap this checker cannot
read is reported as an ERROR naming the owner and the thing that is missing,
and the unit fails. There is no fallback constant anywhere in this file. A
remembered number that quietly replaces an owner's config is how "read, never
copy" becomes "copied once, then forgotten", and the row would go on printing a
confident green against a cap that no longer exists.

That applies to @memory's numbers with particular force. @memory publishes them
through ``entry_limits.load_file_budgets()`` (1.11.0, :971), which delegates to
``config_loader.get_file_budgets()``, which reads ``entry_limits.file_budgets``
out of ``memory.config.json`` — and which serves a REGENERATION SEED when that
key is absent, so @memory keeps working with a broken config. Right for
@memory; fatal for an auditor, which would then score the whole fleet against
numbers no config contains. Importing that function is also a cross-BRANCH
handler import, which seedgo's own handler independence standard forbids and
for which @memory publishes no ``modules/`` gateway. So this checker reads the
config key itself — the same file, the same key, no copy of a number — and an
unreadable or budget-less ``memory.config.json`` is the error row.

ABSENT IS NOT ZERO AND NOT A VIOLATION
--------------------------------------
``.trinity/`` and ``DASHBOARD.local.json`` are gitignored, and a branch may
genuinely not have a dashboard yet. A file that is not there is reported as
ABSENT and leaves its group's denominator; it is never counted as 0 chars (a
silent pass) and never as a violation (a blamed branch). A group with no
present file is not scored at all, and its weight is redistributed across the
groups that measured something. A branch where nothing at all could be measured
reports ``not_applicable`` — the third answer, neither 0 nor 100.

ADVISORY
--------
``ADVISORY = True``: branch_audit leaves this standard out of the gating
average (branch_audit.py:638). It scores, it prints, it gates nothing. A
checker that moved in one commit put 17 of 18 branches red on 2026-09-13; the
room's ruling is advisory first, then a per-file ratchet in CI once the numbers
have a week behind them (DPLAN-0347, "Advisory or gating").

WHAT THIS RULE DELIBERATELY DOES NOT CLAIM
------------------------------------------
It does not measure tokens, the injected kernel/navmap, integration prompts,
or the true cost of a greeting — it measures six files. It does not judge what
is IN them. It does not say a branch under every cap has a good README. And it
never writes: the diet is owner-run and this is the scoreboard (DPLAN-0347,
"Fleet README diet vehicle").
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

# -----------------------------------------------------------------------------
# OWNER MODULES
# -----------------------------------------------------------------------------
# Imported at module scope, the house idiom, but GUARDED: discover_checkers()
# drops a pack module that raises on exec, so a bare import failure here would
# delete the whole standard from the audit and the fleet would read a table that
# simply stopped existing. Guarded, the import failure becomes the error row it
# is, and it names the owner.
#
# The NAME is read off the module at call time rather than bound here
# (`from ... import BRANCH_CHAR_BUDGET`), and that is the whole "read, never
# copy" contract in one line: a binding taken at import is a copy with an
# owner's name on it, and the audit would go on printing it after the owner
# moved the cap.

try:
    from aipass.hooks.apps.modules import grounding_content as hooks_grounding
except Exception as exc:  # noqa: BLE001 - an unimportable owner is a row, not a dead pack
    hooks_grounding = None
    _HOOKS_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    _HOOKS_IMPORT_ERROR = ""

try:
    from aipass.prax.apps.modules import dashboard as prax_dashboard
except Exception as exc:  # noqa: BLE001
    prax_dashboard = None
    _PRAX_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    _PRAX_IMPORT_ERROR = ""


# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

#: Reports a number, gates nothing. Read by branch_audit.py:638, which keeps
#: every ADVISORY standard out of the branch's gating average.
ADVISORY = True

STANDARD_NAME = "startup_budget"

#: Branch-relative globs whose CONTENT decides this score. The incremental
#: cache watches what a branch_level checker declares (branch_audit's ruling 6);
#: without this, a README edit inside apps/-fingerprinting would never mark the
#: branch dirty and a cached row would be served past the edit forever.
BRANCH_INPUTS = (
    "README.md",
    ".aipass/aipass_local_prompt.md",
    ".trinity/*.json",
    "DASHBOARD.local.json",
)

#: Weights sum to 100. The README weighs heaviest because it is the layer the
#: fleet actually fails: 17 of 18 over cap on the day this rule was written.
#: A group with nothing present to measure drops out and its weight is shared
#: across the rest — see _weighted_score().
GROUP_WEIGHTS: Dict[str, int] = {
    "README": 30,
    "Branch prompt": 25,
    "Trinity files": 25,
    "Dashboard": 20,
}

#: Branch-relative spelling of each measured file, in the order the table
#: prints them. The label is what the column header says.
README_REL = "README.md"
PROMPT_REL = ".aipass/aipass_local_prompt.md"
DASHBOARD_REL = "DASHBOARD.local.json"
TRINITY_DIR = ".trinity"

#: (trinity file name, column label). The names are @memory's own budget keys,
#: so a file added to memory.config.json's file_budgets is one line here.
TRINITY_FILES: Tuple[Tuple[str, str], ...] = (
    ("local.json", "LOCAL"),
    ("observations.json", "OBS"),
    ("passport.json", "PASSPORT"),
)

#: Every measured file as (branch-relative path, column label), for the corpus
#: measurer and for anything that wants the list without running a check.
MEASURED_FILES: Tuple[Tuple[str, str], ...] = (
    (README_REL, "README"),
    (PROMPT_REL, "PROMPT"),
    *((f"{TRINITY_DIR}/{name}", label) for name, label in TRINITY_FILES),
    (DASHBOARD_REL, "DASH"),
)

#: What the fleet table calls itself. Carried in the row so the display arm
#: needs no knowledge of this pack.
TABLE_TITLE = "STARTUP BUDGET (ADVISORY) — chars (wc -m) against each layer's cap"

#: How many over-cap notes one branch may contribute to the table's footnotes.
#: A cap that never says it is a cap is the defect this whole pack is about, so
#: the number is announced when it bites.
MAX_NOTES = 6

_STATE_UNDER = "under"
_STATE_OVER = "over"
_STATE_ABSENT = "absent"
_STATE_ERROR = "error"


# =============================================================================
# PATHS — WHERE THE OWNERS KEEP THEIR NUMBERS
# =============================================================================


def _repo_root() -> Path | None:
    """Walk up from this file to the repo root — the dir holding src/aipass.

    Mirrors trinity_groups._repo_root(), through seedgo's guarded ``__file__``
    spelling: ``Path.resolve()`` reads the working directory on Windows, and an
    auditor that cannot be imported without a readable cwd cannot report that
    anything else needs one (handlers/module_root.py).
    """
    for parent in module_file(__file__).parents:
        if (parent / "src" / "aipass").is_dir():
            return parent
    logger.warning("startup_budget: cannot locate repo root from %s", __file__)
    return None


def memory_config_path() -> Path | None:
    """@memory's memory.config.json — the file that owns the .trinity caps.

    The same spelling trinity_check watches, so the two checkers cannot end up
    naming different files as the source of one number. Public because it is
    the seam a test points at a deliberately broken config to prove the error
    row exists.

    Returns:
        The config path, or None outside a repo.
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

    ``BRANCH_INPUTS`` covers what lives in the branch. Five of the six caps are
    owned elsewhere, and a branch-relative glob cannot name them — so the
    checker answers with the paths its own loaders read, and the incremental
    cache watches them. Without this channel an owner moving a cap re-scores
    nothing: every branch keeps serving the row it cached against the OLD
    number until someone runs --full. That is exactly what happened to
    trinity's rows on 2026-09-15, which is why the channel exists
    (branch_audit._external_input_files, landed 097e3bce).

    Spelled from the repo root rather than from each imported module's
    ``__file__`` because one of them — prax's ``operations.py``, where
    ``DASHBOARD_CHAR_BUDGET`` is actually defined — is a handler this checker
    never imports; it reads the re-export. Both files carry the number, so both
    are watched.

    Returns:
        The owner files that exist now. An absent one is left out, and its
        later arrival changes the watch set, which busts the cache by itself.
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


# =============================================================================
# CAPS — EACH READ FROM ITS OWNER, NEVER CARRIED
# =============================================================================


def _as_cap(value: Any) -> int | None:
    """*value* as a usable cap, or None. ``True`` is not a cap of 1."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def readme_cap() -> Tuple[int | None, str]:
    """seedgo's own README cap, read from this pack's pack.json.

    seedgo owns this number, so seedgo keeps it in config rather than in code:
    the Phase 5 CI ratchet has to move it without importing Python, and a
    constant in this module would put the fleet's README cap somewhere no
    non-Python tool can reach.

    Returns:
        ``(cap, "")`` or ``(None, reason)`` — the reason names seedgo and the
        exact key that is missing.
    """
    path = pack_manifest_path()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        logger.warning("startup_budget: cannot read %s: %s", path, exc)
        return None, f"seedgo: cannot read its own {path.name} ({type(exc).__name__}: {exc}) — cap not measured"
    caps = manifest.get("caps") if isinstance(manifest, dict) else None
    entry = caps.get(README_REL) if isinstance(caps, dict) else None
    cap = _as_cap(entry.get("max_chars")) if isinstance(entry, dict) else None
    if cap is None:
        return None, f"seedgo: {path.name} has no caps['{README_REL}'].max_chars — cap not measured"
    return cap, ""


def _cap_from_module(module: Any, name: str, owner: str, import_error: str, dotted: str) -> Tuple[int | None, str]:
    """One borrowed cap, read off the owner's live module by name.

    ``getattr`` at call time is the contract: bound at import this would be a
    copy, and the row would keep printing against a number the owner has since
    moved.
    """
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

    READ FROM @MEMORY'S CONFIG, NOT FROM @MEMORY'S HANDLER. The numbers are
    published by ``entry_limits.load_file_budgets()`` (1.11.0, :971), which
    delegates to ``config_loader.get_file_budgets()``, which reads exactly the
    key opened here: ``entry_limits.file_budgets`` in
    ``memory_json/custom_config/memory.config.json``. Importing the function
    would be a cross-BRANCH handler import, which seedgo's own handler
    independence standard forbids — another branch's handlers are private and a
    consumer is sent to its ``modules/`` gateway. @memory publishes no gateway
    for the budgets today, so this reads the config, which is the same source
    the function reads and the same file trinity_check already watches. Neither
    spelling carries a copy of a number; that is the contract that matters.

    Not going through the loader also fixes a hazard that only bites an
    auditor: ``get_file_budgets()`` legitimately serves a REGENERATION SEED
    when the config publishes no budgets, so @memory keeps working with a
    broken config. An auditor that accepted the seed would score the whole
    fleet against numbers no config contains and print green. Here a missing or
    unreadable ``file_budgets`` is the error row and nothing is scored.

    Returns:
        ``(budgets, "")`` mapping file name to its budget spec, or
        ``(None, reason)`` naming @memory and the thing that is missing.
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


# =============================================================================
# MEASUREMENT
# =============================================================================


def measure_chars(path: Path) -> Tuple[int | None, str]:
    """A file's size in CHARACTERS, or why it has none.

    ``len(read_text())`` is the number ``wc -m`` reports. ``st_size`` would be
    bytes, which is the mistake the boardroom corrected three times in one
    afternoon and the reason this function exists instead of a stat call.

    Args:
        path: The file to measure.

    Returns:
        ``(chars, "")`` when it was read; ``(None, "")`` when it is absent;
        ``(None, reason)`` when it exists and could not be read.
    """
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

    A cap that could not be read makes the cell an ERROR even when the file is
    absent: "we do not know what the limit is" is a different fact from "there
    is no file", and collapsing them is how a missing number becomes a pass.
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
    """Roll a group's cells into the check dict branch_audit stores.

    Absent cells leave the denominator — they are neither a pass nor a fail.
    A group with no unit left scores ``None`` and drops out of the weighted
    mean rather than claiming a measurement that did not happen.
    """
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
    """One cell as the audit's per-check message says it.

    A cell with no ``chars`` is the per-string unit: its number is a count of
    oversized fields, not a file size, and printing "None chars" there is how a
    message stops being read.
    """
    if cell["state"] == _STATE_ERROR:
        return f"{cell['path']}: ERROR — {cell['detail']}"
    if cell["chars"] is None:
        return f"{cell['path']}: {cell['detail']}"
    over_by = f" — OVER by {cell['chars'] - cell['cap']:,}" if cell["state"] == _STATE_OVER else ""
    return f"{cell['path']}: {cell['chars']:,}/{cell['cap']:,} chars{over_by}"


# =============================================================================
# THE .TRINITY GROUP — AGAINST @MEMORY'S PUBLISHED BUDGETS
# =============================================================================


def _trinity_cells(branch_path: Path, budgets: Dict[str, Any] | None, budget_error: str) -> Tuple[list, list]:
    """Cells and over-cap notes for the three .trinity files.

    Two budgets per file, both @memory's: ``max_chars`` for the whole file and,
    where the spec carries one, ``max_string_chars`` for any single string in
    it. passport.json is the file that needs both — 6,000 and 600 — because a
    passport can sit well under its file budget while one identity field runs
    to 869 chars, and no single number in a table column can say that. The
    string hits become footnotes under the table AND one extra scored unit, so
    that passport still reads as a failure.
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

    The same walk ``entry_limits._walk_strings`` (:986) does, spelled here
    because that module is another branch's HANDLER and importing it across
    branches is what seedgo's own independence standard forbids. This duplicates
    a SHAPE, never a number: the cap it is compared against is read from
    @memory's config on every call. The fix that removes the duplication is a
    ``modules/`` gateway on @memory publishing ``check_file_budget``; until
    then, a second walk of a JSON document is the smaller debt of the two.
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

    A file that will not parse yields nothing here on purpose: its SIZE has
    already been measured on the raw text, which is the honest half, and
    guessing at fields inside a broken document is not measurement. The trinity
    standard is the rule that fails an unparseable memory file by name.
    """
    try:
        data = json.loads(text)
    except ValueError as exc:
        logger.warning("startup_budget: cannot parse for the per-string cap: %s", exc)
        return []
    return [(path, len(value)) for path, value in _walk_strings(data) if len(value) > string_cap]


def _string_cell(label: str, rel: str, string_cap: int, over_strings: List[Tuple[str, int]]) -> Dict[str, Any]:
    """The per-string unit for a file whose owner caps individual strings.

    It is a cell so it is SCORED, and it carries no ``chars`` so the table can
    fold it away: a "longest string" column would be a second number in a row
    that is already about file size. Its evidence travels in ``detail`` and in
    the table's footnotes instead.
    """
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


# =============================================================================
# PACK CORPUS
# =============================================================================


def measure_corpus(branch_path: Path | str) -> int:
    """How many startup files this branch actually has — the banner's number.

    ``pack.json`` names this through ``measured_by``, so the line printed over
    the scores describes THIS pack's corpus (six startup files) instead of the
    engine's walk of ``apps/**/*.py``, which no rule here opens.

    Args:
        branch_path: Branch root.

    Returns:
        The count of measured files present, 0 to 6.
    """
    root = Path(branch_path)
    return sum(1 for rel, _label in MEASURED_FILES if (root / rel).is_file())


# =============================================================================
# SCORING
# =============================================================================


def _weighted_score(checks: List[Dict[str, Any]]) -> int | None:
    """Weighted mean over the groups that measured something.

    A group scoring None had nothing present to measure; its weight is
    redistributed rather than counted as 0 (which would blame the branch for a
    gitignored file) or as 100 (which would claim a reading that never
    happened). None means the whole standard stood down.
    """
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


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict[str, Any]:
    """Measure one branch's startup files against the caps their owners publish.

    Four groups: README (seedgo's cap), the branch prompt (hooks'), the three
    ``.trinity`` files (memory's, including passport's per-string cap), and the
    dashboard (prax's). Every cap is read from its owner on this call. A cap
    that cannot be read is an ERROR unit naming the owner; a file that is not
    there is ABSENT and leaves the denominator.

    Args:
        branch_path: Branch root — the directory holding README.md.
        bypass_rules: Accepted for the scoring-API contract and never read.
            There is nothing to be excused from: ADVISORY gates nothing, and a
            branch that needs different numbers moves the CAP at its owner,
            which is the one place every other branch reads it from. Granting
            per-branch exceptions to a fleet-wide measurement would make the
            table's columns mean a different thing in each row.

    Returns:
        ``{"standard": "STARTUP_BUDGET", "score", "passed", "advisory",
        "checks", "fleet_row"}``; ``not_applicable`` with a ``None`` score when
        the branch has none of the six files.
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
