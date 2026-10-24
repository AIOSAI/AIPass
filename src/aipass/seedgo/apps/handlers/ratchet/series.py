# =================== AIPass ====================
# Name: series.py
# Description: the ratchet series - one append-only line per probe, and the archived artifact behind it
# Version: 1.1.1
# Created: 2026-10-12
# Modified: 2026-10-24
# =============================================

"""
THE SERIES IS THE CLOCK. `.seedgo/audit_tests_<BRANCH>.json` is rewritten by
every audit-tests run (one without `--pseudo-tested` resets the group to
`not_applicable`), so the ratchet keeps its own append-only file and archives
each line's artifact into `.seedgo/ratchet/`, where no later run overwrites it.
Lines key on `relpath::qualname`, never line number, so an edit cannot lose them.
Everything written goes through `portable()`: an absolute home path turns CI's
home-paths gate red. A refused probe is still a line, so the pick moves on."""

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

MODULE_NAME = "ratchet.series"

SEEDGO_ROOT = module_file(__file__).parents[3]
ARTIFACT_DIR = SEEDGO_ROOT / ".seedgo"

#: The AIPass root the probe runs in: `src/aipass/seedgo` is three levels down.
REPO_ROOT = SEEDGO_ROOT.parents[2]

HOME_DIR = Path.home()
SERIES_NAME = "ratchet_series.jsonl"
ARCHIVE_DIRNAME = "ratchet"

SERIES_VERSION = "ratchet-series/1"

GROUP_KEY = "pytest.pseudo_tested"

WHOLE_BRANCH = "1/1"

TRIGGER_WEEKLY = "weekly"
TRIGGER_RECORD = "record"

CAMPAIGN_STATUSES: tuple = ("measured", "refused")


def series_path(directory: Optional[Path] = None) -> Path:
    """Where the series file lives."""
    return (Path(directory) if directory else ARTIFACT_DIR) / SERIES_NAME


def read(directory: Optional[Path] = None) -> List[dict]:
    """Every line in the series, oldest first. A missing file is an empty series.

    A line that does not parse raises with its number: a series read past a
    broken line would hand the pick a history with a hole in it. The one
    exception is a final line with no newline, an append cut short: it is
    skipped with a warning, since nothing after it can be missing."""
    path = series_path(directory)
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    rows = text.splitlines()
    lines: List[dict] = []
    for number, raw in enumerate(rows, start=1):
        if not raw.strip():
            continue
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            if number == len(rows) and not text.endswith("\n"):
                logger.warning(f"[RATCHET] {path} line {number} is a truncated append, ignored: {exc}")
                continue
            raise ValueError(f"{path} line {number} is not JSON: {exc}") from exc
    return lines


def append(line: dict, directory: Optional[Path] = None) -> Path:
    """Add one line to the series and return the file it went to."""
    path = series_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")

    json_handler.log_operation(
        "ratchet_series_appended",
        {"branch": line.get("branch"), "run_id": line.get("run_id"), "status": line.get("status")},
        module_name=MODULE_NAME,
    )
    logger.info(f"[RATCHET] series line for {line.get('branch')} ({line.get('status')}) appended to {path}")
    return path


def holds_run(run_id: str, lines: List[dict]) -> bool:
    """Whether a probe with this run id is already in the series."""
    return any(line.get("run_id") == run_id for line in lines)


def portable(value: Any, root: Optional[Path] = None, home: Optional[Path] = None) -> Any:
    """`value` with every path under the AIPass root made repo-relative and any other home path `~`.

    Walks dicts (keys too), lists and strings; the root alone becomes `.`."""
    rewrite = _rewriter(Path(root) if root else REPO_ROOT, Path(home) if home else HOME_DIR)
    return _walk(value, rewrite)


def _rewriter(root: Path, home: Path):
    """One string -> string function for this root and home."""
    passes = []
    for prefix, replacement in ((str(root), "."), (str(home), "~")):
        escaped = re.escape(prefix)
        if replacement == ".":
            passes.append((re.compile(escaped + r"[\\/]"), ""))
        passes.append((re.compile(escaped + r"(?![\w.-])"), replacement))

    def rewrite(text: str) -> str:
        """The text with the root and the home rewritten."""
        for pattern, replacement in passes:
            text = pattern.sub(lambda _: replacement, text)
        return text

    return rewrite


def _walk(value: Any, rewrite) -> Any:
    """Apply `rewrite` to every string in a JSON-shaped value."""
    if isinstance(value, str):
        return rewrite(value)
    if isinstance(value, dict):
        return {_walk(key, rewrite): _walk(item, rewrite) for key, item in value.items()}
    if isinstance(value, list):
        return [_walk(item, rewrite) for item in value]
    return value


def archive(document: dict, branch: str, run_id: str, directory: Optional[Path] = None) -> Path:
    """Copy the probe's artifact, paths made portable, where no later run can overwrite it."""
    target = (Path(directory) if directory else ARTIFACT_DIR) / ARCHIVE_DIRNAME / f"{branch}_{run_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(portable(document), indent=2, sort_keys=True), encoding="utf-8")
    logger.info(f"[RATCHET] archived the {branch} artifact to {target}")
    return target


def campaign_group(document: dict) -> Optional[dict]:
    """The pseudo-tested group of an artifact, or None when the run never reached it."""
    return (document.get("groups") or {}).get(GROUP_KEY)


def campaign_ran(document: dict) -> bool:
    """Whether the artifact holds a campaign that started, finished or ran out of clock."""
    group = campaign_group(document)
    return bool(group) and group.get("status") in CAMPAIGN_STATUSES


def build_line(
    document: dict,
    *,
    branch: str,
    trigger: str,
    pick_reason: str,
    archived: Optional[Path],
    now: Optional[float] = None,
) -> dict:
    """One series line from one audit-tests artifact."""
    group = campaign_group(document) or {}
    provenance = document.get("provenance") or {}
    stamped = now if now is not None else time.time()
    mutants = group.get("mutants") or []
    status = _status(document, group)
    pseudo_tested = _keys(group.get("pseudo_tested") or [])

    line: Dict[str, object] = {
        "series_version": SERIES_VERSION,
        "run_id": provenance.get("run_id") or f"unrun-{int(stamped)}",
        "date": provenance.get("started") or time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(stamped)),
        "branch": branch,
        "slice": WHOLE_BRANCH,
        "trigger": trigger,
        "pick_reason": pick_reason,
        "status": status,
        "reason": _reason(document, group),
        "budget_seconds": group.get("budget_seconds"),
        "budget_exhausted": bool(group.get("budget_exhausted")),
        "functions_total": group.get("functions_total"),
        "functions_probed": group.get("functions_probed"),
        "functions_executed": group.get("functions_executed"),
        "killed_by_assertion": group.get("killed_by_assertion"),
        "killed_by_error": group.get("killed_by_error"),
        "elapsed_seconds": group.get("elapsed_seconds"),
        "seconds_per_mutant": group.get("seconds_per_mutant"),
        "pseudo_tested": pseudo_tested,
        "uncovered": _keys((group.get("uncovered") or {}).get("functions") or []),
        "crash_only": _keys(m for m in mutants if m.get("outcome") == "killed" and m.get("kill_cause") == "error"),
        # None means the markers were not read, never that nothing was declared.
        "declared_equivalent": None,
        # Posix separators so the line reads the same from every host.
        "archive": Path(portable(str(archived))).as_posix() if archived else None,
    }
    line["open_survivors"] = len(pseudo_tested) if status == "measured" else None
    return portable(line)


def _status(document: dict, group: dict) -> str:
    """The group's own status, or the whole run's when the run never reached the group."""
    if group.get("status"):
        return str(group["status"])
    return str(document.get("status") or "refused")


def _reason(document: dict, group: dict) -> str:
    """Why a probe is not a measurement - empty when it is one."""
    if group.get("reason"):
        return str(group["reason"])
    refusal = document.get("refusal") or {}
    return str(refusal.get("reason") or "")


def _keys(records) -> List[str]:
    """`relpath::qualname` for each function record, sorted, so two points diff as sets."""
    return sorted(f"{record.get('relpath')}::{record.get('qualname')}" for record in records)
