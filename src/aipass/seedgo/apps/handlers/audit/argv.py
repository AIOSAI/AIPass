# =================== AIPass ====================
# Name: argv.py
# Description: audit verb argument grammar, read once and answered as data
# Version: 1.0.0
# Created: 2026-09-07
# Modified: 2026-09-07
# =============================================

"""
The `audit` verb's argument grammar.

WHY IT IS NOT IN THE MODULE. `standards_audit` crossed the 600-line module bar
on 2026-09-07, while the unknown-argument ruling was being wired into it, and
the loop that reads argv was the largest thing in that file which is neither
display nor control flow: it decides nothing, prints nothing, and runs no
audit. The module still owns every decision — what to print, what to refuse,
what to audit — it just stopped owning the reading.

LAW ARGV LIVES HERE TOO. A token nobody claims is COLLECTED, never dropped,
and the whole list is read before the caller acts on any of it: a help flag
further along is a question, and a question is answered even beside nonsense.
So `wants_help` and `unrecognized` can both be set on one parse, and the
caller decides which wins — help does.

The parse answers `artifact_path_missing` rather than raising on `--artifact`
with nothing after it. A parser that refuses is a parser its own tests cannot
exercise without a console, and the refusal's exit code belongs to the module
that owns the verb.
"""

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# IMPORTS
# =============================================================================

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from aipass.seedgo.apps.handlers.cli.help_flags import DASHED_HELP_TOKENS
from aipass.seedgo.apps.handlers.json import json_handler

# =============================================================================
# GRAMMAR
# =============================================================================

#: Every flag this verb accepts — the list a mistyped token is offered against.
AUDIT_FLAGS: tuple = tuple(
    "--show-bypasses --bypasses -b --no-bypass --full --artifact --no-artifact --help -h".split()
)

#: Pack, then @branch. A third bare word fills no slot: refused, never dropped.
MAX_POSITIONAL = 2

#: The spellings that ask for help from inside the loop. `help` with no dashes
#: is here and not in :data:`DASHED_HELP_TOKENS` for the obvious reason.
_HELP_WORDS: tuple = ("--help", "-h", "help")


@dataclass
class AuditArgv:
    """One reading of the verb's arguments. Nothing here has acted yet."""

    #: A help spelling appeared. Answered before anything else, including a
    #: refusal, because a question beside nonsense is still a question.
    wants_help: bool = False
    #: Bare words, in order: pack, then @branch.
    positional: List[str] = field(default_factory=list)
    #: Tokens no branch of the grammar claimed (Law ARGV). First one is refused.
    unrecognized: List[str] = field(default_factory=list)
    show_bypasses: bool = False
    no_bypass: bool = False
    force_full: bool = False
    write_artifact: bool = True
    artifact_path: Optional[str] = None
    #: `--artifact` was the last token, so its destination never arrived.
    artifact_path_missing: bool = False


def parse(args: Sequence[str]) -> AuditArgv:
    """Read the whole argument list and answer what it says.

    Args:
        args: The verb's arguments, `--help` and lane word included.

    Returns:
        An :class:`AuditArgv`. A help spelling short-circuits the read, which
        is what makes `--artifact --help` print help instead of writing an
        artifact to a file named `--help` and running an audit to fill it.
    """
    parsed = AuditArgv()
    expect_artifact_path = False
    for arg in args:
        # Before the value slots, never after (see the docstring above).
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
        # A dashed token no branch claimed. It used to fall off the end of this
        # loop and be forgotten (Law ARGV).
        parsed.unrecognized.append(arg)
    parsed.artifact_path_missing = expect_artifact_path
    _log_anomalies(args, parsed)
    return parsed


def _log_anomalies(args: Sequence[str], parsed: AuditArgv) -> None:
    """Record a reading that found something the grammar does not claim.

    THE READING IS A SEPARATE FACT FROM THE DECISION. The module logs the
    refusal it issues; this logs what argv actually contained, which is the
    record that did not exist on the day `audit -tests @backup` had its first
    token dropped and ran a different verb's audit on cached data. A clean
    parse writes nothing: an operation log that fires on every well-formed
    command buries the one line anybody would go looking for.
    """
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
