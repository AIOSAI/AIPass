# =================== AIPass ====================
# Name: startup_ratchet.py
# Description: Per-file CI ratchet — the README and the branch prompt held at their owners' caps
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-10-17
# =============================================

"""The ratchet — CI goes red when a gated startup file grows past its cap.

Reference: startup_budget.md, "The CI ratchet".
"""

from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Sequence, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.context_standards import startup_budget_check as budget
from aipass.seedgo.apps.handlers.json import json_handler

#: Spelled as the advisory checker's cells; a test pins the two together.
STATE_UNDER = "under"
STATE_OVER = "over"
STATE_ABSENT = "absent"
STATE_ERROR = "error"

#: ABSENT is deliberately not a failing state.
FAILING_STATES: Tuple[str, ...] = (STATE_OVER, STATE_ERROR)


class GatedFile(NamedTuple):
    """One file the ratchet holds, and where to ask what its limit is.

    ``cap_reader`` is a name, not the function, so the cap is looked up on every call.
    """

    rel: str
    owner: str
    cap_source: str
    cap_reader: str


#: Only git-tracked files; adding one is a decision about what CI can see.
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

TITLE = "STARTUP RATCHET — README.md and the branch prompt, in chars (wc -m). A file AT its cap passes; over is >."


def discover_branches(repo_root: Path | str) -> List[Dict[str, str]]:
    """Every citizen under ``src/aipass`` that has an ``apps/`` directory.

    The same rule as ``.github/scripts/seedgo_audit.py``; no registry read, which needs a live drone.
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

    The cap is read first: an unreadable cap is an error even when the file is absent.
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
    """Every gated file on every branch, in fleet order then gated order."""
    return [measure_file(str(branch["name"]), branch["path"], gated) for branch in branches for gated in GATED_FILES]


def _measured(row: Mapping[str, Any]) -> str:
    """The measured size, or the honest word for why there isn't one."""
    return f"{row['chars']:,} chars" if row["chars"] is not None else "UNREADABLE"


def _cap(row: Mapping[str, Any]) -> str:
    """The cap, or ``UNREADABLE`` — never a remembered number."""
    return f"{row['cap']:,} chars" if row["cap"] is not None else "UNREADABLE"


def failure_line(row: Mapping[str, Any]) -> str:
    """The red, on one line: file, measured size, cap, owner — in that order, every time."""
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
    """The whole run as printable lines — every branch, not just the red ones."""
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


def run(branches: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Gate every branch's README and branch prompt; an unreadable cap fails like an over one."""
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
