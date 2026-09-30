# =================== AIPass ====================
# Name: dead_rules.py
# Description: Bypass rules that match nothing, and inline bypass comments nothing reads
# Version: 1.1.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""Bypass hygiene: rules that can never match, and comments that claim a rule.

A ``.seedgo/bypass.json`` rule is applied by ``utils.matching_rule``: its ``file``
is a SUBSTRING of the path a checker is handed, and its ``standard`` names one
checker. A rule is dead (it matches nothing, so it does nothing) when:

- its ``file`` is a substring of no file a lane can hand a checker. Retired
  directories, ``(disabled)`` names and caches are never handed to one;
- its ``standard`` is not a discovered checker;
- it is line-level, and every line it names lies past the end of every file
  it matches;
- its ``file`` or its ``standard`` is blank. A rule is active only when it names
  both (owner, 2026-09-25 18:55, survey row #10): the matcher skips it.

``prune`` removes the first three kinds and leaves a blank-field rule for its
owner: its reason is the owner's intent, and the cure is to rewrite it as named
rules, which no tool can do for them.

The inline comment form (a ``#`` then ``seedgo:bypass standard=... reason=...``)
has never been read by any code path. Every one in the corpus is reported as a
comment that claims an exception nobody grants.

Survey rows #11-#13, DPLAN-0354, 2026-09-25.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards import applicability
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import is_disabled_file
from aipass.seedgo.apps.handlers.json import json_handler

#: A whole-line comment, or a trailing one with no quote before its hash. The
#: quote clause keeps a string that only mentions the form out of the list.
_MARKER = re.compile(r"^[^\"'\n]*#\s*seedgo:bypass\b", re.MULTILINE)

#: Directories no lane hands a checker a file from, beside the retired ones.
_NEVER_HANDED = frozenset({".git", "__pycache__", ".venv", "node_modules"})

#: The json.dumps variants a bypass.json is found written in: (ensure_ascii, trailing newline).
_STYLES: Tuple[Tuple[bool, bool], ...] = ((True, False), (True, True), (False, False), (False, True))


def handed_files(branch_path: Path) -> List[str]:
    """Absolute posix paths of every file under the branch that a lane can hand a checker."""
    root = branch_path.resolve()
    handed: List[str] = []

    def _unlistable(err: OSError) -> None:
        logger.warning("[dead_rules] cannot list %s: %s", err.filename, err)

    for dirpath, dirnames, filenames in os.walk(root, onerror=_unlistable):
        dirnames[:] = [d for d in dirnames if d not in _NEVER_HANDED and d not in applicability.RETIRED_DIRS]
        handed.extend((Path(dirpath) / name).as_posix() for name in filenames if not is_disabled_file(name))
    return handed


def _line_count(path: str) -> Optional[int]:
    """Lines in a file, or None when it cannot be read (a rule is never convicted on a guess)."""
    try:
        return Path(path).read_bytes().count(b"\n") + 1
    except OSError as exc:
        logger.warning("[dead_rules] cannot read %s to count its lines: %s", path, exc)
        return None


def why_dead(rule: Dict[str, Any], handed: List[str], known_standards: Set[str]) -> Optional[str]:
    """Why this rule can never match, or None when it can."""
    rule_file, standard = rule.get("file") or "", rule.get("standard") or ""
    if not rule_file or not standard:
        return f"blank {'file' if not rule_file else 'standard'}: a rule needs a file and a standard to be active"
    if standard not in known_standards:
        return f"standard '{standard}' is not a checker"
    needle = Path(rule_file).as_posix()
    matched = [path for path in handed if needle in path]
    if not matched:
        return f"file '{rule_file}' matches no file on disk"
    lines = rule.get("lines")
    if lines and all(isinstance(line, int) for line in lines):
        counts = [_line_count(path) for path in matched]
        if None not in counts:
            longest = max(c for c in counts if c is not None)
            if min(lines) > longest:
                return f"lines {lines} lie past the end of every matching file (longest {longest})"
    return None


def dead_rules(branch_path: Path, rules: List[Dict[str, Any]], known_standards: Set[str]) -> List[Dict[str, Any]]:
    """Every rule in the list that can never match, with its index, fields, why, and its own reason."""
    if not rules:
        return []
    handed = handed_files(branch_path)
    dead = []
    for index, rule in enumerate(rules):
        why = why_dead(rule, handed, known_standards)
        if why is not None:
            dead.append(
                {
                    "index": index,
                    "file": rule.get("file", ""),
                    "standard": rule.get("standard", ""),
                    "why": why,
                    "reason": rule.get("reason", ""),
                    "blank": not rule.get("file") or not rule.get("standard"),
                }
            )
    return dead


def bypass_markers(branch_path: Path, files: Iterable[str]) -> List[str]:
    """``rel:line`` for every inline bypass comment in these files. Nothing honours one."""
    root = branch_path.resolve()
    found: List[Tuple[str, int]] = []
    for file_path in files:
        path = Path(file_path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("[dead_rules] cannot read %s for bypass comments: %s", path, exc)
            continue
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError as exc:
            logger.info("[dead_rules] %s is outside %s, named whole: %s", path, root, exc)
            rel = path.as_posix()
        found.extend((rel, text.count("\n", 0, m.start()) + 1) for m in _MARKER.finditer(text))
    return [f"{rel}:{line}" for rel, line in sorted(found)]


def _dump_style(config: Dict[str, Any], text: str) -> Optional[Tuple[bool, bool]]:
    """The json.dumps variant that reproduces this file byte for byte, or None."""
    for ensure_ascii, newline in _STYLES:
        if json.dumps(config, indent=2, ensure_ascii=ensure_ascii) + ("\n" if newline else "") == text:
            return ensure_ascii, newline
    return None


def prune(branch_path: Path, known_standards: Set[str], dry_run: bool = True) -> Dict[str, Any]:
    """Remove the dead rules from a branch's bypass.json; with dry_run, write nothing.

    Only rules :func:`dead_rules` convicts are removed, so a live rule is never
    touched, and a blank-field rule is left for its owner to rewrite (it is
    reported under ``left``). A file that json.dumps cannot reproduce is refused
    rather than rewritten, because the rewrite would reformat every line the
    owner wrote.

    Raises:
        OSError: the bypass.json cannot be read or written.
        json.JSONDecodeError: the bypass.json is not JSON.
    """
    bypass_file = branch_path / ".seedgo" / "bypass.json"
    text = bypass_file.read_text(encoding="utf-8")
    config = json.loads(text)
    rules = config.get("bypass", [])
    convicted = dead_rules(branch_path, rules, known_standards)
    dead = [entry for entry in convicted if not entry["blank"]]
    outcome: Dict[str, Any] = {
        "file": str(bypass_file),
        "dead": dead,
        "left": [entry for entry in convicted if entry["blank"]],
        "kept": len(rules) - len(dead),
        "written": False,
        "refused": None,
    }
    if not dead or dry_run:
        return outcome
    style = _dump_style(config, text)
    if style is None:
        outcome["refused"] = "the file does not round-trip through json.dumps(indent=2); a rewrite would reformat it"
        return outcome
    gone = {entry["index"] for entry in dead}
    config["bypass"] = [rule for index, rule in enumerate(rules) if index not in gone]
    ensure_ascii, newline = style
    bypass_file.write_text(
        json.dumps(config, indent=2, ensure_ascii=ensure_ascii) + ("\n" if newline else ""), encoding="utf-8"
    )
    outcome["written"] = True
    json_handler.log_operation(
        "bypass_rules_pruned",
        {"file": str(bypass_file), "removed": [entry["index"] for entry in dead], "kept": outcome["kept"]},
    )
    return outcome
