# =================== AIPass ====================
# Name: utils.py
# Description: Shared bypass checking utility for standards checkers
# Version: 1.0.0
# Created: 2026-04-27
# Modified: 2026-04-27
# =============================================

"""Shared bypass checking utility for standards checkers."""

from pathlib import Path

from aipass.seedgo.apps.handlers.json import json_handler


def _scope_matches(rule: dict, line: int | None, name: str | None) -> bool:
    """Decide whether a rule's declared scope is satisfied by what the caller supplied.

    A rule may narrow itself with ``lines`` and/or ``functions``. The contract:

    - every declared scope the caller CAN evaluate must match -- a rule for
      ``update_command`` does not cover a different symbol on the same line;
    - at least one declared scope must actually be evaluable. A rule that declares
      scope the caller supplied nothing for is INERT, not file-wide.

    That last clause is the fix. It used to fall through to a match, and every
    checker's top-of-check_module gate passes neither line nor name -- so a rule
    reading ``"lines": [37, 66]`` silently suppressed the whole file for that
    standard, and the per-line call sites that did pass a line were dead code.

    A rule with no ``lines``/``functions`` keys is file-wide by design and always
    matches here.
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

    Same decision as :func:`is_bypassed`, but hands back the rule so a caller
    that needs the ``category``/``reason`` annotations can read them instead of
    re-implementing the match. trigger_check used to carry its own copy for
    exactly that reason, and the copy never received the FPLAN-0382 scope fix --
    a second implementation of a rule matcher is a second set of semantics.

    Args:
        file_path: Path to the file being checked
        standard: Standard name (e.g., 'cli', 'imports')
        line: Optional specific line number of the violation
        bypass_rules: List of bypass rules from .seedgo/bypass.json
        name: Optional function/symbol name for name-scoped bypasses

    Returns:
        The matching rule dict, or None when nothing covers this violation
    """
    if not bypass_rules:
        return None
    # Normalize to forward slashes for cross-platform matching
    file_path_posix = Path(file_path).as_posix()
    for rule in bypass_rules:
        if rule.get("standard") and rule.get("standard") != standard:
            continue
        rule_file = rule.get("file", "")
        if rule_file and Path(rule_file).as_posix() not in file_path_posix:
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
    """Check if a violation should be bypassed.

    Args:
        file_path: Path to the file being checked
        standard: Standard name (e.g., 'cli', 'imports')
        line: Optional specific line number of the violation
        bypass_rules: List of bypass rules from .seedgo/bypass.json
        name: Optional function/symbol name for name-scoped bypasses

    Returns:
        True if this violation should be bypassed
    """
    return matching_rule(file_path, standard, line, bypass_rules, name) is not None
