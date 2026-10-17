# =================== AIPass ====================
# Name: utils.py
# Description: Shared bypass checking utility for standards checkers
# Version: 1.1.0
# Created: 2026-04-27
# Modified: 2026-10-17
# =============================================

"""Shared bypass checking utility for standards checkers."""

from pathlib import Path

from aipass.seedgo.apps.handlers.json import json_handler


def _scope_matches(rule: dict, line: int | None, name: str | None) -> bool:
    """Decide whether a rule's declared scope is satisfied by what the caller supplied.

    Every evaluable scope must match and at least one must be evaluable: scope the caller
    supplied nothing for is INERT, never file-wide. No scope keys means file-wide.
    """
    functions, rule_lines = rule.get("functions"), rule.get("lines")
    if not functions and not rule_lines:
        return True

    evaluable = False
    if functions and name is not None:
        if name not in functions:
            return False
        evaluable = True
    if rule_lines and line is not None:
        if line not in rule_lines:
            return False
        evaluable = True
    return evaluable


def matching_rule(
    file_path: str,
    standard: str,
    line: int | None = None,
    bypass_rules: list | None = None,
    name: str | None = None,
) -> dict | None:
    """The first bypass rule that covers this violation, or None.

    Callers needing ``category``/``reason`` use this; never re-implement the match.
    """
    if not bypass_rules:
        return None
    file_path_posix = Path(file_path).as_posix()
    for rule in bypass_rules:
        # A rule is active only when it names BOTH a file and a standard: a blank does nothing.
        rule_file, rule_standard = rule.get("file") or "", rule.get("standard") or ""
        if not rule_file or rule_standard != standard:
            continue
        if Path(rule_file).as_posix() not in file_path_posix:
            continue
        if not _scope_matches(rule, line, name):
            continue
        json_handler.log_operation(
            "bypass_matched",
            {
                "file": file_path,
                "standard": standard,
                "line": line,
                "name": name,
                "rule_file": rule_file,
            },
        )
        return rule
    return None


def is_bypassed(
    file_path: str,
    standard: str,
    line: int | None = None,
    bypass_rules: list | None = None,
    name: str | None = None,
) -> bool:
    """Check if a violation should be bypassed."""
    return matching_rule(file_path, standard, line, bypass_rules, name) is not None
