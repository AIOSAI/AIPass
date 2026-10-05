# =================== AIPass ====================
# Name: developer_home_check.py
# Description: Developer Home Standards Checker Handler — no person's home directory in a text file
# Version: 1.0.0
# Created: 2026-10-04
# Modified: 2026-10-04
# =============================================

"""Developer Home Standards Checker Handler.

THE RULING (owner, 2026-10-04). This is a public repo. No tracked text file may
contain a developer's home directory: ``/home/<x>``, ``/Users/<x>`` or
``C:\\Users\\<x>`` (either slash, doubled backslashes as source and JSON carry
them, with or without a trailing separator) where ``<x>`` is not a neutral
placeholder. A home directory names a person the same way a name does.

NOT ``hardcoded_path``. That standard is about the PORTABILITY of code, so it
skips comments and docstrings. This one is about NAMING A PERSON, and prose
names a person exactly as code does — so nothing is skipped: a comment, a
docstring, a markdown page and a JSON value are all read.

TWO LANES, ONE SCAN. ``check_module`` judges one file (the audit and the
checklist); ``scan_tracked`` walks a whole tracked tree for CI, applying each
owning branch's bypass rules. Both call :func:`scan_text` — one implementation.

``TEXT_FILES = True`` tells the checklist this checker judges any text kind,
not only ``.py`` (see ``handlers/checklist/verdicts.py``).
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.context_standards.name_ratchet import tracked_files
from aipass.seedgo.apps.handlers.json import json_handler

# APPLIES_TO: a home path names a person in a test exactly as in production.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"
# This checker's check_module judges any text kind, not only .py.
TEXT_FILES = True

STANDARD = "developer_home"
RESULT_NAME = "DEVELOPER_HOME"

# The text kinds read. An extensionless file (a script, a dotfile) is text too.
TEXT_SUFFIXES = frozenset({".py", ".md", ".json", ".toml", ".yml", ".yaml", ".sh", ".txt"})

# Home segments that name nobody, compared lower-cased after trailing prose
# punctuation is stripped. Each family is here for a reason:
#   * generic logins docs use as the example: user, username, someone, somebody;
#   * the example cast of characters: carol, alice, bob, dave, eve;
#   * second-person and fill-in words: you, yourname, your-name, your_name, me, name;
#   * words that mark a sample: example, test, tester;
#   * the project's own name, which is nobody's login: aipass;
#   * a one-letter stand-in (x) and an elision (...);
#   * GitHub's runner accounts, the home a CI log shows: runner, runneradmin, runner~1.
# Two RULES sit beside the set: ANY single-character segment (an initial names
# nobody findable), and any segment CONTAINING one of TEMPLATE_MARKS (a template
# slot: <user>, <home>, {name}, $USER, %USERNAME%, u{i}, *).
NEUTRAL_SEGMENTS = frozenset(
    {
        "user",
        "username",
        "someone",
        "somebody",
        "carol",
        "alice",
        "bob",
        "dave",
        "eve",
        "you",
        "yourname",
        "your-name",
        "your_name",
        "me",
        "name",
        "example",
        "test",
        "tester",
        "aipass",
        "x",
        "runner",
        "runneradmin",
        "runner~1",
        "...",
    }
)
TEMPLATE_MARKS = "<{$%*"
_TRAILING_PROSE = ".,!?\u2026"

# Same shape as name_ratchet's _HOME_PATH: POSIX and macOS case-sensitive behind a
# (?<![\w.]) guard (so example.com/home/x is a URL, not a home); Windows a drive
# letter, one or two backslashes or a slash, "users" in any case, a separator.
_SEP = r"(?:\\{1,2}|/)"
_HOME_PATH = re.compile(
    r"(?:(?<![\w.])/(?:home|Users)/|(?<![A-Za-z])[A-Za-z]:" + _SEP + r"(?i:users)" + _SEP + r")"
    r"(?P<who>[^\\/\s'\"`()\[\],;:|]+)"
)


def is_text_target(path: str | Path) -> bool:
    """Whether this file's KIND is one the standard reads (suffix only; NUL is checked on read)."""
    suffix = Path(path).suffix.lower()
    return suffix == "" or suffix in TEXT_SUFFIXES


def is_neutral(segment: str) -> bool:
    """Whether a home segment names nobody (see NEUTRAL_SEGMENTS)."""
    bare = segment.rstrip(_TRAILING_PROSE) or segment
    if len(bare) == 1 or any(mark in segment for mark in TEMPLATE_MARKS):
        return True
    return bare.lower() in NEUTRAL_SEGMENTS


def scan_text(text: str) -> List[Tuple[int, str]]:
    """Every home path naming somebody: ``[(lineno, matched_text)]``, one per match."""
    hits: List[Tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for found in _HOME_PATH.finditer(line):
            if not is_neutral(found.group("who")):
                hits.append((lineno, found.group(0)))
    return hits


def read_text(path: Path) -> Tuple[Optional[str], str]:
    """``(text, "")``, ``(None, "binary")`` for a NUL byte, or ``(None, "error: <why>")``."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.warning("[developer_home] cannot read %s: %s", path, exc)
        return None, f"error: {exc}"
    if b"\0" in data:
        return None, "binary"
    return data.decode("utf-8", errors="replace"), ""


def _result(passed: bool, name: str, message: str, declined: bool = False) -> Dict:
    check = {"name": name, "passed": passed, "message": message}
    if declined:
        check["declined"] = True
    return {"passed": passed, "checks": [check], "score": 100 if passed else 0, "standard": RESULT_NAME}


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one text file for a developer's home directory."""
    path = Path(module_path)
    module_path = path.as_posix()

    if is_bypassed(module_path, STANDARD, bypass_rules=bypass_rules):
        return _result(True, "Bypassed", "Standard bypassed via .seedgo/bypass.json")
    if not is_text_target(path):
        return _result(True, "Developer home", "File skipped (not a text kind)", declined=True)
    if not path.exists():
        return _result(False, "File exists", f"File not found: {module_path}")

    text, state = read_text(path)
    if state == "binary":
        return _result(True, "Developer home", "File skipped (binary: NUL byte)", declined=True)
    if text is None:
        return _result(False, "File readable", f"Error reading file: {state.removeprefix('error: ')}")

    hits = [(ln, txt) for ln, txt in scan_text(text) if not is_bypassed(module_path, STANDARD, ln, bypass_rules)]
    score = 0 if hits else 100
    json_handler.log_operation("check_completed", {"file": module_path, "score": score, "standard": STANDARD})
    if not hits:
        return _result(True, "Developer home", "No developer home paths found")
    previews = "; ".join(f"L{ln}: {txt}" for ln, txt in hits[:3])
    more = f" (and {len(hits) - 3} more)" if len(hits) > 3 else ""
    return _result(False, "Developer home", f"{len(hits)} developer home path(s): {previews}{more}")


# =============================================================================
# THE TREE — the CI runner
# =============================================================================


def _owning_branch(rel: str) -> Optional[Tuple[str, str]]:
    """``(branch_dir, branch_relative_path)`` for a file under src/aipass/<branch>/, else None."""
    parts = rel.split("/")
    if len(parts) > 3 and parts[0] == "src" and parts[1] == "aipass":
        return "/".join(parts[:3]), "/".join(parts[3:])
    return None


def _branch_rules(root: Path, branch_dir: str, cache: Dict[str, list]) -> list:
    """The branch's bypass rules, loaded once. A branch with no bypass.json has none.

    Checked before loading because load_bypass_rules CREATES a missing file, and a
    read-only scan must not write into somebody else's branch.
    """
    if branch_dir not in cache:
        branch = root / branch_dir
        has_file = (branch / ".seedgo" / "bypass.json").is_file()
        cache[branch_dir] = load_bypass_rules(str(branch)) if has_file else []
    return cache[branch_dir]


def scan_tracked(repo_root: Path | str, files: Optional[Sequence[str]] = None) -> Dict:
    """Scan every tracked text file under ``repo_root``. Never prints.

    Args:
        repo_root: The checkout's root; every path is read relative to it.
        files: Repo-relative posix paths. None asks git (``git ls-files``); a
            tree git cannot list is RED, never clean.

    Returns:
        ``{"passed", "hits": [(rel, line, matched)], "files_read", "binary_skipped",
        "errors"}``. ``passed`` is False on any hit and on any error.
    """
    root = Path(repo_root)
    errors: List[str] = []
    if files is None:
        files, reason = tracked_files(root)
        if reason:
            errors.append(reason)
    hits: List[Tuple[str, int, str]] = []
    files_read = binary_skipped = 0
    cache: Dict[str, list] = {}
    for rel in files:
        target = root / rel
        if not is_text_target(rel) or not target.is_file():
            continue
        text, state = read_text(target)
        if state == "binary":
            binary_skipped += 1
            continue
        if text is None:
            errors.append(f"{rel}: cannot be read ({state})")
            continue
        files_read += 1
        owner = _owning_branch(rel)
        rules = _branch_rules(root, owner[0], cache) if owner else []
        local = owner[1] if owner else rel
        hits.extend((rel, ln, txt) for ln, txt in scan_text(text) if not is_bypassed(local, STANDARD, ln, rules))
    if hits or errors:
        logger.warning("[developer_home] %d hit(s), %d error(s) over %d file(s)", len(hits), len(errors), files_read)
    json_handler.log_operation(
        "developer_home_tree_scanned", {"files": files_read, "hits": len(hits), "errors": len(errors)}
    )
    return {
        "passed": not hits and not errors,
        "hits": hits,
        "files_read": files_read,
        "binary_skipped": binary_skipped,
        "errors": errors,
    }
