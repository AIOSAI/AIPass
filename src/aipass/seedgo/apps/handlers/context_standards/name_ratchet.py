# =================== AIPass ====================
# Name: name_ratchet.py
# Description: CI ratchet — the owner's first name and a person's home path never regrow in the tracked tree
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-10-17
# =============================================

"""The name ratchet — the public tree never names its owner (DPLAN-0350).

Rule ``name``: the owner's first name, case-insensitive, as a substring of every tracked
text file's lines and of its path. Rule ``home_path``: an absolute home directory in a
``.md`` or ``*_content.py`` (the files rendered to a reader); ``PLACEHOLDER_SEGMENTS``
and template openers name nobody. Home paths in code are ``hardcoded_path``'s.

The name is assembled from two pieces so this source is not a hit, and every reported
line is masked: a public repo's CI log is public too.

Never opened (an exemption is that file, not its family; tests read this list off the doc):
``EXEMPT_PATHS`` by whole path: ``.claude/CLAUDE.md``, ``.claude/hooks/*.jsonl``,
``.claude/hooks/*.log``, ``.claude/settings.json``, ``src/aipass/skills/tools/suspend/*``,
``src/aipass/seedgo/tests/test_checkers_batch10.py`` (``hardcoded_path``'s own inputs);
``EXEMPT_NAMES`` by leaf at any depth: ``CHANGELOG.md``, ``*PLAN-*.md`` (history).

``name_ratchet_baseline.json`` holds counts per file per rule, never a line or a hash,
so it cannot ship the name. Over is red; at or below passes, below is reported LOOSE.
A tracked path carrying the name cannot be baselined, so it is always red.

Tracked means ``git ls-files``; a tree that cannot be listed is red, never clean. Advisory
while ``NAME_RATCHET_GATES`` in ``.github/scripts/seedgo_audit.py`` is False. Never prints.
"""

import fnmatch
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

#: Tests read the joined value off this module; never write the name whole here.
_NAME_PIECES = ("pat", "rick")
OWNER_NAME = "".join(_NAME_PIECES)

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
    """Every rule-breaking line of one file, masked; a line breaking both rules is two hits."""
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


def tracked_files(repo_root: Path | str) -> Tuple[List[str], str]:
    """What git says ships: ``(paths, "")``, or ``([], reason)``, which the caller turns red."""
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
    """Scan every non-exempt file into ``(hits, tally, errors)``; exempt files are never opened."""
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


def load_baseline(path: Path | str) -> Tuple[Dict[str, Dict[str, int]], str]:
    """Read the baseline ``{"files": {rel: {rule: count}}}``; any reason returned is a red."""
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


def run(
    repo_root: Path | str, files: Optional[Sequence[str]] = None, baseline_path: Optional[Path | str] = None
) -> Dict[str, Any]:
    """Hold the tree at its baseline; ``passed`` is False when over OR when anything went unmeasured."""
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
