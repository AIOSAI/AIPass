# =================== AIPass ====================
# Name: rm_gate.py
# Version: 1.1.0
# Description: Guardrail — catches accidental rm -rf, records every raw rm (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-06-02
# Modified: 2026-08-14
# =============================================

"""Early-feedback guardrail — catches accidental recursive rm and teaches drone rm.

Belt-and-suspenders: the actual filesystem boundary is the kernel sandbox
(srt/bwrap) enforced at agent launch. This hook provides fast, helpful feedback
before the sandbox would block the operation at the kernel level.

It also keeps the deletion record for the unsanctioned lane: every raw rm this
gate sees is written down, allowed or blocked. @drone records `drone rm`; this
covers what used to pass through silently.
"""

import json
import re
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger


RM_REDIRECT = (
    "Heads up — raw recursive rm is not the right tool here. Use:\n"
    "  drone rm <path>     # project-aware delete (allows project + /tmp, refuses outside)\n"
    "\n"
    "This guardrail catches rm -rf, rm -r, rm -R, and rm --recursive."
)

_BLOCK_ALLOW = {"stdout": "", "exit_code": 0}

# Prefixes whose deletions belong to someone else's record. `drone rm` is the
# sanctioned lane and @drone writes it down; `git rm` removes from the index and
# answers to git_gate. Logging either here would double-count the fleet's deletions.
_RECORDED_ELSEWHERE = {"drone", "git"}


def _block(reason: str) -> dict:
    return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "rm gate"}


def _strip_quotes(cmd: str) -> str:
    """Remove quoted strings so their contents aren't scanned."""
    cmd = re.sub(r'"(?:[^"\\]|\\.)*"', '""', cmd)
    cmd = re.sub(r"'(?:[^'\\]|\\.)*'", "''", cmd)
    return cmd


def _split_clauses(cmd: str) -> list[str]:
    """Split on compound operators and subshell boundaries."""
    parts = re.split(r"&&|\|\||[;|]", cmd)
    clauses: list[str] = []
    for part in parts:
        clauses.extend(re.split(r"[$()`]", part))
    return clauses


def _has_recursive_flag(tokens: list[str]) -> bool:
    """Return True if any token before '--' contains a recursive flag."""
    for token in tokens:
        if token == "--":
            break
        if token.startswith("-") and not token.startswith("--"):
            if "r" in token[1:] or "R" in token[1:]:
                return True
        elif token == "--recursive":
            return True
    return False


def _scan_clause(clause: str) -> tuple[bool, bool]:
    """Return (deletes, recursive) for one clause in a single token walk.

    Two different questions off the same walk: the gate asks whether this is a
    raw *recursive* rm, the deletion record asks whether anything gets deleted
    at all. They skip different prefixes — `git rm` touches the index and has
    its own lane, but `git rm -r` is still a raw recursive rm to the gate.
    """
    deletes = False
    recursive = False
    tokens = clause.split()
    for i, tok in enumerate(tokens):
        if tok != "rm" and not tok.endswith("/rm"):
            continue
        prev = tokens[i - 1] if i > 0 else ""
        if prev != "drone" and _has_recursive_flag(tokens[i + 1 :]):
            recursive = True
        if prev not in _RECORDED_ELSEWHERE:
            deletes = True
    return deletes, recursive


def _clause_has_raw_recursive_rm(clause: str) -> bool:
    """Return True if a single clause contains a raw recursive rm."""
    return _scan_clause(clause)[1]


def _caller_branch(cwd: str) -> str:
    """Name the citizen that ran the command, from its passport — never the path.

    Path shape lies (learning 109): a projects/* seat has no src/<pkg>/<branch>
    shape and a branch directory can be named anything. The passport does not.
    An unresolvable branch costs the record its name, never the record.
    """
    try:
        search = Path(cwd).resolve()
        home = Path.home()
        while search != home and search.parent != search:
            passport = search / ".trinity" / "passport.json"
            if passport.exists():
                data = json.loads(passport.read_text(encoding="utf-8"))
                branch = data.get("branch_info", {})
                identity = data.get("identity", {})
                return branch.get("branch_name") or identity.get("name") or "unknown"
            search = search.parent
    except Exception as exc:
        logger.info("[HOOKS] rm_gate: caller branch unresolved for %s: %s", cwd, exc)
        return "unknown"
    return "unknown"


def _record(cmd: str, cwd: str, deletions: int, blocked: bool) -> None:
    """Write down every raw rm this gate sees — one line per deleting clause.

    Patrick, 2026-08-14: "if something deletes, it should be a record of it."
    The command is logged as the agent wrote it; quote-stripping is how matching
    works, not what happened. INFO by design (compass #273): a permitted delete is
    chosen behaviour, and the engine already records the block at WARNING — this
    line adds the command, cwd and caller the engine never carried.
    """
    status = "blocked" if blocked else "allowed"
    branch = _caller_branch(cwd)
    for _ in range(deletions):
        logger.info("[HOOKS] rm_gate: DELETE %s | branch=%s | cwd=%s | cmd=%s", status, branch, cwd, cmd)


def handle(hook_data: dict) -> dict:
    """Block raw recursive rm commands and teach drone rm.

    Args:
        hook_data: Parsed hook event dict from engine.

    Returns:
        Result dict with stdout (block JSON or empty) and exit_code.
    """
    try:
        tool_name = hook_data.get("tool_name", "")
        if tool_name != "Bash":
            return _BLOCK_ALLOW

        tool_input = hook_data.get("tool_input", {})
        cmd = tool_input.get("command", "")
        if not cmd:
            return _BLOCK_ALLOW

        scan = _strip_quotes(cmd)
        deletions = 0
        recursive = False
        for clause in _split_clauses(scan):
            clause_deletes, clause_recursive = _scan_clause(clause)
            deletions += 1 if clause_deletes else 0
            recursive = recursive or clause_recursive

        if deletions:
            _record(cmd, hook_data.get("cwd", ""), deletions, blocked=recursive)

        if recursive:
            return _block(RM_REDIRECT)

        return _BLOCK_ALLOW

    except Exception as exc:
        logger.info("[HOOKS] rm_gate: unexpected error (allowing): %s", exc)
        return _BLOCK_ALLOW
