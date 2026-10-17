# =================== AIPass ====================
# Name: comments.py
# Version: 1.0.0
# Description: The comments verb — the comment budget's ledger, trend and on-demand scan
# Branch: hooks
# Layer: apps/modules
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""The comment budget: last edits, a file's trend, over-budget files, or a scan now."""

import importlib
import os
import sys
from pathlib import Path

from aipass.cli.apps.modules import console, err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.json import json_handler
from aipass.hooks.apps.handlers.lifecycle.auto_fix import SCRATCH_DIRS
from aipass.hooks.apps.modules import comment_scan
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = console
SKIP_DIRS = SCRATCH_DIRS | {"node_modules", "__pycache__", "dist", "build"}

HELP_COMMANDS = [
    ("comments [path|--file p|--over]", "Comment budget: ledger, scan, trend, over-budget files"),
]


def print_introspection() -> None:
    """Print module structure for drone routing."""
    err_console.print("[bold cyan]comments[/bold cyan] — the comment budget's ledger and on-demand scan")


def _print_help() -> None:
    """The verb's help: the budget and the metric in four lines."""
    CONSOLE.print(f"Budget: full-line comments at most {comment_scan.BUDGET_PERCENT}% of a file's non-blank lines.")
    CONSOLE.print("Comments: # / // lines, /* */ block lines, Python docstring lines past the first.")
    CONSOLE.print("Free: the AIPass header, one-line docstrings, directives (noqa, eslint-, @ts-...).")
    CONSOLE.print("Usage: comments (last 20 edits) | comments <path> | --file <path> (trend) | --over")


def _caller_path(target: str) -> Path:
    """*target* as the caller meant it: drone runs this module from the branch, not where it was typed."""
    return Path(os.environ.get("AIPASS_CALLER_CWD") or os.getcwd(), target)


def _ledger() -> list[dict]:
    """The handler's ledger rows, oldest first."""
    return importlib.import_module("aipass.hooks.apps.handlers.lifecycle.comment_budget").ledger_rows()


def _row_line(row: dict) -> str:
    """One ledger row as a line."""
    added = row.get("added")
    shown = "-" if added is None else f"{added:+d}"
    return (
        f"{row.get('time', '?')}  {str(row.get('seat', '?'))[:8]:8}  {round(row.get('share', 0) * 100):3d}%  "
        f"over {row.get('over', 0):4d}  added {shown:>4}  {row.get('file', '?')}"
    )


def _show_recent() -> None:
    """The last 20 judged edits."""
    rows = _ledger()[-20:]
    if not rows:
        CONSOLE.print("No judged edits in the ledger yet.")
    for row in rows:
        CONSOLE.print(_row_line(row), markup=False, highlight=False)


def _show_trend(target: str) -> None:
    """Every ledger row for one file, oldest first, then first to latest."""
    key = os.path.abspath(_caller_path(target))
    rows = [row for row in _ledger() if row.get("file") == key]
    if not rows:
        CONSOLE.print(f"No ledger rows for {key}.", markup=False)
        return
    for row in rows:
        CONSOLE.print(_row_line(row), markup=False, highlight=False)
    CONSOLE.print(f"first {round(rows[0]['share'] * 100)}% → latest {round(rows[-1]['share'] * 100)}%")


def _show_over() -> None:
    """Distinct files whose latest row is over budget, worst first."""
    latest = {row.get("file"): row for row in _ledger()}
    over = sorted((r for r in latest.values() if r.get("over", 0) > 0), key=lambda r: -r.get("share", 0))
    if not over:
        CONSOLE.print("No file's latest edit is over budget.")
    for row in over:
        CONSOLE.print(_row_line(row), markup=False, highlight=False)


def _walk_error(error: OSError) -> None:
    """A directory the tree scan could not read is named, not dropped."""
    logger.warning("[HOOKS] comments: unreadable directory skipped: %s", error)
    err_console.print(f"unreadable, skipped: {error.filename}", markup=False)


def _judged_files(root: Path) -> list[Path]:
    """Every judged file under *root*, dot, scratch and build directories skipped."""
    found = []
    for folder, dirs, files in os.walk(root, onerror=_walk_error):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
        found.extend(Path(folder) / name for name in files if comment_scan.kind_of(name))
    return sorted(found)


def _scan_file(path: Path) -> None:
    """One file's share, over and every run."""
    scan = comment_scan.scan(path, comment_scan.kind_of(path) or "")
    CONSOLE.print(
        f"{path}: {scan.comments} of {scan.body} lines are comments ({round(scan.share * 100)}%), "
        f"{max(scan.over(), 0)} over",
        markup=False,
    )
    for first, last in scan.runs:
        CONSOLE.print(f"  L{first}-{last} ({last - first + 1})", markup=False)


def _scan_tree(root: Path) -> None:
    """One row per judged file, worst first, then the totals."""
    scans = [(path, comment_scan.scan(path, comment_scan.kind_of(path) or "")) for path in _judged_files(root)]
    scans.sort(key=lambda item: -item[1].share)
    for path, scan in scans:
        line = f"{round(scan.share * 100):3d}%  over {max(scan.over(), 0):4d}  {path.relative_to(root)}"
        CONSOLE.print(line, markup=False, highlight=False)
    body = sum(scan.body for _, scan in scans)
    comments = sum(scan.comments for _, scan in scans)
    over = sum(1 for _, scan in scans if scan.over() > 0)
    share = round(comments / body * 100) if body else 0
    CONSOLE.print(f"files {len(scans)}, over budget {over}, share {share}% ({comments} of {body} lines)")


def _scan_now(target: str) -> bool:
    """Scan a file or a tree now."""
    path = _caller_path(target)
    if path.is_dir():
        _scan_tree(path)
    elif path.is_file() and comment_scan.kind_of(path):
        _scan_file(path)
    else:
        err_console.print(f"Not a judged file or a directory: {target}", markup=False)
        return False
    json_handler.log_operation("comments_scan", {"target": target})
    return True


def _route(args: list) -> bool:
    """Run the form *args* names; False when it names none."""
    if not args:
        _show_recent()
        return True
    if args == ["--over"]:
        _show_over()
        return True
    if args[0] == "--file" and len(args) == 2:
        _show_trend(args[1])
        return True
    if len(args) == 1 and not args[0].startswith("-"):
        return _scan_now(args[0])
    err_console.print(f"Unknown form: {' '.join(args)}. Try: drone @hooks comments --help", markup=False)
    return False


def handle_command(command: str, args: list) -> bool:
    """Route `drone @hooks comments`; exit 1 on a form it cannot answer."""
    if command != "comments":
        return False
    if wants_help(args):
        _print_help()
        return True
    if not _route(args):
        sys.exit(1)
    return True
