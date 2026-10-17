# =================== AIPass ====================
# Name: argv.py
# Description: audit verb argument grammar, read once and answered as data
# Version: 1.0.0
# Created: 2026-09-07
# Modified: 2026-10-17
# =============================================

"""
The `audit` verb's argument grammar.

An unclaimed token is collected, never dropped; the caller decides, and help wins.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from aipass.seedgo.apps.handlers.cli.help_flags import DASHED_HELP_TOKENS
from aipass.seedgo.apps.handlers.json import json_handler

#: Every flag this verb accepts — the list a mistyped token is offered against.
AUDIT_FLAGS: tuple = tuple(
    "--show-bypasses --bypasses -b --no-bypass --full --artifact --no-artifact --help -h".split()
)

#: Pack, then @branch. A third bare word fills no slot: refused, never dropped.
MAX_POSITIONAL = 2

_HELP_WORDS: tuple = ("--help", "-h", "help")


@dataclass
class AuditArgv:
    """One reading of the verb's arguments. Nothing here has acted yet."""

    #: A help spelling appeared; answered before anything else, a refusal included.
    wants_help: bool = False
    positional: List[str] = field(default_factory=list)
    #: Tokens no branch of the grammar claimed (Law ARGV). First one is refused.
    unrecognized: List[str] = field(default_factory=list)
    show_bypasses: bool = False
    no_bypass: bool = False
    force_full: bool = False
    write_artifact: bool = True
    artifact_path: Optional[str] = None
    artifact_path_missing: bool = False


def parse(args: Sequence[str]) -> AuditArgv:
    """Read the whole argument list and answer what it says."""
    parsed = AuditArgv()
    expect_artifact_path = False
    for arg in args:
        # Before the value slot: `--artifact --help` prints help, not an artifact named `--help`.
        if arg in DASHED_HELP_TOKENS:
            parsed.wants_help = True
            return parsed
        if expect_artifact_path:
            parsed.artifact_path = arg
            expect_artifact_path = False
            continue
        if arg in ("--show-bypasses", "--bypasses", "-b"):
            parsed.show_bypasses = True
            continue
        if arg == "--no-bypass":
            parsed.no_bypass = True
            continue
        if arg == "--full":
            parsed.force_full = True
            continue
        if arg == "--artifact":
            expect_artifact_path = True
            continue
        if arg.startswith("--artifact="):
            parsed.artifact_path = arg.split("=", 1)[1]
            continue
        if arg == "--no-artifact":
            parsed.write_artifact = False
            continue
        if arg in _HELP_WORDS:
            parsed.wants_help = True
            return parsed
        if not arg.startswith("-"):
            parsed.positional.append(arg)
            if len(parsed.positional) > MAX_POSITIONAL:
                parsed.unrecognized.append(arg)
            continue
        parsed.unrecognized.append(arg)
    parsed.artifact_path_missing = expect_artifact_path
    _log_anomalies(args, parsed)
    return parsed


def _log_anomalies(args: Sequence[str], parsed: AuditArgv) -> None:
    """Record what argv held when the grammar left something unclaimed; a clean parse writes nothing."""
    if not parsed.unrecognized and not parsed.artifact_path_missing:
        return
    json_handler.log_operation(
        "audit_argv_unclaimed",
        {
            "args": list(args),
            "unrecognized": list(parsed.unrecognized),
            "artifact_path_missing": parsed.artifact_path_missing,
        },
    )
