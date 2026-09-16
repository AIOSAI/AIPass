# =================== AIPass ====================
# Name: startup_ratchet.py
# Description: Per-file CI ratchet — the README and the branch prompt held at their owners' caps
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""The ratchet — CI goes red when a gated startup file grows past its cap.

WHAT A RATCHET IS FOR. The advisory row next door (``startup_budget_check``)
measures six files and gates nothing: it told the fleet that seventeen of
eighteen READMEs were over budget, and seventeen diets landed on 2026-09-15.
A number nobody is held to drifts back. This is the part that holds: once a
branch is under its cap, the next commit that pushes it back over turns the
``seedgo-audit`` job red, in the same run, with a line that says which file,
how big it got, what the cap is, and who owns the cap.

TWO FILES, AND ONLY TWO
-----------------------
=================================  ======  ===========================
gated                              owner   where the cap is read
=================================  ======  ===========================
``README.md``                      seedgo  this pack's ``pack.json``
``.aipass/aipass_local_prompt.md``  hooks  ``BRANCH_CHAR_BUDGET``
=================================  ======  ===========================

Both are tracked in git, so a clean checkout sees exactly what a local audit
sees. That is the whole selection rule, and it is why the other four measured
files are NOT here:

* ``.trinity/{local,observations,passport}.json`` — ``.gitignore`` line 28.
  Machine-local memory. A CI checkout has none of them, so a gate on them
  would measure nothing on every run and pass by accident forever.
* ``DASHBOARD.local.json`` — ``.gitignore`` line 33. Same fact, same reason.
* ``docs/*.md`` — the 20,000-chars-per-page rule is real and the advisory lane
  measures it, but the fleet holds pages that predate the rule (two research
  pages at 126,181 and 37,180 chars are deliberately unsliced). A ratchet
  drops on numbers that are ALREADY under; dropping it on a corpus that is
  over turns the gate into a demand for work nobody scheduled, which is how
  a gate gets switched off. Stabilise first; widen when the corpus is ready.

A file that is absent is NOT a failure here. A branch with no README already
fails ``readme_check``'s "README exists" unit inside the scored pack, which
gates at 100% in the same job — this rule is about GROWTH, and inventing a
second, differently-worded red for the same defect only splits the diagnosis.

``<=`` PASSES. THE BOUNDARY IS THE CAP ITSELF
---------------------------------------------
A file measuring exactly its cap is UNDER and passes. Over means strictly
greater: ``chars > cap``. The same comparison the advisory checker makes
(``_measure_one``), said the same way in the failure line and in the docs, so
a branch that diets to precisely 10,000 is not told it missed by zero.

CHARS. ``len(text)`` after a utf-8 decode — the number ``wc -m`` prints. Never
bytes, never lines, never tokens; the measurement is delegated to
``startup_budget_check.measure_chars`` so the gate and the advisory row cannot
drift into two different units.

READ, NEVER COPIED — AND NEVER GUESSED
--------------------------------------
No cap number is written in this file. Each gated entry carries the NAME of
the reader function on ``startup_budget_check`` and the name of the owner, and
the reader is fetched with ``getattr`` and called on every measurement. Bind
the function (or worse, the integer) at import and the gate becomes a copy of
a number with someone else's name on it, still printing green after the owner
moved the cap.

A cap that cannot be read is a FAILURE, not a pass and not a fallback. There is
no remembered 10,000 or 9,000 anywhere below. If ``pack.json`` will not parse,
or @hooks cannot be imported, the line says ``cap UNREADABLE`` and names the
owner, and the job goes red — because the alternative, a gate that quietly
substitutes the number it saw last week, is a gate that has stopped measuring
and has not said so.

WHAT IT MUST NOT DEPEND ON
--------------------------
It runs on a cold GitHub runner, so: no incremental cache (every file is read
on every run — 36 reads, well under a second), no registry lookup (the branch
list is a directory walk the caller hands in, or ``discover_branches`` does the
same walk from a repo root), and no absolute path anywhere. Paths are built
from the root the caller names, which is how the same code gates the live tree
and a throwaway copy in a temp directory.

IT NEVER PRINTS. It returns rows and formatted lines; the ``.github`` runner
prints them. A handler that writes to stdout cannot be called from a checker,
a test, or a dashboard without polluting all three.

Design: DPLAN-0347 / FPLAN-0593 Phase 5, boardroom thread 16.
"""

from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Sequence, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.context_standards import startup_budget_check as budget
from aipass.seedgo.apps.handlers.json import json_handler

# =============================================================================
# CONFIGURATION
# =============================================================================

#: The states a gated row can be in. Spelled the same as the advisory
#: checker's private cells so one table vocabulary covers both rules — a test
#: pins the two spellings together.
STATE_UNDER = "under"
STATE_OVER = "over"
STATE_ABSENT = "absent"
STATE_ERROR = "error"

#: The states that turn the job red. ABSENT is deliberately not one of them.
FAILING_STATES: Tuple[str, ...] = (STATE_OVER, STATE_ERROR)


class GatedFile(NamedTuple):
    """One file the ratchet holds, and where to ask what its limit is.

    Every field here is a NAME — a path, a branch, a place to look, and the
    attribute to call. None of them is a number. ``cap_reader`` is stored as a
    string rather than as the function object so the lookup happens at
    measurement time: a bound function is a copy of the owner's answer taken at
    import, and the whole contract this pack was written for is that a cap is
    read on every call.

    Attributes:
        rel: Branch-relative path, taken from the advisory checker so the gate
            and the table can never disagree about which file is meant.
        owner: The branch that rules this cap — the name a red line prints so
            whoever reads it knows who to talk to.
        cap_source: Where the owner keeps the number, in words, for the same
            reason: a red that does not say where to look costs a round trip.
        cap_reader: Attribute on ``startup_budget_check`` returning
            ``(cap, reason)``.
    """

    rel: str
    owner: str
    cap_source: str
    cap_reader: str


#: The gated set. Two entries, both tracked in git. Adding a third is a
#: decision about what CI can see, not a line of config — see the module
#: docstring for why ``.trinity``, the dashboard and ``docs/`` are absent.
GATED_FILES: Tuple[GatedFile, ...] = (
    GatedFile(
        rel=budget.README_REL,
        owner="seedgo",
        cap_source='context_standards/pack.json -> caps["README.md"].max_chars',
        cap_reader="readme_cap",
    ),
    GatedFile(
        rel=budget.PROMPT_REL,
        owner="hooks",
        cap_source="aipass.hooks.apps.modules.grounding_content.BRANCH_CHAR_BUDGET",
        cap_reader="prompt_cap",
    ),
)

#: The banner. It states the unit and the boundary, because a gate that only
#: prints numbers makes every reader guess which side of the cap is legal.
TITLE = "STARTUP RATCHET — README.md and the branch prompt, in chars (wc -m). A file AT its cap passes; over is >."


# =============================================================================
# THE FLEET — THE SAME WALK THE CI SCRIPT MAKES
# =============================================================================


def discover_branches(repo_root: Path | str) -> List[Dict[str, str]]:
    """Every citizen under ``src/aipass`` that has an ``apps/`` directory.

    The same rule ``.github/scripts/seedgo_audit.py`` applies when it builds
    the list it audits — a directory with ``apps/`` is a branch — so the gate
    cannot end up holding a different fleet than the audit standing beside it.
    In CI the script hands its own list to :func:`run`; this function is for
    every other caller: a test, a local check, or the gate pointed at a copied
    tree to watch it go red.

    No registry read, deliberately. The registry resolves from one working
    directory and needs a live ``drone``; a checkout does not.

    Args:
        repo_root: The directory holding ``src/aipass``. Relative is fine and
            is what CI uses — the paths returned are relative to it, which is
            what makes the printed lines repo-relative rather than host-shaped.

    Returns:
        ``[{"name", "path"}, ...]`` sorted by name; empty when there is no
        ``src/aipass`` under *repo_root*.
    """
    fleet = Path(repo_root) / "src" / "aipass"
    if not fleet.is_dir():
        logger.warning("startup_ratchet: no src/aipass under %s — no branches to gate", repo_root)
        return []
    return [
        {"name": entry.name, "path": str(entry)}
        for entry in sorted(fleet.iterdir())
        if entry.is_dir() and (entry / "apps").is_dir()
    ]


# =============================================================================
# MEASUREMENT
# =============================================================================


def _row(
    branch: str,
    path: str,
    gated: GatedFile,
    chars: int | None,
    cap: int | None,
    state: str,
    detail: str = "",
) -> Dict[str, Any]:
    """One gated file's verdict, in the shape the formatters and tests read."""
    return {
        "branch": branch,
        "path": path,
        "rel": gated.rel,
        "owner": gated.owner,
        "cap_source": gated.cap_source,
        "chars": chars,
        "cap": cap,
        "state": state,
        "detail": detail,
    }


def measure_file(branch: str, branch_path: Path | str, gated: GatedFile) -> Dict[str, Any]:
    """Measure one gated file on one branch against the cap its owner publishes.

    The cap is read FIRST and read FRESH: an unreadable cap is an error even
    when the file is absent, because "we do not know the limit" and "there is
    no file" are different facts and collapsing them is how a missing number
    becomes a green run.

    Args:
        branch: The citizen's name, for the report's left column.
        branch_path: The branch root — the directory holding ``README.md``.
        gated: Which file, and whose number to ask for.

    Returns:
        A row dict. ``state`` is one of ``under``, ``over``, ``absent``,
        ``error``; only the last two of those carry a ``detail``.
    """
    display = f"{Path(branch_path).as_posix()}/{gated.rel}"
    cap, cap_error = getattr(budget, gated.cap_reader)()
    if cap is None:
        return _row(branch, display, gated, None, None, STATE_ERROR, cap_error)
    chars, read_error = budget.measure_chars(Path(branch_path) / gated.rel)
    if read_error:
        return _row(branch, display, gated, None, cap, STATE_ERROR, f"exists but cannot be read ({read_error})")
    if chars is None:
        return _row(branch, display, gated, None, cap, STATE_ABSENT, "absent — not gated here")
    state = STATE_OVER if chars > cap else STATE_UNDER
    return _row(branch, display, gated, chars, cap, state)


def measure_branches(branches: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Every gated file on every branch, in fleet order then gated order.

    Args:
        branches: Mappings carrying at least ``name`` and ``path`` — the exact
            dicts the CI script already builds for the audit.

    Returns:
        One row per (branch, gated file).
    """
    return [measure_file(str(branch["name"]), branch["path"], gated) for branch in branches for gated in GATED_FILES]


# =============================================================================
# WHAT A RED SAYS
# =============================================================================


def _measured(row: Mapping[str, Any]) -> str:
    """The measured size, or the honest word for why there isn't one."""
    return f"{row['chars']:,} chars" if row["chars"] is not None else "UNREADABLE"


def _cap(row: Mapping[str, Any]) -> str:
    """The cap, or ``UNREADABLE`` — never a remembered number."""
    return f"{row['cap']:,} chars" if row["cap"] is not None else "UNREADABLE"


def failure_line(row: Mapping[str, Any]) -> str:
    """The red, on one line, naming all four things a reader needs.

    File, measured size, cap, owner — in that order, every time. A red that
    says only "README too big" sends whoever reads it looking for the number
    and then looking for whose number it is; naming the owner inline is the
    difference between a fix and a round trip.
    """
    over = f" (OVER by {row['chars'] - row['cap']:,})" if row["state"] == STATE_OVER else ""
    line = (
        f"  FAIL {row['path']} — measured {_measured(row)}, cap {_cap(row)}{over}, "
        f"owner @{row['owner']} ({row['cap_source']})"
    )
    return f"{line}: {row['detail']}" if row["detail"] else line


def _row_sentence(row: Mapping[str, Any]) -> str:
    """One gated file as the green report prints it."""
    if row["state"] == STATE_ERROR:
        return f"{row['rel']} ERROR"
    if row["state"] == STATE_ABSENT:
        return f"{row['rel']} absent"
    marker = " OVER" if row["state"] == STATE_OVER else ""
    return f"{row['rel']} {row['chars']:,}/{row['cap']:,}{marker}"


def report_lines(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    """The whole run as printable lines — every branch, not just the red ones.

    The green rows are the point of printing at all: a gate whose log only
    appears when it fails leaves nobody able to see how close a branch is
    running, which is the reading that lets a diet happen before the red.

    Args:
        rows: Output of :func:`measure_branches`.

    Returns:
        Title, one line per branch, then a counted summary.
    """
    lines = [TITLE]
    order: List[str] = []
    by_branch: Dict[str, List[Mapping[str, Any]]] = {}
    for row in rows:
        if row["branch"] not in by_branch:
            order.append(row["branch"])
            by_branch[row["branch"]] = []
        by_branch[row["branch"]].append(row)
    for name in order:
        lines.append(f"  {name:>12}: " + " · ".join(_row_sentence(row) for row in by_branch[name]))
    counted = (STATE_OVER, STATE_ERROR, STATE_ABSENT)
    tally = {state: sum(1 for row in rows if row["state"] == state) for state in counted}
    lines.append(
        f"  {len(order)} branch(es), {len(rows)} gated file(s): "
        f"{tally[STATE_OVER]} over cap, {tally[STATE_ERROR]} unmeasurable, {tally[STATE_ABSENT]} absent"
    )
    return lines


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================


def run(branches: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Gate every branch's README and branch prompt. The whole verdict, once.

    Args:
        branches: Mappings with ``name`` and ``path``. CI passes the same list
            it audits, so the gate and the audit always see one fleet.

    Returns:
        ``{"rows", "failures", "failure_lines", "report", "passed"}``.
        ``passed`` is False when any gated file is over its cap OR when any cap
        could not be read — an unmeasurable gate is a failing gate.
    """
    rows = measure_branches(branches)
    failures = [row for row in rows if row["state"] in FAILING_STATES]
    if failures:
        logger.warning("startup_ratchet: %d gated file(s) failed across %d branch(es)", len(failures), len(branches))
    json_handler.log_operation(
        "ratchet_completed",
        {"branches": len(branches), "gated_files": len(rows), "failures": len(failures)},
    )
    return {
        "rows": rows,
        "failures": failures,
        "failure_lines": [failure_line(row) for row in failures],
        "report": report_lines(rows),
        "passed": not failures,
    }
