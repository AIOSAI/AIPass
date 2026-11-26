# =================== AIPass ====================
# Name: dead_rules.py
# Description: Bypass rules that match nothing, and inline bypass comments nothing reads
# Version: 1.4.2
# Created: 2026-09-25
# Modified: 2026-11-26
# =============================================

"""Bypass hygiene: rules that can never match, rules that cover nothing, and comments that claim a rule.

``utils.matching_rule`` treats a rule's ``file`` as a SUBSTRING of the handed path
and skips a rule with a blank field. No code path reads the inline comment form.
A rule covers nothing when, with it removed, its checker answers the same or a clean pass.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from aipass.prax import logger
from aipass.sentry.apps.handlers.aipass_standards import applicability
from aipass.sentry.apps.handlers.aipass_standards.skip_dirs import is_disabled_file
from aipass.sentry.apps.handlers.checklist.verdicts import is_applicable
from aipass.sentry.apps.handlers.json import json_handler

#: The no-quote-before-hash clause keeps a string that only mentions the form out of the list.
_MARKER = re.compile(r"^[^\"'\n]*#\s*sentry:bypass\b", re.MULTILINE)

#: Directories no lane hands a checker a file from, beside the retired ones.
_NEVER_HANDED = frozenset({".git", "__pycache__", ".venv", "node_modules"})


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


def _verdict(result: Dict[str, Any]) -> Tuple[Any, ...]:
    """What a checker answered: its score and every check's name, verdict and message."""
    checks = tuple((c.get("name"), c.get("passed"), c.get("message")) for c in result.get("checks", []))
    return result.get("score"), result.get("passed"), checks


def _answer(checker: Any, branch_path: Path, files: List[str], rules: List[Dict[str, Any]]) -> Tuple[Any, ...]:
    """The checker's verdict under these rules: once for the branch, or once per file it would be handed."""
    if getattr(checker, "AUDIT_SCOPE", "") == "branch_level" or not hasattr(checker, "check_module"):
        return (_verdict(checker.check_branch(str(branch_path), bypass_rules=rules)),)
    return tuple(_verdict(checker.check_module(path, bypass_rules=rules)) for path in files)


def covers_nothing(
    branch_path: Path, rules: List[Dict[str, Any]], index: int, checker: Any, handed: List[str]
) -> Optional[str]:
    """Why rule ``index`` waives nothing (without it, its checker answers the same or a clean pass), or None.

    A checker with a post-pass or observe lane is not judged: those read the rules outside these two calls.
    """
    if hasattr(checker, "check_branch_post") or hasattr(checker, "check_branch_observe"):
        return None
    rule = rules[index]
    needle = Path(rule["file"]).as_posix()
    files = [path for path in handed if needle in path and path.endswith(".py")]
    bare = _answer(checker, branch_path, files, rules[:index] + rules[index + 1 :])
    # A file-wide waiver answers "bypassed", never equal to the bare answer, so a clean bare answer convicts too.
    clean = all(
        score in (None, 100) and passed is True and all(c[1] is True for c in checks) for score, passed, checks in bare
    )
    if not clean and _answer(checker, branch_path, files, rules) != bare:
        return None
    return f"covers nothing: {rule['standard']} answers the same or passes clean with this rule removed"


def _absent_targets(branch_path: Path, checkers: Dict[str, Any]) -> Dict[str, List[str]]:
    """Per standard, the paths its checker judges though they are absent; a row naming one is live by construction."""
    found = {}
    for name, checker in checkers.items():
        lister = getattr(checker, "absent_targets", None)
        if lister is not None:
            found[name] = lister(str(branch_path))
    return found


def dead_rules(
    branch_path: Path,
    rules: List[Dict[str, Any]],
    known_standards: Set[str],
    checkers: Optional[Dict[str, Any]] = None,
    handed_by: Optional[Dict[str, List[str]]] = None,
    listers: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Every rule in the list that can never match, with its index, fields, why, and its own reason.

    With ``checkers`` (standard -> checker module), a rule that matches but waives nothing is dead too;
    ``handed_by`` (standard -> the files the audit hands that checker) limits each checker to its own files.
    ``listers`` (standard -> checker) are asked only for their absent targets, never re-run per rule.
    """
    if not rules:
        return []
    handed = handed_files(branch_path)
    absent = _absent_targets(branch_path, {**(listers or {}), **(checkers or {})})
    dead = []
    for index, rule in enumerate(rules):
        needle = Path(rule.get("file") or "").as_posix()
        if needle and any(needle in target for target in absent.get(rule.get("standard") or "", [])):
            continue
        why = why_dead(rule, handed, known_standards)
        if why is None and checkers and rule.get("standard") in checkers:
            checker = checkers[rule["standard"]]
            own = handed if handed_by is None else handed_by.get(rule["standard"], [])
            # A rule is live if either lane uses it: the checklist hands files the audit never does (__init__.py).
            own = sorted(set(own) | {path for path in handed if is_applicable(checker, path)})
            why = covers_nothing(branch_path, rules, index, checker, own)
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


def _skip(text: str, pos: int) -> int:
    """The first index at or after pos that is not JSON whitespace."""
    while pos < len(text) and text[pos] in " \t\r\n":
        pos += 1
    return pos


def without_rules(text: str, gone: Set[int]) -> str:
    """The file's text with these indexes cut from its top-level "bypass" array; every other byte kept."""
    decoder = json.JSONDecoder()
    pos = _skip(text, text.index("{") + 1)
    while text[pos] != "}":
        key, pos = decoder.raw_decode(text, pos)
        pos = _skip(text, _skip(text, pos) + 1)
        if key == "bypass":
            break
        pos = _skip(text, decoder.raw_decode(text, pos)[1])
        pos = _skip(text, pos + 1) if text[pos] == "," else pos
    else:
        raise ValueError('no top-level "bypass" array')
    spans: List[Tuple[int, int]] = []
    item = _skip(text, pos + 1)
    while text[item] != "]":
        end = decoder.raw_decode(text, item)[1]
        spans.append((item, end))
        after = _skip(text, end)
        item = _skip(text, after + 1) if text[after] == "," else after
    if not spans:
        return text
    sep = text[spans[0][1] : spans[1][0]] if len(spans) > 1 else ""
    kept = [text[start:end] for index, (start, end) in enumerate(spans) if index not in gone]
    if not kept:
        return text[: pos + 1] + text[item:]
    return text[: spans[0][0]] + sep.join(kept) + text[spans[-1][1] : item] + text[item:]


def prune(
    branch_path: Path,
    known_standards: Set[str],
    dry_run: bool = True,
    checkers: Optional[Dict[str, Any]] = None,
    handed_by: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Remove the dead rules from a branch's bypass.json; with dry_run, write nothing.

    Blank-field rules are left for their owner; only the dead rules' text is cut, the owner's layout kept.
    """
    bypass_file = branch_path / ".sentry" / "bypass.json"
    text = bypass_file.read_text(encoding="utf-8")
    config = json.loads(text)
    rules = config.get("bypass", [])
    convicted = dead_rules(branch_path, rules, known_standards, checkers, handed_by)
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
    gone = {entry["index"] for entry in dead}
    config["bypass"] = [rule for index, rule in enumerate(rules) if index not in gone]
    new_text = ""
    try:
        new_text = without_rules(text, gone)
        reads_back = json.loads(new_text) == config
    except (ValueError, IndexError) as exc:
        logger.warning("[dead_rules] cannot cut rules from %s: %s", bypass_file, exc)
        reads_back = False
    if not reads_back:
        outcome["refused"] = "the rewrite did not read back as the kept rules"
        return outcome
    bypass_file.write_text(new_text, encoding="utf-8")
    outcome["written"] = True
    json_handler.log_operation(
        "bypass_rules_pruned",
        {"file": str(bypass_file), "removed": [entry["index"] for entry in dead], "kept": outcome["kept"]},
    )
    return outcome
