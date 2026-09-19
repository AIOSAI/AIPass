# =================== AIPass ====================
# Name: name_ratchet.py
# Description: CI ratchet — the owner's first name and a person's home path never regrow in the tracked tree
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""The name ratchet — the public tree never names its owner (DPLAN-0350).

THE RULING. The owner ruled (2026-09-15 and 2026-09-19) that the public tree
never names him. A seat that reads his first name in a prompt, a config note,
a refusal or a rendered standard on another user's machine is told who its
user is, and gets it wrong. Five sweep waves took the fleet from 682 lines in
316 files down to a residue the owner is still ruling on. This is the part
that keeps the count from regrowing with the next citizen who quotes a ruling.

TWO RULES, ONE CAUSE
--------------------
* ``name`` — the owner's first name, case-insensitive, as a SUBSTRING of any
  line of any tracked text file, and of the tracked path itself. Substring on
  purpose: a test called ``test_the_<name>_ruling`` ships the name as surely as
  prose does, and five of the residual lines were exactly that.
* ``home_path`` — an absolute home directory, ``/home/<x>/``, ``/Users/<x>/``
  or ``C:\\Users\\<x>\\`` (either slash, doubled backslashes too, and with no
  trailing separator — ``/home/<x>`` alone names <x> just the same), in a ``.md``
  file — every prompt is one — or a ``*_content.py``: the two kinds of file
  that are rendered to a reader. A home directory names a person the same way
  a name does. Code is not this rule's: ``hardcoded_path`` is the scored
  standard for a home path in ``apps/``. A segment that names nobody passes —
  ``user``, ``username``, ``you``, ``me``, ``someone``, anything opening with
  ``<``, ``{``, ``$`` or ``%``, and GitHub's runner accounts
  (``PLACEHOLDER_SEGMENTS``). Docs need examples.

The name is never written whole in this file: it is assembled from two pieces,
so the ratchet's own source is not a hit. Nothing it returns carries it either
— every line it reports is masked to ``<owner-name>``, because the CI log of a
public repository is public too.

EXEMPT — HISTORY, AND THE OWNER'S OPEN CALLS
--------------------------------------------
Never opened, for either rule. Full repo-relative paths (``EXEMPT_PATHS``):

* ``.claude/CLAUDE.md`` — the culture doc. History; it stays (the ruling).
* ``.claude/hooks/*.jsonl`` and ``.claude/hooks/*.log`` — the tracked hook run
  logs. The owner's call, pending.
* ``.claude/settings.json`` — the owner's call, pending.
* ``src/aipass/seedgo/tests/test_checkers_batch10.py`` — ``hardcoded_path``'s
  own inputs are home paths with a real name in them, and must stay.
* ``src/aipass/skills/tools/suspend/*`` — the suspend tool. The owner's call,
  pending.

File names at any depth (``EXEMPT_NAMES``):

* ``CHANGELOG.md`` — history; it stays (the ruling).
* ``*PLAN-*.md`` — plans are history; they stay (the ruling).

An exemption is that file, not its family: another branch's ``.claude/settings.json``,
a ``CLAUDE.md`` outside ``.claude/`` and ``test_checkers_batch11.py`` are all read.

THE BASELINE IS WHAT MAKES IT A RATCHET
---------------------------------------
Everything else that hits today is written down in ``name_ratchet_baseline.json``
as a COUNT of lines per file per rule. The file holds paths and numbers only —
never a line and never a hash of one — so the baseline cannot become the next
place the name ships. A file is red when its count for a rule is GREATER than
its baseline; a file the baseline does not list has a baseline of zero. At the
baseline passes. Below it passes too — the cure is never red — and is reported
as LOOSE with the number to write, because a ratchet only turns one way when
somebody tightens it.

Counts, not line hashes: a baselined fixture line that moves, or is edited
around, is the same line, and a hash would call it new. What a count cannot see
is one hit swapped for another inside a file already on the baseline — accepted,
because the residue is a handful of test and config files the owner rules on
one by one. A tracked PATH carrying the name cannot be baselined at all (its
key would carry the name); it is always red. Rename it.

ADVISORY FIRST. ``.github/scripts/seedgo_audit.py`` runs this after the startup
ratchet and prints it; while ``NAME_RATCHET_GATES`` there is False, a red prints
and the job carries on. Flipping it is @devpulse's call, once the owner has
ruled on the exempt set.

TRACKED MEANS ``git ls-files``. An untracked scratch file does not ship, so it is
not read. A tree git cannot list is RED, never clean — no file list is not the
same fact as no hits. A binary file (a NUL byte) is skipped and counted in the
report; anything else is decoded as utf-8, an undecodable byte replaced, which
cannot hide an ASCII name.

IT NEVER PRINTS. It returns lines; the ``.github`` runner prints them.

Design: DPLAN-0350 (the last step), @devpulse brief 69992eaf.
"""

import fnmatch
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# =============================================================================
# CONFIGURATION
# =============================================================================

#: Two pieces, so this file never holds the word it looks for and never flags
#: itself. Joined once; every test reads the joined value off this module.
_NAME_PIECES = ("pat", "rick")
OWNER_NAME = "".join(_NAME_PIECES)

#: What every reported line shows in the name's place.
MASK = "<owner-name>"

RULE_NAME = "name"
RULE_HOME = "home_path"

#: Repo-relative paths, fnmatch-matched against the WHOLE path.
EXEMPT_PATHS: Tuple[str, ...] = (
    ".claude/CLAUDE.md",
    ".claude/hooks/*.jsonl",
    ".claude/hooks/*.log",
    ".claude/settings.json",
    "src/aipass/seedgo/tests/test_checkers_batch10.py",
    "src/aipass/skills/tools/suspend/*",
)

#: File names, fnmatch-matched against the last path segment at any depth.
EXEMPT_NAMES: Tuple[str, ...] = ("CHANGELOG.md", "*PLAN-*.md")

#: The files the home-path rule reads: the ones rendered to a reader.
HOME_PATH_SUFFIXES: Tuple[str, ...] = (".md", "_content.py")

#: Home segments that name nobody. Compared lower-cased.
PLACEHOLDER_SEGMENTS = frozenset(
    {
        "user",
        "username",
        "you",
        "yourname",
        "your-name",
        "your_name",
        "me",
        "someone",
        "name",
        "example",
        "...",
        "x",
        "runner",
        "runneradmin",
        "runner~1",
    }
)

#: A segment opening with one of these is a template slot, not a login.
PLACEHOLDER_OPENERS: Tuple[str, ...] = ("<", "{", "$", "%", "*")

BASELINE_PATH = Path(__file__).with_name("name_ratchet_baseline.json")

TITLE = "NAME RATCHET — the owner's name (tracked files) and a person's home path (.md, *_content.py), at a baseline."

_NAME = re.compile(re.escape(OWNER_NAME), re.IGNORECASE)
_SEP = r"(?:\\{1,2}|/)"
_HOME_PATH = re.compile(
    r"(?:(?<![\w.])/(?:home|Users)/|(?<![A-Za-z])[A-Za-z]:" + _SEP + r"(?i:users)" + _SEP + r")"
    r"(?P<who>[^\\/\s'\"`()\[\],;:|]+)"
)
_SHOWN_CHARS = 140


class Hit(NamedTuple):
    """One line that breaks a rule. ``line`` 0 is the path itself; ``text`` is masked."""

    rel: str
    line: int
    rule: str
    text: str


# =============================================================================
# ONE FILE
# =============================================================================


def mask(text: str) -> str:
    """The text with every spelling of the name replaced by :data:`MASK`."""
    return _NAME.sub(MASK, text)


def exemption(rel: str) -> str:
    """The pattern that exempts ``rel``, or ``""`` when none does."""
    for pattern in EXEMPT_PATHS:
        if fnmatch.fnmatchcase(rel, pattern):
            return pattern
    leaf = rel.rsplit("/", 1)[-1]
    for pattern in EXEMPT_NAMES:
        if fnmatch.fnmatchcase(leaf, pattern):
            return pattern
    return ""


def _is_placeholder(who: str) -> bool:
    # A sentence can end on the path ("under /home/user."): the full stop is prose, not the login.
    bare = who.rstrip(".") or who
    return bare.lower() in PLACEHOLDER_SEGMENTS or who.startswith(PLACEHOLDER_OPENERS)


def home_paths(line: str) -> List[str]:
    """The home-directory segments in ``line`` that could be somebody's login."""
    return [found.group("who") for found in _HOME_PATH.finditer(line) if not _is_placeholder(found.group("who"))]


def _shown(line: str) -> str:
    shown = mask(line.strip())
    return shown if len(shown) <= _SHOWN_CHARS else shown[: _SHOWN_CHARS - 3] + "..."


def scan_text(rel: str, text: str) -> List[Hit]:
    """Every rule-breaking line of one file, masked.

    Args:
        rel: Repo-relative posix path — decides whether the home-path rule reads it.
        text: The file's decoded content.

    Returns:
        One :class:`Hit` per (line, rule); a line breaking both rules is two hits.
    """
    hits: List[Hit] = []
    if _NAME.search(rel):
        hits.append(Hit(rel, 0, RULE_NAME, mask(rel)))
    reads_homes = rel.endswith(HOME_PATH_SUFFIXES)
    for number, line in enumerate(text.splitlines(), start=1):
        if _NAME.search(line):
            hits.append(Hit(rel, number, RULE_NAME, _shown(line)))
        if reads_homes and home_paths(line):
            hits.append(Hit(rel, number, RULE_HOME, _shown(line)))
    return hits


# =============================================================================
# THE TREE
# =============================================================================


def tracked_files(repo_root: Path | str) -> Tuple[List[str], str]:
    """What git says ships: ``git ls-files`` from ``repo_root``.

    Returns:
        ``(paths, "")``, or ``([], reason)`` when git could not answer — which
        the caller turns into a red, never into an empty, clean tree.
    """
    try:
        done = subprocess.run(
            ["git", "ls-files", "-z"], cwd=str(repo_root), capture_output=True, timeout=120, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("name_ratchet: git ls-files could not run in %s: %s", repo_root, exc)
        return [], f"git ls-files could not run: {exc}"
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", errors="replace").strip()[:200]
        return [], f"git ls-files exited {done.returncode}: {said}"
    return [rel for rel in done.stdout.decode("utf-8", errors="replace").split("\0") if rel], ""


def _read(path: Path) -> Tuple[str, Optional[str]]:
    """``(state, text)`` — state is ``read``, ``binary``, ``missing`` or ``error: <why>``."""
    if not path.is_file():
        return "missing", None
    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.warning("name_ratchet: cannot read %s: %s", path, exc)
        return f"error: {exc}", None
    if b"\0" in data:
        return "binary", None
    return "read", data.decode("utf-8", errors="replace")


def scan_tree(repo_root: Path | str, files: Sequence[str]) -> Tuple[List[Hit], Dict[str, int], List[str]]:
    """Scan every non-exempt file. Exempt files are never opened.

    Returns:
        ``(hits, tally, errors)`` — tally counts ``read``/``exempt``/``binary``/
        ``missing`` files; errors are files that exist and could not be read.
    """
    root = Path(repo_root)
    hits: List[Hit] = []
    tally = {"read": 0, "exempt": 0, "binary": 0, "missing": 0}
    errors: List[str] = []
    for rel in files:
        if exemption(rel):
            tally["exempt"] += 1
            continue
        state, text = _read(root / rel)
        if text is None:
            if state.startswith("error"):
                errors.append(f"{mask(rel)} cannot be read ({state})")
            else:
                tally[state] += 1
            continue
        tally["read"] += 1
        hits.extend(scan_text(rel, text))
    return hits, tally, errors


def count_hits(hits: Sequence[Hit]) -> Dict[str, Dict[str, int]]:
    """``{rel: {rule: lines}}`` — the shape the baseline is written in."""
    counts: Dict[str, Dict[str, int]] = {}
    for hit in hits:
        per_rule = counts.setdefault(hit.rel, {})
        per_rule[hit.rule] = per_rule.get(hit.rule, 0) + 1
    return counts


# =============================================================================
# THE BASELINE
# =============================================================================


def load_baseline(path: Path | str) -> Tuple[Dict[str, Dict[str, int]], str]:
    """Read the baseline: ``{"files": {rel: {rule: count}}}``.

    Returns:
        ``(baseline, "")``, or ``({}, reason)`` when the file is missing,
        unparseable or misshapen — the caller reds the run on any reason.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("name_ratchet: baseline %s unreadable: %s", path, exc)
        return {}, f"baseline {Path(path).name} cannot be read: {exc}"
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        return {}, f"baseline {Path(path).name} has no 'files' mapping"
    baseline: Dict[str, Dict[str, int]] = {}
    for rel, rules in files.items():
        if not isinstance(rules, dict) or not all(
            rule in (RULE_NAME, RULE_HOME) and isinstance(n, int) and n >= 0 for rule, n in rules.items()
        ):
            return {}, f"baseline {Path(path).name}: entry {mask(rel)} is not {{rule: count}}"
        baseline[rel] = dict(rules)
    return baseline, ""


def compare(
    counts: Dict[str, Dict[str, int]], baseline: Dict[str, Dict[str, int]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """``(over, loose)``: entries above their baseline, and baseline entries now above the count."""
    over = [
        {"rel": rel, "rule": rule, "count": n, "allowed": baseline.get(rel, {}).get(rule, 0)}
        for rel, rules in sorted(counts.items())
        for rule, n in sorted(rules.items())
        if n > baseline.get(rel, {}).get(rule, 0)
    ]
    loose = [
        {"rel": rel, "rule": rule, "count": counts.get(rel, {}).get(rule, 0), "allowed": allowed}
        for rel, rules in sorted(baseline.items())
        for rule, allowed in sorted(rules.items())
        if counts.get(rel, {}).get(rule, 0) < allowed
    ]
    return over, loose


# =============================================================================
# THE LINES
# =============================================================================


def failure_lines(over: Sequence[Dict[str, Any]], hits: Sequence[Hit], reasons: Sequence[str]) -> List[str]:
    """One head line per file and rule over its baseline, then its lines, masked."""
    lines = [f"  CANNOT MEASURE: {reason}" for reason in reasons]
    for entry in over:
        lines.append(
            f"  {mask(entry['rel'])}: {entry['count']} {entry['rule']} line(s), baseline {entry['allowed']}"
            f" — NEW by {entry['count'] - entry['allowed']}"
        )
        lines.extend(
            f"    L{hit.line}: {hit.text}" for hit in hits if hit.rel == entry["rel"] and hit.rule == entry["rule"]
        )
    return lines


def report_lines(
    hits: Sequence[Hit], tally: Dict[str, int], over: Sequence[Dict[str, Any]], loose: Sequence[Dict[str, Any]]
) -> List[str]:
    """The whole run: what was read, what hit, what is new, what can tighten."""
    lines = [TITLE]
    lines.append(
        f"  {sum(tally.values())} tracked file(s): {tally['read']} read, {tally['exempt']} exempt "
        f"(never opened), {tally['binary']} binary, {tally['missing']} missing from the working tree"
    )
    for rule in (RULE_NAME, RULE_HOME):
        ruled = [hit for hit in hits if hit.rule == rule]
        new = sum(entry["count"] - entry["allowed"] for entry in over if entry["rule"] == rule)
        files = len({hit.rel for hit in ruled})
        lines.append(f"  {rule}: {len(ruled)} line(s) in {files} file(s), {len(ruled) - new} baselined, {new} NEW")
    lines.extend(
        f"  LOOSE: {mask(entry['rel'])} {entry['rule']} baseline {entry['allowed']}, now {entry['count']}"
        f" — write {entry['count']}"
        for entry in loose
    )
    return lines


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================


def run(
    repo_root: Path | str, files: Optional[Sequence[str]] = None, baseline_path: Optional[Path | str] = None
) -> Dict[str, Any]:
    """Hold the tree at its baseline. The whole verdict, once.

    Args:
        repo_root: The checkout's root; every path is read relative to it.
        files: Repo-relative paths to scan. None asks git (``git ls-files``).
        baseline_path: The baseline to hold. None is the shipped one.

    Returns:
        ``{"passed", "hits", "counts", "over", "loose", "tally", "failure_lines", "report"}``.
        ``passed`` is False when any file is over its baseline OR when the run
        could not measure — git could not list, the baseline could not be read,
        a tracked file could not be opened.
    """
    reasons: List[str] = []
    if files is None:
        files, reason = tracked_files(repo_root)
        if reason:
            reasons.append(reason)
    baseline, reason = load_baseline(baseline_path or BASELINE_PATH)
    if reason:
        reasons.append(reason)
    hits, tally, errors = scan_tree(repo_root, files)
    reasons.extend(errors)
    counts = count_hits(hits)
    over, loose = compare(counts, baseline)
    if over or reasons:
        logger.warning("name_ratchet: %d entry(ies) over baseline, %d unmeasured", len(over), len(reasons))
    json_handler.log_operation(
        "name_ratchet_completed",
        {"files": len(files), "hits": len(hits), "over": len(over), "loose": len(loose), "unmeasured": len(reasons)},
    )
    return {
        "passed": not over and not reasons,
        "hits": hits,
        "counts": counts,
        "over": over,
        "loose": loose,
        "tally": tally,
        "failure_lines": failure_lines(over, hits, reasons),
        "report": report_lines(hits, tally, over, loose),
    }
